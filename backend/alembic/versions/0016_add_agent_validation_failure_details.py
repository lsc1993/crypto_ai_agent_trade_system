# 保存有界模型校验诊断：次数、问题数、字段路径与错误类别。
# 列可空以兼容旧运行；仅保存安全摘要，不添加模型原文存储。
"""Persist bounded model-format validation metadata for agent research runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_agent_validation_failure"
down_revision: str | None = "0015_research_symbols"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序应用本版本的数据库变化；以下约束与触发器属于历史定义。
def upgrade() -> None:
    op.add_column(
        "agent_analysis_runs",
        sa.Column("model_validation_attempt_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_analysis_runs",
        sa.Column("model_validation_issue_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_analysis_runs",
        sa.Column("model_validation_field_paths", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "agent_analysis_runs",
        sa.Column("model_validation_error_categories", postgresql.JSONB(), nullable=True),
    )


# 前向迁移明确拒绝回退，避免删除已保存的研究和审计历史。
def downgrade() -> None:
    raise NotImplementedError("模型校验审计记录不可逆，禁止删除历史数据")
