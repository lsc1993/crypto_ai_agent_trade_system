# 验证 T06 人工审核、连续消息与取消的 PostgreSQL 一致性：CAS、请求幂等、材料指纹、
# 单待办、消息水位、取消竞态及不可变触发。每个用例只操作迁移夹具创建的随机 schema。
# 测试使用合成任务/审核材料/消息文本；不访问模型、账户、真实资金或交易执行。
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent_runs.attempts import AttemptCategory, AttemptRequest
from app.agent_runs.contracts import AgentRunError, RunInput, RunStatus
from app.agent_runs.decisions import ControlAction, ProposalDiff
from app.agent_runs.interactions import (
    InteractionDecision,
    InteractionDraft,
    InteractionResponse,
    InteractionStatus,
)
from app.agent_runs.messages import MessageKind, UserMessage
from app.agent_runs.segments import RunFence
from app.agent_runs.service import AgentRunService
from app.infrastructure.persistence.agent_attempt_repository import SqlAlchemyBudgetLedger
from app.infrastructure.persistence.agent_interaction_repository import (
    SqlAlchemyAgentInteractionRepository,
    SqlAlchemyAgentMessageRepository,
)
from app.infrastructure.persistence.agent_run_repository import SqlAlchemyAgentRunRepository
from app.infrastructure.persistence.base import Base
from app.infrastructure.persistence.models.agent_interactions import (
    AgentInteractionFeedbackRecord,
    AgentInteractionRecord,
    AgentRunCancelRequestRecord,
    AgentUserMessageRecord,
)
from app.infrastructure.persistence.models.agent_runs import AgentRunRecord
from app.market.contracts import MarketTimeframe
from app.shared.agent_types import ArtifactRef, ProductKey, VersionRef
from app.trade_planning.inputs import PlanningRefs

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
WORKSPACE_ID = uuid4()


# 测试只依赖迁移夹具暴露的异步会话工厂，不导入具体数据库夹具类型。
class Database(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


# 构造合成任务输入；审核材料只含引用，财务字段不进入请求或事件。
def _input() -> RunInput:
    return RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1,),
        goal="验证人工审核与取消一致性",
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


def _artifact() -> ArtifactRef:
    return ArtifactRef(artifact_id=uuid4(), sha256="f" * 64)


def _draft(
    *,
    request_id: UUID | None = None,
    expires_in: timedelta = timedelta(hours=1),
) -> InteractionDraft:
    return InteractionDraft(
        request_id=request_id or uuid4(),
        action=ControlAction.ADOPT_MANUAL_PLAN,
        material_hash="1" * 64,
        expires_at=datetime.now(UTC) + expires_in,
        diffs=(
            ProposalDiff(
                field="entry_zone",
                before_ref=_artifact(),
                after_ref=_artifact(),
                reason_code="new_candidate",
            ),
        ),
        material_refs=(_artifact(),),
        safe_reason="plan_ready_for_review",
    )


# 通过 T04 仓储建立任务；T06 不实现领取/心跳，直接推进为 running 供 prepare 使用。
async def _running_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, RunFence]:
    repository = SqlAlchemyAgentRunRepository(session_factory, clock=lambda: NOW)
    snapshot = await repository.enqueue(WORKSPACE_ID, _input())
    owner = uuid4()
    async with session_factory() as session, session.begin():
        run = await session.get(AgentRunRecord, snapshot.run_id)
        if run is None:
            raise AssertionError("synthetic run missing")
        run.status = RunStatus.RUNNING.value
        run.owner = owner
        run.lease_epoch = 1
        run.lease_expires_at = datetime.now(UTC) + timedelta(hours=1)
        run.started_at = NOW
    fence = RunFence(
        workspace_id=WORKSPACE_ID,
        run_id=snapshot.run_id,
        revision=1,
        segment_id=uuid4(),
        owner=owner,
        lease_epoch=1,
    )
    return snapshot.run_id, fence


