# 用 PostgreSQL 事务实现 C4 Agent 任务仓储：请求幂等、不可变修订、全局可运行容量与事件分页。
# 入队顺序固定为请求锁 -> 重放检查 -> 会话/父任务解析 -> 队列锁 -> 任务/修订/请求/事件提交。
# 同一 request_id 先查已提交映射，因此队列已满时仍能重放原任务；不同请求键不按币种合并。
# 该仓储不解析策略参数、不调用模型/工具、不访问私有账户或交易执行。
# T08 追加冻结证据 epoch 与内部 context manifest 的围栏持久化，二者均不可变。
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import JsonValue, ValidationError
from sqlalchemy import Text, func, select, text
from sqlalchemy import cast as sql_cast
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.interactive.context import ContextManifest
from app.agent_runs.contracts import (
    RUNNABLE_CAPACITY,
    RUNNABLE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    AgentRunError,
    RunInput,
    RunQuality,
    RunSnapshot,
    RunStatus,
    canonical_run_input_json,
    legacy_run_input_sha256,
    run_input_sha256,
)
from app.agent_runs.events import (
    RunEvent,
    RunEventPage,
    RunEventType,
    appendable_event,
    build_enqueue_events,
)
from app.agent_runs.segments import RunFence, graph_namespace
from app.infrastructure.persistence.models.agent_interactions import (
    AgentInteractionRecord,
    AgentRunCancelRequestRecord,
)
from app.infrastructure.persistence.models.agent_runs import (
    AgentArtifactRecord,
    AgentEvidenceEpochRecord,
    AgentRunEventRecord,
    AgentRunQueueRecord,
    AgentRunRecord,
    AgentRunRequestRecord,
    AgentRunRevisionRecord,
    AgentThreadRecord,
)
from app.infrastructure.persistence.models.agent_segments import AgentSegmentRecord
from app.research.evidence import EvidenceEpoch
from app.shared.agent_types import ArtifactRef, ProductKey, require_utc, sha256_json

_MAX_EVENT_PAGE = 100


