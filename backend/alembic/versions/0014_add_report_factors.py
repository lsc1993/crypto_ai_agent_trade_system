"""Add nullable, immutable policy/funding/ETF topics to existing reports."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_report_factors"
down_revision: str | None = "0013_harness_event_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_report_details", sa.Column("factor_analysis", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    raise NotImplementedError("专题证据分析不可逆，禁止删除审计记录")
