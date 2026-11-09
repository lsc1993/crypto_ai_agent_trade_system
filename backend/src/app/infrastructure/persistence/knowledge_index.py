# 用 PostgreSQL 实现版本化关键词知识库：导入、发布、归档、分页和幂等检索。
# 检索先用工作台/状态/时间/范围/权限与 GIN 词项数组限定候选，再按 4:1 固定公式排序。
# 请求幂等锁、版本正文不可变和分块不可变由事务、唯一约束和数据库触发器共同保证。
from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import JsonValue, ValidationError
from sqlalchemy import ARRAY, Text, any_, bindparam, func, or_, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.knowledge import (
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
    KnowledgeIndexRequestRecord,
    KnowledgeVersionRecord,
)
from app.research.knowledge.contracts import (
    KnowledgeConflictError,
    KnowledgeHit,
    KnowledgeImport,
    KnowledgeIndexError,
    KnowledgeIntegrityError,
    KnowledgeNotAvailableError,
    KnowledgeQuery,
    KnowledgeQueryError,
    KnowledgeStatus,
    KnowledgeVersion,
)
from app.research.knowledge.indexing import (
    MAX_HITS,
    prepare_chunks,
    score_chunk,
)
from app.shared.agent_types import (
    JsonObject,
    PageQuery,
    VersionPage,
    VersionRef,
    require_utc,
    sha256_json,
)

_ACTION_IMPORT = "import"
_ACTION_PUBLISH = "publish"
_ACTION_ARCHIVE = "archive"


# 请求重放快照只保留已提交 JSON 结果，不暴露 ORM 会话或异常。
@dataclass(frozen=True)
class _RequestSnapshot:
    result: JsonObject | None


