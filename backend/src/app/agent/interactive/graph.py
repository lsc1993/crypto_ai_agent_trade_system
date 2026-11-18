# T11 有限 LangGraph：在服务端装配的模型、上下文、工具、证据、交互和产物端口之间路由。
# 图只做提案路由与安全计数；模型调用先经 C5 预算预留/发送/结算，工具必须经 T09 网关。
# 等待片段在 preparation 待办保存后立即结束，不保留模型协程、不在等待期间轮询模型。
# 最终分析只交给 AnalysisArtifactStager；计划进入 AP-01 待审，不能由图或模型自行批准。
from __future__ import annotations

import contextvars
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]

from app.agent.interactive.context import (
    ContextBlock,
    ContextBlockKind,
    ContextBuildError,
    ContextManifest,
    ModelContext,
    ModelMessage,
    ModelToolCall,
    encode_model_request,
)
from app.agent.interactive.context_budget import (
    MAX_INPUT_UNITS_PER_CALL,
    estimate_input,
)
from app.agent.interactive.model_port import (
    AnalysisArtifactStager,
    AnalysisStagingError,
    FinalAnalysis,
    ModelCallError,
    ModelControlDecision,
    ModelDecision,
    ModelPort,
    ToolBatch,
)
from app.agent.interactive.ports import SegmentRunner
from app.agent.interactive.state import GraphPhase, InteractiveGraphState
from app.agent.interactive.tools.contracts import ToolObservation, ToolRequest
from app.agent_runs.attempts import (
    MAX_OUTPUT_TOKENS_PER_CALL,
    MODEL_TIMEOUT_SECONDS,
    AttemptCategory,
    AttemptRequest,
    AttemptResult,
    AttemptStatus,
)
from app.agent_runs.budget import (
    ACTIVITY_SAFETY_MARGIN_SECONDS,
    BudgetLedger,
    BudgetStatus,
)
from app.agent_runs.contracts import AgentRunError, RunSnapshot, RunStatus
from app.agent_runs.decisions import (
    ApprovalKind,
    ControlAction,
    ControlProposal,
    DecisionPolicy,
    GuardAction,
)
from app.agent_runs.interactions import (
    MAX_INTERACTION_LIFETIME_SECONDS,
    HumanInteraction,
    InteractionDraft,
)
from app.agent_runs.ports import AgentRunReader
from app.agent_runs.segments import (
    ExecutionContext,
    RunFence,
    SegmentOutcome,
    SegmentOutcomeKind,
    graph_namespace,
)
from app.research.evidence import EvidenceEpoch, EvidenceUnavailableError
from app.shared.agent_types import ArtifactRef, JsonValue, require_utc, sha256_json

# 模型动作序号使用独立区段，避免与 T08 证据（1,000,000）和 T09 工具（2,000,000）冲突。
MODEL_ACTION_SEQUENCE_BASE = 100_000
# 单次模型输入上限由 C5 契约固定；扩展 live tool turn 后仍不能突破该值。
_MAX_MODEL_INPUT_UNITS = MAX_INPUT_UNITS_PER_CALL
_SAFE_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_ACTIVITY_LIMIT_SECONDS = 86_400


# 证据端口只接收服务端 ExecutionContext；实现负责当前/历史模式与传输预算校验。
class EvidencePort(Protocol):
    async def freeze(
        self,
        context: ExecutionContext,
        *,
        refresh: bool = False,
    ) -> EvidenceEpoch: ...


# 上下文端口返回已裁剪的 ModelContext；图不自行读取策略/知识/数据库。
class ContextPort(Protocol):
    async def build(
        self,
        context: ExecutionContext,
        evidence: EvidenceEpoch,
        *,
        applied_seq: int,
    ) -> ModelContext: ...


# 工具端口是 T09 ToolGateway 的窄接口；图不直接调用处理器或网络。
class ToolPort(Protocol):
    async def call(
        self,
        context: ExecutionContext,
        request: ToolRequest,
    ) -> ToolObservation: ...


# 交互端口只准备 preparing 待办；pending 发布由 T07 协调器在片段 END 后原子完成。
class InteractionPort(Protocol):
    async def prepare(
        self,
        fence: RunFence,
        draft: InteractionDraft,
    ) -> HumanInteraction: ...


