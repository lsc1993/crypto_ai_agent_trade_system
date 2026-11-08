# 声明版本化策略目录的 PostgreSQL ORM 映射。
# 定义稳定策略身份、草稿/发布版本与请求幂等记录；发布版本正文和指纹进入 JSONB/字符列。
# 不可变触发器、约束与索引以对应迁移为准；模型导入只注册元数据，不执行迁移。
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


# 稳定策略身份与目录代次；归档只阻止新执行，不删除历史版本。
class StrategyDefinitionRecord(Base):
    __tablename__ = "strategy_definitions"
    __table_args__ = (
        CheckConstraint("state_version >= 0", name="ck_strategy_definition_version"),
        Index("ix_strategy_definitions_workspace_created", "workspace_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 版本行先作为草稿存在，发布后正文不可再更新；database trigger 拒绝直接改写发布行。
class StrategyVersionRecord(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (
        CheckConstraint("state IN ('draft','published')", name="ck_strategy_version_state"),
        CheckConstraint("state_version >= 0", name="ck_strategy_version_number"),
        CheckConstraint(
            "(state = 'draft' AND published_at IS NULL) OR "
            "(state = 'published' AND published_at IS NOT NULL AND state_version >= 1)",
            name="ck_strategy_version_published",
        ),
        Index(
            "ix_strategy_versions_workspace_state_published",
            "workspace_id",
            "state",
            "published_at",
        ),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    strategy_id: Mapped[UUID] = mapped_column(
        ForeignKey("strategy_definitions.id", name="fk_strategy_versions_definition"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# 请求幂等记录保存原始结果；同一 request_id 只能对应同一操作和同一规范化请求。
class StrategyCatalogRequestRecord(Base):
    __tablename__ = "strategy_catalog_requests"
    __table_args__ = (
        CheckConstraint(
            "action IN ('create_draft','update_draft','publish','archive')",
            name="ck_strategy_catalog_request_action",
        ),
        CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_strategy_catalog_request_sha",
        ),
    )
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
