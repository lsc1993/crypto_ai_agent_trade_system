# T11 图与模型循环测试的共享替身：只构造合成上下文、证据和端口，不连接数据库/网络/模型。
# 这些替身仅证明图的路由、预算预留/结算、等待发布和连接工具守卫的边界；
# 真实模型协议由 test_deepseek 的 MockTransport 证明，真实事务仍由后续任务验证。
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.agent.interactive.context import (
    ContextManifest,
    ModelContext,
    ModelMessage,
    ModelTool,
    encode_model_request,
)
from app.agent.interactive.context_budget import estimate_input
from app.agent.interactive.model_port import (
    ClaimBlock,
    FinalAnalysis,
    ModelControlDecision,
    ToolBatch,
)
from app.agent.interactive.tools.contracts import (
    ToolObservation,
    ToolObservationStatus,
    ToolQuality,
    ToolRequest,
)
from app.agent_runs.attempts import (
    AttemptRequest,
    AttemptResult,
    AttemptStatus,
    StepAttempt,
    TokenUsage,
)
from app.agent_runs.budget import BudgetStatus, initial_budget_limits
from app.agent_runs.contracts import (
    AgentRunError,
    AgentRunErrorCode,
    RunInput,
    RunSnapshot,
    RunStatus,
)
from app.agent_runs.decisions import ControlAction, ControlProposal, ProposalDiff
from app.agent_runs.interactions import (
    HumanInteraction,
    InteractionDraft,
    InteractionStatus,
)
from app.agent_runs.segments import (
    CompletionDecision,
    CompletionDecisionKind,
    ExecutionContext,
    RunFence,
    SegmentOutcome,
)
from app.market.contracts import MarketTimeframe
from app.research.evidence import EvidenceEpoch, EvidenceItem, EvidenceQuality
from app.shared.agent_types import (
    ArtifactRef,
    JsonObject,
    ProductKey,
    VersionRef,
    sha256_json,
)

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
SYNTHETIC_WORKSPACE_ID = uuid4()
SYNTHETIC_RUN_ID = uuid4()
SYNTHETIC_STRATEGY_REF = VersionRef(version_id=uuid4(), sha256="a" * 64)
SYNTHETIC_EVIDENCE_ID = uuid4()


# 构造一个最小但可验证的任务输入；策略与目标均为合成值，不含账户或财务资料。
def run_input(context: ExecutionContext) -> RunInput:
    return RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1,),
        goal="合成研究目标",
        strategy=context.strategy_ref,
        parameters={"threshold": "1"},
    )


# 构造带有效围栏的执行上下文；工具目录指纹与图测试共享，避免伪造权限。
def context(
    *,
    policy_version: str = "interactive_planning_v1",
    tool_catalog_sha256: str | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        fence=RunFence(
            workspace_id=SYNTHETIC_WORKSPACE_ID,
            run_id=SYNTHETIC_RUN_ID,
            revision=1,
            segment_id=uuid4(),
            owner=uuid4(),
            lease_epoch=1,
        ),
        strategy_ref=SYNTHETIC_STRATEGY_REF,
        tool_catalog_sha256=tool_catalog_sha256 or "b" * 64,
        policy_version=policy_version,
        budget_authorization_id=uuid4(),
    )


# 构造 running 任务快照；cancelled_at 可用于验证运行中取消不会继续模型/工具调用。
def snapshot(
    execution_context: ExecutionContext,
    *,
    cancelled_at: datetime | None = None,
    applied_seq: int = 0,
    received_seq: int = 0,
) -> RunSnapshot:
    return RunSnapshot(
        run_id=execution_context.fence.run_id,
        workspace_id=execution_context.fence.workspace_id,
        thread_id=uuid4(),
        revision=execution_context.fence.revision,
        status=RunStatus.RUNNING,
        state_version=2,
        input=run_input(execution_context),
        received_message_seq=received_seq,
        applied_message_seq=applied_seq,
        created_at=NOW,
        updated_at=NOW,
        started_at=NOW,
        cancel_requested_at=cancelled_at,
    )


