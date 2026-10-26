# 给 Agent 详情增加可空的双周期叙事字段并扩展周期检查。
# 旧记录保留原貌，可空列允许读取历史报告而不伪造新增内容。
"""Add nullable dual-horizon narrative sections to immutable Agent reports."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_agent_report_narrative"
down_revision: str | None = "0009_market_snapshot_inputs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序应用本版本的数据库变化；以下约束与触发器属于历史定义。
def upgrade() -> None:
    op.drop_constraint(
        "ck_agent_report_details_horizon",
        "agent_report_details",
        type_="check",
    )
    op.create_check_constraint(
        "ck_agent_report_details_horizon",
        "agent_report_details",
        "horizon IN ('1_to_3_days', 'dual_horizon')",
    )
    op.add_column(
        "agent_report_details",
        sa.Column("market_overview", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "agent_report_details",
        sa.Column("short_term_view", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "agent_report_details",
        sa.Column("long_term_view", postgresql.JSONB(), nullable=True),
    )


# 前向迁移明确拒绝回退，避免删除已保存的研究和审计历史。
def downgrade() -> None:
    raise NotImplementedError("双层研究叙事迁移不可逆，禁止删除审计记录")
