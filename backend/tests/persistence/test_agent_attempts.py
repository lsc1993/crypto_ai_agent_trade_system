# 验证 C5 步骤账本与预算的 PostgreSQL 实现：预留、发送、结算、未知、重试、跨修订累计、
# 并发临界、追加授权、活动时间、fence 失效与历史不可变。
# 测试只写合成任务/用量/UUID，不访问模型、工具、账户或交易执行；每个用例使用随机临时 schema。
# 所有 SQL 用例依赖显式专用测试库与受限角色，不接触业务库，也不把跳过当作通过。
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent_runs.attempts import (
    AttemptCategory,
    AttemptRequest,
    AttemptResult,
    AttemptStatus,
    TokenUsage,
    logical_step_id,
)
from app.agent_runs.budget import (
    BudgetLimits,
)
from app.agent_runs.contracts import AgentRunError, RunInput
from app.agent_runs.segments import RunFence
from app.infrastructure.persistence import agent_attempt_repository
from app.infrastructure.persistence.agent_attempt_repository import SqlAlchemyBudgetLedger
from app.infrastructure.persistence.agent_run_repository import SqlAlchemyAgentRunRepository
from app.infrastructure.persistence.models.agent_attempts import (
    AgentAttemptRecord,
    AgentStepRecord,
    BudgetAuthorizationRecord,
    BudgetReservationRecord,
)
from app.infrastructure.persistence.models.agent_runs import (
    AgentRunRecord,
    AgentRunRevisionRecord,
)
from app.infrastructure.persistence.models.planning_inputs import PlanningPoolRecord
from app.market.contracts import MarketTimeframe
from app.shared.agent_types import ArtifactRef, ProductKey, VersionRef
from app.trade_planning.inputs import PlanningRefs

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
WORKSPACE_ID = uuid4()


# 测试只依赖迁移夹具暴露的异步会话工厂，不导入具体数据库夹具类型。
class Database(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


# 构造最小可持久化任务输入；预算账本不读取目标文本或规划金额。
def _input() -> RunInput:
    return RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1, MarketTimeframe.H4),
        goal="验证 Agent 预算账本",
        strategy=VersionRef(version_id=uuid4(), sha256="a" * 64),
        parameters={"lookback": 20},
        planning=PlanningRefs(
            profile=VersionRef(version_id=uuid4(), sha256="b" * 64),
            policy=VersionRef(version_id=uuid4(), sha256="c" * 64),
            venue_rules=VersionRef(version_id=uuid4(), sha256="d" * 64),
            costs=VersionRef(version_id=uuid4(), sha256="e" * 64),
            pool_id=uuid4(),
            pool_generation=1,
        ),
    )


# 构造合法模型尝试；默认预留小于累计上限，便于观察多次调用的累计。
def _model_request(
    action_sequence: int,
    *,
    input_tokens: int = 1024,
    output_tokens: int = 512,
    input_sha256: str | None = None,
) -> AttemptRequest:
    return AttemptRequest(
        action_sequence=action_sequence,
        input_sha256=input_sha256 or f"{action_sequence:064x}",
        category=AttemptCategory.MODEL,
        reserved_input_tokens=input_tokens,
        reserved_output_tokens=output_tokens,
        timeout_seconds=60,
    )


# 构造工具/传输请求；两类调用不消费模型 Token，只各占一个调用额度。
def _non_model_request(
    action_sequence: int,
    category: AttemptCategory,
) -> AttemptRequest:
    return AttemptRequest(
        action_sequence=action_sequence,
        input_sha256=f"{action_sequence + 1000:064x}",
        category=category,
    )


# 成功结果必须引用已持久化、可复用的校验结果；测试使用合成 ArtifactRef。
def _result_ref() -> ArtifactRef:
    return ArtifactRef(artifact_id=uuid4(), sha256="f" * 64)


# 直接断言数据库拒绝来自 CHECK 约束，而不是唯一键/外键等其他 DBAPIError。
def _assert_check_violation(error: DBAPIError, constraint: str) -> None:
    original = error.orig
    assert getattr(original, "sqlstate", None) == "23514", repr(original)
    # asyncpg 的 wrapped IntegrityError 不总是暴露 constraint_name 属性；
    # 同时核对固定 SQLSTATE 和错误文本中的约束名，排除唯一键/外键等其他 23 类错误。
    assert constraint in str(original), repr(original)