# 直接建立 pending 待办；生产环境由 T07 coordinator 在图结束后原子发布。
async def _pending_interaction(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_id: UUID,
    material_hash: str = "2" * 64,
    expires_at: datetime | None = None,
    action: ControlAction = ControlAction.ADOPT_MANUAL_PLAN,
) -> UUID:
    interaction_id = uuid4()
    deadline = expires_at or (datetime.now(UTC) + timedelta(hours=1))
    async with session_factory() as session, session.begin():
        run = await session.get(AgentRunRecord, run_id)
        if run is None:
            raise AssertionError("synthetic run missing")
        run.status = RunStatus.WAITING_APPROVAL.value
        run.owner = None
        run.lease_expires_at = None
        run.current_interaction_id = interaction_id
        run.state_version = 1
        run.updated_at = NOW
        session.add(
            AgentInteractionRecord(
                id=interaction_id,
                workspace_id=WORKSPACE_ID,
                run_id=run_id,
                revision=1,
                action=action.value,
                status=InteractionStatus.PENDING.value,
                material_hash=material_hash,
                state_version=0,
                expires_at=deadline,
                diffs=[
                    {
                        "field": "entry_zone",
                        "beforeRef": _artifact().model_dump(mode="json"),
                        "afterRef": _artifact().model_dump(mode="json"),
                        "reasonCode": "new_candidate",
                    }
                ],
                material_refs=[_artifact().model_dump(mode="json")],
                safe_reason="plan_ready_for_review",
                open_request_id=uuid4(),
                open_request_sha256="3" * 64,
                created_at=NOW,
                published_at=NOW,
            )
        )
    return interaction_id


def _response(
    interaction_id: UUID,
    *,
    request_id: UUID | None = None,
    expected_state_version: int = 0,
    reviewed_payload_hash: str = "2" * 64,
    decision: InteractionDecision = InteractionDecision.APPROVE,
    **overrides: object,
) -> InteractionResponse:
    values: dict[str, object] = {
        "request_id": request_id or uuid4(),
        "interaction_id": interaction_id,
        "expected_state_version": expected_state_version,
        "reviewed_payload_hash": reviewed_payload_hash,
        "decision": decision,
    }
    values.update(overrides)
    return InteractionResponse.model_validate(values)


def _repository(
    session_factory: async_sessionmaker[AsyncSession],
) -> SqlAlchemyAgentInteractionRepository:
    return SqlAlchemyAgentInteractionRepository(session_factory, clock=lambda: NOW)


def _messages(
    session_factory: async_sessionmaker[AsyncSession],
) -> SqlAlchemyAgentMessageRepository:
    return SqlAlchemyAgentMessageRepository(session_factory, clock=lambda: NOW)


async def _count(session_factory: async_sessionmaker[AsyncSession], model: type[Base]) -> int:
    async with session_factory() as session:
        value = await session.scalar(select(func.count()).select_from(model))
    return int(value or 0)


# 按准备 -> 发布 -> 响应 -> 应用的合法迁移推进测试待办，供后续 prepare 使用。
async def _apply_interaction(
    session_factory: async_sessionmaker[AsyncSession],
    interaction_id: UUID,
) -> None:
    transitions = (
        (InteractionStatus.PENDING, {"published_at": NOW}),
        (InteractionStatus.ANSWERED, {"responded_at": NOW}),
        (InteractionStatus.APPLIED, {"applied_at": NOW}),
    )
    state_version = 0
    for status, values in transitions:
        state_version += 1
        async with session_factory() as session, session.begin():
            row = await session.get(AgentInteractionRecord, interaction_id)
            if row is None:
                raise AssertionError("synthetic interaction missing")
            row.status = status.value
            row.state_version = state_version
            for field, value in values.items():
                setattr(row, field, value)


@pytest.mark.asyncio
async def test_prepare_is_idempotent_and_allows_only_one_active_interaction(
    migrated_database: Database,
) -> None:
    _, fence = await _running_run(migrated_database.session_factory)
    repository = _repository(migrated_database.session_factory)
    draft = _draft()

    prepared = await repository.prepare(fence, draft)

    assert prepared.status is InteractionStatus.PREPARING
    assert prepared.state_version == 0
    assert prepared.published_at is None
    assert prepared.can_respond is False

    # 同请求键同内容必须返回同一待办，不能因页面重试生成第二个准备项。
    replay = await repository.prepare(fence, draft)
    assert replay == prepared
    assert await _count(migrated_database.session_factory, AgentInteractionRecord) == 1

    # 同键不同材料必须冲突；不同键在已有活跃待办时也必须拒绝。
    with pytest.raises(AgentRunError) as conflict:
        await repository.prepare(
            fence,
            draft.model_copy(update={"material_hash": "9" * 64}),
        )
    assert conflict.value.code == "request_conflict"

    with pytest.raises(AgentRunError) as active:
        await repository.prepare(fence, _draft())
    assert active.value.code == "interaction_active"

    # 待办按合法状态逐步应用后才能准备下一项；不能从 preparing 直接跳到 applied。
    await _apply_interaction(migrated_database.session_factory, prepared.interaction_id)
    next_prepared = await repository.prepare(fence, _draft())
    assert next_prepared.interaction_id != prepared.interaction_id


