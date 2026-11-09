# 声明关键词知识索引的异步端口；研究知识层不依赖 Agent、SQLAlchemy 或交易执行。
# 写操作要求幂等 request_id 与乐观并发版本；检索端口只返回有界命中，不授予工具或权限。
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.research.knowledge.contracts import (
    KnowledgeHit,
    KnowledgeImport,
    KnowledgeQuery,
    KnowledgeVersion,
)
from app.shared.agent_types import PageQuery, VersionPage, VersionRef


# 知识索引端口：导入先创建不可变草稿，发布后才进入检索；归档停止新检索但保留历史读取。
class KnowledgeIndex(Protocol):
    async def import_text(
        self,
        workspace_id: UUID,
        draft: KnowledgeImport,
        *,
        request_id: UUID,
    ) -> KnowledgeVersion: ...

    async def search(
        self,
        workspace_id: UUID,
        query: KnowledgeQuery,
    ) -> tuple[KnowledgeHit, ...]: ...

    async def publish(
        self,
        workspace_id: UUID,
        ref: VersionRef,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> KnowledgeVersion: ...

    async def archive(
        self,
        workspace_id: UUID,
        document_id: UUID,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> None: ...

    async def list_versions(
        self,
        workspace_id: UUID,
        query: PageQuery,
    ) -> VersionPage[KnowledgeVersion]: ...


__all__ = ["KnowledgeIndex"]
