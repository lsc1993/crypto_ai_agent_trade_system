# 实现 C6 逐次工具守卫：权限/版本、参数/范围、预算预留、发送、结果校验与安全观察。
# 每次调用都重新读取任务快照并核对目录指纹；模型文本不能扩大工具、范围、预算或参数 Schema。
# 本模块只调用注入的处理器与 C5 预算账本，不实现 SQL/HTTP/MCP，也不访问账户或交易执行。
from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from app.agent.interactive.tools.contracts import (
    MAX_TOOL_SUMMARY_BYTES,
    TOOL_ACTION_SEQUENCE_BASE,
    JsonObject,
    RegisteredTool,
    ToolContractError,
    ToolHandler,
    ToolObservation,
    ToolObservationStatus,
    ToolQuality,
    ToolRequest,
    ToolResult,
    ToolResultStatus,
    ToolSchemaError,
    validate_tool_arguments,
    validate_tool_result_payload,
)
from app.agent.interactive.tools.registry import ToolRegistry
from app.agent_runs.attempts import (
    AttemptCategory,
    AttemptRequest,
    AttemptResult,
    AttemptStatus,
    StepAttempt,
)
from app.agent_runs.budget import BudgetLedger
from app.agent_runs.contracts import AgentRunError, RunSnapshot, RunStatus
from app.agent_runs.ports import AgentRunReader
from app.agent_runs.segments import ExecutionContext, RunFence
from app.shared.agent_types import (
    ArtifactRef,
    JsonValue,
    require_utc,
    sha256_json,
)

# 同一 run/revision 的重复工具输入复用同一逻辑步骤；进程内缓存只重建最近观察。
_MAX_OBSERVATION_CACHE = 256


