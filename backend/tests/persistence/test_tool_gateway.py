# 验证 T09 ToolGateway 与真实任务仓储、C5 预算账本的 PostgreSQL 集成边界。
# 合成只读处理器从独立会话检查发送许可已提交，再返回受控结果；不调用模型或外部服务。
# 测试明确区分同进程步骤复用与重建网关的新只读步骤，不宣称跨进程全局去重或恢复原摘要。
# 所有 SQL 均通过专用测试库预检和随机迁移 schema；中断窗口用协程取消模拟，不终止真实进程。
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.interactive.tools.contracts import (
    TOOL_RESULT_SCHEMA,
    JsonObject,
    RegisteredTool,
    ToolCapability,
    ToolObservationStatus,
    ToolQuality,
    ToolRequest,
    ToolResult,
    ToolResultStatus,
    ToolScope,
)
from app.agent.interactive.tools.gateway import TOOL_ACTION_SEQUENCE_BASE, ToolGateway
from app.agent.interactive.tools.registry import ToolRegistry
from app.agent_runs.attempts import AttemptCategory, AttemptRequest, AttemptResult, AttemptStatus
from app.agent_runs.contracts import AgentRunError, RunInput, RunSnapshot
from app.agent_runs.segments import ExecutionContext, RunFence
from app.infrastructure.persistence import agent_attempt_repository
from app.infrastructure.persistence.agent_attempt_repository import SqlAlchemyBudgetLedger
from app.infrastructure.persistence.agent_run_repository import SqlAlchemyAgentRunRepository
from app.infrastructure.persistence.models.agent_attempts import (
    AgentAttemptRecord,
    AgentStepRecord,
    BudgetAuthorizationRecord,
    BudgetReservationRecord,
)
from app.infrastructure.persistence.models.agent_runs import AgentRunRecord
from app.market.contracts import MarketTimeframe
from app.shared.agent_types import ProductKey, VersionRef

NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


# 只依赖迁移夹具提供的会话工厂；不接管数据库身份、schema 创建或清理。
class Database(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


# 固定审计时钟允许缓存过期测试推进时间；数据库租约仍使用真实 UTC 时钟。
@dataclass
class Clock:
    value: datetime = NOW

    def __call__(self) -> datetime:
        return self.value


# 合成工具只接受有界标签区分输入，不接受 URL、SQL、凭证或交易参数。
def _tool() -> RegisteredTool:
    return RegisteredTool(
        name="read_market_evidence",
        version="1",
        description="读取本次公开研究证据的合成只读处理器。",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"label": {"type": "string", "minLength": 1, "maxLength": 32}},
        },
        output_schema=TOOL_RESULT_SCHEMA,
        capabilities=(ToolCapability.READ_ONLY_RESEARCH,),
        scope=ToolScope(),
        timeout_seconds=5,
        max_result_bytes=8192,
    )


def _result() -> ToolResult:
    return ToolResult(
        status=ToolResultStatus.OK,
        safe_summary="合成公开研究证据已校验。",
        quality=ToolQuality.VALID,
        observed_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )


# 每次处理器进入时从另一 SQL 会话观察已提交状态，能捕获发送事务未提交即执行的回归。
# calls 只记录外部处理器边界；断言同时检查真实账本行、结果引用和累计费用。
class ReadOnlyHandler:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.tool = _tool()
        self.factory = factory
        self.calls: list[JsonObject] = []
        self.result = _result()
        self.error: BaseException | None = None

    async def handle(
        self,
        context: ExecutionContext,
        snapshot: RunSnapshot,
        arguments: JsonObject,
        *,
        sent_at: datetime,
    ) -> ToolResult:
        self.calls.append(arguments)
        assert snapshot.run_id == context.fence.run_id
        async with self.factory() as session:
            attempt = await session.scalar(
                select(AgentAttemptRecord).where(
                    AgentAttemptRecord.run_id == snapshot.run_id,
                    AgentAttemptRecord.status == "in_flight",
                    AgentAttemptRecord.segment_id == context.fence.segment_id,
                )
            )
            assert attempt is not None
            assert attempt.category == "tool"
            assert attempt.sent_at == sent_at
            assert attempt.settled_at is None
            step = await session.get(AgentStepRecord, attempt.step_id)
            assert step is not None and step.status == "in_flight"
            reservation = await session.scalar(
                select(BudgetReservationRecord).where(
                    BudgetReservationRecord.attempt_id == attempt.id
                )
            )
            assert reservation is not None
            assert (reservation.meter, reservation.state) == ("tool_calls", "charged")
            assert (reservation.reserved_amount, reservation.actual_amount) == (1, 1)
            authorization = await session.scalar(
                select(BudgetAuthorizationRecord).where(
                    BudgetAuthorizationRecord.run_id == snapshot.run_id
                )
            )
            assert authorization is not None
        if self.error is not None:
            raise self.error
        return self.result