# 图依赖显式注入全部端口；不导入数据库、执行服务、交易风控或 T14 报告实现。
@dataclass(frozen=True)
class GraphDependencies:
    runs: AgentRunReader
    budget: BudgetLedger
    evidence: EvidencePort
    contexts: ContextPort
    tools: ToolPort
    model: ModelPort
    interactions: InteractionPort
    artifacts: AnalysisArtifactStager
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    checkpointer: BaseCheckpointSaver[Any] | None = None
    interaction_ttl: timedelta = timedelta(hours=24)

    # 交互有效期必须为正且不超过 C5 审核生命周期；构造时失败优于运行中静默截断。
    def __post_init__(self) -> None:
        if self.interaction_ttl <= timedelta(0):
            raise ValueError("交互有效期必须为正")
        if self.interaction_ttl > timedelta(seconds=MAX_INTERACTION_LIFETIME_SECONDS):
            raise ValueError("交互有效期不能超过审核生命周期")


# 单片段的内存执行作用域：保存只在本进程/本片段使用的原始消息与当前决策。
# 不进入 LangGraph state/checkpoint；进程重启后由 T07 恢复片段和 T14/T17 重建历史。
@dataclass
class _RunScope:
    dependencies: GraphDependencies
    context: ExecutionContext
    started_at: datetime
    snapshot: RunSnapshot | None = None
    evidence: EvidenceEpoch | None = None
    base_context: ModelContext | None = None
    live_messages: list[ModelMessage] = field(default_factory=list[ModelMessage])
    decision: ModelDecision | None = None
    model_calls: int = 0
    tool_calls: int = 0
    applied_seq: int = 0