# 为形状测试建立一个没有既有 meter 行的合成模型尝试，避免复用到唯一键冲突。
# 该构造只用于数据库约束验证，不通过生产账本 API，也不代表完整业务状态。
async def _insert_bare_model_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    fence: RunFence,
    *,
    action_sequence: int = 900,
) -> UUID:
    step_id = uuid4()
    attempt_id = uuid4()
    input_sha = f"{action_sequence:064x}"
    async with session_factory() as session, session.begin():
        session.add(
            AgentStepRecord(
                id=step_id,
                workspace_id=fence.workspace_id,
                run_id=fence.run_id,
                revision=fence.revision,
                action_sequence=action_sequence,
                input_sha256=input_sha,
                category=AttemptCategory.MODEL.value,
                status=AttemptStatus.PREPARED.value,
                result_ref=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            AgentAttemptRecord(
                id=attempt_id,
                step_id=step_id,
                workspace_id=fence.workspace_id,
                run_id=fence.run_id,
                revision=fence.revision,
                segment_id=fence.segment_id,
                owner=fence.owner,
                lease_epoch=fence.lease_epoch,
                attempt_number=1,
                category=AttemptCategory.MODEL.value,
                action_sequence=action_sequence,
                input_sha256=input_sha,
                status=AttemptStatus.PREPARED.value,
                provider_receipt=None,
                reason_code=None,
                created_at=NOW,
                sent_at=None,
                settled_at=None,
                updated_at=NOW,
            )
        )
        await session.flush()
    return attempt_id


# 通过 T04 仓储建立任务，再显式推进为可运行状态；T05 尚未实现领取/心跳。
async def _running_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner: UUID | None = None,
    revision: int = 1,
) -> tuple[UUID, UUID, RunFence]:
    run_repository = SqlAlchemyAgentRunRepository(session_factory, clock=lambda: NOW)
    snapshot = await run_repository.enqueue(WORKSPACE_ID, _input())
    run_owner = owner or uuid4()
    async with session_factory() as session, session.begin():
        run = await session.get(AgentRunRecord, snapshot.run_id)
        if run is None:
            raise AssertionError("synthetic run missing")
        run.status = "running"
        run.owner = run_owner
        run.lease_epoch = 1
        run.lease_expires_at = datetime.now(UTC) + timedelta(hours=1)
        run.started_at = NOW
        if revision != 1:
            await _advance_revision_in_session(session, run, revision)
    fence = RunFence(
        workspace_id=WORKSPACE_ID,
        run_id=snapshot.run_id,
        revision=revision,
        segment_id=uuid4(),
        owner=run_owner,
        lease_epoch=1,
    )
    return snapshot.run_id, run_owner, fence


# 在同一事务追加不可变修订行并推进任务当前修订；不修改 T04 请求映射。
async def _advance_revision_in_session(
    session: AsyncSession,
    run: AgentRunRecord,
    revision: int,
) -> None:
    current = await session.get(
        AgentRunRevisionRecord,
        (run.id, run.revision),
    )
    if current is None:
        raise AssertionError("synthetic revision missing")
    for number in range(run.revision + 1, revision + 1):
        session.add(
            AgentRunRevisionRecord(
                run_id=run.id,
                revision=number,
                input=current.input,
                sha256=current.sha256,
                created_at=NOW,
            )
        )
    run.revision = revision


# 模拟租约恢复后的新片段；owner/lease_epoch 不变时证明片段身份也进入成功结果复用。
async def _new_segment(
    session_factory: async_sessionmaker[AsyncSession],
    fence: RunFence,
    *,
    revision: int | None = None,
) -> RunFence:
    target_revision = revision or fence.revision
    if target_revision != fence.revision:
        async with session_factory() as session, session.begin():
            run = await session.get(AgentRunRecord, fence.run_id)
            if run is None:
                raise AssertionError("synthetic run missing")
            await _advance_revision_in_session(session, run, target_revision)
    return fence.model_copy(update={"segment_id": uuid4(), "revision": target_revision})


# 统计表行数，用于证明失败事务与幂等路径没有留下半个账本。
async def _count(session_factory: async_sessionmaker[AsyncSession], model: type[object]) -> int:
    async with session_factory() as session:
        value = await session.scalar(select(func.count()).select_from(model))
    return int(value or 0)


