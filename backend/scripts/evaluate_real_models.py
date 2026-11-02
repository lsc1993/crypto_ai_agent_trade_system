# 真实模型质量评估的显式付费入口：默认仅加载固定公开样本并生成安全指纹。
# live 复用生产综合研究适配器，HTTP 包装层只限制出站权限、调用和时间额度，不修改 Prompt。
# 安全报告不含正文、证据、请求头或推理；接受只表示生产合同通过，语义质量始终等待人工复核。
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any, Literal, NoReturn, TextIO, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from structlog.testing import capture_logs

from app.agent import model as model_module
from app.agent import numeric_facts as numeric_facts_module
from app.agent import prompt as prompt_module
from app.agent.model import (
    AgentAnalysisProposal,
    DeepSeekResearchLanguageModel,
    ModelOutputError,
    ResearchModelRequest,
)
from app.agent.prompt import system_prompt

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITE = ROOT / "backend" / "evaluation" / "real-model" / "v2" / "suite.json"
REPORT_ROOT = ROOT / ".tmp" / "real-model-evaluation"
ENDPOINT = "https://api.deepseek.com/chat/completions"
MAX_SUITE_BYTES = 131_072
MAX_RESPONSE_BYTES = 2_097_152
SafeName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")]
FixtureName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*\.json$")]
ModelName = Literal["deepseek-v4-flash", "deepseek-v4-pro"]


class EvaluationData(BaseModel):
    """固定语料契约拒绝额外字段，不能把样本文件变成任意工具路由。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Case(EvaluationData):
    """仅引用同目录冻结请求；新闻开关表示局部边界检查，不表示抗注入评分。"""

    id: SafeName
    request_file: FixtureName
    check_news_boundary: bool = False


class Suite(EvaluationData):
    """第一版只覆盖综合研究；非空且标识唯一防止空集或重复案例制造成功。"""

    version: SafeName
    scope: Literal["comprehensive-research-only"]
    cases: tuple[Case, ...] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_ids(self) -> Suite:
        """在任何网络调用前拒绝重复案例。"""
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate case")
        return self


class Limits(EvaluationData):
    """进程显式额度；输出上限只能容纳原生产 payload，不能改写生产请求。"""

    max_requests: int = Field(ge=1, le=100)
    max_input_bytes: int = Field(ge=1, le=1_048_576)
    max_output_tokens: int = Field(ge=1, le=7_000)
    request_timeout_seconds: int = Field(ge=1, le=300)
    total_timeout_seconds: int = Field(ge=1, le=3_600)


@dataclass(frozen=True)
class Prices:
    """人工提供的每百万 token 单价；仅估算有效 usage，不承诺供应商账单上限。"""

    input_per_million: Decimal
    output_per_million: Decimal


@dataclass
class RunState:
    """跨案例累计实际传输次数，即使超时、未知 usage 或报告写入失败也不能丢失。"""

    started: float = field(default_factory=perf_counter)
    actual_requests: int = 0
    known_usage_requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    stop_code: str | None = None


@dataclass(frozen=True)
class ReservedArtifact:
    """持有独占创建的文件句柄至运行结束，避免网络等待期间路径替换后误写其他文件。"""

    path: Path
    handle: TextIO


class EvaluationStop(Exception):
    """仅携带程序固定错误码，绝不携带原始异常或上游内容。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _read_bounded(path: Path, maximum: int) -> bytes:
    """有界读取固定语料，避免先读入任意大文件再做输入额度校验。"""
    with path.open("rb") as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise EvaluationStop("input_limit_exceeded")
    return data


def _has_link(path: Path) -> bool:
    """Windows junction 同样可能绕出固定目录，因此与符号链接一起拒绝。"""
    return any(part.is_symlink() or part.is_junction() for part in (path, *path.parents))