# 工具网关：进程内串行执行，先提交预算/发送状态，再调用处理器；任何结果都必须结算。
class ToolGateway:
    def __init__(
        self,
        *,
        runs: AgentRunReader,
        budget: BudgetLedger,
        catalog: ToolRegistry,
        handlers: Mapping[str, ToolHandler],
        policy_version: str = "interactive_planning_v1",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._runs = runs
        self._budget = budget
        self._catalog = catalog
        self._handlers = catalog.bind_handlers(handlers)
        self._policy_version = policy_version
        self._clock = clock or (lambda: datetime.now(UTC))
        # 首期固定并发 1；锁同时阻止两个模型分支对同一任务交错发送。
        self._lock = asyncio.Lock()
        # 只缓存已成功结算的观察，键为逻辑步骤；重启后降级复用持久化引用。
        self._observations: dict[UUID, ToolObservation] = {}
        self._sequences: dict[tuple[UUID, UUID, int, str], int] = {}

    @property
    def catalog(self) -> ToolRegistry:
        return self._catalog

    # 公共入口：所有调用串行化，避免并发工具请求绕过固定并发 1 和短期步骤顺序。
    async def call(
        self,
        context: ExecutionContext,
        request: ToolRequest,
    ) -> ToolObservation:
        async with self._lock:
            return await self._call_locked(context, request)

    async def _call_locked(
        self,
        context: ExecutionContext,
        request: ToolRequest,
    ) -> ToolObservation:
        snapshot = await self._runs.get(
            context.fence.workspace_id,
            context.fence.run_id,
        )
        self._validate_snapshot(context, snapshot)
        assert snapshot is not None
        # C5 状态读取同时验证当前 owner/lease_epoch；拒绝路径也不能只凭旧快照放行。
        budget_status = await self._budget.status(context.fence)
        now = require_utc(self._clock())
        arguments_sha256 = sha256_json(request.arguments)
        tool = self._catalog.get(request.name)
        model_version = self._catalog.model_version(request.name)

        # 策略版本也必须在每次调用时匹配；旧片段不能凭过期授权继续使用工具。
        if context.policy_version != self._policy_version:
            return self._rejected(
                request,
                tool_version=model_version or "unregistered",
                reason_code="policy_not_authorized",
                observed_at=now,
                arguments_sha256=arguments_sha256,
            )
        # 目录指纹不匹配时，连“当前工具版本”都不能信任；拒绝且不预留预算。
        if context.tool_catalog_sha256 != self._catalog.catalog_sha256:
            return self._rejected(
                request,
                tool_version=model_version or "unregistered",
                reason_code="tool_catalog_mismatch",
                observed_at=now,
                arguments_sha256=arguments_sha256,
            )
        if tool is None or model_version is None:
            return self._rejected(
                request,
                tool_version="unregistered",
                reason_code="tool_not_registered",
                observed_at=now,
                arguments_sha256=arguments_sha256,
            )

        try:
            arguments = validate_tool_arguments(tool.input_schema, request.arguments)
        except ToolSchemaError:
            # 已登记工具的 Schema 在目录构造时校验；运行期出现说明目录被篡改。
            return self._rejected(
                request,
                tool_version=model_version,
                reason_code="invalid_tool_schema",
                observed_at=now,
                arguments_sha256=arguments_sha256,
            )
        except ToolContractError:
            return self._rejected(
                request,
                tool_version=model_version,
                reason_code="invalid_arguments",
                observed_at=now,
                arguments_sha256=arguments_sha256,
            )

        scope_reason = _scope_reason(tool, arguments, snapshot)
        if scope_reason is not None:
            return self._rejected(
                request,
                tool_version=model_version,
                reason_code=scope_reason,
                observed_at=now,
                arguments_sha256=arguments_sha256,
            )

        normalized_sha = sha256_json(arguments)
        input_sha256 = self._input_sha256(
            context,
            tool,
            arguments,
        )
        step = await self._reserve_step(
            context.fence,
            input_sha256,
            tool_calls_hint=budget_status.tool_calls,
        )

        # 同一逻辑步骤已成功：不再次发送。进程内缓存可恢复摘要；重启后只复用引用。
        if step.status is AttemptStatus.SUCCEEDED:
            return self._reuse_succeeded(
                request,
                tool=tool,
                tool_version=model_version,
                step=step,
                arguments_sha256=normalized_sha,
                checked_at=require_utc(self._clock()),
            )
        if step.status is not AttemptStatus.PREPARED:
            if step.status is AttemptStatus.UNKNOWN:
                raise AgentRunError("unknown_not_replayable")
            raise AgentRunError("attempt_in_flight")

        # mark_sent 未成功返回时不能调用处理器；保留实际状态交给恢复器，不伪造发送。
        await self._budget.mark_sent(context.fence, step.attempt_id)
        # 发送时刻与结果校验时刻分离：处理器可能执行数秒并产生新的合法观测。
        sent_at = require_utc(self._clock())

        try:
            async with asyncio.timeout(tool.timeout_seconds):
                result = await self._handlers[tool.name].handle(
                    context,
                    snapshot,
                    arguments,
                    sent_at=sent_at,
                )
        except AgentRunError as error:
            # 预算/租约/存储等控制错误必须交给 worker 停止；不能伪装成可继续的普通观察。
            await self._settle_outcome(
                context.fence,
                step,
                status=AttemptStatus.UNKNOWN,
                reason_code=error.code,
            )
            raise
        except TimeoutError:
            checked_at = require_utc(self._clock())
            await self._settle_outcome(
                context.fence,
                step,
                status=AttemptStatus.UNKNOWN,
                reason_code="tool_timeout",
            )
            return self._unsettled_observation(
                request,
                tool=tool,
                tool_version=model_version,
                step=step,
                arguments_sha256=normalized_sha,
                status=ToolObservationStatus.UNKNOWN,
                reason_code="tool_timeout",
                observed_at=checked_at,
            )
        except Exception:
            checked_at = require_utc(self._clock())
            await self._settle_outcome(
                context.fence,
                step,
                status=AttemptStatus.UNKNOWN,
                reason_code="tool_outcome_unknown",
            )
            return self._unsettled_observation(
                request,
                tool=tool,
                tool_version=model_version,
                step=step,
                arguments_sha256=normalized_sha,
                status=ToolObservationStatus.UNKNOWN,
                reason_code="tool_outcome_unknown",
                observed_at=checked_at,
            )

        # 处理器返回类型/形状/Schema/大小/时效均在处理器完成后重新采样校验。
        result_checked_at = require_utc(self._clock())
        try:
            normalized_result = self._validate_handler_result(
                tool,
                result,
                checked_at=result_checked_at,
            )
        except ToolContractError as error:
            await self._settle_outcome(
                context.fence,
                step,
                status=AttemptStatus.FAILED,
                reason_code=error.code,
            )
            return self._unsettled_observation(
                request,
                tool=tool,
                tool_version=model_version,
                step=step,
                arguments_sha256=normalized_sha,
                status=ToolObservationStatus.FAILED,
                reason_code=error.code,
                observed_at=result_checked_at,
            )

        payload = normalized_result.model_dump(mode="json", by_alias=False, exclude_none=True)
        result_ref = normalized_result.result_ref or ArtifactRef(
            artifact_id=step.step_id,
            sha256=sha256_json(payload),
        )
        await self._settle_outcome(
            context.fence,
            step,
            status=AttemptStatus.SUCCEEDED,
            result_ref=result_ref,
        )
        observation = ToolObservation(
            status=(
                ToolObservationStatus.OK
                if normalized_result.status is ToolResultStatus.OK
                else ToolObservationStatus.DEGRADED
            ),
            tool_name=tool.name,
            tool_version=model_version,
            tool_catalog_sha256=self._catalog.catalog_sha256,
            call_id=request.call_id,
            arguments_sha256=normalized_sha,
            step_id=step.step_id,
            attempt_id=step.attempt_id,
            result_ref=result_ref,
            safe_summary=normalized_result.safe_summary,
            quality=normalized_result.quality,
            reason_code=normalized_result.reason_code,
            observed_at=normalized_result.observed_at,
            expires_at=normalized_result.expires_at,
            sent=True,
        )
        self._remember(step.step_id, observation)
        return observation

    # 当前 owner/修订/状态/策略必须仍有效；取消标记优先阻止新的模型/工具调用。
    @staticmethod
    def _validate_snapshot(
        context: ExecutionContext,
        snapshot: RunSnapshot | None,
    ) -> None:
        if snapshot is None:
            raise AgentRunError("run_not_found")
        if snapshot.revision != context.fence.revision or snapshot.status is not RunStatus.RUNNING:
            raise AgentRunError("lease_lost")
        if snapshot.cancel_requested_at is not None:
            raise AgentRunError("run_cancelling")
        if snapshot.input.strategy != context.strategy_ref:
            raise AgentRunError("run_state_conflict")

    # 读取预算状态分配动作序号；同输入复用进程内序号，避免重复逻辑步骤。
    async def _reserve_step(
        self,
        fence: RunFence,
        input_sha256: str,
        *,
        tool_calls_hint: int,
    ) -> StepAttempt:
        key = (fence.workspace_id, fence.run_id, fence.revision, input_sha256)
        for attempt_index in range(2):
            sequence = self._sequences.get(key)
            if sequence is None:
                sequence = TOOL_ACTION_SEQUENCE_BASE + tool_calls_hint
                self._sequences[key] = sequence
            try:
                return await self._budget.reserve(
                    fence,
                    AttemptRequest(
                        action_sequence=sequence,
                        input_sha256=input_sha256,
                        category=AttemptCategory.TOOL,
                    ),
                )
            except AgentRunError as error:
                if error.code == "step_conflict" and attempt_index == 0:
                    # 进程重启/前序发送前失败可能让计数回退；跳过已知序号后重试一次。
                    status = await self._budget.status(fence)
                    retry_sequence = TOOL_ACTION_SEQUENCE_BASE + status.tool_calls
                    self._sequences[key] = max(sequence + 1, retry_sequence)
                    continue
                raise
        raise AgentRunError("step_conflict")

    # 计算稳定输入指纹；包含工具版本、目录、证据/策略版本和规范化参数，不含 call_id。
    def _input_sha256(
        self,
        context: ExecutionContext,
        tool: RegisteredTool,
        arguments: JsonObject,
    ) -> str:
        evidence = context.evidence_epoch
        payload: JsonValue = {
            "tool": tool.name,
            "toolVersion": tool.version,
            "toolCatalogSha256": self._catalog.catalog_sha256,
            "workspaceId": str(context.fence.workspace_id),
            "runId": str(context.fence.run_id),
            "revision": context.fence.revision,
            "strategyRef": context.strategy_ref.model_dump(mode="json", by_alias=False),
            "evidenceEpochId": None if evidence is None else str(evidence.epoch_id),
            "evidenceSha256": None if evidence is None else evidence.sha256,
            "arguments": arguments,
        }
        return sha256_json(payload)

    # 处理器结果先经过 Pydantic 结果类型、目录输出 Schema、大小和未来时间检查。
    @staticmethod
    def _validate_handler_result(
        tool: RegisteredTool,
        result: object,
        *,
        checked_at: datetime,
    ) -> ToolResult:
        if not isinstance(result, ToolResult):
            raise ToolContractError("output_schema_mismatch", "处理器结果类型非法")
        limit = min(tool.max_result_bytes, MAX_TOOL_SUMMARY_BYTES)
        if len(result.safe_summary.encode("utf-8")) > limit:
            raise ToolContractError("output_too_large", "工具摘要超过登记大小上限")
        if result.observed_at > checked_at:
            raise ToolContractError("result_time_in_future", "工具结果观测时间晚于服务端当前时刻")
        if result.expires_at is not None and result.expires_at < result.observed_at:
            raise ToolContractError("result_time_invalid", "工具结果到期时间早于观测时间")
        payload = result.model_dump(mode="json", by_alias=False, exclude_none=True)
        try:
            validate_tool_result_payload(tool.output_schema, payload)
        except ToolSchemaError:
            raise
        except ToolContractError as error:
            raise ToolContractError(
                "output_schema_mismatch", "工具结果不符合输出 Schema"
            ) from error
        if result.expires_at is not None and result.expires_at < checked_at:
            # 已过期结果仍可审计，但不能再作为当前完整观察返回。
            return result.model_copy(
                update={
                    "status": ToolResultStatus.DEGRADED,
                    "quality": ToolQuality.STALE,
                    "reason_code": "result_expired",
                }
            )
        return result

    # 统一结算；失败/未知不携带结果引用，成功必须引用已校验结果。
    async def _settle_outcome(
        self,
        fence: RunFence,
        step: StepAttempt,
        *,
        status: AttemptStatus,
        reason_code: str | None = None,
        result_ref: ArtifactRef | None = None,
    ) -> None:
        await self._budget.settle(
            fence,
            step.attempt_id,
            AttemptResult(
                status=status,
                result_ref=result_ref,
                reason_code=reason_code,
            ),
        )

    # 预发送拒绝：不预留预算、不调用处理器，也不伪造 step/attempt 标识。
    def _rejected(
        self,
        request: ToolRequest,
        *,
        tool_version: str,
        reason_code: str,
        observed_at: datetime,
        arguments_sha256: str,
    ) -> ToolObservation:
        return ToolObservation(
            status=ToolObservationStatus.REJECTED,
            tool_name=request.name,
            tool_version=tool_version,
            tool_catalog_sha256=self._catalog.catalog_sha256,
            call_id=request.call_id,
            arguments_sha256=arguments_sha256,
            result_ref=None,
            safe_summary=f"工具请求被服务端拒绝：{reason_code}。未执行任何外部调用。",
            quality=ToolQuality.UNKNOWN,
            reason_code=reason_code,
            observed_at=observed_at,
            expires_at=None,
            sent=False,
        )

    # 已预留但未成功的结果：保留 step/attempt 便于运行记录关联失败或未知。
    def _unsettled_observation(
        self,
        request: ToolRequest,
        *,
        tool: RegisteredTool,
        tool_version: str,
        step: StepAttempt,
        arguments_sha256: str,
        status: ToolObservationStatus,
        reason_code: str,
        observed_at: datetime,
    ) -> ToolObservation:
        return ToolObservation(
            status=status,
            tool_name=tool.name,
            tool_version=tool_version,
            tool_catalog_sha256=self._catalog.catalog_sha256,
            call_id=request.call_id,
            arguments_sha256=arguments_sha256,
            step_id=step.step_id,
            attempt_id=step.attempt_id,
            result_ref=None,
            safe_summary=f"工具调用未产生可验证结果：{reason_code}。",
            quality=ToolQuality.UNKNOWN,
            reason_code=reason_code,
            observed_at=observed_at,
            expires_at=None,
            sent=True,
        )

    # 重复同一逻辑步骤时优先返回进程内缓存；重启后只复用持久化引用，不伪造摘要。
    def _reuse_succeeded(
        self,
        request: ToolRequest,
        *,
        tool: RegisteredTool,
        tool_version: str,
        step: StepAttempt,
        arguments_sha256: str,
        checked_at: datetime,
    ) -> ToolObservation:
        cached = self._observations.get(step.step_id)
        if cached is not None and cached.result_ref == step.result_ref:
            if cached.expires_at is not None and cached.expires_at < checked_at:
                return cached.model_copy(
                    update={
                        "status": ToolObservationStatus.DEGRADED,
                        "quality": ToolQuality.STALE,
                        "reason_code": "result_expired",
                        "safe_summary": (
                            "该工具调用的缓存结果已过期；保留引用与审计信息，不能继续表示当前有效。"
                        ),
                        "call_id": request.call_id,
                        "arguments_sha256": arguments_sha256,
                    }
                )
            return cached.model_copy(
                update={
                    "call_id": request.call_id,
                    "arguments_sha256": arguments_sha256,
                }
            )
        if step.result_ref is None:
            raise AgentRunError("integrity_violation")
        return ToolObservation(
            status=ToolObservationStatus.DEGRADED,
            tool_name=tool.name,
            tool_version=tool_version,
            tool_catalog_sha256=self._catalog.catalog_sha256,
            call_id=request.call_id,
            arguments_sha256=arguments_sha256,
            step_id=step.step_id,
            attempt_id=step.attempt_id,
            result_ref=step.result_ref,
            safe_summary="该工具调用已成功执行；本进程不重建历史摘要，只复用持久化结果引用。",
            quality=ToolQuality.MISSING,
            reason_code="tool_result_reuse",
            observed_at=checked_at,
            expires_at=None,
            sent=True,
        )

    def _remember(self, step_id: UUID, observation: ToolObservation) -> None:
        if len(self._observations) >= _MAX_OBSERVATION_CACHE:
            self._observations.pop(next(iter(self._observations)))
        self._observations[step_id] = observation


# 范围校验只读取服务端快照；模型提供的 symbol/timeframes 只能复述，不能扩大。
def _scope_reason(
    tool: RegisteredTool,
    arguments: JsonObject,
    snapshot: RunSnapshot,
) -> str | None:
    if tool.scope.symbol_bound and "symbol" in arguments:
        if arguments["symbol"] != snapshot.input.product.symbol:
            return "scope_denied"
    if tool.scope.timeframes_bound and "timeframes" in arguments:
        requested = arguments["timeframes"]
        if not isinstance(requested, list) or any(not isinstance(item, str) for item in requested):
            return "invalid_arguments"
        allowed = {item.value for item in snapshot.input.timeframes}
        if not set(requested) <= allowed:
            return "scope_denied"
    if (
        tool.scope.refresh_requires_current_mode
        and arguments.get("refresh") is True
        and snapshot.input.analysis_mode != "current"
    ):
        return "mode_not_supported"
    return None


__all__ = ["TOOL_ACTION_SEQUENCE_BASE", "ToolGateway"]