@pytest.mark.asyncio
async def test_respond_is_cas_bound_and_never_claims_plan_adoption(
    migrated_database: Database,
) -> None:
    run_id, _ = await _running_run(migrated_database.session_factory)
    interaction_id = await _pending_interaction(
        migrated_database.session_factory,
        run_id=run_id,
    )
    repository = _repository(migrated_database.session_factory)
    response = _response(interaction_id)

    receipt = await repository.respond(WORKSPACE_ID, run_id, response)

    assert receipt.receipt_state == "recorded"
    assert receipt.adoption_applied is False
    assert receipt.interaction_status is InteractionStatus.ANSWERED
    assert receipt.run_status is RunStatus.QUEUED
    assert receipt.state_version == 2

    # 同请求键重放返回原回执且不再次推进状态；不同键再次响应旧待办冲突。
    replay = await repository.respond(WORKSPACE_ID, run_id, response)
    assert replay == receipt
    assert await _count(migrated_database.session_factory, AgentInteractionFeedbackRecord) == 1

    with pytest.raises(AgentRunError) as duplicate:
        await repository.respond(
            WORKSPACE_ID,
            run_id,
            _response(interaction_id, expected_state_version=0),
        )
    assert duplicate.value.code == "review_conflict"

    # 同请求键不同内容必须冲突，不能把两次不同决定折叠成同一回执。
    with pytest.raises(AgentRunError) as key_conflict:
        await repository.respond(
            WORKSPACE_ID,
            run_id,
            _response(
                interaction_id,
                request_id=response.request_id,
                expected_state_version=0,
                decision=InteractionDecision.REJECT,
            ),
        )
    assert key_conflict.value.code == "request_conflict"