# SQL Agent 任务仓储；clock 可注入以稳定事件时刻和测试快照。
class SqlAlchemyAgentRunRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    # 服务端时间必须为 UTC；客户端时间不能用于证明任务时刻。
    def _now(self) -> datetime:
        return require_utc(self._clock())

    # 创建任务；同键同内容重放原结果，同键异内容返回稳定冲突。
    async def enqueue(self, workspace_id: UUID, data: RunInput) -> RunSnapshot:
        # 深度复制，避免调用方在事务提交后修改嵌套参数字典影响已保存请求。
        normalized = data.model_copy(deep=True)
        input_payload = cast(
            dict[str, object],
            normalized.model_dump(mode="json", by_alias=False),
        )
        # 旧行使用 Python JSON 哈希；新行使用 PostgreSQL JSONB 规范文本。
        legacy_sha = legacy_run_input_sha256(workspace_id, normalized)
        request_sha: str | None = None
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                await _lock_request(session, workspace_id, normalized.request_id)
                # 先由 PostgreSQL 生成 JSONB 规范文本，确保 1e20/-0.0 等数值的指纹
                # 与随后持久化、重读的表示完全一致；不能只依赖首次 Python JSON。
                canonical_text = await _canonical_jsonb_text(
                    session,
                    canonical_run_input_json(normalized),
                )
                request_sha = run_input_sha256(workspace_id, canonical_text)
                replay = await _load_request(session, workspace_id, normalized.request_id)
                if replay is not None:
                    if replay.request_sha256 not in {request_sha, legacy_sha}:
                        raise AgentRunError("request_conflict")
                    snapshot = await _load_snapshot(session, workspace_id, replay.run_id)
                    if snapshot is None:
                        raise AgentRunError("integrity_violation")
                    return snapshot

                thread_id = await _resolve_thread(
                    session,
                    workspace_id,
                    normalized,
                    now,
                )
                await _lock_queue(session)
                runnable_count = await session.scalar(
                    select(func.count())
                    .select_from(AgentRunRecord)
                    .where(
                        AgentRunRecord.status.in_([item.value for item in RUNNABLE_RUN_STATUSES])
                    )
                )
                if runnable_count is not None and runnable_count >= RUNNABLE_CAPACITY:
                    raise AgentRunError("queue_full")

                run_id = uuid4()
                run = AgentRunRecord(
                    id=run_id,
                    workspace_id=workspace_id,
                    thread_id=thread_id,
                    parent_run_id=normalized.parent_run_id,
                    revision=1,
                    status=RunStatus.QUEUED.value,
                    state_version=0,
                    received_message_seq=0,
                    applied_message_seq=0,
                    current_interaction_id=None,
                    result_refs=[],
                    result_quality=None,
                    error_code=None,
                    owner=None,
                    lease_epoch=0,
                    lease_expires_at=None,
                    cancel_requested_at=None,
                    created_at=now,
                    updated_at=now,
                    started_at=None,
                    finished_at=None,
                )
                session.add(run)
                # 先落任务行，保证修订/请求/事件的 FK 在同一事务自动 flush 时已有父行。
                await session.flush()
                session.add(
                    AgentRunRevisionRecord(
                        run_id=run_id,
                        revision=1,
                        input=input_payload,
                        sha256=request_sha,
                        created_at=now,
                    )
                )
                session.add(
                    AgentRunRequestRecord(
                        workspace_id=workspace_id,
                        request_id=normalized.request_id,
                        run_id=run_id,
                        request_sha256=request_sha,
                        created_at=now,
                    )
                )
                session.add_all(
                    _event_rows(
                        run_id=run_id,
                        workspace_id=workspace_id,
                        revision=1,
                        product=normalized.product,
                        occurred_at=now,
                        input_sha256=request_sha,
                        strategy_version_id=normalized.strategy.version_id,
                    )
                )
                thread = await session.get(AgentThreadRecord, thread_id)
                if thread is None:
                    raise AgentRunError("integrity_violation")
                thread.updated_at = now
                await session.flush()
                snapshot = await _load_snapshot(session, workspace_id, run_id)
                if snapshot is None:
                    raise AgentRunError("integrity_violation")
                return snapshot
        except AgentRunError:
            raise
        except IntegrityError:
            # 唯一约束兜底并发同键；请求锁已提交读取后仍失败时只接受同内容重放。
            replayed = await self._replay(
                workspace_id,
                normalized.request_id,
                request_sha,
                legacy_sha,
            )
            if replayed is not None:
                return replayed
            raise AgentRunError("storage_unavailable") from None
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 读取任务并校验当前修订指纹；跨工作台按不存在处理，不泄露任务是否存在。
    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None:
        try:
            async with self._factory() as session:
                return await _load_snapshot(session, workspace_id, run_id)
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 按任务内序号读取安全事件；先校验任务归属，再返回游标分页。
    async def list_events(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        after_seq: int = 0,
        limit: int = 50,
    ) -> RunEventPage:
        if after_seq < 0 or not 1 <= limit <= _MAX_EVENT_PAGE:
            raise AgentRunError("invalid_event_page")
        try:
            async with self._factory() as session:
                owned_run_id = await session.scalar(
                    select(AgentRunRecord.id).where(
                        AgentRunRecord.id == run_id,
                        AgentRunRecord.workspace_id == workspace_id,
                    )
                )
                if owned_run_id is None:
                    raise AgentRunError("run_not_found")
                rows = list(
                    (
                        await session.scalars(
                            select(AgentRunEventRecord)
                            .where(
                                AgentRunEventRecord.run_id == run_id,
                                AgentRunEventRecord.sequence > after_seq,
                            )
                            .order_by(AgentRunEventRecord.sequence)
                            .limit(limit + 1)
                        )
                    ).all()
                )
                events = tuple(_event_from_row(row) for row in rows[:limit])
                next_after = events[-1].sequence if len(rows) > limit else None
                return RunEventPage(items=events, next_after=next_after)
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 取消任务：queued/等待态立即终态；running 只置取消标记，由 worker 在边界停止。
    # 请求键在同一工作台内幂等；取消不能重新打开已终态任务，也不操作交易所订单。
    async def cancel(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        request_id: UUID,
        expected_version: int,
    ) -> RunSnapshot:
        request_sha = sha256_json(
            {
                "runId": str(run_id),
                "expectedVersion": expected_version,
            }
        )
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                run = await session.scalar(
                    select(AgentRunRecord)
                    .where(
                        AgentRunRecord.id == run_id,
                        AgentRunRecord.workspace_id == workspace_id,
                    )
                    .with_for_update()
                )
                if run is None:
                    raise AgentRunError("run_not_found")
                existing = await session.scalar(
                    select(AgentRunCancelRequestRecord).where(
                        AgentRunCancelRequestRecord.workspace_id == workspace_id,
                        AgentRunCancelRequestRecord.request_id == request_id,
                    )
                )
                if existing is not None:
                    if existing.run_id != run_id or existing.request_sha256 != request_sha:
                        raise AgentRunError("request_conflict")
                    snapshot = await _load_snapshot(session, workspace_id, run_id)
                    if snapshot is None:
                        raise AgentRunError("integrity_violation")
                    return snapshot

                # 已终态任务优先返回当前结果；迟到取消不覆盖成功/失败历史。
                if run.status in {item.value for item in TERMINAL_RUN_STATUSES}:
                    session.add(
                        AgentRunCancelRequestRecord(
                            workspace_id=workspace_id,
                            request_id=request_id,
                            run_id=run_id,
                            request_sha256=request_sha,
                            created_at=now,
                        )
                    )
                    snapshot = await _load_snapshot(session, workspace_id, run_id)
                    if snapshot is None:
                        raise AgentRunError("integrity_violation")
                    return snapshot

                if run.state_version != expected_version:
                    raise AgentRunError("version_conflict")

                session.add(
                    AgentRunCancelRequestRecord(
                        workspace_id=workspace_id,
                        request_id=request_id,
                        run_id=run_id,
                        request_sha256=request_sha,
                        created_at=now,
                    )
                )
                active = await session.scalar(
                    select(AgentInteractionRecord)
                    .where(
                        AgentInteractionRecord.run_id == run_id,
                        AgentInteractionRecord.status.in_(("preparing", "pending", "answered")),
                    )
                    .with_for_update()
                )
                if run.status == RunStatus.RUNNING.value:
                    if run.cancel_requested_at is None:
                        run.cancel_requested_at = now
                        run.state_version += 1
                        run.updated_at = now
                        if active is not None:
                            active.status = "expired"
                            active.state_version += 1
                            active.expired_at = now
                            await append_run_event(
                                session,
                                run_id=run_id,
                                workspace_id=workspace_id,
                                revision=run.revision,
                                event_type=RunEventType.INTERACTION_EXPIRED,
                                payload={
                                    "interactionId": str(active.id),
                                    "reason": "user_cancelled",
                                },
                                occurred_at=now,
                            )
                        await append_run_event(
                            session,
                            run_id=run_id,
                            workspace_id=workspace_id,
                            revision=run.revision,
                            event_type=RunEventType.RUN_CANCELLATION_REQUESTED,
                            payload={"reason": "user_request"},
                            occurred_at=now,
                        )
                else:
                    # queued/waiting_input/waiting_approval 可直接取消；等待待办同步过期。
                    if active is not None:
                        active.status = "expired"
                        active.state_version += 1
                        active.expired_at = now
                        await append_run_event(
                            session,
                            run_id=run_id,
                            workspace_id=workspace_id,
                            revision=run.revision,
                            event_type=RunEventType.INTERACTION_EXPIRED,
                            payload={
                                "interactionId": str(active.id),
                                "reason": "user_cancelled",
                            },
                            occurred_at=now,
                        )
                    run.status = RunStatus.CANCELLED.value
                    run.current_interaction_id = None
                    run.finished_at = now
                    run.state_version += 1
                    run.updated_at = now
                    await append_run_event(
                        session,
                        run_id=run_id,
                        workspace_id=workspace_id,
                        revision=run.revision,
                        event_type=RunEventType.RUN_CANCELLED,
                        payload={"reason": "user_request"},
                        occurred_at=now,
                    )
                await session.flush()
                snapshot = await _load_snapshot(session, workspace_id, run_id)
                if snapshot is None:
                    raise AgentRunError("integrity_violation")
                return snapshot
        except AgentRunError:
            raise
        except IntegrityError:
            raise AgentRunError("request_conflict") from None
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 保存冻结证据 epoch；围栏校验与插入在同一事务，历史行只允许幂等重放。
    # 证据正文/指纹在读取时重新校验，不能仅凭数据库行 sha 字段信任内容。
    async def save_evidence(self, fence: RunFence, epoch: EvidenceEpoch) -> EvidenceEpoch:
        snapshot = epoch.validated_snapshot()
        document = snapshot.model_dump(mode="json")
        try:
            async with self._factory() as session, session.begin():
                await _lock_live_fence(session, fence)
                existing = await session.get(AgentEvidenceEpochRecord, snapshot.epoch_id)
                if existing is not None:
                    if (
                        existing.workspace_id != fence.workspace_id
                        or existing.run_id != fence.run_id
                        or existing.revision != fence.revision
                        or existing.sha256 != snapshot.sha256
                    ):
                        raise AgentRunError("integrity_violation")
                    return snapshot
                session.add(
                    AgentEvidenceEpochRecord(
                        id=snapshot.epoch_id,
                        workspace_id=fence.workspace_id,
                        run_id=fence.run_id,
                        revision=fence.revision,
                        analysis_as_of=snapshot.analysis_as_of,
                        sealed_at=snapshot.sealed_at,
                        sha256=snapshot.sha256,
                        document=cast(dict[str, object], document),
                        created_at=self._now(),
                    )
                )
                await session.flush()
                return snapshot
        except AgentRunError:
            raise
        except IntegrityError:
            # 并发保存同一 epoch：读取已提交行后只接受完全相同的内容。
            existing = await self.load_evidence(
                fence.workspace_id,
                fence.run_id,
                snapshot.epoch_id,
            )
            if existing is not None and existing.sha256 == snapshot.sha256:
                return existing
            raise AgentRunError("storage_unavailable") from None
        except (SQLAlchemyError, ValidationError):
            raise AgentRunError("storage_unavailable") from None

    # 读取指定证据 epoch；跨工作台/任务按不存在处理，正文不一致 fail-closed。
    async def load_evidence(
        self,
        workspace_id: UUID,
        run_id: UUID,
        epoch_id: UUID,
    ) -> EvidenceEpoch | None:
        try:
            async with self._factory() as session:
                row = await session.scalar(
                    select(AgentEvidenceEpochRecord).where(
                        AgentEvidenceEpochRecord.id == epoch_id,
                        AgentEvidenceEpochRecord.workspace_id == workspace_id,
                        AgentEvidenceEpochRecord.run_id == run_id,
                    )
                )
                if row is None:
                    return None
                return _evidence_from_row(row)
        except AgentRunError:
            raise
        except (SQLAlchemyError, ValidationError):
            raise AgentRunError("storage_unavailable") from None

    # 读取当前修订最新证据；用于片段重入时复用已封存 epoch，避免重复外部读取。
    async def load_latest_evidence(
        self,
        workspace_id: UUID,
        run_id: UUID,
        revision: int,
    ) -> EvidenceEpoch | None:
        try:
            async with self._factory() as session:
                row = await session.scalar(
                    select(AgentEvidenceEpochRecord)
                    .where(
                        AgentEvidenceEpochRecord.workspace_id == workspace_id,
                        AgentEvidenceEpochRecord.run_id == run_id,
                        AgentEvidenceEpochRecord.revision == revision,
                    )
                    .order_by(
                        AgentEvidenceEpochRecord.created_at.desc(),
                        AgentEvidenceEpochRecord.id.desc(),
                    )
                    .limit(1)
                )
                if row is None:
                    return None
                return _evidence_from_row(row)
        except AgentRunError:
            raise
        except (SQLAlchemyError, ValidationError):
            raise AgentRunError("storage_unavailable") from None

    # 统计当前修订证据 epoch 数，用于刷新时分配新的动作序号区段。
    async def count_evidence(
        self,
        workspace_id: UUID,
        run_id: UUID,
        revision: int,
    ) -> int:
        try:
            async with self._factory() as session:
                value = await session.scalar(
                    select(func.count())
                    .select_from(AgentEvidenceEpochRecord)
                    .where(
                        AgentEvidenceEpochRecord.workspace_id == workspace_id,
                        AgentEvidenceEpochRecord.run_id == run_id,
                        AgentEvidenceEpochRecord.revision == revision,
                    )
                )
                return value if isinstance(value, int) else 0
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 将上下文 manifest 保存为内部不可变 artifact；T14 的公开产物投影不得把它当业务报告。
    # manifest 必须先与当前 fence 的 workspace/run/revision/segment 对齐，且引用证据
    # 必须属于同一运行修订；行归属与文档归属不一致时 fail-closed，不能只信任摘要。
    async def save_context_manifest(
        self,
        fence: RunFence,
        manifest: ContextManifest,
    ) -> ArtifactRef:
        _validate_manifest_scope(
            manifest,
            workspace_id=fence.workspace_id,
            run_id=fence.run_id,
            revision=fence.revision,
            segment_id=fence.segment_id,
        )
        document = manifest.model_dump(mode="json")
        digest = sha256_json(cast(JsonValue, document))
        artifact_id = uuid5(
            NAMESPACE_URL,
            f"context-manifest:{fence.run_id}:{fence.revision}:{digest}",
        )
        try:
            async with self._factory() as session, session.begin():
                await _lock_live_fence(session, fence)
                await _require_manifest_evidence(
                    session,
                    manifest,
                    workspace_id=fence.workspace_id,
                    run_id=fence.run_id,
                    revision=fence.revision,
                )
                existing = await session.get(AgentArtifactRecord, artifact_id)
                if existing is not None:
                    if (
                        existing.workspace_id != fence.workspace_id
                        or existing.run_id != fence.run_id
                        or existing.revision != fence.revision
                        or existing.artifact_type != "context_manifest"
                        or existing.sha256 != digest
                    ):
                        raise AgentRunError("integrity_violation")
                    try:
                        existing_manifest = ContextManifest.model_validate(existing.document)
                    except ValidationError as error:
                        raise AgentRunError("integrity_violation") from error
                    _validate_manifest_scope(
                        existing_manifest,
                        workspace_id=fence.workspace_id,
                        run_id=fence.run_id,
                        revision=fence.revision,
                        segment_id=fence.segment_id,
                    )
                    if existing_manifest != manifest:
                        raise AgentRunError("integrity_violation")
                    return ArtifactRef(artifact_id=artifact_id, sha256=digest)
                session.add(
                    AgentArtifactRecord(
                        id=artifact_id,
                        workspace_id=fence.workspace_id,
                        run_id=fence.run_id,
                        revision=fence.revision,
                        artifact_type="context_manifest",
                        quality=None,
                        sha256=digest,
                        document=cast(dict[str, object], document),
                        parent_artifact_id=None,
                        created_at=self._now(),
                    )
                )
                await session.flush()
                return ArtifactRef(artifact_id=artifact_id, sha256=digest)
        except AgentRunError:
            raise
        except IntegrityError:
            existing_manifest = await self.load_context_manifest(
                fence.workspace_id,
                fence.run_id,
                artifact_id,
            )
            if existing_manifest == manifest:
                return ArtifactRef(artifact_id=artifact_id, sha256=digest)
            raise AgentRunError("storage_unavailable") from None
        except (SQLAlchemyError, ValidationError):
            raise AgentRunError("storage_unavailable") from None

    # 读取内部 context manifest；重新计算文档指纹并拒绝被改写/跨类型/归属不一致的 artifact。
    # 读取端不能只验证 SHA；行 workspace/run/revision 与文档、引用证据必须同时一致。
    async def load_context_manifest(
        self,
        workspace_id: UUID,
        run_id: UUID,
        artifact_id: UUID,
    ) -> ContextManifest | None:
        try:
            async with self._factory() as session:
                row = await session.scalar(
                    select(AgentArtifactRecord).where(
                        AgentArtifactRecord.id == artifact_id,
                        AgentArtifactRecord.workspace_id == workspace_id,
                        AgentArtifactRecord.run_id == run_id,
                    )
                )
                if row is None:
                    return None
                if row.artifact_type != "context_manifest":
                    raise AgentRunError("integrity_violation")
                if sha256_json(cast(JsonValue, row.document)) != row.sha256:
                    raise AgentRunError("integrity_violation")
                try:
                    manifest = ContextManifest.model_validate(row.document)
                except ValidationError as error:
                    raise AgentRunError("integrity_violation") from error
                _validate_manifest_scope(
                    manifest,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    revision=row.revision,
                )
                segment = await session.get(AgentSegmentRecord, manifest.segment_id)
                if (
                    segment is None
                    or segment.workspace_id != workspace_id
                    or segment.run_id != run_id
                    or segment.revision != row.revision
                ):
                    raise AgentRunError("integrity_violation")
                await _require_manifest_evidence(
                    session,
                    manifest,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    revision=row.revision,
                )
                return manifest
        except AgentRunError:
            raise
        except SQLAlchemyError:
            raise AgentRunError("storage_unavailable") from None

    # 唯一约束冲突后的独立事务重放；内容不同仍返回冲突而不是伪成功。
    async def _replay(
        self,
        workspace_id: UUID,
        request_id: UUID,
        request_sha: str | None,
        legacy_sha: str,
    ) -> RunSnapshot | None:
        try:
            async with self._factory() as session:
                replay = await _load_request(session, workspace_id, request_id)
                if replay is None:
                    return None
                expected = {legacy_sha}
                if request_sha is not None:
                    expected.add(request_sha)
                if replay.request_sha256 not in expected:
                    raise AgentRunError("request_conflict")
                return await _load_snapshot(session, workspace_id, replay.run_id)
        except AgentRunError:
            raise
        except SQLAlchemyError:
            return None


