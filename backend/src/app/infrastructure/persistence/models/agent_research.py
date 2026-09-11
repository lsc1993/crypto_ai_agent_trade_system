from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


class AgentAnalysisRunRecord(Base):
    __tablename__ = "agent_analysis_runs"
    __table_args__ = (
        Index("ix_agent_analysis_runs_symbol_completed_at", "symbol", "completed_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("analysis_reports.analysis_id", name="fk_agent_runs_analysis"),
        nullable=False,
        unique=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generator_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentReportDetailRecord(Base):
    __tablename__ = "agent_report_details"

    analysis_report_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("analysis_reports.id", name="fk_agent_report_details_report"),
        primary_key=True,
    )
    horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    outlook: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    trend_alignment: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    support_zones: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    resistance_zones: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    catalysts: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    risks_and_invalidation: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    data_quality: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    market_overview: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    short_term_view: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    long_term_view: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    market_metrics: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    factor_analysis: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