# 真实仓储创建不可变输入，再仅设置测试 worker 的租约；不使用替身快照绕过每次任务读取。
async def _runtime(
    factory: async_sessionmaker[AsyncSession],
    *,
    clock: Clock | None = None,
) -> tuple[ToolGateway, SqlAlchemyBudgetLedger, ReadOnlyHandler, ExecutionContext]:
    audit_clock = clock or Clock()
    runs = SqlAlchemyAgentRunRepository(factory, clock=audit_clock)
    data = RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm", symbol="BTCUSDT", settlement="USDT", kind="linear_perpetual"
        ),
        timeframes=(MarketTimeframe.H1, MarketTimeframe.H4),
        goal="验证工具网关真实 SQL 边界",
        strategy=VersionRef(version_id=uuid4(), sha256="a" * 64),
        parameters={},
    )
    snapshot = await runs.enqueue(uuid4(), data)
    owner = uuid4()
    async with factory() as session, session.begin():
        run = await session.get(AgentRunRecord, snapshot.run_id)
        assert run is not None
        run.status = "running"
        run.owner = owner
        run.lease_epoch = 1
        run.lease_expires_at = datetime.now(UTC) + timedelta(hours=1)
        run.started_at = NOW
    handler = ReadOnlyHandler(factory)
    ledger = SqlAlchemyBudgetLedger(factory, clock=audit_clock)
    gateway = _gateway(factory, ledger, handler, clock=audit_clock)
    context = ExecutionContext(
        fence=RunFence(
            workspace_id=snapshot.workspace_id,
            run_id=snapshot.run_id,
            revision=1,
            segment_id=uuid4(),
            owner=owner,
            lease_epoch=1,
        ),
        strategy_ref=data.strategy,
        tool_catalog_sha256=gateway.catalog.catalog_sha256,
        policy_version="interactive_planning_v1",
        budget_authorization_id=uuid4(),
    )
    return gateway, ledger, handler, context


# 重建时使用新的真实仓储和网关，显式丢弃进程内序号与摘要缓存。
def _gateway(
    factory: async_sessionmaker[AsyncSession],
    ledger: SqlAlchemyBudgetLedger,
    handler: ReadOnlyHandler,
    *,
    clock: Callable[[], datetime] = lambda: NOW,
) -> ToolGateway:
    return ToolGateway(
        runs=SqlAlchemyAgentRunRepository(factory, clock=clock),
        budget=ledger,
        catalog=ToolRegistry((handler.tool,)),
        handlers={handler.tool.name: handler},
        clock=clock,
    )


def _request(call_id: str = "call-1") -> ToolRequest:
    return ToolRequest(name="read_market_evidence", arguments={}, call_id=call_id)