def _load() -> tuple[Suite, list[tuple[Case, ResearchModelRequest, str]], str, dict[str, str]]:
    """只加载固定 suite 及其同级 JSON；符号链接与目录穿越均在读取前拒绝。"""
    suite_path = DEFAULT_SUITE
    if _has_link(suite_path) or suite_path.resolve().parent != suite_path.parent.resolve():
        raise EvaluationStop("suite_invalid")
    raw_suite = _read_bounded(suite_path, MAX_SUITE_BYTES)
    suite = Suite.model_validate_json(raw_suite)
    corpus = hashlib.sha256(raw_suite)
    loaded: list[tuple[Case, ResearchModelRequest, str]] = []
    for case in suite.cases:
        candidate = suite_path.parent / case.request_file
        if _has_link(candidate) or candidate.resolve().parent != suite_path.parent.resolve():
            raise EvaluationStop("suite_invalid")
        raw = _read_bounded(candidate, 1_048_576)
        request = ResearchModelRequest.model_validate_json(raw)
        corpus.update(case.request_file.encode("ascii"))
        corpus.update(raw)
        loaded.append((case, request, hashlib.sha256(raw).hexdigest()))
    metadata: dict[str, dict[str, Any]] = {}
    metadata_hashes: dict[str, str] = {}
    # 来源记录、历史快照和人工评分规则也属于评估版本；不能只给模型输入打指纹。
    for name in ("provenance.json", "historical-market.json", "rubric.json"):
        candidate = suite_path.parent / name
        if _has_link(candidate):
            raise EvaluationStop("metadata_invalid")
        try:
            raw = _read_bounded(candidate, 1_048_576)
            payload: object = json.loads(raw)
        except (OSError, ValueError):
            raise EvaluationStop("metadata_invalid") from None
        if not isinstance(payload, dict):
            raise EvaluationStop("metadata_invalid")
        metadata[name] = cast(dict[str, Any], payload)
        metadata_hashes[name] = hashlib.sha256(raw).hexdigest()
        corpus.update(name.encode("ascii"))
        corpus.update(raw)
    if (
        metadata["provenance.json"].get("historical_market_sha256")
        != metadata_hashes["historical-market.json"]
        or not metadata["historical-market.json"].get("candles")
        or not metadata["rubric.json"].get("version")
        or not metadata["rubric.json"].get("dimensions")
    ):
        raise EvaluationStop("metadata_invalid")
    return suite, loaded, corpus.hexdigest(), metadata_hashes


def _boundary_checked(payload: dict[str, Any], required: bool) -> bool:
    """只核对真实用户消息中新闻被边界包裹，不判断模型是否遵从证据指令。"""
    if not required:
        return False
    user = json.loads(payload["messages"][1]["content"])
    news = [item["content"] for item in user["evidences"] if item["kind"] == "news"]
    if not news or any(
        not text.startswith("UNTRUSTED_NEWS_CONTENT\n")
        or not text.endswith("\nEND_UNTRUSTED_NEWS_CONTENT")
        or text.count("UNTRUSTED_NEWS_CONTENT") != 2
        for text in news
    ):
        raise EvaluationStop("news_boundary_invalid")
    return True


def _usage(response: httpx.Response, state: RunState) -> None:
    """usage 缺失或非法按未知记录并停止后续请求，绝不把未知费用当作零。"""
    try:
        payload: object = response.json()
        usage = cast(dict[str, object], payload).get("usage") if isinstance(payload, dict) else None
        typed_usage = cast(dict[str, object], usage) if isinstance(usage, dict) else {}
        prompt = typed_usage.get("prompt_tokens")
        completion = typed_usage.get("completion_tokens")
        if (
            type(prompt) is not int
            or type(completion) is not int
            or min(prompt, completion) < 0
            or max(prompt, completion) > 1_000_000_000
        ):
            state.stop_code = "usage_unknown"
            return
        state.known_usage_requests += 1
        state.prompt_tokens += prompt
        state.completion_tokens += completion
    except (ValueError, TypeError):
        state.stop_code = "usage_unknown"


