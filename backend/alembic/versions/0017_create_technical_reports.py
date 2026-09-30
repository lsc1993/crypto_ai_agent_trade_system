"""Add independent immutable technical reports and bounded Harness policy."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_technical_reports"
down_revision: str | None = "0016_agent_validation_failure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_harness_runs_run_kind", "harness_runs", type_="check")
    op.create_check_constraint(
        "ck_harness_runs_run_kind",
        "harness_runs",
        "run_kind IN ('market_research', 'technical_research')",
    )
    op.drop_constraint("ck_harness_runs_policy_version", "harness_runs", type_="check")
    op.create_check_constraint(
        "ck_harness_runs_policy_version",
        "harness_runs",
        "policy_version IN ('market_research_v1', 'technical_research_v1', 'unregistered')",
    )
    op.create_table(
        "technical_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=False),
        sa.Column("frozen_evidence", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["harness_runs.run_id"], name="fk_technical_reports_run"
        ),
        sa.CheckConstraint(
            "status IN ('completed','degraded')", name="ck_technical_reports_status"
        ),
        sa.CheckConstraint("evidence_sha256 ~ '^[0-9a-f]{64}$'", name="ck_technical_reports_sha"),
    )
    op.create_index(
        "ix_technical_reports_symbol_created", "technical_reports", ["symbol", "created_at"]
    )
    op.execute("""
        CREATE FUNCTION protect_technical_report() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'technical report is immutable'; END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_technical_reports_immutable
        BEFORE UPDATE OR DELETE ON technical_reports
        FOR EACH ROW EXECUTE FUNCTION protect_technical_report();
    """)
    op.execute("""
        CREATE FUNCTION append_technical_terminal() RETURNS trigger AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM harness_runs r JOIN harness_run_events e ON e.run_id = r.run_id
            WHERE r.run_id = NEW.analysis_id AND r.run_kind = 'technical_research'
              AND r.symbol = NEW.symbol AND e.sequence = 2 AND e.event_kind = 'workflow_started'
          ) THEN RAISE EXCEPTION 'technical run must be authorized and started'; END IF;
          INSERT INTO harness_run_events
            (run_id, sequence, event_kind, occurred_at, duration_ms, error_code, details)
          SELECT NEW.analysis_id, 3,
            CASE WHEN NEW.status = 'completed' THEN 'workflow_completed'
              ELSE 'workflow_degraded' END,
            NEW.created_at,
            GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (NEW.created_at - requested_at)) * 1000))::integer,
            NULL, '{}'::jsonb
          FROM harness_runs WHERE run_id = NEW.analysis_id;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SET search_path FROM CURRENT;
    """)
    op.execute("""
        CREATE TRIGGER trg_technical_reports_terminal
        AFTER INSERT ON technical_reports
        FOR EACH ROW EXECUTE FUNCTION append_technical_terminal();
    """)


def downgrade() -> None:
    raise NotImplementedError("技术报告与审计不可逆，禁止删除历史数据")