# 校验 manifest 文档的归属与保存/读取范围一致；摘要一致不能替代行/文档归属校验。
def _validate_manifest_scope(
    manifest: ContextManifest,
    *,
    workspace_id: UUID,
    run_id: UUID,
    revision: int,
    segment_id: UUID | None = None,
) -> None:
    if (
        manifest.workspace_id != workspace_id
        or manifest.run_id != run_id
        or manifest.revision != revision
    ):
        raise AgentRunError("integrity_violation")
    if segment_id is not None and manifest.segment_id != segment_id:
        raise AgentRunError("integrity_violation")


# manifest 引用的证据必须存在、属于同一工作台/任务/修订，且时间与逐项标识一致。
async def _require_manifest_evidence(
    session: AsyncSession,
    manifest: ContextManifest,
    *,
    workspace_id: UUID,
    run_id: UUID,
    revision: int,
) -> None:
    row = await session.get(AgentEvidenceEpochRecord, manifest.evidence_epoch_id)
    if (
        row is None
        or row.workspace_id != workspace_id
        or row.run_id != run_id
        or row.revision != revision
        or row.sha256 != manifest.evidence_sha256
    ):
        raise AgentRunError("integrity_violation")
    epoch = _evidence_from_row(row)
    expected_items = tuple(sorted((item.evidence_id for item in epoch.items), key=str))
    if (
        epoch.analysis_as_of != manifest.analysis_as_of
        or expected_items != manifest.evidence_item_ids
    ):
        raise AgentRunError("integrity_violation")


