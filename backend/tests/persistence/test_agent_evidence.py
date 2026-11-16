# 使用真实 PostgreSQL 验证 T08 证据 epoch 与上下文 manifest 的不可变持久化。
# 覆盖围栏校验、工作台隔离、幂等保存、历史不可改写和读取时指纹重验。
# 所有任务、策略、证据和 manifest 内容均为合成值；不联网、不调用模型或交易执行。
from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from app.agent.interactive.context import (
    ContextBlock,
    ContextBlockKind,
    ContextManifest,
)
from app.agent_runs.contracts import AgentRunError, RunInput
from app.agent_runs.evidence import (
    EvidenceCollection,
    EvidenceDraft,
    EvidenceRepository,
    EvidenceService,
    ResearchEvidencePort,
)
from app.agent_runs.segments import EMPTY_TOOL_CATALOG_SHA256, ExecutionContext, RunFence
from app.infrastructure.persistence.agent_attempt_repository import SqlAlchemyBudgetLedger
from app.infrastructure.persistence.agent_commit_coordinator import (
    SqlAlchemyAgentCommitCoordinator,
)
from app.infrastructure.persistence.agent_run_repository import SqlAlchemyAgentRunRepository
from app.infrastructure.persistence.models.agent_runs import (
    AgentArtifactRecord,
    AgentEvidenceEpochRecord,
)
from app.market.contracts import MarketTimeframe
from app.research.evidence import EvidenceEpoch, EvidenceItem, EvidenceQuality
from app.shared.agent_types import JsonObject, ProductKey, VersionRef, sha256_json
from tests.conftest import MigratedDatabase

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


# 构造合成任务输入；策略版本和参数不连接真实策略目录。
def _run_input() -> RunInput:
    return RunInput(
        request_id=uuid4(),
        product=ProductKey(
            venue="binance_usdm",
            symbol="BTCUSDT",
            settlement="USDT",
            kind="linear_perpetual",
        ),
        timeframes=(MarketTimeframe.H1,),
        goal="合成证据冻结测试",
        strategy=VersionRef(version_id=uuid4(), sha256="a" * 64),
        parameters={"minimum_reward_risk": "1.5"},
    )


# 构造合成冻结证据；content 指纹和 epoch 标识由契约自行计算。
def _epoch() -> EvidenceEpoch:
    content: JsonObject = {"symbol": "BTCUSDT", "price": "106.2"}
    return EvidenceEpoch.seal(
        analysis_as_of=NOW,
        sealed_at=NOW,
        items=(
            EvidenceItem(
                evidence_id=uuid4(),
                kind="market_detail",
                source="synthetic-public-source",
                observed_at=NOW,
                available_at=NOW,
                fetched_at=NOW,
                payload_sha256=sha256_json(content),
                quality=EvidenceQuality.VALID,
                calculation_version="market_detail_v1",
                content=content,
            ),
        ),
    )


# 构造不包含财务值的上下文 manifest；用于验证 manifest 持久化通道。
def _manifest(context: ExecutionContext, epoch: EvidenceEpoch) -> ContextManifest:
    return ContextManifest(
        workspace_id=context.fence.workspace_id,
        run_id=context.fence.run_id,
        revision=context.fence.revision,
        segment_id=context.fence.segment_id,
        strategy_ref=context.strategy_ref,
        evidence_epoch_id=epoch.epoch_id,
        evidence_sha256=epoch.sha256,
        analysis_as_of=epoch.analysis_as_of,
        analysis_mode="current",
        historical_as_of=None,
        applied_seq=0,
        received_seq=0,
        message_sequences=(),
        summary_ids=(),
        knowledge_refs=(),
        knowledge_chunk_ids=(),
        evidence_item_ids=tuple(item.evidence_id for item in epoch.items),
        planning_refs=(),
        pool_generation=None,
        tool_catalog_sha256=EMPTY_TOOL_CATALOG_SHA256,
        prompt_version="interactive-context-v1",
        schema_version="model-context-v1",
        input_reservation=4_800,
        built_at=NOW,
        blocks=(
            ContextBlock(
                block_id="system",
                kind=ContextBlockKind.SYSTEM,
                utf8_bytes=256,
                sha256="b" * 64,
            ),
        ),
        omitted=(),
        limitations=(),
    )


