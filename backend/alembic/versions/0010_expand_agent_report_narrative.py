"""Add nullable dual-horizon narrative sections to immutable Agent reports."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_agent_report_narrative"
down_revision: str | None = "0009_market_snapshot_inputs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def downgrade() -> None:
    raise NotImplementedError("双层研究叙事迁移不可逆，禁止删除审计记录")