# 读取数据库当前时刻；围栏判断不使用客户端时钟或事务开始时钟。
async def _database_now(session: AsyncSession) -> datetime:
    value = await session.scalar(text("SELECT clock_timestamp()"))
    if not isinstance(value, datetime):
        raise AgentRunError("integrity_violation")
    return require_utc(value)


# 在任务/片段行锁后核对当前 owner、租约代次、修订、namespace 和取消标记。
# 证据/manifest 写入与 T07 片段提交使用相同锁序（任务 -> 片段），避免反向死锁。
async def _lock_live_fence(session: AsyncSession, fence: RunFence) -> AgentRunRecord:
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
    database_now = await _database_now(session)
    segment = await session.scalar(
        select(AgentSegmentRecord)
        .where(AgentSegmentRecord.id == fence.segment_id)
        .with_for_update()
    )
    if (
        run.status != RunStatus.RUNNING.value
        or run.owner is None
        or run.owner != fence.owner
        or run.lease_epoch != fence.lease_epoch
        or run.revision != fence.revision
        or run.lease_expires_at is None
        or run.lease_expires_at <= database_now
        or segment is None
        or segment.workspace_id != fence.workspace_id
        or segment.run_id != fence.run_id
        or segment.revision != fence.revision
        or segment.owner != fence.owner
        or segment.lease_epoch != fence.lease_epoch
        or segment.graph_namespace != graph_namespace(fence)
        or segment.status != "running"
        or segment.lease_expires_at is None
        or segment.lease_expires_at <= database_now
    ):
        raise AgentRunError("lease_lost")
    if run.cancel_requested_at is not None:
        raise AgentRunError("run_cancelling")
    return run


