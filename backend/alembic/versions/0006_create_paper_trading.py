# 建立本地模拟账户、仓位、快照、订单、成交、账本与审计表。
# 活动账户及意图幂等键由数据库约束，成交和账本等历史记录只允许追加。
"""Create immutable manual paper trading tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_create_paper_trading"
down_revision: str | None = "0005_create_backtests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABLE_TABLES = (
    (
        "paper_market_snapshots",
        "prevent_paper_snapshot_mutation",
        "trg_paper_market_snapshots_immutable",
    ),
    ("paper_orders", "prevent_paper_order_mutation", "trg_paper_orders_immutable"),
    ("paper_fills", "prevent_paper_fill_mutation", "trg_paper_fills_immutable"),
    (
        "paper_ledger_entries",
        "prevent_paper_ledger_mutation",
        "trg_paper_ledger_entries_immutable",
    ),
    ("paper_audit_events", "prevent_paper_event_mutation", "trg_paper_audit_events_immutable"),
)


# 按修订链顺序应用本版本的数据库变化；以下约束与触发器属于历史定义。
def upgrade() -> None:
    # 当前账户状态可推进，部分唯一索引限制同时活动的账户数量。
    op.create_table(
        "paper_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("initial_cash", sa.Numeric(38, 18), nullable=False),
        sa.Column("cash", sa.Numeric(38, 18), nullable=False),
        sa.Column("equity", sa.Numeric(38, 18), nullable=False),
        sa.Column("peak_equity", sa.Numeric(38, 18), nullable=False),
        sa.Column("daily_start_equity", sa.Numeric(38, 18), nullable=False),
        sa.Column("daily_realized_loss", sa.Numeric(38, 18), nullable=False),
        sa.Column("daily_day", sa.Date(), nullable=False),
        sa.Column("cooldown_remaining", sa.Integer(), nullable=False),
        sa.Column("last_closed_candle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("risk_config", postgresql.JSONB(), nullable=False),
        sa.Column("execution_config", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_paper_accounts_status",
        ),
        sa.CheckConstraint("symbol = 'BTCUSDT'", name="ck_paper_accounts_symbol"),
        sa.CheckConstraint(
            "initial_cash > 0",
            name="ck_paper_accounts_positive_initial_cash",
        ),
        sa.CheckConstraint("cash >= 0", name="ck_paper_accounts_nonnegative_cash"),
        sa.CheckConstraint("equity >= 0", name="ck_paper_accounts_nonnegative_equity"),
        sa.CheckConstraint(
            "peak_equity >= equity",
            name="ck_paper_accounts_peak_equity",
        ),
        sa.CheckConstraint(
            "daily_start_equity >= 0",
            name="ck_paper_accounts_nonnegative_daily_start",
        ),
        sa.CheckConstraint(
            "daily_realized_loss >= 0",
            name="ck_paper_accounts_nonnegative_daily_loss",
        ),
        sa.CheckConstraint(
            "cooldown_remaining >= 0",
            name="ck_paper_accounts_nonnegative_cooldown",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND archived_at IS NULL) OR "
            "(status = 'archived' AND archived_at IS NOT NULL)",
            name="ck_paper_accounts_archive_state",
        ),
    )
    op.create_index(
        "ix_paper_accounts_created_at",
        "paper_accounts",
        ["created_at", "id"],
    )
    op.create_index(
        "uq_paper_accounts_one_active",
        "paper_accounts",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # 仓位保存当前数量、成本及止损状态，历史成交仍由独立表保留。
    op.create_table(
        "paper_positions",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("average_entry_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("remaining_entry_cost", sa.Numeric(38, 18), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            name="fk_paper_positions_account",
        ),
        sa.PrimaryKeyConstraint("account_id", name="pk_paper_positions"),
        sa.CheckConstraint("quantity >= 0", name="ck_paper_positions_nonnegative_quantity"),
        sa.CheckConstraint(
            "remaining_entry_cost >= 0",
            name="ck_paper_positions_nonnegative_cost",
        ),
        sa.CheckConstraint(
            "average_entry_price IS NULL OR average_entry_price > 0",
            name="ck_paper_positions_positive_average_price",
        ),
        sa.CheckConstraint(
            "(quantity > 0 AND average_entry_price IS NOT NULL "
            "AND remaining_entry_cost > 0 AND opened_at IS NOT NULL) OR "
            "(quantity = 0 AND average_entry_price IS NULL "
            "AND remaining_entry_cost = 0 AND opened_at IS NULL)",
            name="ck_paper_positions_open_state",
        ),
    )

    op.create_table(
        "paper_market_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price", sa.Numeric(38, 18), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            name="fk_paper_snapshots_account",
        ),
        sa.CheckConstraint("price > 0", name="ck_paper_snapshots_positive_price"),
        sa.CheckConstraint(
            "fetched_at >= observed_at",
            name="ck_paper_snapshots_fetch_order",
        ),
    )
    op.create_index(
        "ix_paper_snapshots_account_observed_at",
        "paper_market_snapshots",
        ["account_id", "observed_at", "id"],
    )

    # 订单以本地模拟契约保存，不对应真实交易所下单能力。
    op.create_table(
        "paper_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            name="fk_paper_orders_account",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["paper_market_snapshots.id"],
            name="fk_paper_orders_snapshot",
        ),
        sa.CheckConstraint(
            "action IN ('open_long', 'close_long')",
            name="ck_paper_orders_action",
        ),
        sa.CheckConstraint(
            "source IN ('strategy', 'manual', 'risk')",
            name="ck_paper_orders_source",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'filled', 'partially_filled')",
            name="ck_paper_orders_status",
        ),
        sa.CheckConstraint(
            "requested_quantity > 0",
            name="ck_paper_orders_positive_quantity",
        ),
    )
    op.create_index(
        "ix_paper_orders_account_submitted_at",
        "paper_orders",
        ["account_id", "submitted_at", "id"],
    )

    # 成交金额与费用使用精确数值，关联本地模拟订单和行情快照。
    op.create_table(
        "paper_fills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("price", sa.Numeric(38, 18), nullable=False),
        sa.Column("fee", sa.Numeric(38, 18), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["paper_orders.id"],
            name="fk_paper_fills_order",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            name="fk_paper_fills_account",
        ),
        sa.UniqueConstraint("order_id", name="uq_paper_fills_order"),
        sa.CheckConstraint("quantity > 0", name="ck_paper_fills_positive_quantity"),
        sa.CheckConstraint("price > 0", name="ck_paper_fills_positive_price"),
        sa.CheckConstraint("fee >= 0", name="ck_paper_fills_nonnegative_fee"),
        sa.CheckConstraint(
            "status IN ('filled', 'partially_filled')",
            name="ck_paper_fills_status",
        ),
    )
    op.create_index(
        "ix_paper_fills_account_filled_at",
        "paper_fills",
        ["account_id", "filled_at", "id"],
    )

    # 资金变化以追加账本表达，不能仅改余额而失去变化依据。
    op.create_table(
        "paper_ledger_entries",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("cash_delta", sa.Numeric(38, 18), nullable=False),
        sa.Column("position_delta", sa.Numeric(38, 18), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(38, 18), nullable=False),
        sa.Column("fee", sa.Numeric(38, 18), nullable=False),
        sa.Column("cash_after", sa.Numeric(38, 18), nullable=False),
        sa.Column("quantity_after", sa.Numeric(38, 18), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            name="fk_paper_ledger_account",
        ),
        sa.PrimaryKeyConstraint("account_id", "sequence", name="pk_paper_ledger_entries"),
        sa.CheckConstraint("sequence >= 0", name="ck_paper_ledger_nonnegative_sequence"),
        sa.CheckConstraint(
            "kind IN ('open_long', 'close_long')",
            name="ck_paper_ledger_action",
        ),
        sa.CheckConstraint("fee >= 0", name="ck_paper_ledger_nonnegative_fee"),
        sa.CheckConstraint(
            "cash_after >= 0",
            name="ck_paper_ledger_nonnegative_cash_after",
        ),
        sa.CheckConstraint(
            "quantity_after >= 0",
            name="ck_paper_ledger_nonnegative_quantity_after",
        ),
    )
    op.create_index(
        "ix_paper_ledger_account_occurred_at",
        "paper_ledger_entries",
        ["account_id", "occurred_at", "sequence"],
    )

    # 意图幂等索引和追加事件共同防止重复模拟操作且保留拒绝原因。
    op.create_table(
        "paper_audit_events",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            name="fk_paper_events_account",
        ),
        sa.PrimaryKeyConstraint("account_id", "sequence", name="pk_paper_audit_events"),
        sa.CheckConstraint("sequence >= 0", name="ck_paper_events_nonnegative_sequence"),
        sa.CheckConstraint(
            "kind IN ('intent', 'no_signal', 'market_unavailable', 'risk_approved', "
            "'risk_rejected', 'risk_exit', 'order', 'fill', 'archived')",
            name="ck_paper_events_kind",
        ),
    )
    op.create_index(
        "ix_paper_events_account_occurred_at",
        "paper_audit_events",
        ["account_id", "occurred_at", "sequence"],
    )
    op.create_index(
        "uq_paper_events_intent_idempotency",
        "paper_audit_events",
        ["account_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("kind = 'intent'"),
    )

    for table, function, trigger in _IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE FUNCTION {function}() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'paper trading {table} are immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {trigger}
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {function}();
            """
        )


