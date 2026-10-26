# 为市场快照保存完整且不可变的 K 线输入与哈希。
# 研究复算不再依赖之后可能更新的行情表，输入按快照关联并防止改写。
"""Create immutable full candle inputs for auditable market snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_market_snapshot_inputs"
down_revision: str | None = "0008_create_agent_research"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序应用本版本的数据库变化；以下约束与触发器属于历史定义。
def upgrade() -> None:
    # 完整闭合 K 线与快照标识和哈希绑定，供后续确定性研究复算。
    op.create_table(
        "market_snapshot_inputs",
        sa.Column(
            "snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("market_snapshots.id"),
            primary_key=True,
        ),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("candle_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "candle_count BETWEEN 1 AND 800",
            name="ck_market_snapshot_inputs_candle_count",
        ),
        sa.CheckConstraint(
            "payload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_market_snapshot_inputs_payload_sha256",
        ),
    )
    op.create_index(
        "ix_market_snapshot_inputs_symbol",
        "market_snapshot_inputs",
        ["symbol"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_market_snapshot_input_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'market snapshot inputs are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_market_snapshot_inputs_immutable
        BEFORE UPDATE OR DELETE ON market_snapshot_inputs
        FOR EACH ROW EXECUTE FUNCTION prevent_market_snapshot_input_mutation();
        """
    )


# 前向迁移明确拒绝回退，避免删除已保存的研究和审计历史。
def downgrade() -> None:
    raise NotImplementedError("冻结市场输入迁移不可逆，禁止删除审计记录")