# 返回脱离会话的真实账本行；后续检查不会被同一 ORM identity map 的未提交值蒙蔽。
async def _rows(
    factory: async_sessionmaker[AsyncSession], run_id: UUID
) -> tuple[list[AgentStepRecord], list[AgentAttemptRecord], list[BudgetReservationRecord]]:
    async with factory() as session:
        steps = list(
            (
                await session.scalars(
                    select(AgentStepRecord).where(AgentStepRecord.run_id == run_id)
                )
            ).all()
        )
        attempts = list(
            (
                await session.scalars(
                    select(AgentAttemptRecord)
                    .where(AgentAttemptRecord.run_id == run_id)
                    .order_by(AgentAttemptRecord.action_sequence)
                )
            ).all()
        )
        reservations = list(
            (
                await session.scalars(
                    select(BudgetReservationRecord).where(BudgetReservationRecord.run_id == run_id)
                )
            ).all()
        )
    return steps, attempts, reservations


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "invalid_result", "exception", "timeout"])
async def test_gateway_commits_send_then_settles_real_tool_outcome(
    migrated_database: Database,
    outcome: str,
) -> None:
    # 缺少发送提交、错分成功/失败/未知或遗漏 meter 结算都会使本用例失败。
    factory = migrated_database.session_factory
    gateway, ledger, handler, context = await _runtime(factory)
    if outcome == "invalid_result":
        handler.result = _result().model_copy(update={"observed_at": NOW + timedelta(seconds=1)})
    elif outcome == "exception":
        handler.error = RuntimeError("synthetic read failure")
    elif outcome == "timeout":
        # 合成超时只证明网关 timeout 分支的真实 SQL 结算，不验证计时器精度或实际等待。
        handler.error = TimeoutError("synthetic read timeout")

    observation = await gateway.call(context, _request())

    expected = {
        "success": ("ok", "succeeded", "settled", 1, None),
        "invalid_result": ("failed", "failed", "settled", 1, "result_time_in_future"),
        "exception": ("unknown", "unknown", "unknown", None, "tool_outcome_unknown"),
        "timeout": ("unknown", "unknown", "unknown", None, "tool_timeout"),
    }[outcome]
    steps, attempts, reservations = await _rows(factory, context.fence.run_id)
    assert len(steps) == len(attempts) == len(reservations) == 1
    assert observation.status.value == expected[0]
    assert steps[0].status == attempts[0].status == expected[1]
    assert observation.reason_code == attempts[0].reason_code == expected[4]
    assert (reservations[0].state, reservations[0].actual_amount) == expected[2:4]
    assert observation.step_id == steps[0].id
    assert observation.attempt_id == attempts[0].id
    assert attempts[0].sent_at == attempts[0].settled_at == NOW
    assert observation.sent is True
    if outcome == "success":
        assert observation.result_ref is not None
        assert steps[0].result_ref == observation.result_ref.model_dump(mode="json")
    else:
        assert observation.result_ref is None and steps[0].result_ref is None
    status = await ledger.status(context.fence)
    assert (status.tool_calls, status.tool_sent, status.model_calls, status.transport_calls) == (
        1,
        1,
        0,
        0,
    )
    assert handler.calls == [{}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blocked", ["cancelled", "stale_owner", "stale_epoch", "expired_lease", "stale_revision"]
)
async def test_cancel_or_old_fence_never_reserves_or_calls_handler(
    migrated_database: Database, blocked: str
) -> None:
    # 真实快照或 SQL fence 拒绝必须发生在处理器边界之前，不留下孤立步骤或预留。
    factory = migrated_database.session_factory
    gateway, _, handler, context = await _runtime(factory)
    if blocked in {"cancelled", "expired_lease"}:
        async with factory() as session, session.begin():
            run = await session.get(AgentRunRecord, context.fence.run_id)
            assert run is not None
            if blocked == "cancelled":
                run.cancel_requested_at = NOW
            else:
                # 租约使用数据库真实时钟判断，不能用固定审计时刻冒充租约过期证据。
                run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        expected = "run_cancelling" if blocked == "cancelled" else "lease_lost"
    else:
        updates = {
            "stale_owner": {"owner": uuid4()},
            "stale_epoch": {"lease_epoch": 2},
            "stale_revision": {"revision": 2},
        }
        fence = context.fence.model_copy(update=updates[blocked])
        context = context.model_copy(update={"fence": fence})
        expected = "lease_lost"
    with pytest.raises(AgentRunError) as rejected:
        await gateway.call(context, _request())
    assert rejected.value.code == expected
    assert handler.calls == []
    assert await _rows(factory, context.fence.run_id) == ([], [], [])


