from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


class BacktestRunRecord(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (Index("ix_backtest_runs_created_at", "created_at", "id"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    risk_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    execution_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metrics: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BacktestCandleRecord(Base):
    __tablename__ = "backtest_candles"
    __table_args__ = (Index("ix_backtest_candles_run_open_at", "run_id", "open_at"),)

    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("backtest_runs.id", name="fk_backtest_candles_run"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    high_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    low_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BacktestEventRecord(Base):
    __tablename__ = "backtest_events"
    __table_args__ = (
        Index("ix_backtest_events_run_occurred_at", "run_id", "occurred_at", "sequence"),
    )

    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("backtest_runs.id", name="fk_backtest_events_run"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    candle_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