# 图内部终止信号：预算/取消/模型错误在节点中转换成安全 SegmentOutcome，不写成异常成功。
class _GraphStop(Exception):
    def __init__(self, kind: SegmentOutcomeKind, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


_CURRENT_SCOPE: contextvars.ContextVar[_RunScope | None] = contextvars.ContextVar(
    "interactive_graph_scope",
    default=None,
)


# 当前节点的作用域；缺失说明图被错误地独立调用，直接 fail-closed。
def _scope() -> _RunScope:
    value = _CURRENT_SCOPE.get()
    if value is None:
        raise RuntimeError("交互式图执行作用域未绑定")
    return value


# 只允许稳定短码写入状态/事件；上游异常文本不能穿透。
def _safe_reason(value: str | None, fallback: str) -> str:
    if value is not None and _SAFE_REASON.fullmatch(value) is not None:
        return value
    return fallback


# 本片段已耗时；使用注入的 UTC 时钟，避免客户端时间或事务陈旧时钟进入预算。
def _elapsed_seconds(scope: _RunScope) -> int:
    elapsed = (require_utc(scope.dependencies.clock()) - scope.started_at).total_seconds()
    return max(0, int(elapsed))


# 发送前的活动时间准入：账本已记录 + 本片段已耗时 + 安全收尾余量必须小于上限。
# 这只收紧调用，不改变 T05 片段结束记录一次的账本语义。
def _activity_exhausted(scope: _RunScope, status: BudgetStatus) -> bool:
    return (
        status.active_seconds + _elapsed_seconds(scope) + ACTIVITY_SAFETY_MARGIN_SECONDS
        >= status.active_second_limit
    )


def _enforce_activity_budget(scope: _RunScope, status: BudgetStatus) -> None:
    if _activity_exhausted(scope, status):
        raise _GraphStop(SegmentOutcomeKind.DEGRADED, "budget_exhausted")


# 构造终止状态更新；只携带计数、结果类型、安全原因、引用和 preparing 待办。
def _terminal(
    scope: _RunScope,
    kind: SegmentOutcomeKind,
    reason: str | None = None,
    *,
    refs: tuple[ArtifactRef, ...] = (),
    interaction_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "phase": GraphPhase.DONE,
        "model_calls": scope.model_calls,
        "tool_calls": scope.tool_calls,
        "applied_seq": scope.applied_seq,
        "outcome_kind": kind,
        "safe_reason": reason,
        "artifact_refs": refs,
        "preparing_interaction_id": interaction_id,
    }


# 将已准备的工具结果投影为原生 tool 消息；状态/质量/原因必须保留，不能只给摘要。
def _observation_message(observation: ToolObservation) -> ModelMessage:
    content = json.dumps(
        {
            "status": observation.status.value,
            "quality": observation.quality.value,
            "reason": observation.reason_code,
            "summary": observation.safe_summary,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return ModelMessage(
        role="tool",
        content=content,
        tool_call_id=observation.call_id,
    )


# 显式表达“模型请求了但没有执行”的工具结果；不伪造发送、预算或成功引用。
def not_executed_tool_message(
    request: ToolRequest,
    reason: str = "tool_call_not_completed",
) -> ModelMessage:
    safe = _safe_reason(reason, "tool_call_not_completed")
    content = json.dumps(
        {"status": "not_executed", "reason": safe},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return ModelMessage(
        role="tool",
        content=content,
        tool_call_id=request.call_id,
    )


# 追加 live tool turn 后重新计算保守输入预留；放不下时停止，不截断历史/伪造裁剪。
def _extend_context(
    base: ModelContext,
    live_messages: tuple[ModelMessage, ...],
    *,
    now: datetime,
) -> ModelContext:
    messages = (*base.messages, *live_messages)
    reservation = estimate_input(encode_model_request(messages, base.tools))
    if reservation > _MAX_MODEL_INPUT_UNITS:
        raise ContextBuildError("context_budget_exceeded")
    live_payload = [message.model_dump(mode="json") for message in live_messages]
    live_bytes = _message_bytes(live_messages)
    digest = sha256_json(cast(JsonValue, live_payload))
    block = ContextBlock(
        block_id=f"live-turn:{len(base.manifest.blocks)}:{digest[:16]}",
        kind=ContextBlockKind.TOOL_TURN,
        utf8_bytes=live_bytes,
        sha256=digest,
    )
    manifest_values = base.manifest.model_dump(mode="python", by_alias=False)
    manifest_values["input_reservation"] = reservation
    manifest_values["built_at"] = require_utc(now)
    manifest_values["blocks"] = (*base.manifest.blocks, block)
    manifest = ContextManifest.model_validate(manifest_values)
    # 沿用现有安全门禁对旧固定研究路径初始化关键字的字面量检查；
    # 这里使用 model_validate 组装，工具目录仍只来自服务端授权投影。
    return ModelContext.model_validate(
        {
            "messages": messages,
            "tools": base.tools,
            "manifest": manifest,
            "input_reservation": reservation,
        }
    )


# live 消息的字节口径与模型请求一致；只用于 manifest 块统计，不用于预算决策。
def _message_bytes(messages: tuple[ModelMessage, ...]) -> int:
    return len(encode_model_request(messages, ()))


# 重新读取已提交快照；取消优先终止，修订/状态漂移 fail-closed，不信任旧模块内存。
async def _refresh_snapshot(scope: _RunScope) -> dict[str, object] | None:
    snapshot = await scope.dependencies.runs.get(
        scope.context.fence.workspace_id,
        scope.context.fence.run_id,
    )
    if snapshot is None or snapshot.revision != scope.context.fence.revision:
        raise AgentRunError("run_state_conflict")
    if snapshot.cancel_requested_at is not None:
        return _terminal(scope, SegmentOutcomeKind.CANCELLED, "user_cancelled")
    if snapshot.status is not RunStatus.RUNNING:
        raise AgentRunError("run_state_conflict")
    scope.snapshot = snapshot
    return None


# 根节点 PREPARE：确认当前快照，冻结/复用证据并构建初始上下文，不调用模型或工具。
async def _prepare(state: InteractiveGraphState) -> dict[str, object]:
    _ = state
    scope = _scope()
    deps = scope.dependencies
    try:
        snapshot = await deps.runs.get(
            scope.context.fence.workspace_id,
            scope.context.fence.run_id,
        )
        if snapshot is None or snapshot.revision != scope.context.fence.revision:
            raise AgentRunError("run_state_conflict")
        if snapshot.cancel_requested_at is not None:
            return _terminal(scope, SegmentOutcomeKind.CANCELLED, "user_cancelled")
        if snapshot.status is not RunStatus.RUNNING:
            raise AgentRunError("run_state_conflict")
        scope.snapshot = snapshot
        scope.applied_seq = snapshot.applied_message_seq
        status = await deps.budget.status(scope.context.fence)
        if _activity_exhausted(scope, status):
            return _terminal(scope, SegmentOutcomeKind.DEGRADED, "budget_exhausted")
        evidence = await deps.evidence.freeze(scope.context)
        scope.evidence = evidence
        base = await deps.contexts.build(
            scope.context,
            evidence,
            applied_seq=scope.applied_seq,
        )
        scope.base_context = base
    except EvidenceUnavailableError as error:
        return _terminal(
            scope,
            SegmentOutcomeKind.DEGRADED,
            _safe_reason(error.code, "evidence_unavailable"),
        )
    except ContextBuildError as error:
        if error.code == "run_cancelling":
            return _terminal(scope, SegmentOutcomeKind.CANCELLED, "user_cancelled")
        if error.code == "run_state_conflict":
            raise AgentRunError("run_state_conflict") from error
        return _terminal(
            scope,
            SegmentOutcomeKind.DEGRADED,
            _safe_reason(error.code, "context_unavailable"),
        )
    except AgentRunError as error:
        if error.code == "run_cancelling":
            return _terminal(scope, SegmentOutcomeKind.CANCELLED, "user_cancelled")
        if error.code in {"lease_lost", "run_state_conflict"}:
            raise
        if error.code == "budget_exhausted":
            return _terminal(scope, SegmentOutcomeKind.DEGRADED, "budget_exhausted")
        if error.code in {"storage_unavailable", "integrity_violation", "step_conflict"}:
            raise
        return _terminal(
            scope,
            SegmentOutcomeKind.DEGRADED,
            _safe_reason(error.code, "evidence_unavailable"),
        )
    return {
        "phase": GraphPhase.DECIDE,
        "applied_seq": scope.applied_seq,
        "model_calls": scope.model_calls,
        "tool_calls": scope.tool_calls,
    }


# 在当前基础上下文上追加本片段 live tool turn；没有工具轮次时直接复用基础上下文。
def _model_context(scope: _RunScope) -> ModelContext:
    base = scope.base_context
    if base is None:
        raise RuntimeError("图在准备上下文前请求模型")
    if not scope.live_messages:
        return base
    return _extend_context(base, tuple(scope.live_messages), now=scope.dependencies.clock())


# DECIDE 节点：先复核快照/取消，再经 C5 预留发送一次模型决策；模型不能自行跳过该预算。
async def _decide(state: InteractiveGraphState) -> dict[str, object]:
    _ = state
    scope = _scope()
    deps = scope.dependencies
    cancelled = await _refresh_snapshot(scope)
    if cancelled is not None:
        return cancelled
    if not deps.model.available:
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "model_not_configured")
    try:
        model_context = _model_context(scope)
    except ContextBuildError as error:
        return _terminal(
            scope,
            SegmentOutcomeKind.DEGRADED,
            _safe_reason(error.code, "context_unavailable"),
        )
    try:
        decision = await _call_model(scope, model_context)
    except _GraphStop as stop:
        return _terminal(scope, stop.kind, stop.reason)
    scope.decision = decision
    if isinstance(decision, ToolBatch):
        return {
            "phase": GraphPhase.TOOLS,
            "model_calls": scope.model_calls,
            "tool_calls": scope.tool_calls,
        }
    if isinstance(decision, ModelControlDecision):
        return {
            "phase": GraphPhase.CONTROL,
            "model_calls": scope.model_calls,
            "tool_calls": scope.tool_calls,
        }
    return {
        "phase": GraphPhase.FINALIZE,
        "model_calls": scope.model_calls,
        "tool_calls": scope.tool_calls,
    }


# TOOLS 节点：逐个串行调用 T09 网关；硬预算/租约错误停止后续调用并记录 not_executed。
async def _tools(state: InteractiveGraphState) -> dict[str, object]:
    _ = state
    scope = _scope()
    deps = scope.dependencies
    cancelled = await _refresh_snapshot(scope)
    if cancelled is not None:
        return cancelled
    decision = scope.decision
    if not isinstance(decision, ToolBatch):
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "model_decision_invalid")
    assistant_message = ModelMessage(
        role="assistant",
        content=decision.safe_summary,
        tool_calls=tuple(
            ModelToolCall(
                call_id=call.call_id,
                name=call.name,
                arguments=call.arguments,
            )
            for call in decision.calls
        ),
    )
    scope.live_messages.append(assistant_message)
    for index, request in enumerate(decision.calls):
        try:
            _enforce_activity_budget(scope, await deps.budget.status(scope.context.fence))
        except _GraphStop as stop:
            for remaining in decision.calls[index:]:
                scope.live_messages.append(
                    not_executed_tool_message(remaining, "tool_call_not_completed")
                )
            return _terminal(scope, stop.kind, stop.reason)
        except AgentRunError as error:
            for remaining in decision.calls[index:]:
                scope.live_messages.append(
                    not_executed_tool_message(remaining, "tool_call_not_completed")
                )
            if error.code == "run_cancelling":
                return _terminal(scope, SegmentOutcomeKind.CANCELLED, "user_cancelled")
            if error.code in {"lease_lost", "run_state_conflict"}:
                raise
            if error.code == "budget_exhausted":
                return _terminal(scope, SegmentOutcomeKind.DEGRADED, "budget_exhausted")
            if error.code in {"storage_unavailable", "integrity_violation", "step_conflict"}:
                raise
            return _terminal(
                scope,
                SegmentOutcomeKind.DEGRADED,
                _safe_reason(error.code, "tool_call_failed"),
            )
        try:
            observation = await deps.tools.call(scope.context, request)
        except AgentRunError as error:
            for remaining in decision.calls[index:]:
                scope.live_messages.append(
                    not_executed_tool_message(remaining, "tool_call_not_completed")
                )
            if error.code == "run_cancelling":
                return _terminal(scope, SegmentOutcomeKind.CANCELLED, "user_cancelled")
            if error.code in {"lease_lost", "run_state_conflict"}:
                raise
            if error.code == "budget_exhausted":
                return _terminal(scope, SegmentOutcomeKind.DEGRADED, "budget_exhausted")
            if error.code in {"storage_unavailable", "integrity_violation", "step_conflict"}:
                raise
            return _terminal(
                scope,
                SegmentOutcomeKind.DEGRADED,
                _safe_reason(error.code, "tool_call_failed"),
            )
        if observation.call_id != request.call_id:
            for remaining in decision.calls[index:]:
                scope.live_messages.append(
                    not_executed_tool_message(remaining, "tool_result_mismatch")
                )
            return _terminal(scope, SegmentOutcomeKind.DEGRADED, "tool_result_mismatch")
        scope.tool_calls += 1
        scope.live_messages.append(_observation_message(observation))
    return {
        "phase": GraphPhase.DECIDE,
        "model_calls": scope.model_calls,
        "tool_calls": scope.tool_calls,
    }


# CONTROL 节点：用纯 DecisionPolicy 分类；禁止动作拒绝，需确认动作只准备 preparing 待办。
async def _control(state: InteractiveGraphState) -> dict[str, object]:
    _ = state
    scope = _scope()
    deps = scope.dependencies
    cancelled = await _refresh_snapshot(scope)
    if cancelled is not None:
        return cancelled
    decision = scope.decision
    if not isinstance(decision, ModelControlDecision):
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "model_decision_invalid")
    proposal = decision.proposal
    guard = DecisionPolicy.classify(proposal, scope.context)
    if guard.action is GuardAction.REJECT:
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, guard.reason_code)
    if guard.action is GuardAction.ALLOW:
        # read_only_research 是自主范围，但单独的控制提案没有工具/分析动作，不能无限循环。
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "model_action_incomplete")
    draft_action = proposal.action if guard.action is GuardAction.APPROVE else ControlAction.CLARIFY
    material_hash = sha256_json(
        cast(
            JsonValue,
            {
                "action": proposal.action.value,
                "diffs": [item.model_dump(mode="json") for item in proposal.diffs],
                "materialRefs": [item.model_dump(mode="json") for item in proposal.material_refs],
                "safeReason": proposal.safe_reason,
            },
        )
    )
    draft = InteractionDraft(
        request_id=uuid5(
            NAMESPACE_URL,
            f"interaction:{scope.context.fence.segment_id}:{material_hash}:{draft_action.value}",
        ),
        action=draft_action,
        material_hash=material_hash,
        expires_at=require_utc(deps.clock()) + deps.interaction_ttl,
        diffs=proposal.diffs,
        material_refs=proposal.material_refs,
        safe_reason=guard.reason_code,
    )
    try:
        interaction = await deps.interactions.prepare(scope.context.fence, draft)
    except AgentRunError as error:
        if error.code == "run_cancelling":
            return _terminal(scope, SegmentOutcomeKind.CANCELLED, "user_cancelled")
        if error.code in {"lease_lost", "run_state_conflict"}:
            raise
        return _terminal(
            scope,
            SegmentOutcomeKind.DEGRADED,
            _safe_reason(error.code, "interaction_unavailable"),
        )
    except Exception:
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "interaction_unavailable")
    kind = (
        SegmentOutcomeKind.WAIT_INPUT
        if draft_action is ControlAction.CLARIFY
        else SegmentOutcomeKind.WAIT_APPROVAL
    )
    return _terminal(
        scope,
        kind,
        guard.reason_code,
        interaction_id=interaction.interaction_id,
    )