class GovernedTransport(httpx.AsyncBaseTransport):
    """实际 HTTP 前逐次拦截生产适配器的首次和纠错请求，底层不允许重试或跳转。"""

    def __init__(self, *, inner: httpx.AsyncBaseTransport, limits: Limits, state: RunState) -> None:
        self.inner = inner
        self.limits = limits
        self.state = state
        self.check_news = False
        self.news_checked = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """保留生产请求，仅在固定目标、额度与时间均通过后计数并发送。"""
        state = self.state
        if state.stop_code:
            raise EvaluationStop(state.stop_code)
        if request.method != "POST" or str(request.url) != ENDPOINT:
            raise EvaluationStop("endpoint_forbidden")
        raw_payload: object = json.loads(request.content)
        if not isinstance(raw_payload, dict):
            raise EvaluationStop("request_shape_forbidden")
        payload = cast(dict[str, Any], raw_payload)
        if set(payload) != {"model", "messages", "response_format", "thinking", "max_tokens"}:
            raise EvaluationStop("request_shape_forbidden")
        if payload["model"] not in ("deepseek-v4-flash", "deepseek-v4-pro"):
            raise EvaluationStop("request_shape_forbidden")
        if len(request.content) > self.limits.max_input_bytes:
            raise EvaluationStop("input_limit_exceeded")
        if type(payload["max_tokens"]) is not int or not (
            1 <= payload["max_tokens"] <= self.limits.max_output_tokens
        ):
            raise EvaluationStop("output_limit_insufficient")
        self.news_checked = _boundary_checked(payload, self.check_news)
        if state.actual_requests >= self.limits.max_requests:
            raise EvaluationStop("request_limit_exceeded")
        remaining = self.limits.total_timeout_seconds - (perf_counter() - state.started)
        if remaining <= 0:
            raise EvaluationStop("total_timeout")
        # 计数在首次真正交给底层传输前增加，错误和取消也保留已发起次数。
        state.actual_requests += 1
        response: httpx.Response | None = None
        timeout_code = (
            "total_timeout"
            if remaining <= self.limits.request_timeout_seconds
            else "request_timeout"
        )
        try:
            async with asyncio.timeout(min(remaining, self.limits.request_timeout_seconds)):
                response = await self.inner.handle_async_request(request)
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise EvaluationStop("response_limit_exceeded")
                    chunks.append(chunk)
                body = b"".join(chunks)
            # aiter_bytes 已做内容解码；移除压缩头和旧字节长度，避免重建响应时再次解压。
            headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in ("content-encoding", "content-length")
            }
            safe_response = httpx.Response(
                response.status_code, headers=headers, content=body, request=request
            )
            # 重定向作为错误返回适配器，客户端不能跟随并转发 Authorization。
            if 200 <= response.status_code < 300:
                _usage(safe_response, state)
                try:
                    raw_body: object = safe_response.json()
                    body_data = cast(dict[str, Any], raw_body) if isinstance(raw_body, dict) else {}
                    choices: list[Any] = body_data.get("choices", [])
                    if any(
                        isinstance(choice, dict)
                        and isinstance(cast(dict[str, Any], choice).get("message"), dict)
                        and (
                            cast(dict[str, Any], choice)["message"].get("tool_calls")
                            or cast(dict[str, Any], choice)["message"].get("function_call")
                        )
                        for choice in choices
                    ):
                        raise EvaluationStop("response_tools_forbidden")
                except (ValueError, TypeError):
                    # JSON 形态错误仍由生产适配器拒绝；这里只拒绝明确出现的工具调用。
                    pass
            else:
                state.stop_code = "model_upstream_error"
            return safe_response
        except TimeoutError:
            state.stop_code = timeout_code
            raise EvaluationStop(state.stop_code) from None
        except EvaluationStop as error:
            state.stop_code = error.code
            raise
        except Exception:
            state.stop_code = "model_transport_error"
            raise EvaluationStop(state.stop_code) from None
        finally:
            if response is not None:
                await response.aclose()

    async def aclose(self) -> None:
        """退出客户端时关闭底层连接，测试替身也遵循同一生命周期。"""
        await self.inner.aclose()


