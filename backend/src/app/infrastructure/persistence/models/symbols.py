# 声明 研究币种目录、同步租约、操作事件及新闻关联 的 PostgreSQL ORM 映射。
# 字段、外键与索引供仓储构造查询及关联；导入模型只注册元数据，不执行数据库迁移。
# JSONB 保留结构化载荷，时间列按 timezone 声明；不可变触发器等数据库保护以已应用迁移为准。
"""Research admission registry and durable public-data synchronization jobs."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


# 用研究币种作为目录主键，记录启用状态、公开合约元数据、能力与版本；不改写交易枚举。
class ResearchSymbolRecord(Base):
    __tablename__ = "research_symbols"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    base_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    margin_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_type: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    capabilities: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# 保存初始同步阶段及随机租约令牌，version 关联登记版本，快照与来源结果只在完成后填写。
class ResearchSymbolSyncRunRecord(Base):
    __tablename__ = "research_symbol_sync_runs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    symbol: Mapped[str] = mapped_column(
        String(32), ForeignKey("research_symbols.symbol"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("market_snapshots.id")
    )
    sources: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    error: Mapped[str | None] = mapped_column(String(256))


# 记录目录操作与准入拒绝；symbol 不要求目录外键，未登记币种也可留下检查审计。
class ResearchSymbolEventRecord(Base):
    __tablename__ = "research_symbol_events"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    operation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    # Rejected checks are auditable before a directory entry exists.
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("research_symbol_sync_runs.id")
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


# 用 news_id/symbol 复合主键关联新闻与已登记币种，scope 区分资产证据与整体市场上下文。
class ResearchNewsLinkRecord(Base):
    __tablename__ = "research_news_links"

    news_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("news_items.id"), primary_key=True
    )
    symbol: Mapped[str] = mapped_column(
        String(32), ForeignKey("research_symbols.symbol"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
