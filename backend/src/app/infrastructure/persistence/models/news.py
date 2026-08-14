from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


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