@pytest.mark.asyncio
async def test_exhausted_real_tool_budget_stops_before_new_reservation_or_send(
    migrated_database: Database,
) -> None:
    factory = migrated_database.session_factory
    gateway, ledger, handler, context = await _runtime(factory)
    # 十二次尚未发送的预留也占用完整次数，不能只用已发送数量决定准入。
    for sequence in range(1, 13):
        await ledger.reserve(
            context.fence,
            AttemptRequest(
                action_sequence=sequence,
                input_sha256=f"{sequence:064x}",
                category=AttemptCategory.TOOL,
            ),
        )
    with pytest.raises(AgentRunError) as rejected:
        await gateway.call(context, _request())
    assert rejected.value.code == "budget_exhausted"
    assert handler.calls == []
    steps, attempts, reservations = await _rows(factory, context.fence.run_id)
    assert len(steps) == len(attempts) == len(reservations) == 12
    assert {attempt.status for attempt in attempts} == {"prepared"}
    assert {reservation.state for reservation in reservations} == {"reserved"}
    status = await ledger.status(context.fence)
    assert (status.tool_calls, status.tool_sent) == (12, 0)


@pytest.mark.asyncio
async def test_identical_success_and_expired_cache_keep_one_committed_tool_charge(
    migrated_database: Database,
) -> None:
    factory = migrated_database.session_factory
    clock = Clock()
    gateway, ledger, handler, context = await _runtime(factory, clock=clock)
    first = await gateway.call(context, _request())
    repeated = await gateway.call(context, _request("call-2"))
    clock.value = NOW + timedelta(hours=1)
    expired = await gateway.call(context, _request("call-3"))

    assert first.status is repeated.status is ToolObservationStatus.OK
    assert repeated.call_id == "call-2"
    assert expired.call_id == "call-3"
    assert expired.status is ToolObservationStatus.DEGRADED
    assert (expired.quality, expired.reason_code) == (ToolQuality.STALE, "result_expired")
    assert first.result_ref == repeated.result_ref == expired.result_ref
    assert first.step_id == repeated.step_id == expired.step_id
    assert handler.calls == [{}]
    steps, attempts, reservations = await _rows(factory, context.fence.run_id)
    assert len(steps) == len(attempts) == len(reservations) == 1
    assert steps[0].status == attempts[0].status == "succeeded"
    assert reservations[0].state == "settled"
    status = await ledger.status(context.fence)
    assert (status.tool_calls, status.tool_sent) == (1, 1)


@pytest.mark.asyncio
async def test_reconstructed_gateway_records_new_readonly_step_instead_of_global_dedup(
    migrated_database: Database,
) -> None:
    # 当前序号缓存不持久化：重建网关会为相同只读输入新建步骤并重新收费。
    # 旧成功记录仍不可变；此测试不把进程内幂等误写成重启后复用或历史摘要恢复。
    factory = migrated_database.session_factory
    gateway, ledger, handler, context = await _runtime(factory)
    first = await gateway.call(context, _request())
    rebuilt_handler = ReadOnlyHandler(factory)
    rebuilt = _gateway(factory, SqlAlchemyBudgetLedger(factory, clock=Clock()), rebuilt_handler)
    second = await rebuilt.call(context, _request("call-2"))

    assert first.status is second.status is ToolObservationStatus.OK
    assert first.step_id != second.step_id and first.attempt_id != second.attempt_id
    assert handler.calls == rebuilt_handler.calls == [{}]
    steps, attempts, reservations = await _rows(factory, context.fence.run_id)
    assert len(steps) == len(attempts) == len(reservations) == 2
    assert {attempt.input_sha256 for attempt in attempts} == {attempts[0].input_sha256}
    assert [attempt.action_sequence for attempt in attempts] == [
        TOOL_ACTION_SEQUENCE_BASE,
        TOOL_ACTION_SEQUENCE_BASE + 1,
    ]
    assert {step.status for step in steps} == {"succeeded"}
    assert {reservation.state for reservation in reservations} == {"settled"}
    status = await ledger.status(context.fence)
    assert (status.tool_calls, status.tool_sent) == (2, 2)


