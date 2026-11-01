# 离线运行真实综合研究图与技术 v2 两阶段服务，HTTP 只通过固定 MockTransport。
# 输入为独立版本化合成样本，保存/读取经内存公开契约；不读取环境密钥或连接数据库。
# 产物只输出白名单分类、调用阶段与指纹，不保存模型原文、思考、证据、异常或路径。
from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from structlog.testing import capture_logs

from app.agent.model import (
    AgentAnalysisProposal,
    DeepSeekResearchLanguageModel,
    ResearchModelRequest,
)
from app.agent.prompt import system_prompt
from app.agent.service import AgentResearchDependencies, AgentResearchService
from app.agent.technical.engine import calculate_technical_analysis
from app.agent.technical.methods import METHOD_VERSION, method_instructions, selected_methods
from app.agent.technical.plan_model import DeepSeekTechnicalPlanLanguageModel
from app.agent.technical.plan_prompt import plan_messages
from app.agent.technical.plan_service import TechnicalPlanResearchService
from app.reports.technical_plan import (
    TechnicalContext,
    TechnicalDecisionSummary,
    TechnicalGeneration,
    TechnicalPlanReport,
)
from app.reports.technical_runs import TechnicalRunLease, TechnicalRunPhase
from app.shared.config import AppSettings
from scripts.research_flow_fixtures import (
    NOW,
    MarketRecipe,
    MemoryResearchRepository,
    MemoryTechnicalRepository,
    OfflineMarket,
    OfflineNews,
    build_market,
)

DEFAULT_SUITE = Path(__file__).resolve().parents[1] / "evaluation" / "flows" / "suite.json"
SafeName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")]
FixtureName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*\.json$")]
Outcome = Literal["accepted", "rejected", "degraded", "insufficient"]
Stage = Literal["analysis", "composition", "research"]
Quality = Literal[
    "complete",
    "composition_fallback",
    "analysis_unavailable",
    "data_insufficient",
    "research_complete",
    "research_degraded",
]
ErrorCode = Literal[
    "model_invalid_response",
    "model_invalid_evidence",
    "model_timeout",
    "model_not_configured",
    "data_quality_insufficient",
    "market_closed_candle_missing",
    "market_unavailable",
    "model_upstream_error",
    "model_output_limit",
    "model_empty_response",
    "run_timeout",
]