# 历史脚本保留回退实现，仅解释其行为；日常维护不得对业务库执行删表回退。
def downgrade() -> None:
    for table, function, trigger in reversed(_IMMUTABLE_TABLES):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
        op.execute(f"DROP FUNCTION {function}()")
    op.drop_index("uq_paper_events_intent_idempotency", table_name="paper_audit_events")
    op.drop_index("ix_paper_events_account_occurred_at", table_name="paper_audit_events")
    op.drop_table("paper_audit_events")
    op.drop_index("ix_paper_ledger_account_occurred_at", table_name="paper_ledger_entries")
    op.drop_table("paper_ledger_entries")
    op.drop_index("ix_paper_fills_account_filled_at", table_name="paper_fills")
    op.drop_table("paper_fills")
    op.drop_index("ix_paper_orders_account_submitted_at", table_name="paper_orders")
    op.drop_table("paper_orders")
    op.drop_index("ix_paper_snapshots_account_observed_at", table_name="paper_market_snapshots")
    op.drop_table("paper_market_snapshots")
    op.drop_table("paper_positions")
    op.drop_index("uq_paper_accounts_one_active", table_name="paper_accounts")
    op.drop_index("ix_paper_accounts_created_at", table_name="paper_accounts")
    op.drop_table("paper_accounts")