@pytest.mark.asyncio
async def test_post_send_cancellation_preserves_charge_and_recovery_marks_unknown(
    migrated_database: Database,
) -> None:
    factory = migrated_database.session_factory
    gateway, ledger, handler, context = await _runtime(factory)
    handler.error = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await gateway.call(context, _request())
    steps, attempts, reservations = await _rows(factory, context.fence.run_id)
    assert len(steps) == len(attempts) == len(reservations) == 1
    assert steps[0].status == attempts[0].status == "in_flight"
    assert attempts[0].sent_at == NOW and attempts[0].settled_at is None
    assert (reservations[0].state, reservations[0].actual_amount) == ("charged", 1)
    with pytest.raises(AgentRunError) as in_flight:
        await gateway.call(context, _request("call-2"))
    assert in_flight.value.code == "attempt_in_flight"

    # 恢复者持有新的片段/owner/代次；只能保守标 unknown，不能声称原请求未发送。
    recovered_fence = context.fence.model_copy(
        update={"segment_id": uuid4(), "owner": uuid4(), "lease_epoch": 2}
    )
    async with factory() as session, session.begin():
        run = await session.get(AgentRunRecord, context.fence.run_id)
        assert run is not None
        run.owner = recovered_fence.owner
        run.lease_epoch = recovered_fence.lease_epoch
    await ledger.settle(
        recovered_fence,
        attempts[0].id,
        AttemptResult(status=AttemptStatus.UNKNOWN, reason_code="worker_interrupted"),
    )
    recovered_context = context.model_copy(update={"fence": recovered_fence})
    with pytest.raises(AgentRunError) as unknown:
        await gateway.call(recovered_context, _request("call-3"))
    assert unknown.value.code == "unknown_not_replayable"
    assert handler.calls == [{}]

    # 丢失进程内序号后只读请求可形成新步骤；旧 unknown 继续占额且不会被覆盖成成功。
    rebuilt_handler = ReadOnlyHandler(factory)
    rebuilt = _gateway(factory, SqlAlchemyBudgetLedger(factory, clock=Clock()), rebuilt_handler)
    observation = await rebuilt.call(recovered_context, _request("call-4"))
    assert observation.status is ToolObservationStatus.OK
    _, final_attempts, final_reservations = await _rows(factory, context.fence.run_id)
    assert [attempt.status for attempt in final_attempts] == ["unknown", "succeeded"]
    assert final_attempts[0].id == attempts[0].id
    assert {reservation.state for reservation in final_reservations} == {"unknown", "settled"}
    status = await ledger.status(recovered_fence)
    assert (status.tool_calls, status.tool_sent) == (2, 2)
    assert rebuilt_handler.calls == [{}]


@pytest.mark.asyncio
async def test_settlement_failure_rolls_back_step_attempt_and_reservation_together(
    migrated_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = migrated_database.session_factory
    gateway, ledger, handler, context = await _runtime(factory)
    settle_reservation = cast(
        Callable[[BudgetReservationRecord, AttemptResult, datetime], None],
        getattr(agent_attempt_repository, "_settle_reservation"),
    )

    # 故障发生在真实结算已改步骤/尝试并进入 meter 更新之后，保留真实事务边界。
    # 即使 ORM 在读取 meter 时已自动 flush 前面两行，异常仍必须使整个结算事务回滚。
    def fail_after_meter_change(
        reservation: BudgetReservationRecord, result: AttemptResult, now: datetime
    ) -> None:
        settle_reservation(reservation, result, now)
        raise SQLAlchemyError("synthetic settlement failure")

    monkeypatch.setattr(agent_attempt_repository, "_settle_reservation", fail_after_meter_change)
    with pytest.raises(AgentRunError) as failed:
        await gateway.call(context, _request())
    assert failed.value.code == "storage_unavailable"
    steps, attempts, reservations = await _rows(factory, context.fence.run_id)
    assert len(steps) == len(attempts) == len(reservations) == 1
    assert steps[0].status == attempts[0].status == "in_flight"
    assert steps[0].result_ref is None
    assert attempts[0].settled_at is None and attempts[0].reason_code is None
    assert (reservations[0].state, reservations[0].actual_amount) == ("charged", 1)
    status = await ledger.status(context.fence)
    assert (status.tool_calls, status.tool_sent) == (1, 1)
    with pytest.raises(AgentRunError) as replay:
        await gateway.call(context, _request("call-2"))
    assert replay.value.code == "attempt_in_flight"
    assert handler.calls == [{}]
