# 在知识索引端口之上提供应用边界：拒绝未来截至时间与未来声明发布时间。
# 服务不实现检索算法或数据库事务，只把已校验请求委托给索引，便于测试替身和真实仓储替换。
# 未来时间检查使用服务端 UTC 时钟，不能由客户端时间或正文声明绕过。
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from app.research.knowledge.contracts import (
    KnowledgeHit,
    KnowledgeImport,
    KnowledgeQuery,
    KnowledgeQueryError,
    KnowledgeVersion,
)
from app.research.knowledge.ports import KnowledgeIndex
from app.shared.agent_types import PageQuery, VersionPage, VersionRef, require_utc


# 知识应用服务；clock 可注入固定时间，生产默认使用服务端 UTC 当前时刻。
class KnowledgeService:
    def __init__(
        self,
        index: KnowledgeIndex,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._index = index
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return require_utc(self._clock())

    # 用户声明发布时间只能是过去或现在；写入不可变版本前失败，避免未来时点冒充历史可得。
    async def import_text(
        self,
        workspace_id: UUID,
        draft: KnowledgeImport,
        *,
        request_id: UUID,
    ) -> KnowledgeVersion:
        if draft.declared_published_at is not None and draft.declared_published_at > self._now():
            raise KnowledgeQueryError(
                "用户声明发布时间不能晚于服务端当前时间",
                code="knowledge_declared_time_in_future",
            )
        return await self._index.import_text(workspace_id, draft, request_id=request_id)

    # 历史检索的截至时间不能晚于服务端当前时刻；未来时点会包含尚未发生的知识。
    async def search(
        self,
        workspace_id: UUID,
        query: KnowledgeQuery,
    ) -> tuple[KnowledgeHit, ...]:
        if query.as_of is not None and query.as_of > self._now():
            raise KnowledgeQueryError(
                "知识检索截至时间不能晚于服务端当前时间",
                code="knowledge_as_of_in_future",
            )
        return await self._index.search(workspace_id, query)

    async def publish(
        self,
        workspace_id: UUID,
        ref: VersionRef,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> KnowledgeVersion:
        return await self._index.publish(
            workspace_id,
            ref,
            expected_version=expected_version,
            request_id=request_id,
        )

    async def archive(
        self,
        workspace_id: UUID,
        document_id: UUID,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> None:
        await self._index.archive(
            workspace_id,
            document_id,
            expected_version=expected_version,
            request_id=request_id,
        )

    async def list_versions(
        self,
        workspace_id: UUID,
        query: PageQuery,
    ) -> VersionPage[KnowledgeVersion]:
        return await self._index.list_versions(workspace_id, query)


__all__ = ["KnowledgeService"]
