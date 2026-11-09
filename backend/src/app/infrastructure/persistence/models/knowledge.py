# 声明版本化关键词知识库的 PostgreSQL ORM 映射。
# 文档、不可变版本、分块词项数组和请求幂等记录分别建表；实际约束、GIN 索引与
# 不可变触发器由 0020 迁移创建。模型导入只注册元数据，不执行迁移或构建索引。
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


# 稳定知识文档身份与当前元数据；归档只阻止新检索/导入，不删除历史版本。
class KnowledgeDocumentRecord(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint("state_version >= 0", name="ck_knowledge_document_version"),
        CheckConstraint("char_length(title) BETWEEN 1 AND 200", name="ck_knowledge_document_title"),
        CheckConstraint("char_length(scope) BETWEEN 1 AND 64", name="ck_knowledge_document_scope"),
        CheckConstraint("access = 'workspace'", name="ck_knowledge_document_access"),
        Index("ix_knowledge_documents_workspace_created", "workspace_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    access: Mapped[str] = mapped_column(String(16), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 不可变知识版本正文；草稿发布只改变状态列，正文/指纹/来源时间由触发器锁定。
class KnowledgeVersionRecord(Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        CheckConstraint("state IN ('draft','published')", name="ck_knowledge_version_state"),
        CheckConstraint(
            "(state = 'draft' AND state_version = 0 AND published_at IS NULL) OR "
            "(state = 'published' AND state_version >= 1 AND published_at IS NOT NULL)",
            name="ck_knowledge_version_generation",
        ),
        CheckConstraint(
            "octet_length(text) BETWEEN 1 AND 262144",
            name="ck_knowledge_version_text_size",
        ),
        CheckConstraint("char_length(title) BETWEEN 1 AND 200", name="ck_knowledge_version_title"),
        CheckConstraint(
            "char_length(source) BETWEEN 1 AND 500", name="ck_knowledge_version_source"
        ),
        CheckConstraint("char_length(scope) BETWEEN 1 AND 64", name="ck_knowledge_version_scope"),
        CheckConstraint("access = 'workspace'", name="ck_knowledge_version_access"),
        CheckConstraint(
            "char_length(text_sha256) = 64 AND char_length(sha256) = 64",
            name="ck_knowledge_version_sha",
        ),
        CheckConstraint("chunk_count >= 1", name="ck_knowledge_version_chunks"),
        CheckConstraint(
            "declared_published_at IS NULL OR declared_published_at <= first_available_at",
            name="ck_knowledge_version_declared_time",
        ),
        CheckConstraint(
            "published_at IS NULL OR published_at >= first_available_at",
            name="ck_knowledge_version_published_time",
        ),
        Index(
            "ix_knowledge_versions_workspace_state_published",
            "workspace_id",
            "state",
            "published_at",
        ),
        Index("ix_knowledge_versions_document", "document_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", name="fk_knowledge_versions_document"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    access: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    declared_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 版本分块保存原文与两套词项数组；GIN 索引用于召回，正文指纹用于命中完整性校验。
class KnowledgeChunkRecord(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "chunk_index", name="uq_knowledge_chunks_version_index"),
        CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunk_index"),
        CheckConstraint("octet_length(text) >= 1", name="ck_knowledge_chunk_text"),
        CheckConstraint("char_length(sha256) = 64", name="ck_knowledge_chunk_sha"),
        Index("ix_knowledge_chunks_terms", "terms", postgresql_using="gin"),
        Index("ix_knowledge_chunks_title_terms", "title_terms", postgresql_using="gin"),
        Index("ix_knowledge_chunks_workspace_version", "workspace_id", "version_id"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_versions.id", name="fk_knowledge_chunks_version"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    terms: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    title_terms: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)


# 请求幂等记录保存原始导入/发布/归档结果；同一 request_id 只能对应同一操作和同一请求。
class KnowledgeIndexRequestRecord(Base):
    __tablename__ = "knowledge_index_requests"
    __table_args__ = (
        CheckConstraint(
            "action IN ('import','publish','archive')",
            name="ck_knowledge_index_request_action",
        ),
        CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_knowledge_index_request_sha",
        ),
    )
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