@pytest.mark.asyncio
async def test_respond_rejects_stale_material_version_and_invalid_decision(
    migrated_database: Database,
) -> None:
    run_id, _ = await _running_run(migrated_database.session_factory)
    interaction_id = await _pending_interaction(
        migrated_database.session_factory,
        run_id=run_id,
    )
    repository = _repository(migrated_database.session_factory)

    # 材料指纹不一致说明用户审阅的是旧版本，必须拒绝而不是接受“同意”。
    with pytest.raises(AgentRunError) as stale_material:
        await repository.respond(
            WORKSPACE_ID,
            run_id,
            _response(interaction_id, reviewed_payload_hash="4" * 64),
        )
    assert stale_material.value.code == "review_conflict"

    # 状态号 CAS 失败同样拒绝，防止两个页面基于同一旧版本共同推进。
    with pytest.raises(AgentRunError) as stale_version:
        await repository.respond(
            WORKSPACE_ID,
            run_id,
            _response(interaction_id, expected_state_version=1),
        )
    assert stale_version.value.code == "review_conflict"

    # 审批动作夹带修改项属于错误类型，必须请求修改而不是偷偷应用审批。
    with pytest.raises(ValidationError):
        _response(
            interaction_id,
            changes=(
                {
                    "field": "policy",
                    "afterRef": _artifact().model_dump(mode="json"),
                },
            ),
        )

    # 过期待办不能响应；服务端在拒绝时把任务与待办标记为 expired。
    expired_run_id, _ = await _running_run(migrated_database.session_factory)
    expired_id = await _pending_interaction(
        migrated_database.session_factory,
        run_id=expired_run_id,
        material_hash="5" * 64,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(AgentRunError) as expired:
        await repository.respond(
            WORKSPACE_ID,
            expired_run_id,
            _response(expired_id, reviewed_payload_hash="5" * 64),
        )
    assert expired.value.code == "review_expired"
    async with migrated_database.session_factory() as session:
        run = await session.get(AgentRunRecord, expired_run_id)
        interaction = await session.get(AgentInteractionRecord, expired_id)
        assert run is not None and interaction is not None
        assert run.status == RunStatus.EXPIRED.value
        assert interaction.status == InteractionStatus.EXPIRED.value


@pytest.mark.asyncio
async def test_concurrent_respond_has_one_winner_and_same_key_replays(
    migrated_database: Database,
) -> None:
    run_id, _ = await _running_run(migrated_database.session_factory)
    interaction_id = await _pending_interaction(
        migrated_database.session_factory,
        run_id=run_id,
    )
    repository = _repository(migrated_database.session_factory)

    # 两个不同请求键同时批准：只有先取得行锁者能推进，另一个稳定冲突。
    first = _response(interaction_id)
    second = _response(interaction_id)
    results = await asyncio.gather(
        repository.respond(WORKSPACE_ID, run_id, first),
        repository.respond(WORKSPACE_ID, run_id, second),
        return_exceptions=True,
    )
    successes = [item for item in results if not isinstance(item, Exception)]
    failures = [item for item in results if isinstance(item, AgentRunError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].code == "review_conflict"

    # 同一请求键的并发重试应返回同一记录结果，而不是一个成功一个冲突。
    run_id2, _ = await _running_run(migrated_database.session_factory)
    interaction_id2 = await _pending_interaction(
        migrated_database.session_factory,
        run_id=run_id2,
    )
    same = _response(interaction_id2)
    same_results = await asyncio.gather(
        repository.respond(WORKSPACE_ID, run_id2, same),
        repository.respond(WORKSPACE_ID, run_id2, same),
    )
    assert same_results[0] == same_results[1]
    assert await _count(migrated_database.session_factory, AgentInteractionFeedbackRecord) == 2


@pytest.mark.asyncio
async def test_cancel_before_response_and_cancel_after_recorded_feedback(
    migrated_database: Database,
) -> None:
    run_id, _ = await _running_run(migrated_database.session_factory)
    interaction_id = await _pending_interaction(
        migrated_database.session_factory,
        run_id=run_id,
    )
    interaction_repository = _repository(migrated_database.session_factory)
    run_service = AgentRunService(SqlAlchemyAgentRunRepository(migrated_database.session_factory))

    cancelled = await run_service.cancel(
        WORKSPACE_ID,
        run_id,
        request_id=uuid4(),
        expected_version=1,
    )
    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.current_interaction_id is None

    # 取消先提交后，迟到的响应不能把已取消任务重新打开。
    with pytest.raises(AgentRunError) as after_cancel:
        await interaction_repository.respond(
            WORKSPACE_ID,
            run_id,
            _response(interaction_id),
        )
    assert after_cancel.value.code == "run_terminal"

    # 反向顺序：反馈先记录并唤醒任务，随后取消；回执仍为 recorded，未应用。
    run_id2, _ = await _running_run(migrated_database.session_factory)
    interaction_id2 = await _pending_interaction(
        migrated_database.session_factory,
        run_id=run_id2,
    )
    receipt = await interaction_repository.respond(
        WORKSPACE_ID,
        run_id2,
        _response(interaction_id2),
    )
    assert receipt.receipt_state == "recorded"
    assert receipt.adoption_applied is False

    cancelled_after = await run_service.cancel(
        WORKSPACE_ID,
        run_id2,
        request_id=uuid4(),
        expected_version=receipt.state_version,
    )
    assert cancelled_after.status is RunStatus.CANCELLED
    async with migrated_database.session_factory() as session:
        interaction = await session.get(AgentInteractionRecord, interaction_id2)
        feedback = await session.scalar(
            select(AgentInteractionFeedbackRecord).where(
                AgentInteractionFeedbackRecord.interaction_id == interaction_id2
            )
        )
        assert interaction is not None and feedback is not None
        assert interaction.applied_at is None
        assert feedback.decision == "approve"


@pytest.mark.asyncio
async def test_running_cancel_sets_flag_without_reopening_terminal_run(
    migrated_database: Database,
) -> None:
    run_id, _ = await _running_run(migrated_database.session_factory)
    service = AgentRunService(SqlAlchemyAgentRunRepository(migrated_database.session_factory))
    request_id = uuid4()

    requested = await service.cancel(
        WORKSPACE_ID,
        run_id,
        request_id=request_id,
        expected_version=0,
    )
    assert requested.status is RunStatus.RUNNING
    assert requested.cancel_requested_at is not None
    assert requested.state_version == 1

    # 同请求键重放返回当前快照，不再推进状态或写重复事件。
    replay = await service.cancel(
        WORKSPACE_ID,
        run_id,
        request_id=request_id,
        expected_version=0,
    )
    assert replay.state_version == requested.state_version

    # 已终态任务不能被迟到取消重新打开；新请求键只读取当前终态。
    async with migrated_database.session_factory() as session, session.begin():
        run = await session.get(AgentRunRecord, run_id)
        if run is None:
            raise AssertionError("synthetic run missing")
        run.status = RunStatus.COMPLETED.value
        run.finished_at = NOW
        run.cancel_requested_at = None
        run.owner = None
        run.lease_expires_at = None
    terminal = await service.cancel(
        WORKSPACE_ID,
        run_id,
        request_id=uuid4(),
        expected_version=requested.state_version,
    )
    assert terminal.status is RunStatus.COMPLETED
    assert terminal.finished_at == NOW
    async with migrated_database.session_factory() as session:
        run = await session.get(AgentRunRecord, run_id)
        assert run is not None
        assert run.status == RunStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_message_watermarks_are_recorded_applied_separately(
    migrated_database: Database,
) -> None:
    run_id, fence = await _running_run(migrated_database.session_factory)
    run_repository = SqlAlchemyAgentRunRepository(migrated_database.session_factory)
    messages = _messages(migrated_database.session_factory)

    first = UserMessage(
        request_id=uuid4(),
        kind=MessageKind.TEXT,
        text="请补充反证",
    )
    receipt = await messages.record(WORKSPACE_ID, run_id, first)
    assert receipt.receipt_state == "recorded"
    assert receipt.received_message_seq == 1
    assert receipt.applied_message_seq == 0

    # 同键重放不重复占用序号；同键不同内容稳定冲突。
    assert await messages.record(WORKSPACE_ID, run_id, first) == receipt
    with pytest.raises(AgentRunError) as conflict:
        await messages.record(
            WORKSPACE_ID,
            run_id,
            first.model_copy(update={"text": "另一个消息"}),
        )
    assert conflict.value.code == "request_conflict"

    second = UserMessage(
        request_id=uuid4(),
        kind=MessageKind.TEXT,
        text="继续",
    )
    second_receipt = await messages.record(WORKSPACE_ID, run_id, second)
    assert second_receipt.sequence == 2
    # “继续”只是普通上下文，不改变授权、预算或任务状态。
    snapshot = await run_repository.get(WORKSPACE_ID, run_id)
    assert snapshot is not None
    assert snapshot.status is RunStatus.RUNNING
    assert snapshot.received_message_seq == 2
    assert snapshot.applied_message_seq == 0
    assert snapshot.messages_pending is True

    applied = await messages.mark_applied(fence, 1)
    assert applied.applied_message_seq == 1
    assert applied.messages_pending is True
    async with migrated_database.session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(AgentUserMessageRecord).order_by(AgentUserMessageRecord.sequence)
                )
            ).all()
        )
        assert [row.applied_at is not None for row in rows] == [True, False]

    with pytest.raises(AgentRunError) as beyond:
        await messages.mark_applied(fence, 3)
    assert beyond.value.code == "invalid_message"

    # 终态任务不接受新消息，避免把迟到的“继续”当成重新开始。
    async with migrated_database.session_factory() as session, session.begin():
        run = await session.get(AgentRunRecord, run_id)
        if run is None:
            raise AssertionError("synthetic run missing")
        run.status = RunStatus.COMPLETED.value
        run.finished_at = NOW
        run.owner = None
        run.lease_expires_at = None
    with pytest.raises(AgentRunError) as terminal:
        await messages.record(
            WORKSPACE_ID,
            run_id,
            UserMessage(request_id=uuid4(), kind=MessageKind.TEXT, text="迟到消息"),
        )
    assert terminal.value.code == "run_terminal"


