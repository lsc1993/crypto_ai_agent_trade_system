# 用 PostgreSQL 实现 C5 预算/尝试账本：在 run 行锁与租约围栏下预留、发送、结算和恢复。
# 顺序固定为：锁定并校验 fence -> 初始授权 -> 读取累计 meter -> 预留/复用 -> 同事务提交。
# prepared 发送前不算已发送；in_flight 失联只能保守 unknown；未知调用不自动重放。
# 本模块不发送外部请求，只向调用方返回“已提交的发送许可”；不访问模型、工具或交易执行。
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent_runs.attempts import (
    MAX_ATTEMPTS_PER_STEP,
    SENT_ATTEMPT_STATUSES,
    AttemptCategory,
    AttemptRequest,
    AttemptResult,
    AttemptStatus,
    StepAttempt,
    TokenUsage,
    logical_step_id,
)
from app.agent_runs.budget import (
    BudgetLimits,
    BudgetStatus,
    effective_budget_limits,
    initial_budget_limits,
    validate_activity_start,
    validate_append_limits,
    validate_reservation_fits,
)
from app.agent_runs.contracts import AgentRunError
from app.agent_runs.segments import RunFence
from app.infrastructure.persistence.models.agent_attempts import (
    AgentAttemptRecord,
    AgentStepRecord,
    BudgetAuthorizationRecord,
    BudgetReservationRecord,
)
from app.infrastructure.persistence.models.agent_runs import AgentRunRecord
from app.shared.agent_types import ArtifactRef, require_utc

_COUNT_METERS = frozenset({"model_calls", "tool_calls", "transport_calls"})
_MAX_ACTIVITY_RECORD_SECONDS = 86_400


# 围栏校验只需要不可变的任务身份；任务行仍由 T07 的心跳更新 owner/租约。
@dataclass(frozen=True)
class _FencedRun:
    id: UUID
    workspace_id: UUID
    revision: int