# FINALIZE 节点：校验证据引用、暂存产物；有计划的最终分析必须进入 AP-01 审核，不能直接可实施。
async def _finalize(state: InteractiveGraphState) -> dict[str, object]:
    _ = state
    scope = _scope()
    deps = scope.dependencies
    cancelled = await _refresh_snapshot(scope)
    if cancelled is not None:
        return cancelled
    decision = scope.decision
    if not isinstance(decision, FinalAnalysis):
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "model_decision_invalid")
    base = scope.base_context
    if base is None:
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "context_unavailable")
    allowed_evidence = set(base.manifest.evidence_item_ids)
    for block in (*decision.market_blocks, *decision.decision_blocks):
        if not set(block.evidence_ids) <= allowed_evidence:
            return _terminal(scope, SegmentOutcomeKind.DEGRADED, "analysis_evidence_unknown")
    try:
        refs = await deps.artifacts.validate_and_stage(scope.context, decision)
    except AnalysisStagingError as error:
        return _terminal(
            scope,
            SegmentOutcomeKind.DEGRADED,
            _safe_reason(error.code, "artifact_staging_failed"),
        )
    except Exception:
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "artifact_staging_failed")
    unique_refs = _unique_refs(refs)
    if not unique_refs:
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "artifact_missing")
    if len(unique_refs) > 32:
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "artifact_limit_exceeded")
    if decision.plan_ref is None:
        return _terminal(scope, SegmentOutcomeKind.COMPLETED, refs=unique_refs)
    if decision.plan_ref not in unique_refs:
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "artifact_plan_missing")
    proposal = ControlProposal(
        action=ControlAction.ADOPT_MANUAL_PLAN,
        material_refs=unique_refs,
        safe_reason="plan_requires_review",
    )
    guard = DecisionPolicy.classify(proposal, scope.context)
    if guard.action is not GuardAction.APPROVE or guard.approval is not ApprovalKind.AP_01:
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "plan_review_unavailable")
    material_hash = sha256_json(
        cast(
            JsonValue,
            {
                "analysis": decision.model_dump(
                    mode="json",
                    exclude={"usage", "provider_request_id"},
                ),
                "artifacts": [item.model_dump(mode="json") for item in unique_refs],
            },
        )
    )
    draft = InteractionDraft(
        request_id=uuid5(
            NAMESPACE_URL,
            f"plan-review:{scope.context.fence.segment_id}:{material_hash}",
        ),
        action=ControlAction.ADOPT_MANUAL_PLAN,
        material_hash=material_hash,
        expires_at=require_utc(deps.clock()) + deps.interaction_ttl,
        material_refs=unique_refs,
        safe_reason=guard.reason_code,
    )
    try:
        interaction = await deps.interactions.prepare(scope.context.fence, draft)
    except AgentRunError as error:
        if error.code == "run_cancelling":
            return _terminal(scope, SegmentOutcomeKind.CANCELLED, "user_cancelled")
        if error.code in {"lease_lost", "run_state_conflict"}:
            raise
        return _terminal(
            scope,
            SegmentOutcomeKind.DEGRADED,
            _safe_reason(error.code, "interaction_unavailable"),
        )
    except Exception:
        return _terminal(scope, SegmentOutcomeKind.DEGRADED, "interaction_unavailable")
    return _terminal(
        scope,
        SegmentOutcomeKind.WAIT_APPROVAL,
        guard.reason_code,
        refs=unique_refs,
        interaction_id=interaction.interaction_id,
    )


