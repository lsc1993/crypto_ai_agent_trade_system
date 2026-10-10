"""Durable manually requested technical research queue."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018_technical_report_runs"
down_revision: str | None = "0017_technical_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "technical_report_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.CheckConstraint("id = 1", name="ck_technical_queue_singleton"),
    )
    op.execute("INSERT INTO technical_report_queue (id) VALUES (1)")
    op.create_table(
        "technical_report_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), unique=True, nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("owner", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("technical_reports.id")
        ),
        sa.Column("error_code", sa.String(32)),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','degraded','failed')",
            name="ck_technical_run_status",
        ),
        sa.CheckConstraint(
            "phase IN ('queued','collecting','analyzing','validating',"
            "'composing','saving','finished')",
            name="ck_technical_run_phase",
        ),
        sa.CheckConstraint(
            "(status IN ('completed','degraded','failed')) = "
            "(finished_at IS NOT NULL AND phase = 'finished')",
            name="ck_technical_run_terminal",
        ),
        sa.CheckConstraint(
            "(status IN ('completed','degraded')) = (report_id IS NOT NULL)",
            name="ck_technical_run_report",
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)", name="ck_technical_run_error"
        ),
        sa.CheckConstraint(
            "(status = 'running') = (owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_technical_run_lease",
        ),
    )
    op.create_index(
        "uq_technical_run_active_symbol",
        "technical_report_runs",
        ["symbol"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
    )
    op.create_index("ix_technical_run_created", "technical_report_runs", ["created_at", "id"])
    op.create_table(
        "technical_report_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("technical_report_runs.id"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    raise NotImplementedError("技术研究任务和审计历史禁止删除")
