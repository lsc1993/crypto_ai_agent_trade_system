"""Create append-only manual trade journal tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_create_trade_journal"
down_revision: str | None = "0003_create_analysis_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("horizon", sa.String(length=16), nullable=False),
        sa.Column("analysis_report_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("leverage", sa.Numeric(38, 18), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("review", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("gross_realized_pnl", sa.Numeric(38, 18), nullable=False),
        sa.Column("total_fees", sa.Numeric(38, 18), nullable=False),
        sa.Column("total_funding_cashflow", sa.Numeric(38, 18), nullable=False),
        sa.Column("net_pnl", sa.Numeric(38, 18), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_report_id"], ["analysis_reports.id"], name="fk_trades_analysis_report"
        ),
        sa.CheckConstraint("symbol IN ('BTCUSDT', 'ETHUSDT')", name="ck_trades_symbol"),
        sa.CheckConstraint("direction IN ('long', 'short')", name="ck_trades_direction"),
        sa.CheckConstraint("horizon IN ('short_term', 'medium_term')", name="ck_trades_horizon"),
        sa.CheckConstraint("status IN ('open', 'closed')", name="ck_trades_status"),
        sa.CheckConstraint("leverage > 0", name="ck_trades_positive_leverage"),
        sa.CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at", name="ck_trades_closed_after_open"
        ),
        sa.CheckConstraint(
            "archived_at IS NULL OR archived_at >= opened_at", name="ck_trades_archived_after_open"
        ),
    )
    op.create_index("ix_trades_active_updated_at", "trades", ["archived_at", "updated_at"])
    op.create_index("ix_trades_symbol_status", "trades", ["symbol", "status"])

    op.create_table(
        "trade_legs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trade_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(38, 18), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("fee", sa.Numeric(38, 18), nullable=False),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], name="fk_trade_legs_trade"),
        sa.CheckConstraint("action IN ('open', 'reduce', 'close')", name="ck_trade_legs_action"),
        sa.CheckConstraint("sequence >= 0", name="ck_trade_legs_sequence"),
        sa.CheckConstraint("price > 0", name="ck_trade_legs_positive_price"),
        sa.CheckConstraint("quantity > 0", name="ck_trade_legs_positive_quantity"),
        sa.CheckConstraint("fee >= 0", name="ck_trade_legs_nonnegative_fee"),
    )
    op.create_index(
        "uq_trade_legs_active_execution",
        "trade_legs",
        ["trade_id", "executed_at", "sequence"],
        unique=True,
        postgresql_where=sa.text("voided_at IS NULL"),
    )
    op.create_index(
        "ix_trade_legs_active_trade_executed",
        "trade_legs",
        ["trade_id", "voided_at", "executed_at"],
    )

    op.create_table(
        "trade_cashflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trade_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], name="fk_trade_cashflows_trade"),
    )
    op.create_index("ix_trade_cashflows_active_trade", "trade_cashflows", ["trade_id", "voided_at"])

    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("value", sa.String(length=100), nullable=False, unique=True),
    )
    op.create_table(
        "trade_tags",
        sa.Column("trade_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], name="fk_trade_tags_trade"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], name="fk_trade_tags_tag"),
        sa.PrimaryKeyConstraint("trade_id", "tag_id", name="uq_trade_tags_scope"),
    )

    op.create_table(
        "trade_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trade_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("before_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("after_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], name="fk_trade_audit_events_trade"),
        sa.CheckConstraint(
            "action IN ('created', 'updated', 'archived')", name="ck_trade_audit_events_action"
        ),
    )
    op.create_index(
        "ix_trade_audit_events_trade_occurred", "trade_audit_events", ["trade_id", "occurred_at"]
    )
    op.execute(
        """
        CREATE FUNCTION prevent_trade_audit_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'trade audit events are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_trade_audit_events_immutable
        BEFORE UPDATE OR DELETE ON trade_audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_trade_audit_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_trade_audit_events_immutable ON trade_audit_events")
    op.execute("DROP FUNCTION prevent_trade_audit_mutation")
    op.drop_index("ix_trade_audit_events_trade_occurred", table_name="trade_audit_events")
    op.drop_table("trade_audit_events")
    op.drop_table("trade_tags")
    op.drop_table("tags")
    op.drop_index("ix_trade_cashflows_active_trade", table_name="trade_cashflows")
    op.drop_table("trade_cashflows")
    op.drop_index("ix_trade_legs_active_trade_executed", table_name="trade_legs")
    op.drop_index("uq_trade_legs_active_execution", table_name="trade_legs")
    op.drop_table("trade_legs")
    op.drop_index("ix_trades_symbol_status", table_name="trades")
    op.drop_index("ix_trades_active_updated_at", table_name="trades")
    op.drop_table("trades")