# 从数据库行恢复证据并重新计算 epoch 标识/内容指纹；任何不一致都按完整性破坏处理。
def _evidence_from_row(row: AgentEvidenceEpochRecord) -> EvidenceEpoch:
    try:
        epoch = EvidenceEpoch.model_validate(row.document)
        epoch = epoch.validated_snapshot()
    except (ValidationError, TypeError, ValueError) as error:
        raise AgentRunError("integrity_violation") from error
    if (
        epoch.epoch_id != row.id
        or epoch.sha256 != row.sha256
        or epoch.analysis_as_of != row.analysis_as_of
        or epoch.sealed_at != row.sealed_at
    ):
        raise AgentRunError("integrity_violation")
    return epoch


# 解析/验证有效会话与父任务；父任务必须终态且属于同一会话，避免并行子任务借用旧上下文。
async def _resolve_thread(
    session: AsyncSession,
    workspace_id: UUID,
    data: RunInput,
    now: datetime,
) -> UUID:
    parent: AgentRunRecord | None = None
    if data.parent_run_id is not None:
        parent = await session.scalar(
            select(AgentRunRecord)
            .where(
                AgentRunRecord.id == data.parent_run_id,
                AgentRunRecord.workspace_id == workspace_id,
            )
            .with_for_update(read=True)
        )
        if parent is None:
            raise AgentRunError("parent_not_found")
        if parent.status not in {item.value for item in TERMINAL_RUN_STATUSES}:
            raise AgentRunError("parent_not_terminal")

    thread_id = data.thread_id
    if parent is not None:
        if thread_id is None:
            thread_id = parent.thread_id
        elif thread_id != parent.thread_id:
            raise AgentRunError("thread_conflict")

    if thread_id is None:
        thread = AgentThreadRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            created_at=now,
            updated_at=now,
        )
        session.add(thread)
        await session.flush()
        return thread.id

    thread = await session.get(AgentThreadRecord, thread_id)
    if thread is None or thread.workspace_id != workspace_id:
        raise AgentRunError("thread_not_found")
    return thread.id