@pytest.mark.asyncio
async def test_interaction_and_message_database_guards_reject_unsafe_history(
    migrated_database: Database,
) -> None:
    run_id, _ = await _running_run(migrated_database.session_factory)
    interaction_id = await _pending_interaction(
        migrated_database.session_factory,
        run_id=run_id,
    )
    repository = _repository(migrated_database.session_factory)
    messages = _messages(migrated_database.session_factory)

    # 部分唯一索引拒绝同任务第二个活跃待办；数据库不能只依赖应用层判断。
    with pytest.raises(DBAPIError):
        async with migrated_database.session_factory() as session, session.begin():
            session.add(
                AgentInteractionRecord(
                    id=uuid4(),
                    workspace_id=WORKSPACE_ID,
                    run_id=run_id,
                    revision=1,
                    action=ControlAction.ADOPT_MANUAL_PLAN.value,
                    status=InteractionStatus.PENDING.value,
                    material_hash="6" * 64,
                    state_version=0,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                    diffs=[],
                    material_refs=[],
                    safe_reason="duplicate_pending",
                    open_request_id=uuid4(),
                    open_request_sha256="6" * 64,
                    created_at=NOW,
                    published_at=NOW,
                )
            )

    # 已记录反馈不可改写；用户不能删除历史决定。
    receipt = await repository.respond(
        WORKSPACE_ID,
        run_id,
        _response(interaction_id),
    )
    with pytest.raises(DBAPIError):
        async with migrated_database.session_factory() as session, session.begin():
            await session.execute(
                update(AgentInteractionFeedbackRecord)
                .where(AgentInteractionFeedbackRecord.interaction_id == interaction_id)
                .values(decision=InteractionDecision.REJECT.value)
            )
    assert receipt.receipt_state == "recorded"

    # 消息正文不可改；只有 applied_at 可由 worker 推进。
    message_receipt = await messages.record(
        WORKSPACE_ID,
        run_id,
        UserMessage(request_id=uuid4(), kind=MessageKind.TEXT, text="原始内容"),
    )
    with pytest.raises(DBAPIError):
        async with migrated_database.session_factory() as session, session.begin():
            await session.execute(
                update(AgentUserMessageRecord)
                .where(AgentUserMessageRecord.id == message_receipt.message_id)
                .values(text="篡改内容")
            )

    # 取消请求映射是不可变幂等记录，不能被重写。
    current = await SqlAlchemyAgentRunRepository(migrated_database.session_factory).get(
        WORKSPACE_ID, run_id
    )
    if current is None:
        raise AssertionError("synthetic run missing")
    cancel = AgentRunService(SqlAlchemyAgentRunRepository(migrated_database.session_factory))
    await cancel.cancel(
        WORKSPACE_ID,
        run_id,
        request_id=uuid4(),
        expected_version=current.state_version,
    )
    with pytest.raises(DBAPIError):
        async with migrated_database.session_factory() as session, session.begin():
            await session.execute(
                update(AgentRunCancelRequestRecord).values(request_sha256="8" * 64)
            )


