# 给综合报告增加可空的政策、资金费率及 ETF 专题分析。
# 旧报告无需回写专题，新增 JSONB 列仍受报告详情不可变规则约束。
"""Add nullable, immutable policy/funding/ETF topics to existing reports."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_report_factors"
down_revision: str | None = "0013_harness_event_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序应用本版本的数据库变化；以下约束与触发器属于历史定义。
def upgrade() -> None:
    op.add_column(
        "agent_report_details", sa.Column("factor_analysis", postgresql.JSONB(), nullable=True)
    )


# 前向迁移明确拒绝回退，避免删除已保存的研究和审计历史。
def downgrade() -> None:
    raise NotImplementedError("专题证据分析不可逆，禁止删除审计记录")