# 构造一条合成公开证据；内容与指纹一致，但不代表真实市场数据。
def evidence_epoch() -> EvidenceEpoch:
    content: JsonObject = {"kind": "synthetic_evidence", "quality": "valid"}
    item = EvidenceItem(
        evidence_id=SYNTHETIC_EVIDENCE_ID,
        kind="market_detail",
        source="synthetic_public_fixture",
        observed_at=NOW - timedelta(minutes=2),
        available_at=NOW - timedelta(minutes=1),
        fetched_at=NOW - timedelta(minutes=1),
        payload_sha256=sha256_json(content),
        quality=EvidenceQuality.VALID,
        calculation_version="synthetic_v1",
        content=content,
    )
    return EvidenceEpoch.seal(
        analysis_as_of=NOW,
        sealed_at=NOW,
        items=(item,),
    )


# 构造上下文清单；输入预留由调用方传入，确保与 ModelContext 的校验一致。
def manifest(
    execution_context: ExecutionContext,
    *,
    input_reservation: int,
    applied_seq: int = 0,
    received_seq: int = 0,
    evidence_id: UUID = SYNTHETIC_EVIDENCE_ID,
) -> ContextManifest:
    return ContextManifest(
        workspace_id=execution_context.fence.workspace_id,
        run_id=execution_context.fence.run_id,
        revision=execution_context.fence.revision,
        segment_id=execution_context.fence.segment_id,
        strategy_ref=execution_context.strategy_ref,
        evidence_epoch_id=uuid4(),
        evidence_sha256="d" * 64,
        analysis_as_of=NOW,
        analysis_mode="current",
        applied_seq=applied_seq,
        received_seq=received_seq,
        evidence_item_ids=(evidence_id,),
        tool_catalog_sha256=execution_context.tool_catalog_sha256,
        prompt_version="interactive-context-v1",
        schema_version="model-context-v1",
        input_reservation=input_reservation,
        built_at=NOW,
    )


# 构造模型可见工具投影；只读工具的 Schema 与 T09 目录风格一致，不含执行能力。
def model_tool() -> ModelTool:
    return ModelTool(
        name="read_market_evidence",
        version="v1",
        description="读取当前冻结的合成公开行情证据。",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"symbol": {"type": "string"}},
            "required": [],
        },
    )


# 构造基础上下文；content_repeat 用于制造接近单次预算上限的输入。
def model_context(
    execution_context: ExecutionContext,
    *,
    content_repeat: int = 0,
    tools: tuple[ModelTool, ...] | None = None,
) -> ModelContext:
    tool_values = (model_tool(),) if tools is None else tools
    content = "合成系统约束" + ("x" * content_repeat)
    messages = (
        ModelMessage(role="system", content="你是受治理的合成研究助手。"),
        ModelMessage(role="user", content=content),
    )
    reservation = estimate_input(encode_model_request(messages, tool_values))
    return ModelContext(
        messages=messages,
        tools=tool_values,
        manifest=manifest(execution_context, input_reservation=reservation),
        input_reservation=reservation,
    )


# 构造工具观察替身；默认成功结果带引用，失败结果不带结果引用。
def tool_observation(
    execution_context: ExecutionContext,
    request: ToolRequest,
    *,
    summary: str = "合成只读工具观察",
    status: ToolObservationStatus = ToolObservationStatus.OK,
    reason_code: str | None = None,
) -> ToolObservation:
    succeeded = status in {ToolObservationStatus.OK, ToolObservationStatus.DEGRADED}
    return ToolObservation(
        status=status,
        tool_name=request.name,
        tool_version="v1",
        tool_catalog_sha256=execution_context.tool_catalog_sha256,
        call_id=request.call_id,
        arguments_sha256=sha256_json(request.arguments),
        step_id=uuid4(),
        attempt_id=uuid4(),
        result_ref=ArtifactRef(artifact_id=uuid4(), sha256="e" * 64) if succeeded else None,
        safe_summary=summary,
        quality=ToolQuality.VALID if succeeded else ToolQuality.MISSING,
        reason_code=reason_code,
        observed_at=NOW,
        sent=True,
    )


# 记录运行的只读仓储替身；可按用例切换取消标记，不模拟数据库事务。
class FakeRuns:
    def __init__(self, value: RunSnapshot | list[RunSnapshot]) -> None:
        self._values = value if isinstance(value, list) else [value]
        self._index = 0
        self.get_calls: list[tuple[UUID, UUID]] = []

    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None:
        self.get_calls.append((workspace_id, run_id))
        index = min(self._index, len(self._values) - 1)
        self._index += 1
        return self._values[index]