# 创建任务并领取片段，返回仓库、上下文与运行标识。
async def _claimed_run(
    database: MigratedDatabase,
) -> tuple[SqlAlchemyAgentRunRepository, ExecutionContext]:
    repository = SqlAlchemyAgentRunRepository(database.session_factory)
    coordinator = SqlAlchemyAgentCommitCoordinator(
        database.session_factory,
        clock=lambda: NOW,
    )
    snapshot = await repository.enqueue(uuid4(), _run_input())
    context = await coordinator.claim(uuid4())
    assert context is not None
    assert context.fence.run_id == snapshot.run_id
    return repository, context


# 通过协议类型调用仓储，确保新方法可被 EvidenceService 依赖而不是仅测试专用。
def _as_evidence_repository(
    repository: SqlAlchemyAgentRunRepository,
) -> EvidenceRepository:
    return repository


# 正常保存/读取：epoch 标识、正文与指纹保持一致，重复保存不产生第二行。
@pytest.mark.asyncio
async def test_evidence_epoch_roundtrips_and_is_idempotent(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    evidence_repository = _as_evidence_repository(repository)
    epoch = _epoch()

    saved = await evidence_repository.save_evidence(context.fence, epoch)
    loaded = await evidence_repository.load_evidence(
        context.fence.workspace_id,
        context.fence.run_id,
        epoch.epoch_id,
    )
    latest = await evidence_repository.load_latest_evidence(
        context.fence.workspace_id,
        context.fence.run_id,
        context.fence.revision,
    )
    assert saved == epoch
    assert loaded == epoch
    assert latest == epoch

    await evidence_repository.save_evidence(context.fence, epoch)
    assert (
        await evidence_repository.count_evidence(
            context.fence.workspace_id,
            context.fence.run_id,
            context.fence.revision,
        )
        == 1
    )


# 失租/伪造 owner 的围栏不能写入证据；数据库行锁后按当前 owner/代次判定。
@pytest.mark.asyncio
async def test_evidence_save_rejects_stale_fence(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    stale = RunFence(
        workspace_id=context.fence.workspace_id,
        run_id=context.fence.run_id,
        revision=context.fence.revision,
        segment_id=context.fence.segment_id,
        owner=uuid4(),
        lease_epoch=context.fence.lease_epoch,
    )

    with pytest.raises(AgentRunError) as raised:
        await _as_evidence_repository(repository).save_evidence(stale, _epoch())

    assert raised.value.code == "lease_lost"
    assert (
        await _as_evidence_repository(repository).count_evidence(
            context.fence.workspace_id,
            context.fence.run_id,
            context.fence.revision,
        )
        == 0
    )


# 证据按工作台隔离；其他工作台不能读取已保存 epoch。
@pytest.mark.asyncio
async def test_evidence_is_scoped_to_workspace(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    epoch = _epoch()
    await _as_evidence_repository(repository).save_evidence(context.fence, epoch)

    assert (
        await _as_evidence_repository(repository).load_evidence(
            uuid4(),
            context.fence.run_id,
            epoch.epoch_id,
        )
        is None
    )


# 证据历史不可更新/删除；触发器拒绝改写已封存正文。
@pytest.mark.asyncio
async def test_evidence_history_is_immutable(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    epoch = _epoch()
    await _as_evidence_repository(repository).save_evidence(context.fence, epoch)

    with pytest.raises(DBAPIError):
        async with migrated_database.session_factory() as session, session.begin():
            await session.execute(
                update(AgentEvidenceEpochRecord)
                .where(AgentEvidenceEpochRecord.id == epoch.epoch_id)
                .values(sha256="f" * 64)
            )


# 读取时重验文档与行指纹；即使绕过应用写入伪造文档，也不能当作可用证据。
@pytest.mark.asyncio
async def test_evidence_load_rejects_tampered_document(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    epoch = _epoch()
    await _as_evidence_repository(repository).save_evidence(context.fence, epoch)

    # 使用 ORM 插入伪造文档，确保 schema_translate_map 指向本次临时 schema。
    tampered_id = uuid4()
    async with migrated_database.session_factory() as session, session.begin():
        session.add(
            AgentEvidenceEpochRecord(
                id=tampered_id,
                workspace_id=context.fence.workspace_id,
                run_id=context.fence.run_id,
                revision=context.fence.revision,
                analysis_as_of=NOW,
                sealed_at=NOW,
                sha256=epoch.sha256,
                document={"epochId": "00000000-0000-0000-0000-000000000000"},
                created_at=NOW,
            )
        )

    with pytest.raises(AgentRunError) as raised:
        await _as_evidence_repository(repository).load_evidence(
            context.fence.workspace_id,
            context.fence.run_id,
            tampered_id,
        )
    assert raised.value.code == "integrity_violation"


# manifest 保存为不可变内部 artifact；重复保存同一 manifest 复用同一引用。
@pytest.mark.asyncio
async def test_context_manifest_roundtrips_and_is_idempotent(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    epoch = _epoch()
    await _as_evidence_repository(repository).save_evidence(context.fence, epoch)
    manifest = _manifest(context, epoch)

    first = await repository.save_context_manifest(context.fence, manifest)
    second = await repository.save_context_manifest(context.fence, manifest)
    loaded = await repository.load_context_manifest(
        context.fence.workspace_id,
        context.fence.run_id,
        first.artifact_id,
    )

    assert first == second
    assert loaded == manifest
    async with migrated_database.session_factory() as session:
        row = await session.scalar(
            select(AgentArtifactRecord).where(AgentArtifactRecord.id == first.artifact_id)
        )
    assert row is not None
    assert row.artifact_type == "context_manifest"
    assert row.sha256 == first.sha256


# manifest 历史不可改写；审计不能通过 UPDATE 覆盖模型实际使用的上下文清单。
@pytest.mark.asyncio
async def test_context_manifest_history_is_immutable(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    epoch = _epoch()
    await _as_evidence_repository(repository).save_evidence(context.fence, epoch)
    manifest = _manifest(context, epoch)
    reference = await repository.save_context_manifest(context.fence, manifest)

    with pytest.raises(DBAPIError):
        async with migrated_database.session_factory() as session, session.begin():
            await session.execute(
                update(AgentArtifactRecord)
                .where(AgentArtifactRecord.id == reference.artifact_id)
                .values(sha256="f" * 64)
            )


# manifest 保存同样受围栏约束；旧 owner 不能在失租后补充审计材料。
@pytest.mark.asyncio
async def test_context_manifest_rejects_stale_fence(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    epoch = _epoch()
    await _as_evidence_repository(repository).save_evidence(context.fence, epoch)
    stale = RunFence(
        workspace_id=context.fence.workspace_id,
        run_id=context.fence.run_id,
        revision=context.fence.revision,
        segment_id=context.fence.segment_id,
        owner=uuid4(),
        lease_epoch=context.fence.lease_epoch,
    )

    with pytest.raises(AgentRunError) as raised:
        await repository.save_context_manifest(stale, _manifest(context, epoch))

    assert raised.value.code == "lease_lost"


# 合成证据端口：声明两次公开读取并返回一条公开草稿，不联网。
class FakeEvidencePort:
    def planned_transport_calls(self, timeframes: tuple[MarketTimeframe, ...]) -> int:
        return 1 + len(timeframes)

    async def collect(
        self,
        *,
        product: ProductKey,
        timeframes: tuple[MarketTimeframe, ...],
        analysis_as_of: datetime,
    ) -> EvidenceCollection:
        _ = (product, timeframes, analysis_as_of)
        content: JsonObject = {"symbol": "BTCUSDT", "price": "106.2"}
        return EvidenceCollection(
            items=(
                EvidenceDraft(
                    kind="market_detail",
                    source="synthetic-public-source",
                    observed_at=NOW,
                    available_at=NOW,
                    fetched_at=NOW,
                    quality=EvidenceQuality.VALID,
                    calculation_version="market_detail_v1",
                    content=content,
                ),
            )
        )


# 证据冻结与 T05 预算账本的真实 SQL 联验：预留/发送/成功结算与证据保存一致。
@pytest.mark.asyncio
async def test_evidence_service_reserves_transport_budget_and_persists(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    ledger = SqlAlchemyBudgetLedger(
        migrated_database.session_factory,
        clock=lambda: NOW,
    )
    service = EvidenceService(
        run_reader=repository,
        evidence_port=cast(ResearchEvidencePort, FakeEvidencePort()),
        repository=repository,
        budget=ledger,
        clock=lambda: NOW,
    )

    epoch = await service.freeze(context)
    status = await ledger.status(context.fence)
    latest = await _as_evidence_repository(repository).load_latest_evidence(
        context.fence.workspace_id,
        context.fence.run_id,
        context.fence.revision,
    )

    assert latest == epoch
    assert status.transport_calls == 2
    assert status.transport_sent == 2


# manifest 文档归属必须与保存围栏一致；只校验围栏活性不能让 B 的清单落到 A。
@pytest.mark.asyncio
async def test_context_manifest_rejects_document_scope_mismatch(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    epoch = _epoch()
    await _as_evidence_repository(repository).save_evidence(context.fence, epoch)
    manifest = _manifest(context, epoch)
    variants = (
        manifest.model_copy(update={"workspace_id": uuid4()}),
        manifest.model_copy(update={"run_id": uuid4()}),
        manifest.model_copy(update={"revision": manifest.revision + 1}),
        manifest.model_copy(update={"segment_id": uuid4()}),
    )

    for variant in variants:
        with pytest.raises(AgentRunError) as raised:
            await repository.save_context_manifest(context.fence, variant)
        assert raised.value.code == "integrity_violation"

    async with migrated_database.session_factory() as session:
        count = await session.scalar(select(AgentArtifactRecord))
    assert count is None


# manifest 引用的证据必须属于当前运行修订；同 run 的后续修订证据也不能借用。
@pytest.mark.asyncio
async def test_context_manifest_rejects_evidence_from_other_revision(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    other_content: JsonObject = {"symbol": "BTCUSDT", "price": "107.0"}
    other_epoch = EvidenceEpoch.seal(
        analysis_as_of=NOW,
        sealed_at=NOW,
        items=(
            EvidenceItem(
                evidence_id=uuid4(),
                kind="market_detail",
                source="synthetic-public-source",
                observed_at=NOW,
                available_at=NOW,
                fetched_at=NOW,
                payload_sha256=sha256_json(other_content),
                quality=EvidenceQuality.VALID,
                calculation_version="market_detail_v1",
                content=other_content,
            ),
        ),
    )
    async with migrated_database.session_factory() as session, session.begin():
        session.add(
            AgentEvidenceEpochRecord(
                id=other_epoch.epoch_id,
                workspace_id=context.fence.workspace_id,
                run_id=context.fence.run_id,
                revision=context.fence.revision + 1,
                analysis_as_of=other_epoch.analysis_as_of,
                sealed_at=other_epoch.sealed_at,
                sha256=other_epoch.sha256,
                document=cast(dict[str, object], other_epoch.model_dump(mode="json")),
                created_at=NOW,
            )
        )

    with pytest.raises(AgentRunError) as raised:
        await repository.save_context_manifest(
            context.fence,
            _manifest(context, other_epoch),
        )

    assert raised.value.code == "integrity_violation"


# 读取端同样核对行归属与文档归属；手动插入的错绑 artifact 不能被当作合法清单。
@pytest.mark.asyncio
async def test_context_manifest_load_rejects_row_document_scope_mismatch(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    epoch = _epoch()
    await _as_evidence_repository(repository).save_evidence(context.fence, epoch)
    manifest = _manifest(context, epoch).model_copy(update={"workspace_id": uuid4()})
    document = manifest.model_dump(mode="json")
    digest = sha256_json(cast(JsonValue, document))
    artifact_id = uuid4()
    async with migrated_database.session_factory() as session, session.begin():
        session.add(
            AgentArtifactRecord(
                id=artifact_id,
                workspace_id=context.fence.workspace_id,
                run_id=context.fence.run_id,
                revision=context.fence.revision,
                artifact_type="context_manifest",
                quality=None,
                sha256=digest,
                document=cast(dict[str, object], document),
                parent_artifact_id=None,
                created_at=NOW,
            )
        )

    with pytest.raises(AgentRunError) as raised:
        await repository.load_context_manifest(
            context.fence.workspace_id,
            context.fence.run_id,
            artifact_id,
        )

    assert raised.value.code == "integrity_violation"


# 读取端还核对 manifest 片段属于 run/revision；未知片段不能作为合法审计清单。
@pytest.mark.asyncio
async def test_context_manifest_load_rejects_unknown_segment(
    migrated_database: MigratedDatabase,
) -> None:
    repository, context = await _claimed_run(migrated_database)
    epoch = _epoch()
    await _as_evidence_repository(repository).save_evidence(context.fence, epoch)
    manifest = _manifest(context, epoch).model_copy(update={"segment_id": uuid4()})
    document = manifest.model_dump(mode="json")
    digest = sha256_json(cast(JsonValue, document))
    artifact_id = uuid4()
    async with migrated_database.session_factory() as session, session.begin():
        session.add(
            AgentArtifactRecord(
                id=artifact_id,
                workspace_id=context.fence.workspace_id,
                run_id=context.fence.run_id,
                revision=context.fence.revision,
                artifact_type="context_manifest",
                quality=None,
                sha256=digest,
                document=cast(dict[str, object], document),
                parent_artifact_id=None,
                created_at=NOW,
            )
        )

    with pytest.raises(AgentRunError) as raised:
        await repository.load_context_manifest(
            context.fence.workspace_id,
            context.fence.run_id,
            artifact_id,
        )

    assert raised.value.code == "integrity_violation"