# 请求级事务锁串行化同一工作台/请求键；必须在队列容量检查之前以便满队列重放。
async def _lock_request(session: AsyncSession, workspace_id: UUID, request_id: UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:request_key, 0))"),
        {"request_key": f"agent-run-request:{workspace_id}:{request_id}"},
    )


# 读取请求幂等映射；不存在返回 None，存在则由调用方核对内容指纹。
async def _load_request(
    session: AsyncSession,
    workspace_id: UUID,
    request_id: UUID,
) -> AgentRunRequestRecord | None:
    return await session.scalar(
        select(AgentRunRequestRecord).where(
            AgentRunRequestRecord.workspace_id == workspace_id,
            AgentRunRequestRecord.request_id == request_id,
        )
    )


# 锁定单例队列行；容量判断与插入必须在同一事务内完成。
async def _lock_queue(session: AsyncSession) -> None:
    queue = await session.scalar(
        select(AgentRunQueueRecord).where(AgentRunQueueRecord.id == 1).with_for_update()
    )
    if queue is None:
        raise AgentRunError("integrity_violation")


# 由 PostgreSQL 生成 JSONB 规范文本；1e20、-0.0 等合法数值的表示由此固定。
# 该查询不改业务数据，只把同一 JSON 输入转换为后续持久化和重读都会得到的文本。
async def _canonical_jsonb_text(session: AsyncSession, raw_json: str) -> str:
    canonical = await session.scalar(
        text("SELECT CAST(:payload AS jsonb)::text"),
        {"payload": raw_json},
    )
    if not isinstance(canonical, str):
        raise AgentRunError("integrity_violation")
    return canonical