# 直接读取尝试行数量，用于核对重试/复用只产生真实发送尝试。
async def _attempt_rows(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
) -> list[AgentAttemptRecord]:
    async with session_factory() as session:
        return list(
            (
                await session.scalars(
                    select(AgentAttemptRecord)
                    .where(AgentAttemptRecord.run_id == run_id)
                    .order_by(AgentAttemptRecord.created_at, AgentAttemptRecord.attempt_number)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_reserve_send_settle_known_usage_and_reuse_success(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    run_id, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)
    request = _model_request(1)

    prepared = await ledger.reserve(fence, request)
    assert prepared.status is AttemptStatus.PREPARED
    assert prepared.attempt_number == 1
    assert prepared.step_id == logical_step_id(fence, request)
    assert prepared.reserved_input_tokens == 1024
    assert prepared.reserved_output_tokens == 512

    # 先预留再发送：prepared 已占调用与 Token 额度，但尚未计为已发送。
    before_send = await ledger.status(fence)
    assert before_send.model_calls == 1
    assert before_send.model_sent == 0
    assert before_send.input_tokens == 1024
    assert before_send.output_tokens == 512

    await ledger.mark_sent(fence, prepared.attempt_id)
    sent = await ledger.status(fence)
    assert sent.model_sent == 1

    # 成功按供应商已知 usage 结算，未使用预留被释放为实际用量。
    await ledger.settle(
        fence,
        prepared.attempt_id,
        AttemptResult(
            status=AttemptStatus.SUCCEEDED,
            result_ref=_result_ref(),
            usage=TokenUsage(input_tokens=800, output_tokens=120),
        ),
    )
    settled = await ledger.status(fence)
    assert settled.model_calls == 1
    assert settled.model_sent == 1
    assert settled.input_tokens == 800
    assert settled.output_tokens == 120

    # 同一成功逻辑键再次预留时复用已保存结果，不新增调用或 Token 预留。
    reused = await ledger.reserve(fence, request)
    assert reused.attempt_id == prepared.attempt_id
    assert reused.status is AttemptStatus.SUCCEEDED
    assert reused.result_ref is not None
    after_reuse = await ledger.status(fence)
    assert after_reuse.model_calls == 1
    assert after_reuse.input_tokens == 800

    with pytest.raises(AgentRunError) as repeated_settle:
        await ledger.settle(
            fence,
            prepared.attempt_id,
            AttemptResult(status=AttemptStatus.SUCCEEDED, result_ref=_result_ref()),
        )
    assert repeated_settle.value.code == "invalid_attempt_transition"

    with pytest.raises(AgentRunError) as repeated_send:
        await ledger.mark_sent(fence, prepared.attempt_id)
    assert repeated_send.value.code == "invalid_attempt_transition"

    assert len(await _attempt_rows(session_factory, run_id)) == 1
    # 三个 meter 行（模型次数、输入、输出）不是每次结算重复追加。
    assert await _count(session_factory, BudgetReservationRecord) == 3


@pytest.mark.asyncio
async def test_budget_accumulates_across_segments_and_revisions_without_reset(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, first_fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)

    first = await ledger.reserve(first_fence, _model_request(1))
    await ledger.mark_sent(first_fence, first.attempt_id)
    await ledger.settle(
        first_fence,
        first.attempt_id,
        AttemptResult(
            status=AttemptStatus.SUCCEEDED,
            result_ref=_result_ref(),
            usage=TokenUsage(input_tokens=800, output_tokens=120),
        ),
    )
    before_revision = await ledger.status(first_fence)

    # 新修订/新片段只改变执行归属，不清零任务累计预算。
    second_fence = await _new_segment(session_factory, first_fence, revision=2)
    after_revision = await ledger.status(second_fence)
    assert after_revision.model_sent == before_revision.model_sent
    assert after_revision.model_calls == before_revision.model_calls
    assert after_revision.input_tokens == before_revision.input_tokens
    assert after_revision.output_tokens == before_revision.output_tokens

    second = await ledger.reserve(second_fence, _model_request(1))
    await ledger.mark_sent(second_fence, second.attempt_id)
    await ledger.settle(
        second_fence,
        second.attempt_id,
        AttemptResult(
            status=AttemptStatus.SUCCEEDED,
            result_ref=_result_ref(),
            usage=TokenUsage(input_tokens=1000, output_tokens=200),
        ),
    )
    third_fence = await _new_segment(session_factory, second_fence)
    third = await ledger.reserve(third_fence, _model_request(2))
    await ledger.mark_sent(third_fence, third.attempt_id)

    accumulated = await ledger.status(third_fence)
    assert accumulated.model_calls == 3
    assert accumulated.model_sent == 3
    assert accumulated.input_tokens == 800 + 1000 + 1024
    assert accumulated.output_tokens == 120 + 200 + 512


@pytest.mark.asyncio
async def test_unknown_paid_call_keeps_worst_case_reservation_and_is_not_replayed(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)
    request = _model_request(1, input_tokens=16384, output_tokens=4096)

    attempt = await ledger.reserve(fence, request)
    await ledger.mark_sent(fence, attempt.attempt_id)
    await ledger.settle(
        fence,
        attempt.attempt_id,
        AttemptResult(status=AttemptStatus.UNKNOWN, reason_code="provider_timeout"),
    )

    unknown = await ledger.status(fence)
    assert unknown.input_tokens == 16384
    assert unknown.output_tokens == 4096
    assert unknown.model_sent == 1

    # 恢复器不得自动重放未知付费调用；同一逻辑键必须显式拒绝。
    with pytest.raises(AgentRunError) as replay:
        await ledger.reserve(fence, request)
    assert replay.value.code == "unknown_not_replayable"

    # 供应商可验证回执可以消除未知；新片段在现有租约内完成结算。
    reconciling_fence = await _new_segment(session_factory, fence)
    await ledger.settle(
        reconciling_fence,
        attempt.attempt_id,
        AttemptResult(
            status=AttemptStatus.SUCCEEDED,
            result_ref=_result_ref(),
            usage=TokenUsage(input_tokens=500, output_tokens=80),
            provider_receipt="receipt-verified-1",
            receipt_verified=True,
        ),
    )
    reconciled = await ledger.status(reconciling_fence)
    assert reconciled.input_tokens == 500
    assert reconciled.output_tokens == 80

    reused = await ledger.reserve(reconciling_fence, request)
    assert reused.attempt_id == attempt.attempt_id
    assert reused.status is AttemptStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_retry_creates_new_attempt_and_third_retry_is_rejected(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    run_id, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)
    request = _model_request(1)

    first = await ledger.reserve(fence, request)
    await ledger.mark_sent(fence, first.attempt_id)
    await ledger.settle(
        fence,
        first.attempt_id,
        AttemptResult(status=AttemptStatus.FAILED, reason_code="http_429"),
    )

    # 已知可重试失败使用新的独立 attempt，不覆盖首发票据或直接复用预留。
    second = await ledger.reserve(fence, request)
    assert second.attempt_id != first.attempt_id
    assert second.attempt_number == 2
    assert second.status is AttemptStatus.PREPARED
    await ledger.mark_sent(fence, second.attempt_id)
    await ledger.settle(
        fence,
        second.attempt_id,
        AttemptResult(status=AttemptStatus.FAILED, reason_code="http_429"),
    )

    with pytest.raises(AgentRunError) as third:
        await ledger.reserve(fence, request)
    assert third.value.code == "attempt_limit"

    # 两次实际发送各自累计次数与未知 usage 的最坏预留。
    status = await ledger.status(fence)
    assert status.model_calls == 2
    assert status.model_sent == 2
    assert status.input_tokens == 2048
    assert status.output_tokens == 1024
    rows = await _attempt_rows(session_factory, run_id)
    assert [row.attempt_number for row in rows] == [1, 2]
    assert {row.status for row in rows} == {"failed"}


@pytest.mark.asyncio
async def test_concurrent_reservations_serialize_at_limit_and_reuse_same_step(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    first_run_id, _, first_fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)

    # 先占用 7 个模型调用，再并发竞争最后 1 个额度；行锁必须保证只有一个成功。
    for sequence in range(1, 8):
        await ledger.reserve(first_fence, _model_request(sequence))
    results = await asyncio.gather(
        ledger.reserve(first_fence, _model_request(8)),
        ledger.reserve(first_fence, _model_request(9)),
        return_exceptions=True,
    )
    successes = [item for item in results if not isinstance(item, BaseException)]
    errors = [item for item in results if isinstance(item, AgentRunError)]
    assert len(successes) == 1
    assert len(errors) == 1
    assert errors[0].code == "budget_exhausted"
    at_limit = await ledger.status(first_fence)
    assert at_limit.model_calls == 8
    assert len(await _attempt_rows(session_factory, first_run_id)) == 8

    # 同一逻辑步骤并发预留只能产生一个 prepared attempt 和一份预算。
    _, _, second_fence = await _running_run(session_factory)
    same_request = _model_request(1)
    reused = await asyncio.gather(
        ledger.reserve(second_fence, same_request),
        ledger.reserve(second_fence, same_request),
    )
    assert reused[0].attempt_id == reused[1].attempt_id
    second_status = await ledger.status(second_fence)
    assert second_status.model_calls == 1
    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AgentStepRecord)
                .where(AgentStepRecord.run_id == second_fence.run_id)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_append_authorization_enables_extra_calls_but_never_touches_planning_pool(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)

    # 先建立合成资金池，证明 AP-05 式 Agent 预算追加不推动规划代次或资金资料。
    async with session_factory() as session, session.begin():
        session.add(
            PlanningPoolRecord(
                id=uuid4(),
                workspace_id=WORKSPACE_ID,
                generation=3,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    for sequence in range(1, 9):
        await ledger.reserve(fence, _model_request(sequence))
    with pytest.raises(AgentRunError) as exhausted:
        await ledger.reserve(fence, _model_request(9))
    assert exhausted.value.code == "budget_exhausted"

    authorization_ref = uuid4()
    increased = _limits(model_calls=9)
    status = await ledger.append_authorization(
        fence,
        increased,
        authorization_ref=authorization_ref,
        reason="合成 AP-05 追加授权",
    )
    assert status.model_limit == 9
    ninth = await ledger.reserve(fence, _model_request(9))
    assert ninth.status is AttemptStatus.PREPARED

    # 同一授权引用重放是幂等的；换内容复用同一引用必须拒绝。
    replay = await ledger.append_authorization(
        fence,
        increased,
        authorization_ref=authorization_ref,
        reason="合成 AP-05 追加授权",
    )
    assert replay.model_limit == 9
    with pytest.raises(AgentRunError) as conflicting_ref:
        await ledger.append_authorization(
            fence,
            _limits(model_calls=10),
            authorization_ref=authorization_ref,
            reason="冲突的追加授权",
        )
    assert conflicting_ref.value.code == "invalid_budget_authorization"

    with pytest.raises(AgentRunError) as hard_breach:
        await ledger.append_authorization(
            fence,
            _limits(model_calls=33),
            authorization_ref=uuid4(),
            reason="超过部署硬上限",
        )
    assert hard_breach.value.code == "invalid_budget_authorization"

    with pytest.raises(AgentRunError) as decrease:
        await ledger.append_authorization(
            fence,
            _limits(model_calls=8),
            authorization_ref=uuid4(),
            reason="不能降低已有上限",
        )
    assert decrease.value.code == "invalid_budget_authorization"

    async with session_factory() as session:
        pool = await session.scalar(
            select(PlanningPoolRecord).where(PlanningPoolRecord.workspace_id == WORKSPACE_ID)
        )
        assert pool is not None
        assert pool.generation == 3
    assert await _count(session_factory, BudgetAuthorizationRecord) == 2


@pytest.mark.asyncio
async def test_activity_budget_records_segment_time_and_blocks_calls_below_margin(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)

    assert (await ledger.record_activity(fence, 100)).active_seconds == 100
    second_segment = await _new_segment(session_factory, fence)
    assert (await ledger.record_activity(second_segment, 484)).active_seconds == 584
    # 584+15 < 600，仍可开始最后一个有界调用。
    await ledger.reserve(second_segment, _model_request(1))

    third_segment = await _new_segment(session_factory, second_segment)
    assert (await ledger.record_activity(third_segment, 1)).active_seconds == 585
    with pytest.raises(AgentRunError) as margin:
        await ledger.reserve(third_segment, _model_request(2))
    assert margin.value.code == "budget_exhausted"

    # 同一片段重放相同活动时长是幂等的，不同时长不能悄悄覆盖真实记录。
    assert (await ledger.record_activity(third_segment, 1)).active_seconds == 585
    with pytest.raises(AgentRunError) as conflicting_activity:
        await ledger.record_activity(third_segment, 2)
    assert conflicting_activity.value.code == "invalid_activity"

    appended = _limits(model_calls=8, active_seconds=900)
    await ledger.append_authorization(
        third_segment,
        appended,
        authorization_ref=uuid4(),
        reason="合成活动时间追加",
    )
    await ledger.reserve(third_segment, _model_request(2))
    next_segment = await _new_segment(session_factory, third_segment)
    assert (await ledger.record_activity(next_segment, 400)).active_seconds == 985


@pytest.mark.asyncio
async def test_recovers_in_flight_as_unknown_and_requires_verified_receipt_to_reconcile(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)
    request = _model_request(1)
    attempt = await ledger.reserve(fence, request)
    await ledger.mark_sent(fence, attempt.attempt_id)

    recovery_fence = await _new_segment(session_factory, fence)
    # 新片段可把失租的在途调用保守标记为 unknown，不假定未发送或无费用。
    await ledger.settle(
        recovery_fence,
        attempt.attempt_id,
        AttemptResult(status=AttemptStatus.UNKNOWN, reason_code="worker_terminated"),
    )
    status = await ledger.status(recovery_fence)
    assert status.model_calls == 1
    assert status.model_sent == 1
    assert status.input_tokens == 1024

    # 未知后的成功结算必须有可验证供应商回执；无回执不得解除未知。
    with pytest.raises(AgentRunError) as receipt_required:
        await ledger.settle(
            recovery_fence,
            attempt.attempt_id,
            AttemptResult(
                status=AttemptStatus.SUCCEEDED,
                result_ref=_result_ref(),
                usage=TokenUsage(input_tokens=100, output_tokens=10),
            ),
        )
    assert receipt_required.value.code == "receipt_required"

    await ledger.settle(
        recovery_fence,
        attempt.attempt_id,
        AttemptResult(
            status=AttemptStatus.SUCCEEDED,
            result_ref=_result_ref(),
            usage=TokenUsage(input_tokens=100, output_tokens=10),
            provider_receipt="receipt-verified-2",
            receipt_verified=True,
        ),
    )
    assert (await ledger.status(recovery_fence)).input_tokens == 100


@pytest.mark.asyncio
async def test_tool_and_transport_reservations_count_each_real_send_without_tokens(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)

    tool = await ledger.reserve(
        fence,
        _non_model_request(1, AttemptCategory.TOOL),
    )
    transport = await ledger.reserve(
        fence,
        _non_model_request(2, AttemptCategory.TRANSPORT),
    )
    await ledger.mark_sent(fence, tool.attempt_id)
    await ledger.mark_sent(fence, transport.attempt_id)
    await ledger.settle(
        fence,
        tool.attempt_id,
        AttemptResult(status=AttemptStatus.SUCCEEDED, result_ref=_result_ref()),
    )
    await ledger.settle(
        fence,
        transport.attempt_id,
        AttemptResult(status=AttemptStatus.SUCCEEDED, result_ref=_result_ref()),
    )

    status = await ledger.status(fence)
    assert status.model_calls == 0
    assert status.tool_calls == 1
    assert status.tool_sent == 1
    assert status.transport_calls == 1
    assert status.input_tokens == 0
    assert status.output_tokens == 0
    assert await _count(session_factory, BudgetReservationRecord) == 2


@pytest.mark.asyncio
async def test_fence_lease_and_immutable_ledger_rows_reject_stale_or_tampered_writes(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    run_id, owner, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)
    attempt = await ledger.reserve(fence, _model_request(1))
    await ledger.mark_sent(fence, attempt.attempt_id)
    await ledger.settle(
        fence,
        attempt.attempt_id,
        AttemptResult(
            status=AttemptStatus.SUCCEEDED,
            result_ref=_result_ref(),
            usage=TokenUsage(input_tokens=100, output_tokens=10),
        ),
    )

    # 旧 owner、旧租约代次与跨工作台围栏都不能读取或写入预算账本。
    for stale in (
        fence.model_copy(update={"owner": uuid4()}),
        fence.model_copy(update={"lease_epoch": 2}),
        fence.model_copy(update={"workspace_id": uuid4()}),
        fence.model_copy(update={"revision": 2}),
    ):
        with pytest.raises(AgentRunError) as rejected:
            await ledger.status(stale)
        assert rejected.value.code == "lease_lost"

    async with session_factory() as session, session.begin():
        await session.execute(
            update(AgentRunRecord)
            .where(AgentRunRecord.id == run_id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    with pytest.raises(AgentRunError) as expired:
        await ledger.status(fence)
    assert expired.value.code == "lease_lost"

    # 恢复租约后验证历史行不可被篡改或删除；失败的尝试/费用不能回写成成功。
    async with session_factory() as session, session.begin():
        await session.execute(
            update(AgentRunRecord)
            .where(AgentRunRecord.id == run_id)
            .values(lease_expires_at=datetime.now(UTC) + timedelta(hours=1))
        )
    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                update(AgentStepRecord)
                .where(AgentStepRecord.run_id == run_id)
                .values(action_sequence=99)
            )
    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError, match="terminal"):
            await session.execute(
                update(AgentAttemptRecord)
                .where(AgentAttemptRecord.id == attempt.attempt_id)
                .values(status="prepared")
            )
    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                delete(BudgetAuthorizationRecord).where(BudgetAuthorizationRecord.run_id == run_id)
            )
    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(delete(BudgetReservationRecord))

    # 旧 owner 的发送被拒绝，不能把已结算步骤重新交给迟到 worker。
    with pytest.raises(AgentRunError) as stale_send:
        await ledger.mark_sent(
            fence.model_copy(update={"owner": owner, "lease_epoch": 9}),
            attempt.attempt_id,
        )
    assert stale_send.value.code == "lease_lost"


@pytest.mark.asyncio
async def test_failed_transaction_leaves_no_partial_attempt_or_reservation(
    migrated_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)

    async def fail_insert(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic ledger failure")

    monkeypatch.setattr(agent_attempt_repository, "_insert_attempt", fail_insert)
    with pytest.raises(RuntimeError, match="synthetic ledger failure"):
        await ledger.reserve(fence, _model_request(1))

    # 预留事务整体回滚，不能留下孤立步骤、尝试或占额度的 reservation。
    assert await _count(session_factory, AgentStepRecord) == 0
    assert await _count(session_factory, AgentAttemptRecord) == 0
    assert await _count(session_factory, BudgetReservationRecord) == 0
    assert await _count(session_factory, BudgetAuthorizationRecord) == 0


# 构造绝对上限对象；追加授权使用绝对值而非增量。
def _limits(**overrides: Any) -> BudgetLimits:
    values: dict[str, Any] = {
        "model_calls": 8,
        "tool_calls": 12,
        "input_tokens": 98304,
        "output_tokens": 32768,
        "active_seconds": 600,
        "transport_calls": 64,
    }
    values.update(overrides)
    return BudgetLimits(**values)


@pytest.mark.asyncio
async def test_tool_budget_rejects_thirteenth_call_before_append_authorization(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)

    for sequence in range(1, 13):
        await ledger.reserve(fence, _non_model_request(sequence, AttemptCategory.TOOL))
    with pytest.raises(AgentRunError) as exhausted:
        await ledger.reserve(fence, _non_model_request(13, AttemptCategory.TOOL))
    assert exhausted.value.code == "budget_exhausted"

    status = await ledger.append_authorization(
        fence,
        _limits(tool_calls=13),
        authorization_ref=uuid4(),
        reason="合成工具次数追加",
    )
    assert status.tool_limit == 13
    thirteenth = await ledger.reserve(
        fence,
        _non_model_request(13, AttemptCategory.TOOL),
    )
    assert thirteenth.status is AttemptStatus.PREPARED
    assert thirteenth.category is AttemptCategory.TOOL
    assert (await ledger.status(fence)).tool_calls == 13


@pytest.mark.asyncio
async def test_mark_sent_blocks_prepared_when_actual_usage_exceeds_token_limit(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)

    # 六个大预留加一个待发送预留；前四个实际输入比预留高但仍未超过单次上限。
    attempts = [
        await ledger.reserve(
            fence,
            _model_request(sequence, input_tokens=16000, output_tokens=512),
        )
        for sequence in range(1, 7)
    ]
    target = await ledger.reserve(fence, _model_request(7, input_tokens=1024))
    for attempt in attempts[:4]:
        await ledger.mark_sent(fence, attempt.attempt_id)
        await ledger.settle(
            fence,
            attempt.attempt_id,
            AttemptResult(
                status=AttemptStatus.SUCCEEDED,
                result_ref=_result_ref(),
                usage=TokenUsage(input_tokens=16384, output_tokens=1),
            ),
        )

    over_limit = await ledger.status(fence)
    assert over_limit.input_tokens > over_limit.input_token_limit

    # prepared 的自身预留已在累计中，发送前不能再放宽一次额度；应保持 prepared。
    with pytest.raises(AgentRunError) as blocked:
        await ledger.mark_sent(fence, target.attempt_id)
    assert blocked.value.code == "budget_exhausted"
    async with session_factory() as session:
        row = await session.get(AgentAttemptRecord, target.attempt_id)
        assert row is not None
        assert row.status == AttemptStatus.PREPARED.value

    # 取得足额追加授权后，同一 prepared 才能发送；不重复加一份预留。
    await ledger.append_authorization(
        fence,
        _limits(input_tokens=100000),
        authorization_ref=uuid4(),
        reason="合成输入 Token 追加",
    )
    await ledger.mark_sent(fence, target.attempt_id)
    assert (await ledger.status(fence)).model_sent == 5


@pytest.mark.asyncio
async def test_historical_unknown_can_be_reconciled_by_current_fence_with_verified_receipt(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, old_fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)
    request = _model_request(1)
    attempt = await ledger.reserve(old_fence, request)
    await ledger.mark_sent(old_fence, attempt.attempt_id)
    await ledger.settle(
        old_fence,
        attempt.attempt_id,
        AttemptResult(status=AttemptStatus.UNKNOWN, reason_code="provider_timeout"),
    )

    # 修订推进后，当前 owner 的新围栏可对账旧 unknown，但必须有可验证回执。
    current_fence = await _new_segment(session_factory, old_fence, revision=2)
    with pytest.raises(AgentRunError) as missing_receipt:
        await ledger.settle(
            current_fence,
            attempt.attempt_id,
            AttemptResult(status=AttemptStatus.FAILED, reason_code="receipt_missing"),
        )
    assert missing_receipt.value.code == "receipt_required"

    await ledger.settle(
        current_fence,
        attempt.attempt_id,
        AttemptResult(
            status=AttemptStatus.SUCCEEDED,
            result_ref=_result_ref(),
            usage=TokenUsage(input_tokens=500, output_tokens=50),
            provider_receipt="receipt-old-revision",
            receipt_verified=True,
        ),
    )
    status = await ledger.status(current_fence)
    assert status.model_calls == 1
    assert status.input_tokens == 500
    assert status.output_tokens == 50

    # 旧 revision 的 fence 仍然失效，不能重新取得执行权。
    with pytest.raises(AgentRunError) as old_writer:
        await ledger.status(old_fence)
    assert old_writer.value.code == "lease_lost"


@pytest.mark.asyncio
async def test_historical_prepared_cannot_be_sent_after_revision_advance(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, old_fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)
    attempt = await ledger.reserve(old_fence, _model_request(1))

    current_fence = await _new_segment(session_factory, old_fence, revision=2)
    # 新围栏只允许对账历史 unknown/in_flight 回执，不能发送旧 revision 的 prepared。
    with pytest.raises(AgentRunError) as hidden:
        await ledger.mark_sent(current_fence, attempt.attempt_id)
    assert hidden.value.code == "attempt_not_found"
    with pytest.raises(AgentRunError) as stale:
        await ledger.mark_sent(old_fence, attempt.attempt_id)
    assert stale.value.code == "lease_lost"


@pytest.mark.asyncio
async def test_pre_send_failure_releases_budget_without_faking_sent_at(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)
    request = _model_request(1)

    first = await ledger.reserve(fence, request)
    await ledger.settle(
        fence,
        first.attempt_id,
        AttemptResult(status=AttemptStatus.FAILED, reason_code="cancelled_before_send"),
    )

    rows = await _attempt_rows(session_factory, fence.run_id)
    assert len(rows) == 1
    assert rows[0].status == AttemptStatus.FAILED.value
    assert rows[0].sent_at is None
    assert rows[0].settled_at is not None
    async with session_factory() as session:
        reservations = list(
            (
                await session.scalars(
                    select(BudgetReservationRecord).where(
                        BudgetReservationRecord.attempt_id == first.attempt_id
                    )
                )
            ).all()
        )
    assert len(reservations) == 3
    assert {row.state for row in reservations} == {"released"}
    assert all(row.actual_amount is None for row in reservations)

    # 发送前失败不消耗模型次数/Token，但仍占用该逻辑步骤的一次 attempt。
    released = await ledger.status(fence)
    assert released.model_calls == 0
    assert released.model_sent == 0
    assert released.input_tokens == 0
    assert released.output_tokens == 0

    second = await ledger.reserve(fence, request)
    assert second.attempt_number == 2
    assert second.status is AttemptStatus.PREPARED
    await ledger.settle(
        fence,
        second.attempt_id,
        AttemptResult(status=AttemptStatus.FAILED, reason_code="cancelled_before_send"),
    )
    with pytest.raises(AgentRunError) as third:
        await ledger.reserve(fence, request)
    assert third.value.code == "attempt_limit"


@pytest.mark.asyncio
async def test_sql_rejects_actual_on_unsettled_token_reservation_and_bad_insert(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, fence = await _running_run(session_factory)
    ledger = SqlAlchemyBudgetLedger(session_factory, clock=lambda: NOW)
    model_attempt = await ledger.reserve(fence, _model_request(1))

    # prepared 的 Token 行在发送前只有预留；直接写 actual=0 不得静默释放。
    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError) as rejected_update:
            await session.execute(
                update(BudgetReservationRecord)
                .where(
                    BudgetReservationRecord.attempt_id == model_attempt.attempt_id,
                    BudgetReservationRecord.meter.in_(("input_tokens", "output_tokens")),
                )
                .values(actual_amount=0)
            )
    _assert_check_violation(rejected_update.value, "ck_budget_reservation_shape")
    unchanged = await ledger.status(fence)
    assert unchanged.input_tokens == 1024
    assert unchanged.output_tokens == 512

    # 使用没有既有 meter 行的合成尝试，避免 (attempt_id, meter) 唯一键掩盖形状错误。
    bare_attempt_id = await _insert_bare_model_attempt(session_factory, fence)

    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError) as rejected_unknown:
            session.add(
                BudgetReservationRecord(
                    id=uuid4(),
                    attempt_id=bare_attempt_id,
                    workspace_id=WORKSPACE_ID,
                    run_id=fence.run_id,
                    segment_id=fence.segment_id,
                    meter="input_tokens",
                    reserved_amount=100,
                    actual_amount=0,
                    state="unknown",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.flush()
    _assert_check_violation(rejected_unknown.value, "ck_budget_reservation_shape")

    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError) as rejected_reserved_count:
            session.add(
                BudgetReservationRecord(
                    id=uuid4(),
                    attempt_id=bare_attempt_id,
                    workspace_id=WORKSPACE_ID,
                    run_id=fence.run_id,
                    segment_id=fence.segment_id,
                    meter="model_calls",
                    reserved_amount=1,
                    actual_amount=1,
                    state="reserved",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.flush()
    _assert_check_violation(rejected_reserved_count.value, "ck_budget_reservation_shape")


@pytest.mark.asyncio
async def test_sql_count_settled_requires_non_null_actual_but_allows_one(
    migrated_database: Database,
) -> None:
    session_factory = migrated_database.session_factory
    _, _, fence = await _running_run(session_factory)
    attempt_id = await _insert_bare_model_attempt(session_factory, fence, action_sequence=901)

    # R1：state='settled' AND actual_amount=1 在 actual 为 NULL 时整体为 NULL，
    # PostgreSQL CHECK 因此放行；直接 INSERT 必须由显式非空条件拒绝。
    async with session_factory() as session, session.begin():
        with pytest.raises(DBAPIError) as settled_null:
            session.add(
                BudgetReservationRecord(
                    id=uuid4(),
                    attempt_id=attempt_id,
                    workspace_id=WORKSPACE_ID,
                    run_id=fence.run_id,
                    segment_id=fence.segment_id,
                    meter="model_calls",
                    reserved_amount=1,
                    actual_amount=None,
                    state="settled",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.flush()
    _assert_check_violation(settled_null.value, "ck_budget_reservation_shape")

    # settled + actual=1 是合法终态；事务回滚避免污染后续预算聚合。
    async with session_factory() as session:
        session.add(
            BudgetReservationRecord(
                id=uuid4(),
                attempt_id=attempt_id,
                workspace_id=WORKSPACE_ID,
                run_id=fence.run_id,
                segment_id=fence.segment_id,
                meter="model_calls",
                reserved_amount=1,
                actual_amount=1,
                state="settled",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        await session.rollback()

    # charged + actual=1 是 mark_sent 的合法次数形状；同样回滚。
    async with session_factory() as session:
        session.add(
            BudgetReservationRecord(
                id=uuid4(),
                attempt_id=attempt_id,
                workspace_id=WORKSPACE_ID,
                run_id=fence.run_id,
                segment_id=fence.segment_id,
                meter="model_calls",
                reserved_amount=1,
                actual_amount=1,
                state="charged",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        await session.rollback()