# SQL 预算账本；clock 只用于审计时间，租约合法性始终由数据库 clock_timestamp() 判定。
class SqlAlchemyBudgetLedger:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return require_utc(self._clock())

    # 预留一个逻辑步骤；同键成功结果复用，prepared 可被新片段接管，未知调用拒绝自动重放。
    async def reserve(self, fence: RunFence, request: AttemptRequest) -> StepAttempt:
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                run = await _lock_fenced_run(session, fence)
                await _ensure_initial_authorization(session, run, now)
                limits = await _load_effective_limits(session, run.id)
                status = await _load_budget_status(session, run.id, limits)
                step = await session.scalar(
                    select(AgentStepRecord).where(
                        AgentStepRecord.run_id == run.id,
                        AgentStepRecord.revision == fence.revision,
                        AgentStepRecord.action_sequence == request.action_sequence,
                    )
                )
                if step is not None:
                    return await _reuse_or_retry_attempt(
                        session,
                        run=run,
                        fence=fence,
                        step=step,
                        request=request,
                        status=status,
                        now=now,
                    )

                # 只有真正新建发送尝试才消费额度；成功复用不重复计入。
                validate_reservation_fits(status, request)
                step = AgentStepRecord(
                    id=logical_step_id(fence, request),
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    revision=fence.revision,
                    action_sequence=request.action_sequence,
                    input_sha256=request.input_sha256,
                    category=request.category.value,
                    status=AttemptStatus.PREPARED.value,
                    result_ref=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(step)
                await session.flush()
                attempt = await _insert_attempt(
                    session,
                    step=step,
                    fence=fence,
                    attempt_number=1,
                    request=request,
                    now=now,
                )
                _insert_attempt_reservations(session, attempt, request, now)
                await session.flush()
                return await _load_step_attempt(session, step, attempt)
        except AgentRunError:
            raise
        except ValidationError as error:
            raise AgentRunError("integrity_violation") from error
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 提交 in_flight 后才允许传输；重复调用拒绝，避免一次预留触发两次真实发送。
    async def mark_sent(self, fence: RunFence, attempt_id: UUID) -> None:
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                run = await _lock_fenced_run(session, fence)
                attempt = await _load_attempt(session, run, fence, attempt_id)
                if attempt.status != AttemptStatus.PREPARED.value:
                    raise AgentRunError("invalid_attempt_transition")
                step = await session.get(AgentStepRecord, attempt.step_id)
                if step is None or step.status != AttemptStatus.PREPARED.value:
                    raise AgentRunError("integrity_violation")

                limits = await _load_effective_limits(session, run.id)
                status = await _load_budget_status(session, run.id, limits)
                # 次数/Token 已在预留时占用；发送前仍需确认活动时间安全余量。
                validate_activity_start(status)

                attempt.status = AttemptStatus.IN_FLIGHT.value
                attempt.segment_id = fence.segment_id
                attempt.owner = fence.owner
                attempt.lease_epoch = fence.lease_epoch
                attempt.sent_at = now
                attempt.updated_at = now
                step.status = AttemptStatus.IN_FLIGHT.value
                step.updated_at = now
                for reservation in await _load_attempt_reservations(session, attempt.id):
                    reservation.state = "charged"
                    if reservation.meter in _COUNT_METERS:
                        reservation.actual_amount = 1
                    reservation.updated_at = now
                await session.flush()
        except AgentRunError:
            raise
        except ValidationError as error:
            raise AgentRunError("integrity_violation") from error
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 结算成功/失败/未知；未知只能由可验证回执解除，未知状态不会自动释放预留。
    async def settle(
        self,
        fence: RunFence,
        attempt_id: UUID,
        result: AttemptResult,
    ) -> None:
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                run = await _lock_fenced_run(session, fence)
                attempt = await _load_attempt(session, run, fence, attempt_id)
                step = await session.get(AgentStepRecord, attempt.step_id)
                if step is None or step.status != attempt.status:
                    raise AgentRunError("integrity_violation")
                _validate_settlement_authority(fence, attempt, result)
                if attempt.category != AttemptCategory.MODEL.value and result.usage is not None:
                    raise AgentRunError("invalid_attempt_transition")

                attempt.status = result.status.value
                attempt.provider_receipt = result.provider_receipt
                attempt.reason_code = result.reason_code
                attempt.settled_at = now
                attempt.updated_at = now
                step.status = result.status.value
                step.result_ref = (
                    cast(dict[str, object], result.result_ref.model_dump(mode="json"))
                    if result.status is AttemptStatus.SUCCEEDED and result.result_ref is not None
                    else None
                )
                step.updated_at = now

                for reservation in await _load_attempt_reservations(session, attempt.id):
                    _settle_reservation(reservation, result, now)
                await session.flush()
        except AgentRunError:
            raise
        except ValidationError as error:
            raise AgentRunError("integrity_violation") from error
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 读取当前有效上限与累计占用；读取也要求当前租约围栏，避免旧 worker 观察新预算。
    async def status(self, fence: RunFence) -> BudgetStatus:
        try:
            async with self._factory() as session:
                run = await _lock_fenced_run(session, fence)
                limits = await _load_effective_limits(session, run.id)
                return await _load_budget_status(session, run.id, limits)
        except AgentRunError:
            raise
        except ValidationError as error:
            raise AgentRunError("integrity_violation") from error
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 按片段记录累计活动秒数；一个片段只允许一条活动记录，重放相同值幂等。
    async def record_activity(self, fence: RunFence, seconds: int) -> BudgetStatus:
        if isinstance(seconds, bool) or not 1 <= seconds <= _MAX_ACTIVITY_RECORD_SECONDS:
            raise AgentRunError("invalid_activity")
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                run = await _lock_fenced_run(session, fence)
                existing = await session.scalar(
                    select(BudgetReservationRecord).where(
                        BudgetReservationRecord.run_id == run.id,
                        BudgetReservationRecord.segment_id == fence.segment_id,
                        BudgetReservationRecord.meter == "activity_seconds",
                    )
                )
                if existing is not None:
                    # T07 在片段结束时记录一次；重放同值返回当前状态，不重复累计。
                    if existing.actual_amount != seconds:
                        raise AgentRunError("invalid_activity")
                else:
                    session.add(
                        BudgetReservationRecord(
                            id=uuid4(),
                            attempt_id=None,
                            workspace_id=run.workspace_id,
                            run_id=run.id,
                            segment_id=fence.segment_id,
                            meter="activity_seconds",
                            reserved_amount=0,
                            actual_amount=seconds,
                            state="settled",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    await session.flush()
                limits = await _load_effective_limits(session, run.id)
                return await _load_budget_status(session, run.id, limits)
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # AP-05 追加绝对上限；同一授权引用幂等复用，任何维度不得降低或突破部署硬上限。
    async def append_authorization(
        self,
        fence: RunFence,
        limits: BudgetLimits,
        *,
        authorization_ref: UUID,
        reason: str,
    ) -> BudgetStatus:
        if authorization_ref.int == 0 or not _is_safe_reason(reason):
            raise AgentRunError("invalid_budget_authorization")
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                run = await _lock_fenced_run(session, fence)
                await _ensure_initial_authorization(session, run, now)
                current = await _load_effective_limits(session, run.id)
                existing = await session.scalar(
                    select(BudgetAuthorizationRecord).where(
                        BudgetAuthorizationRecord.run_id == run.id,
                        BudgetAuthorizationRecord.authorization_ref == authorization_ref,
                    )
                )
                if existing is not None:
                    if _authorization_matches(existing, limits):
                        return await _load_budget_status(session, run.id, current)
                    raise AgentRunError("invalid_budget_authorization")
                validate_append_limits(current, limits)
                session.add(
                    BudgetAuthorizationRecord(
                        id=uuid4(),
                        workspace_id=run.workspace_id,
                        run_id=run.id,
                        kind="append",
                        model_calls=limits.model_calls,
                        tool_calls=limits.tool_calls,
                        input_tokens=limits.input_tokens,
                        output_tokens=limits.output_tokens,
                        active_seconds=limits.active_seconds,
                        transport_calls=limits.transport_calls,
                        authorization_ref=authorization_ref,
                        reason=reason.strip(),
                        created_at=now,
                    )
                )
                await session.flush()
                refreshed = await _load_effective_limits(session, run.id)
                return await _load_budget_status(session, run.id, refreshed)
        except AgentRunError:
            raise
        except IntegrityError:
            raise AgentRunError("invalid_budget_authorization") from None
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None


# 锁定任务行并核对工作台、修订、owner、租约代次与数据库当前时刻；失败统一 lease_lost。
# 使用 ORM 查询以保留测试/部署的 schema 映射；时刻读取在行锁之后执行。
async def _lock_fenced_run(session: AsyncSession, fence: RunFence) -> _FencedRun:
    run = await session.scalar(
        select(AgentRunRecord)
        .where(
            AgentRunRecord.id == fence.run_id,
            AgentRunRecord.workspace_id == fence.workspace_id,
        )
        .with_for_update()
    )
    if run is None:
        raise AgentRunError("lease_lost")
    database_now = await session.scalar(text("SELECT clock_timestamp()"))
    if not isinstance(database_now, datetime):
        raise AgentRunError("integrity_violation")
    if (
        run.status != "running"
        or run.owner != fence.owner
        or run.lease_epoch != fence.lease_epoch
        or run.revision != fence.revision
        or run.lease_expires_at is None
        or run.lease_expires_at <= database_now
    ):
        raise AgentRunError("lease_lost")
    return _FencedRun(
        id=run.id,
        workspace_id=run.workspace_id,
        revision=run.revision,
    )


# 首次预留时写入不可变初始授权；唯一索引与 run 行锁共同保证只写一次。
async def _ensure_initial_authorization(
    session: AsyncSession,
    run: _FencedRun,
    now: datetime,
) -> None:
    existing = await session.scalar(
        select(BudgetAuthorizationRecord.id).where(
            BudgetAuthorizationRecord.run_id == run.id,
            BudgetAuthorizationRecord.kind == "initial",
        )
    )
    if existing is not None:
        return
    limits = initial_budget_limits()
    session.add(
        BudgetAuthorizationRecord(
            id=uuid4(),
            workspace_id=run.workspace_id,
            run_id=run.id,
            kind="initial",
            model_calls=limits.model_calls,
            tool_calls=limits.tool_calls,
            input_tokens=limits.input_tokens,
            output_tokens=limits.output_tokens,
            active_seconds=limits.active_seconds,
            transport_calls=limits.transport_calls,
            authorization_ref=None,
            reason=None,
            created_at=now,
        )
    )
    await session.flush()


# 有效上限取全部授权逐维度最大值；没有任何行时仍使用初始档，不伪造已写授权。
async def _load_effective_limits(session: AsyncSession, run_id: UUID) -> BudgetLimits:
    rows = (
        await session.scalars(
            select(BudgetAuthorizationRecord).where(BudgetAuthorizationRecord.run_id == run_id)
        )
    ).all()
    return effective_budget_limits(
        tuple(
            BudgetLimits(
                model_calls=row.model_calls,
                tool_calls=row.tool_calls,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                active_seconds=row.active_seconds,
                transport_calls=row.transport_calls,
            )
            for row in rows
        )
    )


# 聚合 meter 预留/实际值和已发送尝试数；所有未知调用继续按最坏预留占额。
async def _load_budget_status(
    session: AsyncSession,
    run_id: UUID,
    limits: BudgetLimits,
) -> BudgetStatus:
    meter_rows = (
        await session.execute(
            select(
                BudgetReservationRecord.meter,
                func.sum(
                    func.coalesce(
                        BudgetReservationRecord.actual_amount,
                        BudgetReservationRecord.reserved_amount,
                    )
                ),
            )
            .where(BudgetReservationRecord.run_id == run_id)
            .group_by(BudgetReservationRecord.meter)
        )
    ).all()
    meter_totals: dict[str, int] = {str(meter): int(total or 0) for meter, total in meter_rows}

    sent_values = tuple(status.value for status in SENT_ATTEMPT_STATUSES)
    attempt_rows = (
        await session.execute(
            select(
                AgentAttemptRecord.category,
                AgentAttemptRecord.status,
                func.count(),
            )
            .where(AgentAttemptRecord.run_id == run_id)
            .group_by(AgentAttemptRecord.category, AgentAttemptRecord.status)
        )
    ).all()
    counts: dict[tuple[str, str], int] = {
        (str(category), str(status)): int(count) for category, status, count in attempt_rows
    }

    def calls(category: str) -> int:
        return sum(
            count for (item_category, _), count in counts.items() if item_category == category
        )

    def sent(category: str) -> int:
        return sum(
            count
            for (item_category, status), count in counts.items()
            if item_category == category and status in sent_values
        )

    model_calls = calls("model")
    tool_calls = calls("tool")
    transport_calls = calls("transport")
    # meter 行与尝试行必须一一对应；不一致说明事务/触发器被绕过，按不变量破坏拒绝。
    if (
        meter_totals.get("model_calls", 0) != model_calls
        or meter_totals.get("tool_calls", 0) != tool_calls
        or meter_totals.get("transport_calls", 0) != transport_calls
    ):
        raise AgentRunError("integrity_violation")

    try:
        return BudgetStatus(
            model_limit=limits.model_calls,
            tool_limit=limits.tool_calls,
            input_token_limit=limits.input_tokens,
            output_token_limit=limits.output_tokens,
            active_second_limit=limits.active_seconds,
            transport_limit=limits.transport_calls,
            model_calls=model_calls,
            model_sent=sent("model"),
            tool_calls=tool_calls,
            tool_sent=sent("tool"),
            transport_calls=transport_calls,
            transport_sent=sent("transport"),
            input_tokens=meter_totals.get("input_tokens", 0),
            output_tokens=meter_totals.get("output_tokens", 0),
            active_seconds=meter_totals.get("activity_seconds", 0),
        )
    except ValidationError as error:
        raise AgentRunError("integrity_violation") from error


# 已有逻辑步骤的复用/重试分支；成功复用不新增预算，未知拒绝自动重放。
async def _reuse_or_retry_attempt(
    session: AsyncSession,
    *,
    run: _FencedRun,
    fence: RunFence,
    step: AgentStepRecord,
    request: AttemptRequest,
    status: BudgetStatus,
    now: datetime,
) -> StepAttempt:
    if (
        step.input_sha256 != request.input_sha256
        or step.category != request.category.value
        or step.run_id != run.id
        or step.revision != fence.revision
    ):
        raise AgentRunError("step_conflict")
    attempts = list(
        (
            await session.scalars(
                select(AgentAttemptRecord)
                .where(AgentAttemptRecord.step_id == step.id)
                .order_by(AgentAttemptRecord.attempt_number)
            )
        ).all()
    )
    if not attempts:
        raise AgentRunError("integrity_violation")

    if step.status == AttemptStatus.SUCCEEDED.value:
        successful = next(
            (item for item in attempts if item.status == AttemptStatus.SUCCEEDED.value),
            None,
        )
        if successful is None:
            raise AgentRunError("integrity_violation")
        return await _load_step_attempt(session, step, successful)
    if step.status == AttemptStatus.PREPARED.value:
        prepared = next(
            (item for item in attempts if item.status == AttemptStatus.PREPARED.value),
            None,
        )
        if prepared is None:
            raise AgentRunError("integrity_violation")
        return await _load_step_attempt(session, step, prepared)
    if step.status == AttemptStatus.IN_FLIGHT.value:
        # 在途尝试不能被第二个片段重新发送；调用方应等待真实回执或恢复为 unknown。
        raise AgentRunError("attempt_in_flight")
    if step.status == AttemptStatus.UNKNOWN.value:
        raise AgentRunError("unknown_not_replayable")
    if step.status != AttemptStatus.FAILED.value:
        raise AgentRunError("integrity_violation")
    if len(attempts) >= MAX_ATTEMPTS_PER_STEP:
        raise AgentRunError("attempt_limit")

    validate_reservation_fits(status, request)
    step.status = AttemptStatus.PREPARED.value
    step.result_ref = None
    step.updated_at = now
    attempt = await _insert_attempt(
        session,
        step=step,
        fence=fence,
        attempt_number=len(attempts) + 1,
        request=request,
        now=now,
    )
    _insert_attempt_reservations(session, attempt, request, now)
    await session.flush()
    return await _load_step_attempt(session, step, attempt)


# 读取属于当前 run/workspace 的尝试，并核对当前修订；不泄露其他工作台的尝试。
async def _load_attempt(
    session: AsyncSession,
    run: _FencedRun,
    fence: RunFence,
    attempt_id: UUID,
) -> AgentAttemptRecord:
    attempt = await session.scalar(
        select(AgentAttemptRecord).where(
            AgentAttemptRecord.id == attempt_id,
            AgentAttemptRecord.run_id == run.id,
            AgentAttemptRecord.workspace_id == fence.workspace_id,
        )
    )
    if attempt is None or attempt.revision != run.revision:
        raise AgentRunError("attempt_not_found")
    return attempt


# 结算权限：发送者可提交已知结果；失联恢复可标记 unknown；其他写者必须提供可验证回执。
def _validate_settlement_authority(
    fence: RunFence,
    attempt: AgentAttemptRecord,
    result: AttemptResult,
) -> None:
    current = AttemptStatus(attempt.status)
    if current is AttemptStatus.IN_FLIGHT:
        if result.status is AttemptStatus.UNKNOWN:
            return
        if _fence_matches_attempt(fence, attempt):
            return
        if result.receipt_verified and result.provider_receipt is not None:
            return
        raise AgentRunError("lease_lost")
    if current is AttemptStatus.UNKNOWN:
        if not (result.receipt_verified and result.provider_receipt is not None):
            raise AgentRunError("receipt_required")
        return
    raise AgentRunError("invalid_attempt_transition")


# 围栏必须同时匹配发送片段、owner 与租约代次，防止旧片段在接管后误结算。
def _fence_matches_attempt(fence: RunFence, attempt: AgentAttemptRecord) -> bool:
    return (
        attempt.segment_id == fence.segment_id
        and attempt.owner == fence.owner
        and attempt.lease_epoch == fence.lease_epoch
    )


# 按结算结果更新 meter 行；未知保留 reserved 值，已知 usage 才替换为实际值。
def _settle_reservation(
    reservation: BudgetReservationRecord,
    result: AttemptResult,
    now: datetime,
) -> None:
    if result.status is AttemptStatus.UNKNOWN:
        reservation.state = "unknown"
        reservation.actual_amount = None
    elif reservation.meter in _COUNT_METERS:
        reservation.state = "settled"
        reservation.actual_amount = 1
    else:
        usage = result.usage
        actual: int | None = None
        if usage is not None:
            if reservation.meter == "input_tokens":
                actual = usage.input_tokens
            elif reservation.meter == "output_tokens":
                actual = usage.output_tokens
        if actual is None:
            # 供应商未返回 usage：保留最大预留，不能按零成本结算。
            reservation.state = "unknown"
            reservation.actual_amount = None
        else:
            reservation.state = "settled"
            reservation.actual_amount = actual
    reservation.updated_at = now


# 新建一个真实发送尝试；调用方必须先持有对应步骤与 fence。
async def _insert_attempt(
    session: AsyncSession,
    *,
    step: AgentStepRecord,
    fence: RunFence,
    attempt_number: int,
    request: AttemptRequest,
    now: datetime,
) -> AgentAttemptRecord:
    attempt = AgentAttemptRecord(
        id=uuid4(),
        step_id=step.id,
        workspace_id=step.workspace_id,
        run_id=step.run_id,
        revision=step.revision,
        segment_id=fence.segment_id,
        owner=fence.owner,
        lease_epoch=fence.lease_epoch,
        attempt_number=attempt_number,
        category=request.category.value,
        action_sequence=request.action_sequence,
        input_sha256=request.input_sha256,
        status=AttemptStatus.PREPARED.value,
        provider_receipt=None,
        reason_code=None,
        created_at=now,
        sent_at=None,
        settled_at=None,
        updated_at=now,
    )
    session.add(attempt)
    await session.flush()
    return attempt


# 每个真实发送对应自己的 meter 行；模型另占输入/输出 Token，工具/传输只占次数。
def _insert_attempt_reservations(
    session: AsyncSession,
    attempt: AgentAttemptRecord,
    request: AttemptRequest,
    now: datetime,
) -> None:
    rows: list[BudgetReservationRecord] = [
        BudgetReservationRecord(
            id=uuid4(),
            attempt_id=attempt.id,
            workspace_id=attempt.workspace_id,
            run_id=attempt.run_id,
            segment_id=attempt.segment_id,
            meter=f"{request.category.value}_calls",
            reserved_amount=1,
            actual_amount=None,
            state="reserved",
            created_at=now,
            updated_at=now,
        )
    ]
    if request.category is AttemptCategory.MODEL:
        rows.extend(
            [
                BudgetReservationRecord(
                    id=uuid4(),
                    attempt_id=attempt.id,
                    workspace_id=attempt.workspace_id,
                    run_id=attempt.run_id,
                    segment_id=attempt.segment_id,
                    meter="input_tokens",
                    reserved_amount=request.reserved_input_tokens,
                    actual_amount=None,
                    state="reserved",
                    created_at=now,
                    updated_at=now,
                ),
                BudgetReservationRecord(
                    id=uuid4(),
                    attempt_id=attempt.id,
                    workspace_id=attempt.workspace_id,
                    run_id=attempt.run_id,
                    segment_id=attempt.segment_id,
                    meter="output_tokens",
                    reserved_amount=request.reserved_output_tokens,
                    actual_amount=None,
                    state="reserved",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
    session.add_all(rows)


# 读取某次尝试的全部 meter 行，用于结算/快照；缺失行说明不变量已破坏。
async def _load_attempt_reservations(
    session: AsyncSession,
    attempt_id: UUID,
) -> Sequence[BudgetReservationRecord]:
    rows = (
        await session.scalars(
            select(BudgetReservationRecord).where(BudgetReservationRecord.attempt_id == attempt_id)
        )
    ).all()
    if len(rows) < 1:
        raise AgentRunError("integrity_violation")
    return rows


# 组装对外 StepAttempt；结果引用来自逻辑步骤，usage 只在已知结算时出现。
async def _load_step_attempt(
    session: AsyncSession,
    step: AgentStepRecord,
    attempt: AgentAttemptRecord,
) -> StepAttempt:
    reservations = await _load_attempt_reservations(session, attempt.id)
    reserved = {row.meter: row.reserved_amount for row in reservations}
    usage: TokenUsage | None = None
    input_row = next((row for row in reservations if row.meter == "input_tokens"), None)
    output_row = next((row for row in reservations if row.meter == "output_tokens"), None)
    if (
        attempt.status in {AttemptStatus.SUCCEEDED.value, AttemptStatus.FAILED.value}
        and input_row is not None
        and output_row is not None
        and input_row.actual_amount is not None
        and output_row.actual_amount is not None
    ):
        usage = TokenUsage(
            input_tokens=input_row.actual_amount,
            output_tokens=output_row.actual_amount,
        )
    result_ref: ArtifactRef | None = None
    if attempt.status == AttemptStatus.SUCCEEDED.value:
        if step.result_ref is None:
            raise AgentRunError("integrity_violation")
        try:
            result_ref = ArtifactRef.model_validate(step.result_ref)
        except ValidationError as error:
            raise AgentRunError("integrity_violation") from error
    try:
        return StepAttempt(
            attempt_id=attempt.id,
            step_id=step.id,
            run_id=step.run_id,
            revision=step.revision,
            segment_id=attempt.segment_id,
            attempt_number=attempt.attempt_number,
            category=AttemptCategory(attempt.category),
            action_sequence=step.action_sequence,
            input_sha256=step.input_sha256,
            status=AttemptStatus(attempt.status),
            reserved_input_tokens=reserved.get("input_tokens", 0),
            reserved_output_tokens=reserved.get("output_tokens", 0),
            result_ref=result_ref,
            usage=usage,
            provider_receipt=attempt.provider_receipt,
            reason_code=attempt.reason_code,
            created_at=attempt.created_at,
            sent_at=attempt.sent_at,
            settled_at=attempt.settled_at,
        )
    except ValidationError as error:
        raise AgentRunError("integrity_violation") from error


# 追加授权引用与请求内容必须完全一致，才能安全重放同一 AP-05 结果。
def _authorization_matches(row: BudgetAuthorizationRecord, limits: BudgetLimits) -> bool:
    return (
        row.model_calls == limits.model_calls
        and row.tool_calls == limits.tool_calls
        and row.input_tokens == limits.input_tokens
        and row.output_tokens == limits.output_tokens
        and row.active_seconds == limits.active_seconds
        and row.transport_calls == limits.transport_calls
    )


# 授权原因只用于本地审计摘要；拒绝控制字符和超长自由文本。
def _is_safe_reason(reason: str) -> bool:
    normalized = reason.strip()
    return 1 <= len(normalized) <= 256 and all(character.isprintable() for character in normalized)


__all__ = ["SqlAlchemyBudgetLedger"]