def _base_report(state: RunState) -> dict[str, Any]:
    """仅构造程序白名单元数据，错误输出同样保留调用计数。"""
    return {
        "status": "blocked",
        "error_code": None,
        "mode": "prepare",
        "scope": "comprehensive-research-only",
        "cases": [],
        "summary": {"actual_requests": state.actual_requests},
        "limitations": [
            "accepted means production contract validation only",
            "semantic support, factual correctness, injection resistance "
            "and research value are pending",
            "technical v2, research evidence gates and persistence are not covered",
            "usage-based estimates are not a supplier billing limit; absent usage is unknown",
            "all input tokens use the explicit input price; cache discounts are not modelled",
            "raw model text is not stored; semantic review requires a separate authorized process",
        ],
    }


def _summary(state: RunState, prices: Prices | None) -> dict[str, Any]:
    """有效 token 仅累计已确认 usage；部分未知时总费用估算保持未知。"""
    complete = state.known_usage_requests == state.actual_requests
    estimate = None
    if prices is not None and state.actual_requests and complete:
        estimate = str(
            (
                Decimal(state.prompt_tokens) * prices.input_per_million
                + Decimal(state.completion_tokens) * prices.output_per_million
            )
            / Decimal(1_000_000)
        )
    return {
        "actual_requests": state.actual_requests,
        "known_usage_requests": state.known_usage_requests,
        "unknown_usage_requests": state.actual_requests - state.known_usage_requests,
        "usage_status": "known" if state.actual_requests and complete else "unknown",
        "known_prompt_tokens": state.prompt_tokens if state.known_usage_requests else None,
        "known_completion_tokens": state.completion_tokens if state.known_usage_requests else None,
        "estimated_cost": estimate,
        "duration_ms": max(0, round((perf_counter() - state.started) * 1_000)),
    }


def _reserve_output(output: Path) -> ReservedArtifact:
    """网络前独占写入小型安全报告，预检权限且防止覆盖既有运行结果。"""
    path = output if output.is_absolute() else ROOT / output
    resolved = path.resolve()
    root = REPORT_ROOT.resolve()
    if not resolved.is_relative_to(root) or resolved == root or path.suffix != ".json":
        raise EvaluationStop("report_path_forbidden")
    # 不接受任何已有符号链接；resolved 限制同时阻止父目录链接绕出固定结果目录。
    if _has_link(path):
        raise EvaluationStop("report_path_forbidden")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    handle: TextIO | None = None
    try:
        handle = resolved.open("x", encoding="utf-8", newline="\n")
        handle.write('{"status":"reserved","actual_requests":0}\n')
        handle.flush()
        os.fsync(handle.fileno())
    except OSError:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        raise EvaluationStop("report_preflight_failed") from None
    return ReservedArtifact(resolved, handle)


def _write_report(artifact: ReservedArtifact, report: dict[str, Any]) -> None:
    """只更新本运行独占预留的产物；失败由主入口保留统计并安全报告。"""
    artifact.handle.seek(0)
    artifact.handle.write(json.dumps(report, ensure_ascii=True, indent=2) + "\n")
    artifact.handle.truncate()
    artifact.handle.flush()
    os.fsync(artifact.handle.fileno())