# 从任务行和当前修订构造对外快照；任何正文/指纹/引用不一致按不变量破坏处理。
async def _load_snapshot(
    session: AsyncSession,
    workspace_id: UUID,
    run_id: UUID,
) -> RunSnapshot | None:
    run = await session.get(AgentRunRecord, run_id)
    if run is None or run.workspace_id != workspace_id:
        return None
    row = (
        await session.execute(
            select(
                AgentRunRevisionRecord,
                sql_cast(AgentRunRevisionRecord.input, Text).label("canonical_text"),
            ).where(
                AgentRunRevisionRecord.run_id == run_id,
                AgentRunRevisionRecord.revision == run.revision,
            )
        )
    ).one_or_none()
    if row is None:
        raise AgentRunError("integrity_violation")
    revision, canonical_text = row
    if not isinstance(canonical_text, str):
        raise AgentRunError("integrity_violation")
    try:
        run_input = RunInput.model_validate(revision.input)
        status = RunStatus(run.status)
        result_refs = tuple(ArtifactRef.model_validate(item) for item in run.result_refs)
        canonical_sha = run_input_sha256(workspace_id, canonical_text)
        legacy_sha = legacy_run_input_sha256(workspace_id, run_input)
    except (ValueError, TypeError) as error:
        raise AgentRunError("integrity_violation") from error
    # 新行校验 PostgreSQL 规范文本哈希；首轮已提交的稳定数值行允许旧算法兼容。
    # 旧行若含 JSONB 已规范化的数值，旧表示无法恢复，仍必须拒绝而非放宽校验。
    if revision.sha256 not in {canonical_sha, legacy_sha}:
        raise AgentRunError("integrity_violation")
    try:
        return RunSnapshot(
            run_id=run.id,
            workspace_id=run.workspace_id,
            thread_id=run.thread_id,
            parent_run_id=run.parent_run_id,
            revision=run.revision,
            status=status,
            state_version=run.state_version,
            input=run_input,
            received_message_seq=run.received_message_seq,
            applied_message_seq=run.applied_message_seq,
            current_interaction_id=run.current_interaction_id,
            result_refs=result_refs,
            result_quality=cast(RunQuality | None, run.result_quality),
            created_at=run.created_at,
            updated_at=run.updated_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            cancel_requested_at=run.cancel_requested_at,
        )
    except ValidationError as error:
        raise AgentRunError("integrity_violation") from error


