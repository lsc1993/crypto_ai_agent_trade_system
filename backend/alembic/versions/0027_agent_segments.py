# 建立 T07 执行片段 schema：唯一 Harness run、图 namespace、owner/epoch 租约与结果文档。
# 同时扩展既有 harness_runs 约束以允许 interactive_planning；不改写旧审计/报告/任务历史。
# 片段身份不可变且终态不可重开；downgrade 会删除租约历史，因此明确拒绝。
"""Leased interactive agent segments with atomic governance audit commits."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0027_agent_segments"
down_revision: str | None = "0026_agent_interactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 既有两类运行保持原序列化值；新增交互式规划类别使用独立策略版本。
    op.drop_constraint("ck_harness_runs_run_kind", "harness_runs", type_="check")
    op.create_check_constraint(
        "ck_harness_runs_run_kind",
        "harness_runs",
        "run_kind IN ('market_research', 'technical_research', 'interactive_planning')",
    )
    op.drop_constraint("ck_harness_runs_policy_version", "harness_runs", type_="check")
    op.create_check_constraint(
        "ck_harness_runs_policy_version",
        "harness_runs",
        "policy_version IN ('market_research_v1', 'technical_research_v1', "
        "'interactive_planning_v1', 'unregistered')",
    )

    op.create_table(
        "agent_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_segments_run"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("owner", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("graph_namespace", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("outcome_kind", sa.String(16)),
        sa.Column(
            "outcome",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("safe_reason", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("revision >= 1", name="ck_agent_segment_revision"),
        sa.CheckConstraint("lease_epoch >= 0", name="ck_agent_segment_lease_epoch"),
        sa.CheckConstraint(
            "status IN ('running','waiting_input','waiting_approval','completed',"
            "'degraded','failed','cancelled','interrupted')",
            name="ck_agent_segment_status",
        ),
        sa.CheckConstraint(
            "outcome_kind IS NULL OR outcome_kind IN "
            "('wait_input','wait_approval','completed','degraded','failed','cancelled')",
            name="ck_agent_segment_outcome_kind",
        ),
        sa.CheckConstraint(
            "graph_namespace ~ '^ir:[0-9a-f-]{36}:[0-9]+:[0-9a-f-]{36}$'",
            name="ck_agent_segment_namespace",
        ),
        sa.CheckConstraint(
            "safe_reason IS NULL OR safe_reason ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_agent_segment_reason",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND finished_at IS NULL AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'running' AND finished_at IS NOT NULL AND lease_expires_at IS NULL)",
            name="ck_agent_segment_shape",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(outcome) = 'object'",
            name="ck_agent_segment_outcome",
        ),
        sa.UniqueConstraint("graph_namespace", name="uq_agent_segment_namespace"),
    )
    op.create_index(
        "ix_agent_segments_run_started",
        "agent_segments",
        ["run_id", "started_at"],
    )
    op.create_index(
        "ux_agent_segments_active",
        "agent_segments",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_agent_segments_status_lease",
        "agent_segments",
        ["status", "lease_expires_at"],
    )

    # 身份/租约代次不可改写；running 只允许心跳字段更新，结束必须同时释放租约。
    op.execute(
        """
        CREATE FUNCTION validate_agent_segment_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.run_id IS DISTINCT FROM OLD.run_id
               OR NEW.revision IS DISTINCT FROM OLD.revision
               OR NEW.owner IS DISTINCT FROM OLD.owner
               OR NEW.lease_epoch IS DISTINCT FROM OLD.lease_epoch
               OR NEW.graph_namespace IS DISTINCT FROM OLD.graph_namespace
               OR NEW.started_at IS DISTINCT FROM OLD.started_at THEN
                RAISE EXCEPTION 'agent segment identity is immutable';
            END IF;
            IF OLD.status <> 'running' THEN
                RAISE EXCEPTION 'agent segment is terminal';
            END IF;
            IF NEW.status = 'running' THEN
                IF NEW.finished_at IS NOT NULL OR NEW.lease_expires_at IS NULL
                   OR NEW.outcome_kind IS NOT NULL OR NEW.safe_reason IS NOT NULL
                   OR NEW.outcome <> '{}'::jsonb THEN
                    RAISE EXCEPTION 'agent segment heartbeat shape is invalid';
                END IF;
            ELSE
                IF NEW.finished_at IS NULL OR NEW.lease_expires_at IS NOT NULL THEN
                    RAISE EXCEPTION 'agent segment finish must release lease';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_segments_validate_update
        BEFORE UPDATE ON agent_segments
        FOR EACH ROW EXECUTE FUNCTION validate_agent_segment_update();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_agent_segment_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'agent segment history is immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_segments_no_delete
        BEFORE DELETE ON agent_segments
        FOR EACH ROW EXECUTE FUNCTION reject_agent_segment_delete();
        """
    )


# 前向迁移拒绝回退，避免删除片段租约、审计关联或完成历史。
def downgrade() -> None:
    raise NotImplementedError("执行片段与审计关联不可逆，禁止删除历史数据")
