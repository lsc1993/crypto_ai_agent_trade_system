# 为模拟账户建立不可变估值序列，支持绩效聚合。
# 旧账户补初始记录和迁移基线，基线表示部分历史而非完整历史重建。
"""Create immutable paper account valuation records."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_paper_account_valuations"
down_revision: str | None = "0006_create_paper_trading"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序应用本版本的数据库变化；以下约束与触发器属于历史定义。
def upgrade() -> None:
    # 估值序列记录初始、迁移基线及后续状态，迁移基线显式标为部分历史。
    op.create_table(
        "paper_account_valuations",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("valued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cash", sa.Numeric(38, 18), nullable=False),
        sa.Column("position_quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("equity", sa.Numeric(38, 18), nullable=False),
        sa.Column("peak_equity", sa.Numeric(38, 18), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            name="fk_paper_valuations_account",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["paper_market_snapshots.id"],
            name="fk_paper_valuations_snapshot",
        ),
        sa.PrimaryKeyConstraint("account_id", "sequence", name="pk_paper_account_valuations"),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_paper_valuations_nonnegative_sequence",
        ),
        sa.CheckConstraint(
            "kind IN ('initial', 'market_valuation', 'migration_baseline')",
            name="ck_paper_valuations_kind",
        ),
        sa.CheckConstraint("cash >= 0", name="ck_paper_valuations_nonnegative_cash"),
        sa.CheckConstraint(
            "position_quantity >= 0",
            name="ck_paper_valuations_nonnegative_quantity",
        ),
        sa.CheckConstraint("equity >= 0", name="ck_paper_valuations_nonnegative_equity"),
        sa.CheckConstraint(
            "peak_equity >= equity",
            name="ck_paper_valuations_peak_equity",
        ),
        sa.CheckConstraint(
            "(kind = 'initial' AND snapshot_id IS NULL) OR "
            "(kind = 'market_valuation' AND snapshot_id IS NOT NULL) OR "
            "kind = 'migration_baseline'",
            name="ck_paper_valuations_snapshot_kind",
        ),
    )
    op.create_index(
        "ix_paper_valuations_account_valued_at",
        "paper_account_valuations",
        ["account_id", "valued_at", "sequence"],
    )

    op.execute(
        """
        INSERT INTO paper_account_valuations (
          account_id, sequence, kind, snapshot_id, valued_at, cash,
          position_quantity, equity, peak_equity
        )
        SELECT id, 0, 'initial', NULL, created_at, initial_cash, 0, initial_cash, initial_cash
        FROM paper_accounts
        """
    )
    op.execute(
        """
        WITH latest_snapshots AS (
          SELECT DISTINCT ON (account_id) id, account_id, observed_at
          FROM paper_market_snapshots
          ORDER BY account_id, observed_at DESC, id DESC
        )
        INSERT INTO paper_account_valuations (
          account_id, sequence, kind, snapshot_id, valued_at, cash,
          position_quantity, equity, peak_equity
        )
        SELECT accounts.id, 1, 'migration_baseline', snapshots.id,
               COALESCE(snapshots.observed_at, accounts.created_at), accounts.cash,
               positions.quantity, accounts.equity, accounts.peak_equity
        FROM paper_accounts AS accounts
        JOIN paper_positions AS positions ON positions.account_id = accounts.id
        LEFT JOIN latest_snapshots AS snapshots ON snapshots.account_id = accounts.id
        """
    )

    op.execute(
        """
        CREATE FUNCTION prevent_paper_valuation_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'paper trading paper_account_valuations are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_paper_account_valuations_immutable
        BEFORE UPDATE OR DELETE ON paper_account_valuations
        FOR EACH ROW EXECUTE FUNCTION prevent_paper_valuation_mutation();
        """
    )


# 历史脚本保留回退实现，仅解释其行为；日常维护不得对业务库执行删表回退。
def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_paper_account_valuations_immutable "
        "ON paper_account_valuations"
    )
    op.execute("DROP FUNCTION prevent_paper_valuation_mutation()")
    op.drop_index(
        "ix_paper_valuations_account_valued_at",
        table_name="paper_account_valuations",
    )
    op.drop_table("paper_account_valuations")