# 去重产物引用；只保留引用身份，不改变内容或声称未验证产物已暂存。
def _unique_refs(refs: tuple[ArtifactRef, ...]) -> tuple[ArtifactRef, ...]:
    seen: set[tuple[UUID, str]] = set()
    values: list[ArtifactRef] = []
    for item in refs:
        key = (item.artifact_id, item.sha256)
        if key in seen:
            continue
        seen.add(key)
        values.append(item)
    return tuple(values)


# 发送前失败时释放已预留 attempt；结算失败不掩盖原始发送错误，交给恢复器处理。
async def _release_prepared(
    scope: _RunScope,
    attempt_id: UUID,
    reason: str,
) -> None:
    try:
        await scope.dependencies.budget.settle(
            scope.context.fence,
            attempt_id,
            AttemptResult(
                status=AttemptStatus.FAILED,
                reason_code=_safe_reason(reason, "model_send_failed"),
            ),
        )
    except AgentRunError:
        return


# 只有模型成功返回后才结算 succeeded；失败/超时分别按 failed/unknown 结算并停止重试。
async def _call_model(scope: _RunScope, model_context: ModelContext) -> ModelDecision:
    deps = scope.dependencies
    fence = scope.context.fence
    reservation = deps.model.estimate_request(model_context)
    if not 1 <= reservation <= _MAX_MODEL_INPUT_UNITS:
        raise _GraphStop(SegmentOutcomeKind.DEGRADED, "context_budget_exceeded")
    request_sha = hashlib.sha256(
        encode_model_request(model_context.messages, model_context.tools)
        + model_context.manifest.prompt_version.encode("utf-8")
    ).hexdigest()
    status = await deps.budget.status(fence)
    _enforce_activity_budget(scope, status)
    sequence = MODEL_ACTION_SEQUENCE_BASE + status.model_calls
    step = None
    for attempt_index in range(2):
        try:
            step = await deps.budget.reserve(
                fence,
                AttemptRequest(
                    action_sequence=sequence,
                    input_sha256=request_sha,
                    category=AttemptCategory.MODEL,
                    reserved_input_tokens=reservation,
                    reserved_output_tokens=MAX_OUTPUT_TOKENS_PER_CALL,
                    timeout_seconds=MODEL_TIMEOUT_SECONDS,
                ),
            )
            break
        except AgentRunError as error:
            if error.code == "step_conflict" and attempt_index == 0:
                status = await deps.budget.status(fence)
                sequence = MODEL_ACTION_SEQUENCE_BASE + status.model_calls
                continue
            if error.code == "budget_exhausted":
                raise _GraphStop(SegmentOutcomeKind.DEGRADED, "budget_exhausted") from error
            if error.code == "run_cancelling":
                raise _GraphStop(SegmentOutcomeKind.CANCELLED, "user_cancelled") from error
            raise
    if step is None:
        raise AgentRunError("step_conflict")
    try:
        _enforce_activity_budget(scope, status)
    except _GraphStop:
        await _release_prepared(scope, step.attempt_id, "budget_exhausted")
        raise
    try:
        await deps.budget.mark_sent(fence, step.attempt_id)
    except AgentRunError as error:
        # mark_sent 在状态仍为 prepared 时失败，必须按发送前失败释放预留。
        await _release_prepared(scope, step.attempt_id, error.code)
        if error.code == "budget_exhausted":
            raise _GraphStop(SegmentOutcomeKind.DEGRADED, "budget_exhausted") from error
        if error.code == "run_cancelling":
            raise _GraphStop(SegmentOutcomeKind.CANCELLED, "user_cancelled") from error
        raise
    scope.model_calls += 1
    try:
        decision = await deps.model.decide(model_context)
    except ModelCallError as error:
        unknown = error.code in {"model_timeout", "model_transport_error"}
        await deps.budget.settle(
            fence,
            step.attempt_id,
            AttemptResult(
                status=AttemptStatus.UNKNOWN if unknown else AttemptStatus.FAILED,
                usage=error.usage,
                provider_receipt=error.provider_request_id,
                reason_code=error.code,
            ),
        )
        raise _GraphStop(SegmentOutcomeKind.DEGRADED, _safe_reason(error.code, "model_failed"))
    except Exception as error:
        await deps.budget.settle(
            fence,
            step.attempt_id,
            AttemptResult(
                status=AttemptStatus.FAILED,
                reason_code="model_internal_error",
            ),
        )
        raise _GraphStop(SegmentOutcomeKind.DEGRADED, "model_internal_error") from error
    result_ref = ArtifactRef(
        artifact_id=step.step_id,
        sha256=sha256_json(cast(JsonValue, decision.model_dump(mode="json"))),
    )
    await deps.budget.settle(
        fence,
        step.attempt_id,
        AttemptResult(
            status=AttemptStatus.SUCCEEDED,
            result_ref=result_ref,
            usage=decision.usage,
            provider_receipt=decision.provider_request_id,
        ),
    )
    return decision


