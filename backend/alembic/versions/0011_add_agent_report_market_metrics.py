# 给 Agent 详情增加可空的冻结市场指标。
# 使用 JSONB 保留结构化事实，历史报告不被补写或重新解释。
"""Add nullable frozen market metrics to immutable Agent reports."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_agent_report_metrics"
down_revision: str | None = "0010_agent_report_narrative"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序应用本版本的数据库变化；以下约束与触发器属于历史定义。
def upgrade() -> None:
    op.add_column(
        "agent_report_details",
        sa.Column("market_metrics", postgresql.JSONB(), nullable=True),
    )


# 前向迁移明确拒绝回退，避免删除已保存的研究和审计历史。
def downgrade() -> None:
    raise NotImplementedError("冻结市场指标迁移不可逆，禁止删除审计记录")