@pytest.mark.asyncio
async def test_expire_due_and_list_interactions_keep_safe_history(
    migrated_database: Database,
) -> None:
    run_id, _ = await _running_run(migrated_database.session_factory)
    interaction_id = await _pending_interaction(
        migrated_database.session_factory,
        run_id=run_id,
        material_hash="a" * 64,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    repository = _repository(migrated_database.session_factory)

    listed = await repository.list_interactions(WORKSPACE_ID, run_id)
    assert [item.interaction_id for item in listed] == [interaction_id]
    assert listed[0].can_respond is True

    assert await repository.expire_due(WORKSPACE_ID, run_id) == 1
    assert await repository.expire_due(WORKSPACE_ID, run_id) == 0
    assert (await repository.list_interactions(WORKSPACE_ID, run_id))[0].status is (
        InteractionStatus.EXPIRED
    )
    async with migrated_database.session_factory() as session:
        run = await session.get(AgentRunRecord, run_id)
        assert run is not None
        assert run.status == RunStatus.EXPIRED.value


@pytest.mark.asyncio
async def test_prepare_rejects_cancel_requested_and_planning_ref_message_uses_sql_null(
    migrated_database: Database,
) -> None:
    run_id, fence = await _running_run(migrated_database.session_factory)
    repository = _repository(migrated_database.session_factory)

    # 资料引用消息必须通过 JSONB 对象传递，且 text 为 SQL NULL；
    # 这验证 JSONB 默认的 JSON 'null' 不会误满足“已提供资料”的形状约束。
    messages = _messages(migrated_database.session_factory)
    receipt = await messages.record(
        WORKSPACE_ID,
        run_id,
        UserMessage(
            request_id=uuid4(),
            kind=MessageKind.PLANNING_REF,
            planning_ref=VersionRef(version_id=uuid4(), sha256="b" * 64),
        ),
    )
    async with migrated_database.session_factory() as session:
        row = await session.get(AgentUserMessageRecord, receipt.message_id)
        assert row is not None
        assert row.text is None
        assert row.planning_ref is not None
        assert row.planning_ref["sha256"] == "b" * 64

    async with migrated_database.session_factory() as session, session.begin():
        run = await session.get(AgentRunRecord, run_id)
        if run is None:
            raise AssertionError("synthetic run missing")
        run.cancel_requested_at = datetime.now(UTC)
    with pytest.raises(AgentRunError) as cancelling:
        await repository.prepare(fence, _draft())
    assert cancelling.value.code == "run_cancelling"


@pytest.mark.asyncio
async def test_interaction_trigger_rejects_skipped_state_and_material_rewrite(
    migrated_database: Database,
) -> None:
    run_id, _ = await _running_run(migrated_database.session_factory)
    interaction_id = await _pending_interaction(
        migrated_database.session_factory,
        run_id=run_id,
    )

    # 不能从 pending 直接跳到 applied；必须先记录响应再应用。
    with pytest.raises(DBAPIError):
        async with migrated_database.session_factory() as session, session.begin():
            await session.execute(
                update(AgentInteractionRecord)
                .where(AgentInteractionRecord.id == interaction_id)
                .values(status=InteractionStatus.APPLIED.value, state_version=1)
            )

    # 审核材料、差异和有效期在待办创建后不可改写。
    with pytest.raises(DBAPIError):
        async with migrated_database.session_factory() as session, session.begin():
            await session.execute(
                update(AgentInteractionRecord)
                .where(AgentInteractionRecord.id == interaction_id)
                .values(material_hash="9" * 64)
            )


@pytest.mark.asyncio
async def test_events_are_ordered_and_never_embed_message_or_material_text(
    migrated_database: Database,
) -> None:
    run_id, _ = await _running_run(migrated_database.session_factory)
    messages = _messages(migrated_database.session_factory)
    messages_repo = messages
    secret_text = "请补充反证并保留当前策略"
    await messages_repo.record(
        WORKSPACE_ID,
        run_id,
        UserMessage(request_id=uuid4(), kind=MessageKind.TEXT, text=secret_text),
    )
    interaction_id = await _pending_interaction(
        migrated_database.session_factory,
        run_id=run_id,
    )
    await _repository(migrated_database.session_factory).respond(
        WORKSPACE_ID,
        run_id,
        _response(interaction_id),
    )
    page = await SqlAlchemyAgentRunRepository(migrated_database.session_factory).list_events(
        WORKSPACE_ID, run_id, limit=100
    )

    sequences = [item.sequence for item in page.items]
    assert sequences == list(range(1, len(sequences) + 1))
    event_types = [item.event_type.value for item in page.items]
    assert "message.recorded" in event_types
    assert "interaction.responded" in event_types
    serialized = "".join(str(item.payload) for item in page.items)
    assert secret_text not in serialized
    assert "reviewedPayloadHash" not in serialized


@pytest.mark.asyncio
async def test_running_cancel_blocks_new_budget_reservations_but_keeps_ledger(
    migrated_database: Database,
) -> None:
    run_id, fence = await _running_run(migrated_database.session_factory)
    ledger = SqlAlchemyBudgetLedger(migrated_database.session_factory, clock=lambda: NOW)
    first = AttemptRequest(
        action_sequence=1,
        input_sha256="c" * 64,
        category=AttemptCategory.MODEL,
        reserved_input_tokens=100,
        reserved_output_tokens=100,
        timeout_seconds=60,
    )
    await ledger.reserve(fence, first)

    service = AgentRunService(SqlAlchemyAgentRunRepository(migrated_database.session_factory))
    requested = await service.cancel(
        WORKSPACE_ID,
        run_id,
        request_id=uuid4(),
        expected_version=0,
    )
    assert requested.cancel_requested_at is not None

    # 取消后不能再预留新的模型/工具调用；已预留账本仍可查询并结算真实费用。
    with pytest.raises(AgentRunError) as blocked:
        await ledger.reserve(fence, first.model_copy(update={"action_sequence": 2}))
    assert blocked.value.code == "run_cancelling"
    status = await ledger.status(fence)
    assert status.model_calls == 1