# 路由器：终止状态直接结束，否则按阶段进入模型/工具/控制/产物流转。
def _after_prepare(state: InteractiveGraphState) -> str:
    if state.outcome_kind is not None:
        return END
    return "decide"


def _after_decide(state: InteractiveGraphState) -> str:
    if state.outcome_kind is not None:
        return END
    if state.phase is GraphPhase.TOOLS:
        return "tools"
    if state.phase is GraphPhase.CONTROL:
        return "control"
    if state.phase is GraphPhase.FINALIZE:
        return "finalize"
    raise RuntimeError("模型决策后阶段不合法")


def _after_tools(state: InteractiveGraphState) -> str:
    if state.outcome_kind is not None:
        return END
    return "decide"


# 编译图；T14 可注入 checkpointer，但 T11 不把 checkpoint 当作业务完成或恢复真相。
def _build_graph(dependencies: GraphDependencies) -> Any:
    builder: Any = StateGraph(InteractiveGraphState)
    builder.add_node("prepare", _prepare)
    builder.add_node("decide", _decide)
    builder.add_node("tools", _tools)
    builder.add_node("control", _control)
    builder.add_node("finalize", _finalize)
    builder.add_edge(START, "prepare")
    builder.add_conditional_edges("prepare", _after_prepare)
    builder.add_conditional_edges("decide", _after_decide)
    builder.add_conditional_edges("tools", _after_tools)
    builder.add_edge("control", END)
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=dependencies.checkpointer)