# C5 预算账本替身；默认允许预留，可在指定第 N 次预留注入稳定错误。
class FakeBudget:
    def __init__(
        self,
        *,
        reserve_error_at: int | None = None,
        reserve_error: AgentRunErrorCode = "budget_exhausted",
        mark_sent_error_at: int | None = None,
        mark_sent_error: AgentRunErrorCode = "budget_exhausted",
        initial_active_seconds: int = 0,
        on_mark_sent: Callable[[], None] | None = None,
    ) -> None:
        self.reserve_error_at = reserve_error_at
        self.reserve_error: AgentRunErrorCode = reserve_error
        self.mark_sent_error_at = mark_sent_error_at
        self.mark_sent_error: AgentRunErrorCode = mark_sent_error
        self._active_seconds = initial_active_seconds
        self._on_mark_sent = on_mark_sent
        self.reserve_calls: list[AttemptRequest] = []
        self.marked_sent: list[UUID] = []
        self.settled: list[tuple[UUID, AttemptResult]] = []
        self.activity: list[int] = []

    def _status(self) -> BudgetStatus:
        limits = initial_budget_limits()
        count = len(self.reserve_calls)
        return BudgetStatus(
            model_limit=limits.model_calls,
            tool_limit=limits.tool_calls,
            input_token_limit=limits.input_tokens,
            output_token_limit=limits.output_tokens,
            active_second_limit=limits.active_seconds,
            transport_limit=limits.transport_calls,
            model_calls=count,
            model_sent=len(self.marked_sent),
            tool_calls=0,
            tool_sent=0,
            transport_calls=0,
            transport_sent=0,
            input_tokens=sum(item.reserved_input_tokens for item in self.reserve_calls),
            output_tokens=sum(item.reserved_output_tokens for item in self.reserve_calls),
            active_seconds=self._active_seconds,
        )

    async def status(self, fence: RunFence) -> BudgetStatus:
        _ = fence
        return self._status()

    async def reserve(self, fence: RunFence, request: AttemptRequest) -> StepAttempt:
        if (
            self.reserve_error_at is not None
            and len(self.reserve_calls) + 1 == self.reserve_error_at
        ):
            self.reserve_calls.append(request)
            raise AgentRunError(self.reserve_error)
        self.reserve_calls.append(request)
        return StepAttempt(
            attempt_id=uuid4(),
            step_id=uuid4(),
            run_id=fence.run_id,
            revision=fence.revision,
            segment_id=fence.segment_id,
            attempt_number=1,
            category=request.category,
            action_sequence=request.action_sequence,
            input_sha256=request.input_sha256,
            status=AttemptStatus.PREPARED,
            reserved_input_tokens=request.reserved_input_tokens,
            reserved_output_tokens=request.reserved_output_tokens,
            created_at=NOW,
        )

    async def mark_sent(self, fence: RunFence, attempt_id: UUID) -> None:
        _ = fence
        self.marked_sent.append(attempt_id)
        if self._on_mark_sent is not None:
            self._on_mark_sent()
        if self.mark_sent_error_at is not None and len(self.marked_sent) == self.mark_sent_error_at:
            raise AgentRunError(self.mark_sent_error)

    async def settle(
        self,
        fence: RunFence,
        attempt_id: UUID,
        result: AttemptResult,
    ) -> None:
        _ = fence
        self.settled.append((attempt_id, result))

    async def record_activity(self, fence: RunFence, seconds: int) -> BudgetStatus:
        _ = fence
        self.activity.append(seconds)
        self._active_seconds += seconds
        return self._status()

    async def append_authorization(
        self,
        fence: RunFence,
        limits: Any,
        *,
        authorization_ref: UUID,
        reason: str,
    ) -> BudgetStatus:
        _ = fence, limits, authorization_ref, reason
        return self._status()


# 证据端口替身：默认返回合成 epoch；可按用例注入领域异常。
class FakeEvidence:
    def __init__(
        self, value: EvidenceEpoch | None = None, *, error: Exception | None = None
    ) -> None:
        self.value = value or evidence_epoch()
        self.error = error
        self.calls: list[ExecutionContext] = []

    async def freeze(self, context: ExecutionContext, *, refresh: bool = False) -> EvidenceEpoch:
        _ = refresh
        self.calls.append(context)
        if self.error is not None:
            raise self.error
        return self.value