def _safe_validation_log(entry: Mapping[str, Any]) -> dict[str, Any]:
    """每次拒绝仅保留白名单诊断；未知类别/键或原始正文不能进入安全报告。"""
    allowed = {
        "schema",
        "trading_instruction",
        "text_length",
        "narrative_length",
        "numeric_reference",
        "unbound_numeric_claim",
    }
    paths = entry.get("validation_field_paths", ())
    categories = entry.get("validation_error_categories", ())
    # 数值模块的路径收敛器仅允许契约位置，不转发任意ASCII JSON键。
    safe_paths = (
        [
            numeric_facts_module.NumericReferenceError(path).path
            for path in cast(list[object] | tuple[object, ...], paths)[:8]
            if isinstance(path, str)
        ]
        if isinstance(paths, (tuple, list))
        else []
    )
    safe_categories = (
        [
            category if category in allowed else "schema"
            for category in cast(list[object] | tuple[object, ...], categories)[:8]
            if isinstance(category, str)
        ]
        if isinstance(categories, (tuple, list))
        else []
    )
    attempt = entry.get("attempt")
    count = entry.get("validation_issue_count")
    return {
        "attempt": min(3, max(1, attempt)) if type(attempt) is int else 1,
        "issue_count": min(99, max(0, count)) if type(count) is int else 0,
        "field_paths": safe_paths,
        "categories": safe_categories,
    }


