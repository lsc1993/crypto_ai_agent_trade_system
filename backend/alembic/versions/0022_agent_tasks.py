# 建立 C4 Agent 持久任务 schema：线程、任务、不可变修订、请求幂等、安全事件、
# 证据/产物前向表、队列单例与 owner/租约字段。迁移只新增表/约束/触发器，不改写旧报告或审计。
# 修订、请求、事件、证据与产物行禁止 UPDATE/DELETE；任务终态禁止重新打开，任务/线程禁止删除。
# 0022 尚未应用到业务库；回退会删除任务历史，因此明确拒绝。
"""Persistent agent tasks, revisions, request replay and safe events."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022_agent_tasks"
down_revision: str | None = "0021_planning_inputs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按修订链顺序创建任务、历史与事件表；所有外键只指向本迁移内已创建的表。
def upgrade() -> None:
    op.create_table(
        "agent_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_threads_workspace_created",
        "agent_threads",
        ["workspace_id", "created_at"],
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "thread_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_threads.id", name="fk_agent_runs_thread"),
            nullable=False,
        ),
        sa.Column(
            "parent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_runs_parent"),
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("received_message_seq", sa.Integer(), nullable=False),
        sa.Column("applied_message_seq", sa.Integer(), nullable=False),
        sa.Column("current_interaction_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "result_refs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("result_quality", sa.String(16)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("owner", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued','running','waiting_input','waiting_approval',"
            "'completed','degraded','failed','cancelled','expired')",
            name="ck_agent_run_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_agent_run_revision"),
        sa.CheckConstraint("state_version >= 0", name="ck_agent_run_state_version"),
        sa.CheckConstraint(
            "received_message_seq >= 0 AND applied_message_seq >= 0 AND "
            "applied_message_seq <= received_message_seq",
            name="ck_agent_run_message_watermarks",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'running' AND owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_agent_run_lease",
        ),
        sa.CheckConstraint("lease_epoch >= 0", name="ck_agent_run_lease_epoch"),
        sa.CheckConstraint(
            "(status IN ('completed','degraded','failed','cancelled','expired')) = "
            "(finished_at IS NOT NULL)",
            name="ck_agent_run_terminal",
        ),
        sa.CheckConstraint(
            "parent_run_id IS NULL OR parent_run_id <> id",
            name="ck_agent_run_parent",
        ),
        sa.CheckConstraint(
            "result_quality IS NULL OR result_quality IN ('complete','degraded','unknown')",
            name="ck_agent_run_result_quality",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result_refs) = 'array'",
            name="ck_agent_run_result_refs",
        ),
    )
    op.create_index("ix_agent_runs_workspace_created", "agent_runs", ["workspace_id", "created_at"])
    op.create_index("ix_agent_runs_thread", "agent_runs", ["thread_id", "created_at"])
    op.create_index(
        "ix_agent_runs_runnable",
        "agent_runs",
        ["status"],
        postgresql_where=sa.text("status IN ('queued','running')"),
    )

    op.create_table(
        "agent_run_revisions",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_run_revisions_run"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_agent_run_revision_number"),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_agent_run_revision_sha"),
    )

    op.create_table(
        "agent_run_requests",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_run_requests_run"),
            nullable=False,
        ),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_agent_run_requests_run"),
        sa.CheckConstraint("char_length(request_sha256) = 64", name="ck_agent_run_request_sha"),
    )

    op.create_table(
        "agent_run_events",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_run_events_run"),
            primary_key=True,
        ),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_agent_run_event_sequence"),
        sa.CheckConstraint("revision >= 1", name="ck_agent_run_event_revision"),
        sa.CheckConstraint("projection_version >= 1", name="ck_agent_run_event_projection"),
    )

    op.create_table(
        "agent_evidence_epochs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_evidence_epochs_run"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("analysis_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_agent_evidence_epoch_revision"),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_agent_evidence_epoch_sha"),
    )
    op.create_index(
        "ix_agent_evidence_epochs_run_revision",
        "agent_evidence_epochs",
        ["run_id", "revision", "created_at"],
    )

    op.create_table(
        "agent_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_artifacts_run"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("quality", sa.String(16)),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column(
            "parent_artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_artifacts.id", name="fk_agent_artifacts_parent"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_agent_artifact_revision"),
        sa.CheckConstraint("char_length(sha256) = 64", name="ck_agent_artifact_sha"),
    )
    op.create_index(
        "ix_agent_artifacts_run_revision",
        "agent_artifacts",
        ["run_id", "revision", "created_at"],
    )

    # 单例队列行是容量检查与领取的共同锁锚点；没有该行时仓储拒绝继续。
    op.create_table(
        "agent_run_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.CheckConstraint("id = 1", name="ck_agent_run_queue_singleton"),
    )
    op.execute("INSERT INTO agent_run_queue (id) VALUES (1)")

    # 历史事实表禁止 UPDATE/DELETE；schema 回退通过显式拒绝的 downgrade 管理。
    op.execute(
        """
        CREATE FUNCTION reject_agent_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'agent run history is immutable';
        END;
        $$;
        """
    )
    for table in (
        "agent_run_revisions",
        "agent_run_requests",
        "agent_run_events",
        "agent_evidence_epochs",
        "agent_artifacts",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_agent_history_mutation();
            """
        )

    # 任务终态不可重新打开；任何终态后的状态/结果写入都视为不变量破坏。
    op.execute(
        """
        CREATE FUNCTION reject_agent_terminal_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status IN ('completed','degraded','failed','cancelled','expired') THEN
                RAISE EXCEPTION 'agent run is terminal';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_runs_terminal_immutable
        BEFORE UPDATE ON agent_runs
        FOR EACH ROW EXECUTE FUNCTION reject_agent_terminal_mutation();
        """
    )

    # 任务和会话是审计关联根；保留历史，不提供删除入口。
    op.execute(
        """
        CREATE FUNCTION reject_agent_run_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'agent run history is immutable';
        END;
        $$;
        """
    )
    for table in ("agent_runs", "agent_threads"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_agent_run_delete();
            """
        )


# 前向迁移拒绝回退，避免删除任务、事件和证据历史。
def downgrade() -> None:
    raise NotImplementedError("Agent 任务迁移不可逆，禁止删除任务历史")