# 上下文构建端口替身：记录 build 参数并返回预先构造的安全上下文。
class FakeContexts:
    def __init__(
        self, value: ModelContext | None = None, *, error: Exception | None = None
    ) -> None:
        self.value = value
        self.error = error
        self.calls: list[tuple[ExecutionContext, EvidenceEpoch, int]] = []

    async def build(
        self,
        context: ExecutionContext,
        evidence: EvidenceEpoch,
        *,
        applied_seq: int,
    ) -> ModelContext:
        self.calls.append((context, evidence, applied_seq))
        if self.error is not None:
            raise self.error
        assert self.value is not None
        return self.value


# 工具端口替身：记录每次调用并返回合成观察；可按调用序号注入稳定错误。
class FakeTools:
    def __init__(
        self,
        *,
        summary: str = "合成只读工具观察",
        status: ToolObservationStatus = ToolObservationStatus.OK,
        reason_code: str | None = None,
        error_at: int | None = None,
        error: Exception | None = None,
    ) -> None:
        self.summary = summary
        self.status = status
        self.reason_code = reason_code
        self.error_at = error_at
        self.error = error
        self.calls: list[ToolRequest] = []

    async def call(self, context: ExecutionContext, request: ToolRequest) -> ToolObservation:
        self.calls.append(request)
        if self.error_at is not None and len(self.calls) == self.error_at:
            raise self.error or AgentRunError("budget_exhausted")
        return tool_observation(
            context,
            request,
            summary=self.summary,
            status=self.status,
            reason_code=self.reason_code,
        )


# 模型端口替身：按脚本逐个返回 ToolBatch/控制提案/最终分析，或抛出预置异常。
class FakeModel:
    requested_model = "synthetic-model"
    available = True

    def __init__(
        self, decisions: list[Any], *, on_decide: Callable[[], None] | None = None
    ) -> None:
        self._decisions = list(decisions)
        self._on_decide = on_decide
        self.contexts: list[ModelContext] = []

    def estimate_request(self, context: ModelContext) -> int:
        return context.input_reservation

    async def decide(self, context: ModelContext) -> Any:
        self.contexts.append(context)
        if not self._decisions:
            raise AssertionError("模型替身没有剩余脚本")
        decision = self._decisions.pop(0)
        if self._on_decide is not None:
            self._on_decide()
        if isinstance(decision, BaseException):
            raise decision
        return decision


# 交互端口替身：把 preparing 待办按草稿构造为本地对象，不发布 pending。
class FakeInteractions:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.drafts: list[InteractionDraft] = []
        self.fences: list[RunFence] = []
        self.prepared: list[HumanInteraction] = []

    async def prepare(self, fence: RunFence, draft: InteractionDraft) -> HumanInteraction:
        if self.error is not None:
            raise self.error
        self.fences.append(fence)
        self.drafts.append(draft)
        interaction = HumanInteraction(
            interaction_id=uuid4(),
            workspace_id=fence.workspace_id,
            run_id=fence.run_id,
            revision=fence.revision,
            action=draft.action,
            status=InteractionStatus.PREPARING,
            material_hash=draft.material_hash,
            state_version=0,
            expires_at=draft.expires_at,
            diffs=draft.diffs,
            material_refs=draft.material_refs,
            safe_reason=draft.safe_reason,
            created_at=NOW,
        )
        self.prepared.append(interaction)
        return interaction


# 产物暂存替身：记录最终分析并返回引用；失败时抛稳定 AnalysisStagingError。
class FakeStager:
    def __init__(
        self, refs: tuple[ArtifactRef, ...] | None = None, *, error: Exception | None = None
    ) -> None:
        self.refs = refs
        self.error = error
        self.calls: list[tuple[ExecutionContext, FinalAnalysis]] = []

    async def validate_and_stage(
        self,
        context: ExecutionContext,
        analysis: FinalAnalysis,
    ) -> tuple[ArtifactRef, ...]:
        self.calls.append((context, analysis))
        if self.error is not None:
            raise self.error
        if self.refs is not None:
            return self.refs
        return (ArtifactRef(artifact_id=uuid4(), sha256="f" * 64),)


# 组装模型调用批次；只允许最多四项，调用标识唯一。
def tool_batch(*requests: ToolRequest, summary: str = "需要补充只读研究证据。") -> ToolBatch:
    return ToolBatch(calls=requests, safe_summary=summary)


