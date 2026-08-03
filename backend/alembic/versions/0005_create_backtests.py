"""Create immutable deterministic backtest tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_create_backtests"
down_revision: str | None = "0004_create_trade_journal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_cash", sa.Numeric(38, 18), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("risk_config", postgresql.JSONB(), nullable=False),
        sa.Column("execution_config", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_backtest_runs_status",
        ),
        sa.CheckConstraint("symbol = 'BTCUSDT'", name="ck_backtest_runs_symbol"),
        sa.CheckConstraint("timeframe = '1h'", name="ck_backtest_runs_timeframe"),
        sa.CheckConstraint("initial_cash > 0", name="ck_backtest_runs_positive_initial_cash"),
        sa.CheckConstraint("end_at > start_at", name="ck_backtest_runs_range"),
        sa.CheckConstraint(
            "(status = 'pending' AND finished_at IS NULL AND metrics IS NULL "
            "AND failure_code IS NULL AND failure_message IS NULL) OR "
            "(status = 'completed' AND finished_at IS NOT NULL AND metrics IS NOT NULL "
            "AND snapshot_hash IS NOT NULL AND failure_code IS NULL "
            "AND failure_message IS NULL) OR "
            "(status = 'failed' AND finished_at IS NOT NULL AND metrics IS NULL "
            "AND failure_code IS NOT NULL AND failure_message IS NOT NULL)",
            name="ck_backtest_runs_terminal_state",
        ),
    )
    op.create_index(
        "ix_backtest_runs_created_at",
        "backtest_runs",
        ["created_at", "id"],
    )

    op.create_table(
        "backtest_candles",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("open_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("high_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("low_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("close_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("volume", sa.Numeric(38, 18), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.id"],
            name="fk_backtest_candles_run",
        ),
        sa.PrimaryKeyConstraint("run_id", "sequence", name="pk_backtest_candles"),
        sa.CheckConstraint("sequence >= 0", name="ck_backtest_candles_sequence"),
        sa.CheckConstraint("symbol = 'BTCUSDT'", name="ck_backtest_candles_symbol"),
        sa.CheckConstraint("timeframe = '1h'", name="ck_backtest_candles_timeframe"),
        sa.CheckConstraint("close_at > open_at", name="ck_backtest_candles_range"),
        sa.CheckConstraint("open_price >= 0", name="ck_backtest_candles_nonnegative_open"),
        sa.CheckConstraint("high_price >= 0", name="ck_backtest_candles_nonnegative_high"),
        sa.CheckConstraint("low_price >= 0", name="ck_backtest_candles_nonnegative_low"),
        sa.CheckConstraint("close_price >= 0", name="ck_backtest_candles_nonnegative_close"),
        sa.CheckConstraint("volume >= 0", name="ck_backtest_candles_nonnegative_volume"),
    )
    op.create_index(
        "ix_backtest_candles_run_open_at",
        "backtest_candles",
        ["run_id", "open_at"],
    )

    op.create_table(
        "backtest_events",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candle_sequence", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["backtest_runs.id"],
            name="fk_backtest_events_run",
        ),
        sa.PrimaryKeyConstraint("run_id", "sequence", name="pk_backtest_events"),
        sa.CheckConstraint("sequence >= 0", name="ck_backtest_events_sequence"),
        sa.CheckConstraint(
            "candle_sequence IS NULL OR candle_sequence >= 0",
            name="ck_backtest_events_candle_sequence",
        ),
        sa.CheckConstraint(
            "kind IN ('decision', 'risk_approved', 'risk_rejected', 'order', 'fill', "
            "'risk_exit', 'circuit_breaker', 'completed')",
            name="ck_backtest_events_kind",
        ),
    )
    op.create_index(
        "ix_backtest_events_run_occurred_at",
        "backtest_events",
        ["run_id", "occurred_at", "sequence"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_backtest_candle_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'backtest candles are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_backtest_candles_immutable
        BEFORE UPDATE OR DELETE ON backtest_candles
        FOR EACH ROW EXECUTE FUNCTION prevent_backtest_candle_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_backtest_event_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'backtest events are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_backtest_events_immutable
        BEFORE UPDATE OR DELETE ON backtest_events
        FOR EACH ROW EXECUTE FUNCTION prevent_backtest_event_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_backtest_events_immutable ON backtest_events")
    op.execute("DROP FUNCTION prevent_backtest_event_mutation()")
    op.execute("DROP TRIGGER trg_backtest_candles_immutable ON backtest_candles")
    op.execute("DROP FUNCTION prevent_backtest_candle_mutation()")
    op.drop_index("ix_backtest_events_run_occurred_at", table_name="backtest_events")
    op.drop_table("backtest_events")
    op.drop_index("ix_backtest_candles_run_open_at", table_name="backtest_candles")
    op.drop_table("backtest_candles")
    op.drop_index("ix_backtest_runs_created_at", table_name="backtest_runs")
    op.drop_table("backtest_runs")