# 将领域事件转成 ORM 行；事件载荷已在 events.py 按类型白名单校验。
def _event_rows(
    *,
    run_id: UUID,
    workspace_id: UUID,
    revision: int,
    product: ProductKey,
    occurred_at: datetime,
    input_sha256: str,
    strategy_version_id: UUID,
) -> list[AgentRunEventRecord]:
    events = build_enqueue_events(
        run_id=run_id,
        revision=revision,
        product=product,
        occurred_at=occurred_at,
        input_sha256=input_sha256,
        strategy_version_id=strategy_version_id,
    )
    return [
        AgentRunEventRecord(
            run_id=event.run_id,
            sequence=event.sequence,
            workspace_id=workspace_id,
            revision=event.revision,
            event_type=event.event_type.value,
            occurred_at=event.occurred_at,
            payload=cast(dict[str, object], event.payload),
            projection_version=event.projection_version,
        )
        for event in events
    ]


# 解析事件行并重新校验白名单载荷；未知类型或多余字段不能被当作安全事件返回。
def _event_from_row(row: AgentRunEventRecord) -> RunEvent:
    try:
        return RunEvent(
            run_id=row.run_id,
            revision=row.revision,
            sequence=row.sequence,
            event_type=RunEventType(row.event_type),
            occurred_at=row.occurred_at,
            payload=cast(dict[str, JsonValue], row.payload),
            projection_version=row.projection_version,
        )
    except (ValueError, ValidationError, TypeError) as error:
        raise AgentRunError("integrity_violation") from error


# 读取当前任务快照的公开包装；T06 消息应用水位需要返回同一安全投影。
async def load_run_snapshot(
    session: AsyncSession,
    workspace_id: UUID,
    run_id: UUID,
) -> RunSnapshot | None:
    return await _load_snapshot(session, workspace_id, run_id)


# 在已成锁的事务中追加一条单调安全事件；调用方必须持有任务行锁。
# 事件对象先经 RunEvent 白名单校验，再落库，避免内部调用绕过载荷限制。
async def append_run_event(
    session: AsyncSession,
    *,
    run_id: UUID,
    workspace_id: UUID,
    revision: int,
    event_type: RunEventType,
    payload: dict[str, JsonValue],
    occurred_at: datetime,
) -> RunEvent:
    next_sequence = await session.scalar(
        select(func.coalesce(func.max(AgentRunEventRecord.sequence), 0) + 1).where(
            AgentRunEventRecord.run_id == run_id
        )
    )
    if not isinstance(next_sequence, int):
        raise AgentRunError("integrity_violation")
    event = appendable_event(
        run_id=run_id,
        workspace_id=workspace_id,
        revision=revision,
        sequence=next_sequence,
        event_type=event_type,
        payload=payload,
        occurred_at=occurred_at,
    )
    session.add(
        AgentRunEventRecord(
            run_id=run_id,
            sequence=event.sequence,
            workspace_id=workspace_id,
            revision=event.revision,
            event_type=event.event_type.value,
            occurred_at=event.occurred_at,
            payload=event.payload,
            projection_version=event.projection_version,
        )
    )
    await session.flush()
    return event


__all__ = [
    "SqlAlchemyAgentRunRepository",
    "append_run_event",
    "load_run_snapshot",
]
