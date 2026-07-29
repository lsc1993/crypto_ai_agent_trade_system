"""Create bounded market research persistence tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_create_market_persistence"
down_revision: str | None = "0001_initialize_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_candles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("timeframe", sa.String(length=3), nullable=False),
        sa.Column("open_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("high_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("low_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("close_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("volume", sa.Numeric(38, 18), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "symbol IN ('BTCUSDT', 'ETHUSDT')", name="ck_market_candles_symbol"
        ),
        sa.CheckConstraint(
            "timeframe IN ('15m', '1h', '4h', '1d')", name="ck_market_candles_timeframe"
        ),
        sa.CheckConstraint("close_at > open_at", name="ck_market_candles_time_order"),
        sa.CheckConstraint(
            "high_price >= GREATEST(open_price, close_price)", name="ck_market_candles_high_range"
        ),
        sa.CheckConstraint(
            "low_price <= LEAST(open_price, close_price)", name="ck_market_candles_low_range"
        ),
        sa.CheckConstraint(
            "low_price >= 0 AND volume >= 0", name="ck_market_candles_non_negative"
        ),
        sa.UniqueConstraint("symbol", "timeframe", "open_at", name="uq_market_candles_scope"),
    )
    op.create_index(
        "ix_market_candles_scope_open_at",
        "market_candles",
        ["symbol", "timeframe", sa.text("open_at DESC")],
    )

    op.create_table(
        "derivative_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("metric_type", sa.String(length=20), nullable=False),
        sa.Column("value", sa.Numeric(38, 18), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "symbol IN ('BTCUSDT', 'ETHUSDT')", name="ck_derivative_observations_symbol"
        ),
        sa.CheckConstraint(
            "metric_type IN ('price', 'funding_rate', 'open_interest', 'change_24h', 'volume_24h')",
            name="ck_derivative_observations_metric_type",
        ),
        sa.UniqueConstraint(
            "symbol",
            "metric_type",
            "observed_at",
            "source",
            name="uq_derivative_observations_scope",
        ),
    )
    op.create_index(
        "ix_derivative_observations_symbol_observed_at",
        "derivative_observations",
        ["symbol", sa.text("observed_at DESC")],
    )

    op.create_table(
        "market_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_version", sa.String(length=20), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "symbol IN ('BTCUSDT', 'ETHUSDT')", name="ck_market_snapshots_symbol"
        ),
        sa.CheckConstraint(
            "data_version = 'market-v1'", name="ck_market_snapshots_data_version"
        ),
        sa.CheckConstraint(
            "data_as_of <= captured_at", name="ck_market_snapshots_time_order"
        ),
        sa.CheckConstraint(
            "char_length(payload_sha256) = 64", name="ck_market_snapshots_hash_length"
        ),
        sa.CheckConstraint(
            "octet_length(payload::text) <= 65536", name="ck_market_snapshots_payload_size"
        ),
    )
    op.create_index(
        "ix_market_snapshots_symbol_captured_at",
        "market_snapshots",
        ["symbol", sa.text("captured_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_market_snapshots_symbol_captured_at", table_name="market_snapshots")
    op.drop_table("market_snapshots")
    op.drop_index(
        "ix_derivative_observations_symbol_observed_at", table_name="derivative_observations"
    )
    op.drop_table("derivative_observations")
    op.drop_index("ix_market_candles_scope_open_at", table_name="market_candles")
    op.drop_table("market_candles")
