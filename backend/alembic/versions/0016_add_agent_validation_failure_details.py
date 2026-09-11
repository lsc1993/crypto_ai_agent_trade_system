"""Persist bounded model-format validation metadata for agent research runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_agent_validation_failure"
down_revision: str | None = "0015_research_symbols"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def downgrade() -> None:
    raise NotImplementedError("模型校验审计记录不可逆，禁止删除历史数据")