async def evaluate(
    *,
    report: dict[str, Any],
    state: RunState,
    suite: Suite,
    loaded: list[tuple[Case, ResearchModelRequest, str]],
    corpus_hash: str,
    metadata_hashes: dict[str, str],
    model: ModelName,
    limits: Limits | None,
    key: SecretStr | None,
    accepted_proposals: dict[str, Any] | None = None,
) -> None:
    """离线只准备；live 经固定适配器逐案运行，未知消耗或传输失败后停止后续请求。"""
    report["versions"] = {
        "suite": suite.version,
        "corpus_sha256": corpus_hash,
        "metadata_sha256": metadata_hashes,
        "model": model,
        "prompt_sha256": hashlib.sha256(system_prompt().encode("utf-8")).hexdigest(),
        "prompt_template_sha256": hashlib.sha256(
            Path(prompt_module.__file__).read_bytes()
        ).hexdigest(),
        "adapter_sha256": hashlib.sha256(Path(model_module.__file__).read_bytes()).hexdigest(),
        "numeric_renderer_sha256": hashlib.sha256(
            Path(numeric_facts_module.__file__).read_bytes()
        ).hexdigest(),
        "contract_sha256": hashlib.sha256(
            json.dumps(AgentAnalysisProposal.model_json_schema(), sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "adapter": "DeepSeekResearchLanguageModel",
    }
    report["cases"] = [
        {
            "id": case.id,
            "input_sha256": digest,
            "outcome": "blocked",
            "error_code": "not_run",
            "actual_requests": 0,
            "format_retries": 0,
            "news_boundary_checked": False,
            "reference_membership": "not_checked",
            "semantic_review": "pending",
            "validation_failures": cast(list[dict[str, Any]], []),
            "duration_ms": 0,
        }
        for case, _, digest in loaded
    ]
    if limits is None:
        report["status"] = "prepared"
        report["error_code"] = None
        return
    report["mode"] = "live"
    report["limits"] = limits.model_dump()
    transport = GovernedTransport(
        inner=httpx.AsyncHTTPTransport(retries=0, trust_env=False), limits=limits, state=state
    )
    async with httpx.AsyncClient(
        transport=transport,
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(limits.request_timeout_seconds),
    ) as client:
        validation_records: list[dict[str, Any]] = []

        def observe_validation(error: ModelOutputError, attempt: int) -> None:
            """直接接收生产适配器的安全诊断，不从日志反解析，也不改变重试/验证结论。"""
            validation_records.append(
                _safe_validation_log(
                    {
                        "attempt": attempt,
                        "validation_issue_count": error.validation_issue_count,
                        "validation_field_paths": error.validation_field_paths,
                        "validation_error_categories": error.validation_error_categories,
                    }
                )
            )

        adapter = DeepSeekResearchLanguageModel(
            client=client, api_key=key, model=model, validation_observer=observe_validation
        )
        for index, (case, request, _) in enumerate(loaded):
            result: dict[str, Any] = report["cases"][index]
            if state.stop_code:
                result["error_code"] = state.stop_code
                continue
            start = perf_counter()
            before = state.actual_requests
            before_known = state.known_usage_requests
            before_prompt = state.prompt_tokens
            before_completion = state.completion_tokens
            transport.check_news = case.check_news_boundary
            transport.news_checked = False
            validation_records.clear()
            try:
                # 捕获生产安全诊断，不让多行日志污染唯一 JSON 产物；不保留日志内容。
                with capture_logs():
                    proposal = await adapter.generate(request)
                result.update(outcome="accepted", error_code=None, reference_membership="passed")
                if accepted_proposals is not None:
                    # 只有显式本地人工审核选项才暂存已接受提案；原始候选和推理从不保留。
                    accepted_proposals[case.id] = proposal.model_dump(mode="json")
            except EvaluationStop as error:
                state.stop_code = error.code
                result.update(outcome="blocked", error_code=error.code)
            except ModelOutputError as error:
                if error.code in ("model_invalid_response", "model_invalid_evidence"):
                    result.update(outcome="rejected", error_code=error.code)
                else:
                    # 所有码均来自生产白名单；未知类型统一折叠，不能反射任意异常字符串。
                    code = (
                        error.code
                        if error.code
                        in {
                            "model_timeout",
                            "model_transport_error",
                            "model_upstream_error",
                            "model_empty_response",
                            "model_not_configured",
                        }
                        else "model_error"
                    )
                    state.stop_code = code
                    result.update(outcome="error", error_code=code)
            except Exception:
                state.stop_code = "evaluation_runtime_error"
                result.update(outcome="error", error_code=state.stop_code)
            result["validation_failures"] = list(validation_records[:3])
            result.update(
                actual_requests=state.actual_requests - before,
                format_retries=max(0, state.actual_requests - before - 1),
                duration_ms=max(0, round((perf_counter() - start) * 1_000)),
                news_boundary_checked=transport.news_checked,
                usage_status="known"
                if state.actual_requests > before
                and (state.actual_requests - before == state.known_usage_requests - before_known)
                else "unknown",
                known_prompt_tokens=state.prompt_tokens - before_prompt
                if state.known_usage_requests > before_known
                else None,
                known_completion_tokens=state.completion_tokens - before_completion
                if state.known_usage_requests > before_known
                else None,
            )
    report["error_code"] = state.stop_code
    report["status"] = "completed" if state.stop_code is None else "blocked"


class SafeParser(argparse.ArgumentParser):
    """参数错误只返回固定码，避免 argparse 回显用户误传入的敏感参数。"""

    def error(self, message: str) -> NoReturn:
        raise EvaluationStop("arguments_invalid")


def main(argv: list[str] | None = None) -> int:
    """CLI 默认离线；live 所有额度、模型、显式进程密钥与可写报告均在网络前校验。"""
    state = RunState()
    report = _base_report(state)
    output: ReservedArtifact | None = None
    review_output: ReservedArtifact | None = None
    accepted_proposals: dict[str, Any] | None = None
    prices: Prices | None = None
    try:
        parser = SafeParser(
            description="Prepare or explicitly run comprehensive research evaluation"
        )
        parser.add_argument("--live", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--save-accepted-proposals", action="store_true")
        parser.add_argument("--model", choices=("deepseek-v4-flash", "deepseek-v4-pro"))
        parser.add_argument("--output", type=Path)
        for name in (
            "max-requests",
            "max-input-bytes",
            "max-output-tokens",
            "request-timeout-seconds",
            "total-timeout-seconds",
        ):
            parser.add_argument("--" + name, type=int)
        parser.add_argument("--input-price-per-million", type=Decimal)
        parser.add_argument("--output-price-per-million", type=Decimal)
        args = parser.parse_args(argv)
        if args.save_accepted_proposals and not args.live:
            raise EvaluationStop("review_requires_live")
        limits = None
        key = None
        if args.live:
            required = (
                args.max_requests,
                args.max_input_bytes,
                args.max_output_tokens,
                args.request_timeout_seconds,
                args.total_timeout_seconds,
            )
            if args.dry_run or args.model is None or args.output is None or None in required:
                raise EvaluationStop("live_configuration_required")
            limits = Limits(
                max_requests=args.max_requests,
                max_input_bytes=args.max_input_bytes,
                max_output_tokens=args.max_output_tokens,
                request_timeout_seconds=args.request_timeout_seconds,
                total_timeout_seconds=args.total_timeout_seconds,
            )
            # 不导入 AppSettings、不读取 dotenv；只有 live 才读取专用进程变量。
            value = os.environ.get("REAL_MODEL_EVAL_API_KEY", "").strip()
            if not value or len(value) > 1_024 or any(character.isspace() for character in value):
                raise EvaluationStop("explicit_api_key_required")
            key = SecretStr(value)
        input_price, output_price = args.input_price_per_million, args.output_price_per_million
        if (input_price is None) != (output_price is None):
            raise EvaluationStop("prices_invalid")
        if input_price is not None:
            if not all(
                price.is_finite()
                and (price == 0 or Decimal("0.000000000001") <= price <= Decimal("1000000"))
                for price in (input_price, output_price)
            ):
                raise EvaluationStop("prices_invalid")
            prices = Prices(input_price, output_price)
        suite, loaded, corpus_hash, metadata_hashes = _load()
        if limits is not None and any(
            (4_000 if request.factor_analysis is None else 7_000) > limits.max_output_tokens
            for _, request, _ in loaded
        ):
            raise EvaluationStop("output_limit_insufficient")
        if args.output is not None:
            output = _reserve_output(args.output)
            if args.save_accepted_proposals:
                review_output = _reserve_output(
                    output.path.with_name(output.path.stem + ".review.json")
                )
                accepted_proposals = {}
        asyncio.run(
            evaluate(
                report=report,
                state=state,
                suite=suite,
                loaded=loaded,
                corpus_hash=corpus_hash,
                metadata_hashes=metadata_hashes,
                model=cast(ModelName, args.model or "deepseek-v4-flash"),
                limits=limits,
                key=key,
                accepted_proposals=accepted_proposals,
            )
        )
    except EvaluationStop as error:
        report.update(status="blocked", error_code=error.code)
    except Exception:
        report.update(status="blocked", error_code="evaluation_failed")
    report["summary"] = _summary(state, prices)
    for outcome in ("accepted", "rejected", "error", "blocked"):
        report["summary"][outcome] = sum(case["outcome"] == outcome for case in report["cases"])
    report["summary"]["total"] = len(report["cases"])
    report["summary"]["format_retries"] = sum(case["format_retries"] for case in report["cases"])
    if prices is not None:
        report["prices"] = {
            "input_per_million": str(prices.input_per_million),
            "output_per_million": str(prices.output_per_million),
            "source": "explicit_operator_values",
            "billing_limit": False,
        }
    if output is not None:
        try:
            if review_output is not None:
                review = {
                    "versions": report.get("versions"),
                    "proposals": accepted_proposals,
                    "warning": "untrusted model text for local human review only",
                }
                _write_report(review_output, review)
                report["review_artifact_sha256"] = hashlib.sha256(
                    json.dumps(review, ensure_ascii=True, indent=2).encode("utf-8") + b"\n"
                ).hexdigest()
                report["accepted_proposals_saved"] = True
            _write_report(output, report)
        except Exception:
            report.update(status="blocked", error_code="report_write_failed")
        finally:
            for artifact in (output, review_output):
                if artifact is not None:
                    try:
                        artifact.handle.close()
                    except Exception:
                        # close 也可能再次 flush；磁盘故障不能阻止 stdout 保留付费调用统计。
                        report.update(status="blocked", error_code="report_write_failed")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["status"] in ("prepared", "completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