class EvaluationData(BaseModel):
    """拒绝额外字段与隐式转换，避免错误配置变成不知情的评估通过。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Expected(EvaluationData):
    """分类与精确调用阶段一起构成预期，门控必须明确为零调用。"""

    outcome: Outcome
    quality: Quality
    error_code: ErrorCode | None = None
    calls: tuple[Stage, ...] = Field(max_length=4)

    @model_validator(mode="after")
    def consistent(self) -> Expected:
        """成功不能带错误，失败不能缺错误；证据不足不能调用模型。"""
        if (self.outcome == "accepted") != (self.error_code is None):
            raise ValueError("outcome_error")
        if self.outcome == "insufficient" and self.calls:
            raise ValueError("gate_calls")
        return self


class Case(EvaluationData):
    """只允许固定两类服务和故障模式；数据文件不能成为任意路径或工具。"""

    id: SafeName
    flow: Literal["technical", "research"]
    scenario: Literal["valid", "invalid", "timeout", "composition_timeout", "insufficient"]
    response_file: FixtureName
    expected: Expected
    configured: bool = True

    @model_validator(mode="after")
    def supported(self) -> Case:
        """只对技术服务支持编排失败，综合服务不能静默忽略无效模式。"""
        if self.flow == "research" and self.scenario == "composition_timeout":
            raise ValueError("scenario_flow")
        return self


class Suite(EvaluationData):
    """非空、唯一标识的独立流程评估集。"""

    version: SafeName
    market_file: FixtureName
    cases: tuple[Case, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self) -> Suite:
        """重复标识使计数不可审查，加载时即失败。"""
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate_case")
        return self


class ResponseMessage(EvaluationData):
    """外壳结构必须有效，只有 content 内的模型 JSON 可故意无效。"""

    content: str
    reasoning_content: str | None = None


class ResponseChoice(EvaluationData):
    """技术模型要求停止原因，综合模型可使用不带该字段的既有外壳。"""

    message: ResponseMessage
    finish_reason: Literal["stop", "length"] | None = None


class ResponseFixture(EvaluationData):
    """空 choices 属于坏评估配置，不能冒充预期模型格式拒绝。"""

    choices: tuple[ResponseChoice, ...] = Field(min_length=1, max_length=1)


class CaseResult(EvaluationData):
    """运行结果只携带白名单元数据，统计阶段保持类型而非重新解析 JSON。"""

    id: SafeName
    flow: Literal["technical", "research"]
    expected: Expected
    actual: Expected
    saved: bool
    readable: bool
    matched: bool


def fixture_path(directory: Path, name: str) -> Path:
    """解析经过文件名校验的同目录输入，同时防止符号链接绕出样本目录。"""
    path = (directory / name).resolve()
    if path.parent != directory.resolve():
        raise ValueError("fixture_escape")
    return path


class FixtureTransport:
    """仅把固定响应绑定到本次冻结证据身份，不从输入生成研究判断。"""

    def __init__(self, case: Case, response: ResponseFixture) -> None:
        self.case = case
        self.response = response.model_dump(mode="json", exclude_none=True)
        self.calls: list[Stage] = []
        self.analysis_context: object | None = None
        self.integrity_valid = True
        self.private_reasoning = response.choices[0].message.reasoning_content

    def handle(self, request: httpx.Request) -> httpx.Response:
        """检查真实请求的权限及两阶段冻结关系，再注入固定失败或返回固定正文。"""
        payload = json.loads(request.content)
        if (
            "tools" in payload
            or "tool_choice" in payload
            or (
                isinstance(self.private_reasoning, str)
                and self.private_reasoning
                and self.private_reasoning in request.content.decode("utf-8")
            )
        ):
            # 适配器可能捕获 handler 异常；另保留完整性标记，防止权限/原文泄漏被算作预期拒绝。
            self.integrity_valid = False
            raise ValueError("unexpected_tools")
        messages = payload["messages"]
        user = json.loads(messages[1]["content"])
        if self.case.flow == "technical":
            thinking = payload["thinking"]["type"]
            stage: Stage = "analysis" if thinking == "enabled" else "composition"
            context = user["frozenContext"]
            evidence_id = context["analysis"]["evidenceId"]
            if stage == "analysis":
                self.analysis_context = context
            elif context != self.analysis_context or "validatedDecision" not in user:
                self.integrity_valid = False
                raise ValueError("unfrozen_composition")
        else:
            stage = "research"
            evidence_id = user["evidences"][0]["id"]
        self.calls.append(stage)
        if self.case.scenario == "timeout" or (
            self.case.scenario == "composition_timeout" and stage == "composition"
        ):
            raise httpx.ReadTimeout("offline_timeout", request=request)
        # 响应中的身份标记不属于模型研究内容，只绑定生产服务随机生成的当前证据 ID。
        body = json.dumps(self.response, ensure_ascii=False).replace("__EVIDENCE_ID__", evidence_id)
        return httpx.Response(200, content=body.encode("utf-8"))


async def no_progress(phase: TechnicalRunPhase) -> None:
    """离线调用不装配队列进度；真实数据库回归另通过 Harness 建立审计。"""


async def no_lease() -> TechnicalRunLease | None:
    """离线合同不宣称队列所有权；生产服务仍经过保存前回调。"""
    return None


def technical_model(
    client: httpx.AsyncClient, *, configured: bool = True
) -> DeepSeekTechnicalPlanLanguageModel:
    """显式关闭环境/.env 读取，唯一凭证是 MockTransport 内存占位符。"""
    return DeepSeekTechnicalPlanLanguageModel(
        client=client,
        api_key=SecretStr("offline-placeholder") if configured else None,
        # 只取生产声明的默认值，跳过 BaseSettings 的环境与 .env source；没有外部输入。
        model="deepseek-v4-pro",
        settings=AppSettings.model_construct(),
    )


async def evaluate_case(case: Case, directory: Path, recipe: MarketRecipe) -> CaseResult:
    """执行真实服务并重新读取保存副本；任何非预期运行故障直接使整个评估失败。"""
    fixture = ResponseFixture.model_validate_json(
        fixture_path(directory, case.response_file).read_bytes()
    )
    transport = FixtureTransport(case, fixture)
    market = OfflineMarket(build_market(recipe), insufficient=case.scenario == "insufficient")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport.handle), trust_env=False
    ) as client:
        if case.flow == "technical":
            repository = MemoryTechnicalRepository()
            service = TechnicalPlanResearchService(
                market=market,
                repository=repository,
                model=technical_model(client, configured=case.configured),
                clock=lambda: NOW,
            )
            report = await service.generate(
                "BTCUSDT", analysis_id=uuid4(), progress=no_progress, before_save=no_lease
            )
            readable = await repository.get(report.id) == report
            actual = Expected(
                outcome=(
                    "accepted"
                    if report.status == "completed"
                    else "insufficient"
                    if report.generation.quality == "data_insufficient"
                    else "rejected"
                    if report.error_code in {"model_invalid_response", "model_invalid_evidence"}
                    else "degraded"
                ),
                quality=report.generation.quality,
                error_code=report.error_code,
                calls=tuple(transport.calls),
            )
            saved = len(repository.documents) == 1
        else:
            research_repository = MemoryResearchRepository()
            research_service = AgentResearchService(
                dependencies=AgentResearchDependencies(
                    market=market,
                    news=OfflineNews(),
                    repository=research_repository,
                    model=DeepSeekResearchLanguageModel(
                        client=client,
                        api_key=SecretStr("offline-placeholder") if case.configured else None,
                        model="deepseek-v4-flash",
                    ),
                    clock=lambda: NOW,
                )
            )
            research_report = await research_service.generate("BTCUSDT")
            readable = await research_repository.get(research_report.id) == research_report
            complete = research_report.status.value == "completed"
            error_code = (
                None
                if complete
                else (
                    research_report.agent_analysis.data_quality.missing_inputs[0]
                    if research_report.agent_analysis is not None
                    else None
                )
            )
            actual = Expected.model_validate(
                {
                    "outcome": "accepted"
                    if complete
                    else "insufficient"
                    if not transport.calls and case.scenario == "insufficient"
                    else "rejected"
                    if error_code in {"model_invalid_response", "model_invalid_evidence"}
                    else "degraded",
                    "quality": "research_complete" if complete else "research_degraded",
                    "error_code": error_code,
                    "calls": tuple(transport.calls),
                }
            )
            saved = len(research_repository.documents) == 1
    if not transport.integrity_valid:
        raise ValueError("offline_request_integrity")
    return CaseResult(
        id=case.id,
        flow=case.flow,
        expected=case.expected,
        actual=actual,
        saved=saved,
        readable=readable,
        matched=actual == case.expected and saved and readable,
    )


def _digest(value: object) -> str:
    """指纹使用稳定 JSON 编码，不把原文写入结果。"""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


async def evaluate(suite_path: Path) -> dict[str, object]:
    """运行非空样本并分别统计接受、拒绝、降级与证据不足，记录实际方法/契约指纹。"""
    suite = Suite.model_validate_json(suite_path.read_bytes())
    recipe_path = fixture_path(suite_path.parent, suite.market_file)
    recipe = MarketRecipe.model_validate_json(recipe_path.read_bytes())
    files = {suite_path.resolve(), recipe_path}
    files.update(fixture_path(suite_path.parent, case.response_file) for case in suite.cases)
    corpus = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.name):
        corpus.update(path.name.encode())
        corpus.update(path.read_bytes())
    # Prompt 含本次随机证据标识，先固定仅用于指纹的上下文，避免每次评估无意义漂移。
    detail = build_market(recipe)
    analysis = calculate_technical_analysis(detail, captured_at=NOW).model_copy(
        update={"evidence_id": UUID("00000000-0000-0000-0000-000000000001")}
    )
    context = TechnicalContext(
        analysis=analysis,
        summary_price=detail.summary.price,
        latest_closed_prices={},
        data_cutoff_at=NOW,
    )
    with capture_logs():
        results = [await evaluate_case(case, suite_path.parent, recipe) for case in suite.cases]
    matched = sum(result.matched for result in results)
    counts = {
        outcome: sum(result.actual.outcome == outcome for result in results)
        for outcome in ("accepted", "rejected", "degraded", "insufficient")
    }
    return {
        "status": "passed" if matched == len(results) else "failed",
        "versions": {
            "suite": suite.version,
            "corpus_sha256": corpus.hexdigest(),
            # 实际分析 Prompt 加构造函数源码，包含只在编排阶段追加的规则。
            "technical_prompt_sha256": _digest(
                [plan_messages(context)[0]["content"], inspect.getsource(plan_messages)]
            ),
            "research_prompt_sha256": _digest(system_prompt()),
            "market_sha256": _digest(detail.model_dump(mode="json")),
            "method_version": METHOD_VERSION,
            "method_sha256": _digest(method_instructions(selected_methods(include_reversal=True))),
            "contract_sha256": _digest(
                [
                    model.model_json_schema()
                    for model in (
                        TechnicalDecisionSummary,
                        TechnicalContext,
                        TechnicalPlanReport,
                        AgentAnalysisProposal,
                        ResearchModelRequest,
                    )
                ]
            ),
            "technical_prompt_version": TechnicalGeneration.model_fields["prompt_version"].default,
        },
        "summary": {"total": len(results), "matched": matched, **counts},
        "cases": [result.model_dump(mode="json") for result in results],
        "limitations": [
            "Fixed transport responses validate production contracts, not live model quality.",
            "Memory save/read verifies contracts; database regression is a separate pytest.",
            "Synthetic inputs do not prove numeric factual accuracy or investment performance.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI 仅在非空集合全部匹配时退出零；错误只打印固定安全码。"""
    parser = argparse.ArgumentParser(description="Evaluate research service flows offline")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output is not None and args.output.resolve().is_relative_to(
            args.suite.resolve().parent
        ):
            raise ValueError("output_overwrites_corpus")
        report = asyncio.run(evaluate(args.suite))
        text = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
        if args.output is not None:
            args.output.write_text(text, encoding="utf-8")
    except Exception:
        # 不输出路径或异常：无效配置和模型原文都可能含敏感内容。
        report = {"status": "failed", "error_code": "evaluation_failed"}
        text = json.dumps(report) + "\n"
    print(text, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
