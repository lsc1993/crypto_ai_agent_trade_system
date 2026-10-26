# 声明 去重英文新闻标题摘要、来源和内容哈希 的 PostgreSQL ORM 映射。
# 字段、外键与索引供仓储构造查询及关联；导入模型只注册元数据，不执行数据库迁移。
# JSONB 保留结构化载荷，时间列按 timezone 声明；不可变触发器等数据库保护以已应用迁移为准。
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


# 以 deduplication_key 唯一保存新闻元数据，分别保留发布日期、抓取日期、内容哈希与来源归因。
class NewsItemRecord(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint("deduplication_key", name="uq_news_items_deduplication_key"),
        Index("ix_news_items_published_at", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    deduplication_key: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    source_item_id: Mapped[str | None] = mapped_column(String(300))
    canonical_url: Mapped[str | None] = mapped_column(String(2048))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(String(1600), nullable=False)
    related_symbols: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    event_category: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
