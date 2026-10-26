# 建立不可变 Harness 运行、生命周期事件及策略评估审计。
# 研究运行写入通过数据库触发器同步追加关联终态，避免报告和审计分别提交。
"""Create forward-only immutable Harness audit records."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_harness_audit"
down_revision: str | None = "0011_agent_report_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序应用本版本的数据库变化；以下约束与触发器属于历史定义。
def upgrade() -> None:
    # 保存运行准入上下文与策略指纹，不保存原始新闻或模型载荷。
    op.create_table(
        "harness_runs",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_kind", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("policy_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initiator_kind", sa.String(length=32), nullable=False),
        sa.Column("request_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "run_kind = 'market_research'",
            name="ck_harness_runs_run_kind",
        ),
        sa.CheckConstraint(
            "policy_version IN ('market_research_v1', 'unregistered')",
            name="ck_harness_runs_policy_version",
        ),
        sa.CheckConstraint(
            "policy_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_harness_runs_policy_sha256",
        ),
        sa.CheckConstraint(
            "symbol IN ('BTCUSDT', 'ETHUSDT')",
            name="ck_harness_runs_symbol",
        ),
        sa.CheckConstraint(
            "initiator_kind = 'manual_api'",
            name="ck_harness_runs_initiator_kind",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_harness_runs_request_sha256",
        ),
    )
    op.create_index(
        "ix_harness_runs_kind_symbol_requested",
        "harness_runs",
        ["run_kind", "symbol", sa.text("requested_at DESC"), "run_id"],
    )

    # 事件按运行和序号唯一，数据库终态触发器与报告保存处于同一事务。
    op.create_table(
        "harness_run_events",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_kind", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["harness_runs.run_id"],
            name="fk_harness_run_events_run",
        ),
        sa.PrimaryKeyConstraint(
            "run_id",
            "sequence",
            name="pk_harness_run_events",
        ),
        sa.CheckConstraint(
            "sequence BETWEEN 0 AND 3",
            name="ck_harness_run_events_sequence",
        ),
        sa.CheckConstraint(
            "event_kind IN ("
            "'requested', 'policy_authorized', 'policy_rejected', 'workflow_started', "
            "'workflow_completed', 'workflow_degraded', 'workflow_failed'"
            ")",
            name="ck_harness_run_events_kind",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0",
            name="ck_harness_run_events_duration",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z0-9_]+$'",
            name="ck_harness_run_events_error_code",
        ),
    )
    op.create_index(
        "ix_harness_events_run_occurred",
        "harness_run_events",
        ["run_id", "occurred_at", "sequence"],
    )
    op.create_index(
        "ix_harness_events_kind_occurred",
        "harness_run_events",
        ["event_kind", sa.text("occurred_at DESC"), "run_id"],
    )

    # 策略评估单独保存安全结论及指纹，拒绝原因可关联运行。
    op.create_table(
        "harness_evaluations",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("evaluator_name", sa.String(length=64), nullable=False),
        sa.Column("evaluator_version", sa.String(length=16), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["harness_runs.run_id"],
            name="fk_harness_evaluations_run",
        ),
        sa.PrimaryKeyConstraint(
            "run_id",
            "sequence",
            name="pk_harness_evaluations",
        ),
        sa.CheckConstraint(
            "sequence >= 0",
            name="ck_harness_evaluations_sequence",
        ),
        sa.CheckConstraint(
            "evaluator_name = 'policy_allowlist'",
            name="ck_harness_evaluations_name",
        ),
        sa.CheckConstraint(
            "evaluator_version = '1'",
            name="ck_harness_evaluations_version",
        ),
        sa.CheckConstraint(
            "decision IN ('passed', 'rejected')",
            name="ck_harness_evaluations_decision",
        ),
        sa.CheckConstraint(
            "(decision = 'passed' AND reason_code IS NULL) OR "
            "(decision = 'rejected' AND reason_code ~ '^[a-z0-9_]+$')",
            name="ck_harness_evaluations_reason",
        ),
    )
    op.create_index(
        "ix_harness_evaluations_run_evaluated",
        "harness_evaluations",
        ["run_id", "evaluated_at", "sequence"],
    )

    _install_harness_immutable_trigger(
        table_name="harness_runs",
        function_name="prevent_harness_run_mutation",
        trigger_name="trg_harness_runs_immutable",
    )
    _install_harness_immutable_trigger(
        table_name="harness_run_events",
        function_name="prevent_harness_run_event_mutation",
        trigger_name="trg_harness_run_events_immutable",
    )
    _install_harness_immutable_trigger(
        table_name="harness_evaluations",
        function_name="prevent_harness_evaluation_mutation",
        trigger_name="trg_harness_evaluations_immutable",
    )
    _install_agent_terminal_event_trigger()


# 保护运行、事件及评估记录；调用方只能追加，不可更改历史审计。
def _install_harness_immutable_trigger(
    *,
    table_name: str,
    function_name: str,
    trigger_name: str,
) -> None:
    op.execute(
        f"""
        CREATE FUNCTION {function_name}() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'analysis records are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {trigger_name}
        BEFORE UPDATE OR DELETE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION {function_name}();
        """
    )


# 在研究运行插入的同一数据库事务内追加结束事件，并校验已开始的关联运行。
def _install_agent_terminal_event_trigger() -> None:
    op.execute(
        """
        CREATE FUNCTION append_harness_agent_terminal_event() RETURNS trigger AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM harness_runs WHERE run_id = NEW.analysis_id
          ) THEN
            RETURN NEW;
          END IF;

          INSERT INTO harness_run_events (
            run_id,
            sequence,
            event_kind,
            occurred_at,
            duration_ms,
            error_code,
            details
          ) SELECT
            NEW.analysis_id,
            3,
            CASE NEW.status
              WHEN 'completed' THEN 'workflow_completed'
              WHEN 'degraded' THEN 'workflow_degraded'
            END,
            NEW.completed_at,
            GREATEST(
              0,
              FLOOR(
                EXTRACT(
                  EPOCH FROM (NEW.completed_at - harness_runs.requested_at)
                ) * 1000
              )::integer
            ),
            NEW.error_code,
            '{}'::jsonb
          FROM harness_runs
          WHERE harness_runs.run_id = NEW.analysis_id;

          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        SET search_path FROM CURRENT;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_runs_harness_terminal
        AFTER INSERT ON agent_analysis_runs
        FOR EACH ROW EXECUTE FUNCTION append_harness_agent_terminal_event();
        """
    )


# 前向迁移明确拒绝回退，避免删除已保存的研究和审计历史。
def downgrade() -> None:
    raise NotImplementedError("Harness 审计迁移不可逆，禁止删除审计记录")
