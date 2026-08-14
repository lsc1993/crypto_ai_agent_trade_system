"""Add nullable frozen market metrics to immutable Agent reports."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_agent_report_metrics"
down_revision: str | None = "0010_agent_report_narrative"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_report_details",
        sa.Column("market_metrics", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    raise NotImplementedError("冻结市场指标迁移不可逆，禁止删除审计记录")