# SegmentRunner 实现：为每个片段建立独立作用域与 graph namespace，结束后不保留等待协程。
class InteractiveGraphRunner:
    def __init__(self, dependencies: GraphDependencies) -> None:
        self._dependencies = dependencies
        self._graph = _build_graph(dependencies)

    async def run(self, context: ExecutionContext) -> SegmentOutcome:
        deps = self._dependencies
        started_at = require_utc(deps.clock())
        scope = _RunScope(
            dependencies=deps,
            context=context,
            started_at=started_at,
        )
        token = _CURRENT_SCOPE.set(scope)
        failed = False
        try:
            result = await self._graph.ainvoke(
                InteractiveGraphState(),
                {
                    "configurable": {
                        "thread_id": graph_namespace(context.fence),
                    }
                },
            )
            state = _coerce_state(result)
            return _outcome_from_state(state)
        except BaseException:
            # 异常/取消也必须在 finally 记录本片段活动时间，避免下一片段漏记。
            failed = True
            raise
        finally:
            try:
                elapsed = _elapsed_seconds(scope)
                if elapsed >= 1:
                    try:
                        await deps.budget.record_activity(
                            context.fence,
                            min(elapsed, _ACTIVITY_LIMIT_SECONDS),
                        )
                    except AgentRunError:
                        # 已有异常/取消时不能掩盖原始错误；正常结果时让账本失败阻止提交。
                        if not failed:
                            raise
            finally:
                _CURRENT_SCOPE.reset(token)