# SQL 知识索引实现；clock 可注入固定时间，生产默认使用服务端 UTC。
class SqlAlchemyKnowledgeIndex:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    # 服务端时间必须带时区 UTC；不能以客户端时间证明历史可得性或发布顺序。
    def _now(self) -> datetime:
        return require_utc(self._clock())

    # 导入先创建不可变草稿；同文档重复内容返回原版本，发布后才进入检索。
    # 请求结果与版本、分块、文档元数据在同一事务提交，崩溃不会留下半个导入。
    async def import_text(
        self,
        workspace_id: UUID,
        draft: KnowledgeImport,
        *,
        request_id: UUID,
    ) -> KnowledgeVersion:
        draft_payload = _draft_payload(draft)
        snapshot = _parse_import(draft_payload)
        request_sha = _request_sha(_ACTION_IMPORT, workspace_id, {"draft": draft_payload})
        now = self._now()
        if snapshot.declared_published_at is not None and snapshot.declared_published_at > now:
            raise KnowledgeQueryError(
                "用户声明发布时间不能晚于服务端当前时间",
                code="knowledge_declared_time_in_future",
            )
        try:
            async with self._factory() as session, session.begin():
                await _lock_request(session, request_id)
                replay = await _load_request(
                    session,
                    request_id,
                    workspace_id,
                    _ACTION_IMPORT,
                    request_sha,
                )
                if replay is not None:
                    return _version_result(replay)

                document_id = snapshot.document_id or uuid4()
                document = await self._prepare_document(
                    session,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    create=snapshot.document_id is None,
                    now=now,
                    snapshot=snapshot,
                )
                version_id = uuid4()
                candidate = KnowledgeVersion.build(
                    version_id=version_id,
                    document_id=document_id,
                    draft=snapshot,
                    first_available_at=now,
                )
                existing = await session.scalar(
                    select(KnowledgeVersionRecord)
                    .where(
                        KnowledgeVersionRecord.document_id == document_id,
                        KnowledgeVersionRecord.sha256 == candidate.ref.sha256,
                    )
                    .order_by(KnowledgeVersionRecord.created_at.desc())
                    .limit(1)
                )
                if existing is not None:
                    version = _version_from_row(existing, document)
                else:
                    version = candidate
                    session.add(_version_row(version, workspace_id=workspace_id, created_at=now))
                    await session.flush()
                    session.add_all(_chunk_rows(version, workspace_id=workspace_id))
                    document.title = version.title
                    document.scope = version.scope
                    document.access = version.access.value
                    document.updated_at = now

                _store_request(
                    session,
                    request_id=request_id,
                    workspace_id=workspace_id,
                    action=_ACTION_IMPORT,
                    request_sha256=request_sha,
                    result=_version_payload(version),
                    now=now,
                )
            return version
        except IntegrityError:
            replayed = await self._replay_request(
                request_id,
                workspace_id,
                _ACTION_IMPORT,
                request_sha,
            )
            if replayed is not None:
                return _version_result(replayed)
            raise KnowledgeConflictError("知识导入写入冲突") from None
        except SQLAlchemyError:
            raise KnowledgeIndexError("知识索引写入不可用") from None

    # 发布草稿：校验精确引用和草稿代次，冻结发布时间并递增文档代次。
    async def publish(
        self,
        workspace_id: UUID,
        ref: VersionRef,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> KnowledgeVersion:
        request_sha = _request_sha(
            _ACTION_PUBLISH,
            workspace_id,
            {
                "ref": ref.model_dump(mode="json", by_alias=False),
                "expectedVersion": expected_version,
            },
        )
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                await _lock_request(session, request_id)
                replay = await _load_request(
                    session,
                    request_id,
                    workspace_id,
                    _ACTION_PUBLISH,
                    request_sha,
                )
                if replay is not None:
                    return _version_result(replay)

                row = await session.scalar(
                    select(KnowledgeVersionRecord)
                    .where(
                        KnowledgeVersionRecord.id == ref.version_id,
                        KnowledgeVersionRecord.workspace_id == workspace_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise KnowledgeNotAvailableError("知识版本不存在或不属于当前工作台")
                if row.sha256 != ref.sha256:
                    raise KnowledgeConflictError("知识版本引用指纹不一致")
                if row.state != "draft":
                    raise KnowledgeConflictError("只有草稿可以发布")
                if row.state_version != expected_version:
                    raise KnowledgeConflictError("知识草稿代次已变化，请重新读取")
                document = await _lock_document(session, workspace_id, row.document_id)
                if document.archived_at is not None:
                    raise KnowledgeNotAvailableError("知识文档已停用，不能发布新版本")

                draft_version = _version_from_row(row, document)
                published = _published_version(
                    draft_version,
                    published_at=now,
                    state_version=document.state_version + 1,
                )
                row.state = published.status.value
                row.state_version = published.state_version
                row.published_at = published.published_at
                row.updated_at = now
                document.state_version = published.state_version
                document.title = published.title
                document.scope = published.scope
                document.access = published.access.value
                document.updated_at = now
                _store_request(
                    session,
                    request_id=request_id,
                    workspace_id=workspace_id,
                    action=_ACTION_PUBLISH,
                    request_sha256=request_sha,
                    result=_version_payload(published),
                    now=now,
                )
            return published
        except IntegrityError:
            replayed = await self._replay_request(
                request_id,
                workspace_id,
                _ACTION_PUBLISH,
                request_sha,
            )
            if replayed is not None:
                return _version_result(replayed)
            raise KnowledgeConflictError("知识发布冲突") from None
        except SQLAlchemyError:
            raise KnowledgeIndexError("知识索引写入不可用") from None

    # 归档文档：阻止新导入、发布与检索，但历史版本仍可由已发布清单读取。
    async def archive(
        self,
        workspace_id: UUID,
        document_id: UUID,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> None:
        request_sha = _request_sha(
            _ACTION_ARCHIVE,
            workspace_id,
            {"documentId": str(document_id), "expectedVersion": expected_version},
        )
        now = self._now()
        try:
            async with self._factory() as session, session.begin():
                await _lock_request(session, request_id)
                replay = await _load_request(
                    session,
                    request_id,
                    workspace_id,
                    _ACTION_ARCHIVE,
                    request_sha,
                )
                if replay is not None:
                    return None
                document = await _lock_document(session, workspace_id, document_id)
                if document.state_version != expected_version:
                    raise KnowledgeConflictError("知识文档代次已变化，请重新读取")
                if document.archived_at is None:
                    document.archived_at = now
                    document.state_version += 1
                    document.updated_at = now
                _store_request(
                    session,
                    request_id=request_id,
                    workspace_id=workspace_id,
                    action=_ACTION_ARCHIVE,
                    request_sha256=request_sha,
                    result=None,
                    now=now,
                )
            return None
        except IntegrityError:
            replayed = await self._replay_request(
                request_id,
                workspace_id,
                _ACTION_ARCHIVE,
                request_sha,
            )
            if replayed is not None:
                return None
            raise KnowledgeConflictError("知识归档冲突") from None
        except SQLAlchemyError:
            raise KnowledgeIndexError("知识索引写入不可用") from None

    # 分页读取已发布历史（包括已归档文档）；草稿不进入公开历史清单。
    async def list_versions(
        self,
        workspace_id: UUID,
        query: PageQuery,
    ) -> VersionPage[KnowledgeVersion]:
        if query.page < 1 or not 1 <= query.page_size <= 100:
            raise ValueError("知识库分页无效")
        statement = (
            select(KnowledgeVersionRecord, KnowledgeDocumentRecord)
            .join(
                KnowledgeDocumentRecord,
                KnowledgeDocumentRecord.id == KnowledgeVersionRecord.document_id,
            )
            .where(
                KnowledgeVersionRecord.workspace_id == workspace_id,
                KnowledgeVersionRecord.state == KnowledgeStatus.PUBLISHED.value,
            )
        )
        try:
            async with self._factory() as session:
                rows = (
                    await session.execute(
                        statement.order_by(
                            KnowledgeVersionRecord.published_at.desc(),
                            KnowledgeVersionRecord.id.desc(),
                        )
                        .offset((query.page - 1) * query.page_size)
                        .limit(query.page_size)
                    )
                ).all()
                total = await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeVersionRecord)
                    .where(
                        KnowledgeVersionRecord.workspace_id == workspace_id,
                        KnowledgeVersionRecord.state == KnowledgeStatus.PUBLISHED.value,
                    )
                )
        except SQLAlchemyError:
            raise KnowledgeIndexError("知识索引读取不可用") from None
        items = tuple(
            _version_from_row(version_row, document_row) for version_row, document_row in rows
        )
        return VersionPage(
            items=items,
            page=query.page,
            page_size=query.page_size,
            total=total or 0,
        )

    # 检索先限定工作台、发布状态、归档、权限、范围与截至时间，再按 GIN 词项交集召回。
    # SQL 只返回最多 6 条；Python 重算分数并稳定排序，防止 SQL 表达式与纯函数漂移。
    async def search(
        self,
        workspace_id: UUID,
        query: KnowledgeQuery,
    ) -> tuple[KnowledgeHit, ...]:
        terms = query.terms
        if not terms:
            raise KnowledgeQueryError("知识查询没有可检索词项")
        now = self._now()
        if query.as_of is not None and query.as_of > now:
            raise KnowledgeQueryError(
                "知识检索截至时间不能晚于服务端当前时间",
                code="knowledge_as_of_in_future",
            )

        terms_param = bindparam("terms", type_=ARRAY(Text))
        title_match = _match_count(KnowledgeChunkRecord.title_terms, terms_param)
        body_match = _match_count(KnowledgeChunkRecord.terms, terms_param)
        score = (4 * title_match + body_match).label("score")
        statement = (
            select(
                KnowledgeVersionRecord.id.label("version_id"),
                KnowledgeVersionRecord.document_id.label("document_id"),
                KnowledgeVersionRecord.sha256.label("version_sha256"),
                KnowledgeVersionRecord.title.label("title"),
                KnowledgeVersionRecord.source.label("source"),
                KnowledgeVersionRecord.scope.label("scope"),
                KnowledgeVersionRecord.first_available_at.label("first_available_at"),
                KnowledgeVersionRecord.declared_published_at.label("declared_published_at"),
                KnowledgeVersionRecord.published_at.label("published_at"),
                KnowledgeChunkRecord.id.label("chunk_id"),
                KnowledgeChunkRecord.chunk_index.label("chunk_index"),
                KnowledgeChunkRecord.text.label("chunk_text"),
                KnowledgeChunkRecord.sha256.label("chunk_sha256"),
                KnowledgeChunkRecord.terms.label("terms"),
                KnowledgeChunkRecord.title_terms.label("title_terms"),
                score,
            )
            .join(
                KnowledgeVersionRecord,
                KnowledgeVersionRecord.id == KnowledgeChunkRecord.version_id,
            )
            .join(
                KnowledgeDocumentRecord,
                KnowledgeDocumentRecord.id == KnowledgeVersionRecord.document_id,
            )
            .where(
                KnowledgeVersionRecord.workspace_id == workspace_id,
                KnowledgeVersionRecord.state == KnowledgeStatus.PUBLISHED.value,
                KnowledgeDocumentRecord.archived_at.is_(None),
                KnowledgeVersionRecord.access == query.access.value,
                or_(
                    KnowledgeChunkRecord.terms.overlap(terms_param),
                    KnowledgeChunkRecord.title_terms.overlap(terms_param),
                ),
            )
            .order_by(
                score.desc(),
                KnowledgeVersionRecord.id.asc(),
                KnowledgeChunkRecord.chunk_index.asc(),
            )
            .limit(MAX_HITS)
        )
        if query.scope is not None:
            statement = statement.where(KnowledgeVersionRecord.scope == query.scope)
        if query.as_of is not None:
            statement = statement.where(
                KnowledgeVersionRecord.published_at <= query.as_of,
                KnowledgeVersionRecord.first_available_at <= query.as_of,
            )
        try:
            async with self._factory() as session:
                rows = (await session.execute(statement, {"terms": list(terms)})).all()
        except SQLAlchemyError:
            raise KnowledgeIndexError("知识索引检索不可用") from None

        hits = tuple(_row_to_hit(row, terms) for row in rows)
        return tuple(
            sorted(
                hits,
                key=lambda hit: (
                    -hit.score,
                    str(hit.version_ref.version_id),
                    hit.chunk_index,
                ),
            )
        )

    # 新建或锁定既有文档；新建时先 flush 满足版本外键，既有文档不允许跨工作台或归档写入。
    async def _prepare_document(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        document_id: UUID,
        create: bool,
        now: datetime,
        snapshot: KnowledgeImport,
    ) -> KnowledgeDocumentRecord:
        if create:
            document = KnowledgeDocumentRecord(
                id=document_id,
                workspace_id=workspace_id,
                title=snapshot.title,
                scope=snapshot.scope,
                access=snapshot.access.value,
                state_version=0,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
            session.add(document)
            await session.flush()
            return document
        document = await session.get(
            KnowledgeDocumentRecord,
            document_id,
            with_for_update=True,
        )
        if document is None or document.workspace_id != workspace_id:
            raise KnowledgeNotAvailableError("知识文档不存在或不属于当前工作台")
        if document.archived_at is not None:
            raise KnowledgeNotAvailableError("知识文档已停用，不能导入新版本")
        return document

    # 并发相同请求在唯一约束上失败后重读已提交结果；内容不同按冲突处理。
    async def _replay_request(
        self,
        request_id: UUID,
        workspace_id: UUID,
        action: str,
        request_sha: str,
    ) -> _RequestSnapshot | None:
        try:
            async with self._factory() as session:
                return await _load_request(
                    session,
                    request_id,
                    workspace_id,
                    action,
                    request_sha,
                )
        except SQLAlchemyError:
            return None


# 请求级事务锁：同一 request_id 的并发调用在业务读取前串行化，避免第二个请求误读已变化状态。
async def _lock_request(session: AsyncSession, request_id: UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:request_key, 0))"),
        {"request_key": str(request_id)},
    )


# 读取并校验请求幂等记录；同一 request_id 不能对应不同工作台、操作或内容。
async def _load_request(
    session: AsyncSession,
    request_id: UUID,
    workspace_id: UUID,
    action: str,
    request_sha: str,
) -> _RequestSnapshot | None:
    record = await session.get(KnowledgeIndexRequestRecord, request_id)
    if record is None:
        return None
    if (
        record.workspace_id != workspace_id
        or record.action != action
        or record.request_sha256 != request_sha
    ):
        raise KnowledgeConflictError("请求键已用于不同操作或内容")
    return _RequestSnapshot(result=cast(JsonObject | None, record.result))


# 写入请求结果；result 为 None 表示成功但无返回体（归档）。
def _store_request(
    session: AsyncSession,
    *,
    request_id: UUID,
    workspace_id: UUID,
    action: str,
    request_sha256: str,
    result: JsonObject | None,
    now: datetime,
) -> None:
    session.add(
        KnowledgeIndexRequestRecord(
            request_id=request_id,
            workspace_id=workspace_id,
            action=action,
            request_sha256=request_sha256,
            result=result,
            created_at=now,
        )
    )


# 锁定当前工作台文档；不存在或跨工作台按不可用处理。
async def _lock_document(
    session: AsyncSession,
    workspace_id: UUID,
    document_id: UUID,
) -> KnowledgeDocumentRecord:
    document = await session.get(
        KnowledgeDocumentRecord,
        document_id,
        with_for_update=True,
    )
    if document is None or document.workspace_id != workspace_id:
        raise KnowledgeNotAvailableError("知识文档不存在或不属于当前工作台")
    return document


# 规范化请求指纹覆盖操作、工作台和业务参数，不把 request_id 自身计入内容。
def _request_sha(action: str, workspace_id: UUID, payload: JsonObject) -> str:
    body: JsonObject = {
        "action": action,
        "workspaceId": str(workspace_id),
        "payload": payload,
    }
    return sha256_json(cast(JsonValue, body))


# 导入草稿持久化载荷；深拷贝避免调用方稍后修改嵌套对象影响事务内数据。
def _draft_payload(draft: KnowledgeImport) -> JsonObject:
    return cast(
        JsonObject,
        copy.deepcopy(draft.model_dump(mode="json", by_alias=False)),
    )


# 解析导入快照；非法字段在写入前失败，不把原始文本带入错误消息。
def _parse_import(payload: JsonObject) -> KnowledgeImport:
    try:
        return KnowledgeImport.model_validate(payload)
    except ValidationError as error:
        raise KnowledgeIntegrityError("知识导入内容校验失败") from error


# 发布版本持久化载荷；正文和分块不复制，只保存可重建的完整版本 JSON。
def _version_payload(version: KnowledgeVersion) -> JsonObject:
    return cast(
        JsonObject,
        copy.deepcopy(version.model_dump(mode="json", by_alias=False)),
    )


# 解析请求重放结果；损坏的历史结果不能被当作成功响应。
def _version_result(snapshot: _RequestSnapshot) -> KnowledgeVersion:
    if snapshot.result is None:
        raise KnowledgeIntegrityError("知识请求缺少已保存结果")
    try:
        return KnowledgeVersion.model_validate(snapshot.result)
    except ValidationError as error:
        raise KnowledgeIntegrityError("知识请求结果校验失败") from error


# 构造版本 ORM 行；正文指纹和内容指纹已在版本模型重算，数据库触发器再锁定列值。
def _version_row(
    version: KnowledgeVersion,
    *,
    workspace_id: UUID,
    created_at: datetime,
) -> KnowledgeVersionRecord:
    return KnowledgeVersionRecord(
        id=version.ref.version_id,
        document_id=version.document_id,
        workspace_id=workspace_id,
        state=version.status.value,
        state_version=version.state_version,
        title=version.title,
        source=version.source,
        scope=version.scope,
        access=version.access.value,
        text=version.text,
        text_sha256=version.text_sha256,
        sha256=version.ref.sha256,
        chunk_count=version.chunk_count,
        first_available_at=version.first_available_at,
        declared_published_at=version.declared_published_at,
        published_at=version.published_at,
        created_at=created_at,
        updated_at=created_at,
    )


# 构造分块 ORM 行；标题词项重复到每块，SQL 才能在不额外连接标题表的情况下计分。
def _chunk_rows(
    version: KnowledgeVersion,
    *,
    workspace_id: UUID,
) -> list[KnowledgeChunkRecord]:
    return [
        KnowledgeChunkRecord(
            id=chunk.chunk_id,
            version_id=version.ref.version_id,
            workspace_id=workspace_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            sha256=chunk.sha256,
            terms=list(chunk.terms),
            title_terms=list(chunk.title_terms),
        )
        for chunk in prepare_chunks(version.ref.version_id, version.title, version.text)
    ]


# 把发布版本推进到已发布状态；发布时间和文档代次由仓储提供，不读取客户端时间。
def _published_version(
    version: KnowledgeVersion,
    *,
    published_at: datetime,
    state_version: int,
) -> KnowledgeVersion:
    payload = version.model_dump(mode="python", by_alias=False)
    payload["status"] = KnowledgeStatus.PUBLISHED
    payload["state_version"] = state_version
    payload["published_at"] = published_at
    try:
        return KnowledgeVersion.model_validate(payload)
    except ValidationError as error:
        raise KnowledgeIntegrityError("知识发布内容校验失败") from error


# 将版本行和文档行重建为契约对象，并核对标识、正文哈希和归档状态。
def _version_from_row(
    row: KnowledgeVersionRecord,
    document: KnowledgeDocumentRecord,
) -> KnowledgeVersion:
    if row.workspace_id != document.workspace_id:
        raise KnowledgeIntegrityError("知识版本与文档工作台不一致")
    payload: JsonObject = {
        "ref": {"version_id": str(row.id), "sha256": row.sha256},
        "document_id": str(row.document_id),
        "title": row.title,
        "source": row.source,
        "scope": row.scope,
        "access": row.access,
        "text": row.text,
        "text_sha256": row.text_sha256,
        "chunk_count": row.chunk_count,
        "first_available_at": row.first_available_at.isoformat(),
        "declared_published_at": (
            None if row.declared_published_at is None else row.declared_published_at.isoformat()
        ),
        "status": row.state,
        "state_version": row.state_version,
        "published_at": None if row.published_at is None else row.published_at.isoformat(),
        "archived": document.archived_at is not None,
        "archived_at": (None if document.archived_at is None else document.archived_at.isoformat()),
    }
    try:
        version = KnowledgeVersion.model_validate(payload)
    except ValidationError as error:
        raise KnowledgeIntegrityError("知识版本行与内容不一致") from error
    if (
        version.ref.version_id != row.id
        or version.document_id != row.document_id
        or version.ref.sha256 != row.sha256
    ):
        raise KnowledgeIntegrityError("知识版本行标识与内容不一致")
    return version


# 计算查询词项与标题/正文词项数组的交集数量；相关子查询按外层分块行关联。
# render_derived 渲染 unnest(...) AS alias(term)，否则 PostgreSQL 只暴露名为 unnest 的列。
def _match_count(column: Any, terms: Any) -> Any:
    unnest = func.unnest(column).table_valued("term").render_derived()
    return (
        select(func.count())
        .select_from(unnest)
        .where(unnest.c.term == any_(terms))
        .correlate(KnowledgeChunkRecord)
        .scalar_subquery()
    )


# 将 SQL 行转为命中契约；先重算 4:1 分数和块指纹，防止 SQL 表达式或存储内容漂移。
def _row_to_hit(row: Any, query_terms: tuple[str, ...]) -> KnowledgeHit:
    title_terms = tuple(str(term) for term in row.title_terms)
    body_terms = tuple(str(term) for term in row.terms)
    expected_score = score_chunk(title_terms, body_terms, query_terms)
    sql_score = int(row.score)
    if expected_score != sql_score or sql_score < 1:
        raise KnowledgeIntegrityError("知识检索分数与纯函数评分不一致")
    published_at = row.published_at
    if not isinstance(published_at, datetime):
        raise KnowledgeIntegrityError("已发布知识版本缺少发布时间")
    try:
        return KnowledgeHit(
            document_id=row.document_id,
            version_ref=VersionRef(
                version_id=row.version_id,
                sha256=row.version_sha256,
            ),
            chunk_id=row.chunk_id,
            chunk_index=row.chunk_index,
            title=row.title,
            text=row.chunk_text,
            source=row.source,
            scope=row.scope,
            first_available_at=row.first_available_at,
            declared_published_at=row.declared_published_at,
            published_at=published_at,
            chunk_sha256=row.chunk_sha256,
            score=sql_score,
        )
    except ValidationError as error:
        raise KnowledgeIntegrityError("知识检索行校验失败") from error


__all__ = ["SqlAlchemyKnowledgeIndex"]
