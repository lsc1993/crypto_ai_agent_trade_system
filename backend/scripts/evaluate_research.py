# 离线评估只把版本化公开合成证据和固定 HTTP 响应送入真实综合研究适配器。
# MockTransport 从构造上隔离网络；不读取环境配置、数据库、真实密钥或现有测试私有 helper。
# 结果仅含白名单版本、案例标识和分类计数，拒绝率不能表示真实模型或投资研究质量。
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from structlog.testing import capture_logs

from app.agent.contracts import AgentErrorCode
from app.agent.model import (
    AgentAnalysisProposal,
    DeepSeekResearchLanguageModel,
    ModelOutputError,
    ResearchModelRequest,
)
from app.agent.prompt import system_prompt

DEFAULT_SUITE = Path(__file__).resolve().parents[1] / "evaluation" / "suite.json"
Outcome = Literal["accepted", "rejected", "degraded"]
SafeName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")]
FixtureName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*\.json$")]


class EvaluationData(BaseModel):
    """评估配置严格拒绝额外字段，避免拼写错误默默改变验证语义。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Expected(EvaluationData):
    """记录可审查的行为预期；调用次数也约束格式纠正和配置缺失分支。"""

    outcome: Outcome
    error_code: AgentErrorCode | None = None
    attempts: int = Field(ge=0, le=3)

    @model_validator(mode="after")
    def require_consistent_error(self) -> Expected:
        """接受不能带错误，拒绝或降级必须有错误，防止模糊预期产生假绿。"""
        if (self.outcome == "accepted") != (self.error_code is None):
            raise ValueError("评估预期分类与错误不一致")
        return self


class Case(EvaluationData):
    """一个固定响应案例，无工具路由；路径限于同目录 JSON 文件名。"""

    id: SafeName
    request_file: FixtureName
    response_file: FixtureName
    expected: Expected
    configured: bool = True
    transport_timeout: bool = False
    check_news_boundary: bool = False


class Suite(EvaluationData):
    """非空且标识唯一的版本化集合，拒绝无案例的成功报告。"""

    version: SafeName
    cases: tuple[Case, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_ids(self) -> Suite:
        """重复案例会扭曲分项计数，因此加载时即拒绝。"""
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("评估案例标识重复")
        return self


class Message(EvaluationData):
    """响应外壳必须完整，正文字符串本身允许故意包含无效模型 JSON。"""

    content: str


class Choice(EvaluationData):
    """固定的无工具 HTTP 响应选择项。"""

    message: Message


class ResponseFixture(EvaluationData):
    """外壳损坏属于评估数据故障，不能冒充预期模型拒绝。"""

    choices: tuple[Choice, ...] = Field(min_length=1, max_length=1)


class CaseResult(EvaluationData):
    """可安全输出的结果，只包含有限分类和受校验的案例标识。"""

    id: SafeName
    expected: Expected
    actual: Expected
    matched: bool
    news_boundary_checked: bool


def _fixture_path(directory: Path, name: str) -> Path:
    """拒绝符号链接绕出样本目录；文件名语法另由配置模型约束。"""
    path = (directory / name).resolve()
    if path.parent != directory.resolve():
        raise ValueError("评估样本路径越界")
    return path


def _check_news_boundary(request: httpx.Request) -> None:
    """核对实际发送的用户消息保留新闻边界及转义，不声称测得模型抗注入能力。"""
    payload = json.loads(request.content)
    if "tools" in payload or "tool_choice" in payload:
        raise ValueError("离线请求出现工具")
    messages = payload["messages"]
    user = json.loads(messages[1]["content"])
    news = [item["content"] for item in user["evidences"] if item["kind"] == "news"]
    if not news:
        raise ValueError("注入案例缺少新闻")
    for content in news:
        # 原文中的伪造标记必须被转义；只剩程序添加的一对真实边界。
        if (
            not content.startswith("UNTRUSTED_NEWS_CONTENT\n")
            or not content.endswith("\nEND_UNTRUSTED_NEWS_CONTENT")
            or content.count("UNTRUSTED_NEWS_CONTENT") != 2
            or "UNTRUSTED_NEWS\\u005fCONTENT" not in content
        ):
            raise ValueError("新闻边界校验失败")


async def _evaluate_case(case: Case, directory: Path) -> CaseResult:
    """通过真实适配器校验一个固定响应；只捕获受控模型错误，其余故障令评估失败。"""
    request = ResearchModelRequest.model_validate_json(
        _fixture_path(directory, case.request_file).read_bytes()
    )
    response = ResponseFixture.model_validate_json(
        _fixture_path(directory, case.response_file).read_bytes()
    )
    attempts = 0
    boundary_checked = False

    def handler(posted: httpx.Request) -> httpx.Response:
        nonlocal attempts, boundary_checked
        attempts += 1
        # 每次重试都核对边界，防止纠正提示改变原先不可信证据的角色。
        if case.check_news_boundary:
            _check_news_boundary(posted)
            boundary_checked = True
        if case.transport_timeout:
            raise httpx.ReadTimeout("offline timeout", request=posted)
        return httpx.Response(200, json=response.model_dump(mode="json"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
        model = DeepSeekResearchLanguageModel(
            client=client,
            # 此字面量仅供内存替身请求头使用，从不读取或输出真实配置。
            api_key=SecretStr("offline-placeholder") if case.configured else None,
            model="deepseek-v4-flash",
        )
        try:
            await model.generate(request)
            actual = Expected(outcome="accepted", attempts=attempts)
        except ModelOutputError as error:
            code = AgentErrorCode(error.code)
            outcome: Outcome = (
                "rejected"
                if code
                in (
                    AgentErrorCode.MODEL_INVALID_RESPONSE,
                    AgentErrorCode.MODEL_INVALID_EVIDENCE,
                )
                else "degraded"
            )
            actual = Expected(outcome=outcome, error_code=code, attempts=attempts)
    matched = actual == case.expected and (not case.check_news_boundary or boundary_checked)
    return CaseResult(
        id=case.id,
        expected=case.expected,
        actual=actual,
        matched=matched,
        news_boundary_checked=boundary_checked,
    )


async def evaluate(suite_path: Path) -> dict[str, object]:
    """加载固定集并返回安全统计；不保存响应、异常消息或任何输入载荷。"""
    suite = Suite.model_validate_json(suite_path.read_bytes())
    # 指纹随实际 Prompt、契约和所有数据文件变化，版本标签不能掩盖样本漂移。
    files = {suite_path.resolve()}
    for case in suite.cases:
        files.add(_fixture_path(suite_path.parent, case.request_file))
        files.add(_fixture_path(suite_path.parent, case.response_file))
    corpus_hash = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.name):
        corpus_hash.update(path.name.encode("utf-8"))
        corpus_hash.update(path.read_bytes())
    # 使用 structlog 的公开上下文捕获 API，避免模型诊断行污染单一 JSON 输出。
    # 捕获内容不参与报告，也不替换适配器的真实校验逻辑。
    with capture_logs():
        results = [await _evaluate_case(case, suite_path.parent) for case in suite.cases]
    matched = sum(result.matched for result in results)
    return {
        "status": "passed" if matched == len(results) else "failed",
        "versions": {
            "suite": suite.version,
            "corpus_sha256": corpus_hash.hexdigest(),
            "prompt_sha256": hashlib.sha256(system_prompt().encode("utf-8")).hexdigest(),
            "contract_sha256": hashlib.sha256(
                json.dumps(AgentAnalysisProposal.model_json_schema(), sort_keys=True).encode(
                    "utf-8"
                )
            ).hexdigest(),
            "adapter": "DeepSeekResearchLanguageModel",
            "model": "deepseek-v4-flash-offline-fixture",
        },
        "summary": {
            "total": len(results),
            "matched": matched,
            "accepted": sum(result.actual.outcome == "accepted" for result in results),
            "rejected": sum(result.actual.outcome == "rejected" for result in results),
            "degraded": sum(result.actual.outcome == "degraded" for result in results),
        },
        "cases": [result.model_dump(mode="json") for result in results],
        "limitations": [
            "Fixed responses test contracts; rejection rates do not measure live model quality.",
            "News cases verify prompt boundaries, not a live model's injection resistance.",
            "Degraded means fallback eligibility; evidence gates and persistence are untested.",
            "Numeric extra fields are rejected; arbitrary numeric factual accuracy is untested.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI 返回零仅表示非空集合全部符合预期；数据、运行及产物写入失败均返回一。"""
    parser = argparse.ArgumentParser(description="Evaluate research contracts offline")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        # 防止归档路径覆盖评估器自己的输入；未知或损坏输入也不会被覆盖。
        if args.output is not None and args.output.resolve().parent == args.suite.resolve().parent:
            raise ValueError("产物不能写入样本目录")
        report = asyncio.run(evaluate(args.suite))
        text = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
        if args.output is not None:
            args.output.write_text(text, encoding="utf-8")
    except Exception:
        # 不输出异常、路径或 ValidationError，因为其中可能包含原始模型或样本内容。
        report = {"status": "failed", "error_code": "evaluation_failed"}
        text = json.dumps(report) + "\n"
    print(text, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