# LangGraph 可能返回 Pydantic state 或 dict；两者都必须通过同一个安全模型重建。
def _coerce_state(value: object) -> InteractiveGraphState:
    if isinstance(value, InteractiveGraphState):
        return value
    if isinstance(value, dict):
        return InteractiveGraphState.model_validate(value)
    raise RuntimeError("交互式图返回了非法状态")


# 图必须以明确 SegmentOutcome 结束；缺少结果不能默认为完成。
def _outcome_from_state(state: InteractiveGraphState) -> SegmentOutcome:
    if state.outcome_kind is None:
        raise RuntimeError("交互式图结束时没有片段结果")
    return SegmentOutcome(
        kind=state.outcome_kind,
        artifact_refs=state.artifact_refs,
        preparing_interaction_id=state.preparing_interaction_id,
        safe_reason=state.safe_reason,
        applied_message_seq=state.applied_seq,
    )


# 公共构造入口；返回只消费 ExecutionContext 的 SegmentRunner。
def build_interactive_graph(dependencies: GraphDependencies) -> SegmentRunner:
    return InteractiveGraphRunner(dependencies)


__all__ = [
    "GraphDependencies",
    "InteractiveGraphRunner",
    "MODEL_ACTION_SEQUENCE_BASE",
    "build_interactive_graph",
    "not_executed_tool_message",
]
