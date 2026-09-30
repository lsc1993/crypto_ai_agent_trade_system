from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


class TechnicalReportRecord(Base):
    __tablename__ = "technical_reports"
    __table_args__ = (Index("ix_technical_reports_symbol_created", "symbol", "created_at"),)
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("harness_runs.run_id", name="fk_technical_reports_run"),
        unique=True,
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    frozen_evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