# 构造只读工具请求；参数为合成值。
def tool_request(name: str = "read_market_evidence", call_id: str = "call_1") -> ToolRequest:
    return ToolRequest(name=name, arguments={"symbol": "BTCUSDT"}, call_id=call_id)


# 构造最终分析；可带已暂存计划引用，但不能由模型直接声明可实施。
def final_analysis(
    *,
    plan_ref: ArtifactRef | None = None,
    selected_candidate_id: str | None = None,
    evidence_id: UUID = SYNTHETIC_EVIDENCE_ID,
    usage: TokenUsage | None = TokenUsage(input_tokens=120, output_tokens=60),
) -> FinalAnalysis:
    return FinalAnalysis(
        market_blocks=(
            ClaimBlock(
                text="合成市场结构保持中性，等待更明确的方向确认。",
                evidence_ids=(evidence_id,),
            ),
        ),
        decision_blocks=(
            ClaimBlock(
                text="需要继续观察，当前不生成可手动实施的交易计划。",
                evidence_ids=(evidence_id,),
            ),
        ),
        selected_candidate_id=selected_candidate_id,
        plan_ref=plan_ref,
        no_plan_reasons=() if plan_ref is not None else ("no_valid_candidate",),
        limitations=(),
        safe_summary="合成最终研究分析。",
        usage=usage,
        provider_request_id="synthetic-request-1",
    )


# 构造类型化控制提案；默认为澄清，不授予任何权限。
def control_proposal(
    action: ControlAction = ControlAction.CLARIFY,
    *,
    diffs: tuple[ProposalDiff, ...] = (),
    material_refs: tuple[ArtifactRef, ...] = (),
    safe_reason: str = "user_input_required",
) -> ModelControlDecision:
    return ModelControlDecision(
        proposal=ControlProposal(
            action=action,
            diffs=diffs,
            material_refs=material_refs,
            safe_reason=safe_reason,
        ),
        safe_summary="需要用户确认。",
        usage=TokenUsage(input_tokens=80, output_tokens=20),
        provider_request_id="synthetic-request-2",
    )


# 构造带计划引用的产物引用；只用于证明图会把计划送入待审而非直接可实施。
def plan_ref() -> ArtifactRef:
    return ArtifactRef(artifact_id=uuid4(), sha256="9" * 64)


# 审计协调器替身：只记录治理包装的调用，供 T11 worker 注入测试使用。
class FakeAuditCoordinator:
    def __init__(self) -> None:
        self.requested: list[Any] = []
        self.evaluations: list[Any] = []
        self.started: list[Any] = []
        self.failures: list[Any] = []
        self.failure_committed = True

    async def create_requested_run(self, fence: RunFence, run: Any, event: Any) -> None:
        self.requested.append((fence, run, event))

    async def append_policy_evaluation(self, fence: RunFence, evaluation: Any, event: Any) -> None:
        self.evaluations.append((fence, evaluation, event))

    async def append_started_event(self, fence: RunFence, event: Any) -> None:
        self.started.append((fence, event))

    async def commit_audit_failure(self, fence: RunFence, event: Any) -> bool:
        self.failures.append((fence, event))
        return self.failure_committed

    async def get_audit_trace(self, run_id: UUID) -> None:
        _ = run_id
        return None


# 片段仓储替身：记录提交结果，不回写真实业务状态。
@dataclass
class FakeSegments:
    contexts: list[ExecutionContext]
    commits: list[tuple[RunFence, SegmentOutcome]] = field(
        default_factory=list[tuple[RunFence, SegmentOutcome]]
    )
    heartbeat_calls: int = 0
    recover_calls: int = 0

    async def recover_expired(self) -> int:
        self.recover_calls += 1
        return 0

    async def claim(self, owner: UUID) -> ExecutionContext | None:
        _ = owner
        return self.contexts.pop(0) if self.contexts else None

    async def heartbeat(self, fence: RunFence) -> bool:
        _ = fence
        self.heartbeat_calls += 1
        return True

    async def commit(self, fence: RunFence, outcome: SegmentOutcome) -> CompletionDecision:
        self.commits.append((fence, outcome))
        return CompletionDecision(kind=CompletionDecisionKind.COMMITTED, state_version=3)
