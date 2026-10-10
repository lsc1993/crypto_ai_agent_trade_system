"""Durable queue records separate from immutable report history."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


class TechnicalRunRecord(Base):
    __tablename__ = "technical_report_runs"
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), unique=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report_id: Mapped[UUID | None] = mapped_column(ForeignKey("technical_reports.id"))
    error_code: Mapped[str | None] = mapped_column(String(32))


class TechnicalRequestRecord(Base):
    __tablename__ = "technical_report_requests"
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("technical_report_runs.id"), nullable=False)


class TechnicalQueueRecord(Base):
    __tablename__ = "technical_report_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
