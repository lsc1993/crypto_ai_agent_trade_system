# 建立 T06 人工审核 schema：交互待办、反馈、用户消息与取消请求幂等映射。
# 同时为 agent_runs 增加 running 取消标记；不修改已有任务/尝试/审计历史。
# 触发器保证待办材料不可变、状态迁移单步、反馈/取消请求不可改写、消息正文不可篡改。
# 0026 尚未应用到业务库；downgrade 会删除审核历史，因此明确拒绝。
"""Human review interactions, continuous messages and cancellation consistency."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0026_agent_interactions"
down_revision: str | None = "0025_agent_attempt_shape_fix"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # running 任务收到取消时保留 owner，由 worker 在各安全边界检查该标记。
    op.add_column(
        "agent_runs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_agent_runs_cancel_requested",
        "agent_runs",
        ["cancel_requested_at"],
        postgresql_where=sa.text("cancel_requested_at IS NOT NULL"),
    )

    op.create_table(
        "agent_interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_interactions_run"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("material_hash", sa.String(64), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("diffs", postgresql.JSONB(), nullable=False),
        sa.Column("material_refs", postgresql.JSONB(), nullable=False),
        sa.Column("safe_reason", sa.String(64), nullable=False),
        sa.Column("open_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("open_request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('preparing','pending','answered','applied','expired')",
            name="ck_agent_interaction_status",
        ),
        sa.CheckConstraint(
            "action IN ('clarify','adopt_manual_plan','change_strategy','change_parameters',"
            "'expand_scope','increase_budget','adopt_revised_plan','enable_monitoring')",
            name="ck_agent_interaction_action",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_agent_interaction_revision"),
        sa.CheckConstraint("state_version >= 0", name="ck_agent_interaction_state_version"),
        sa.CheckConstraint(
            "char_length(material_hash) = 64",
            name="ck_agent_interaction_material_sha",
        ),
        sa.CheckConstraint(
            "char_length(open_request_sha256) = 64",
            name="ck_agent_interaction_open_request_sha",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_agent_interaction_expiry"),
        sa.CheckConstraint("jsonb_typeof(diffs) = 'array'", name="ck_agent_interaction_diffs"),
        sa.CheckConstraint(
            "jsonb_typeof(material_refs) = 'array'",
            name="ck_agent_interaction_material_refs",
        ),
        sa.CheckConstraint(
            "safe_reason ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_agent_interaction_reason",
        ),
        sa.CheckConstraint(
            "(status = 'preparing' AND published_at IS NULL AND responded_at IS NULL "
            "AND applied_at IS NULL AND expired_at IS NULL) OR "
            "(status = 'pending' AND published_at IS NOT NULL AND responded_at IS NULL "
            "AND applied_at IS NULL AND expired_at IS NULL) OR "
            "(status = 'answered' AND published_at IS NOT NULL AND responded_at IS NOT NULL "
            "AND applied_at IS NULL AND expired_at IS NULL) OR "
            "(status = 'applied' AND published_at IS NOT NULL AND responded_at IS NOT NULL "
            "AND applied_at IS NOT NULL AND expired_at IS NULL) OR "
            "(status = 'expired' AND expired_at IS NOT NULL AND applied_at IS NULL)",
            name="ck_agent_interaction_state_shape",
        ),
    )
    op.create_index(
        "ix_agent_interactions_workspace_run",
        "agent_interactions",
        ["workspace_id", "run_id", "created_at"],
    )
    op.create_index(
        "ux_agent_interactions_active",
        "agent_interactions",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('preparing','pending','answered')"),
    )
    op.create_unique_constraint(
        "uq_agent_interactions_open_request",
        "agent_interactions",
        ["workspace_id", "open_request_id"],
    )

    op.create_table(
        "agent_interaction_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_interaction_feedback_run"),
            nullable=False,
        ),
        sa.Column(
            "interaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "agent_interactions.id",
                name="fk_agent_interaction_feedback_interaction",
            ),
            nullable=False,
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reviewed_payload_hash", sa.String(64), nullable=False),
        sa.Column("message", sa.String(4_000)),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approve','reject','request_changes','provide_input')",
            name="ck_agent_interaction_feedback_decision",
        ),
        sa.CheckConstraint(
            "char_length(reviewed_payload_hash) = 64",
            name="ck_agent_interaction_feedback_material_sha",
        ),
        sa.CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_agent_interaction_feedback_request_sha",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(changes) = 'array'",
            name="ck_agent_interaction_feedback_changes",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "request_id",
            name="uq_agent_interaction_feedback_request",
        ),
    )
    op.create_index(
        "ix_agent_interaction_feedback_run",
        "agent_interaction_feedback",
        ["run_id", "created_at"],
    )

    op.create_table(
        "agent_user_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_user_messages_run"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("text", sa.String(4_000)),
        sa.Column("planning_ref", postgresql.JSONB()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("sequence >= 1", name="ck_agent_user_message_sequence"),
        sa.CheckConstraint("kind IN ('text','planning_ref')", name="ck_agent_user_message_kind"),
        sa.CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_agent_user_message_request_sha",
        ),
        sa.CheckConstraint(
            "(kind = 'text' AND text IS NOT NULL AND planning_ref IS NULL) OR "
            "(kind = 'planning_ref' AND text IS NULL AND planning_ref IS NOT NULL)",
            name="ck_agent_user_message_content",
        ),
        sa.CheckConstraint(
            "planning_ref IS NULL OR jsonb_typeof(planning_ref) = 'object'",
            name="ck_agent_user_message_planning_ref",
        ),
        sa.CheckConstraint(
            "applied_at IS NULL OR applied_at >= received_at",
            name="ck_agent_user_message_applied_at",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "request_id",
            name="uq_agent_user_message_request",
        ),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_user_message_sequence"),
    )
    op.create_index("ix_agent_user_messages_run", "agent_user_messages", ["run_id", "sequence"])

    op.create_table(
        "agent_run_cancel_requests",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_run_cancel_requests_run"),
            nullable=False,
        ),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_agent_run_cancel_request_sha",
        ),
    )
    op.create_index(
        "ix_agent_run_cancel_requests_run",
        "agent_run_cancel_requests",
        ["run_id", "created_at"],
    )

    # 待办材料不可变；状态只能单步推进，且每次推进必须恰好增加一个状态号。
    op.execute(
        """
        CREATE FUNCTION validate_agent_interaction_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.id IS DISTINCT FROM NEW.id
               OR OLD.workspace_id IS DISTINCT FROM NEW.workspace_id
               OR OLD.run_id IS DISTINCT FROM NEW.run_id
               OR OLD.revision IS DISTINCT FROM NEW.revision
               OR OLD.action IS DISTINCT FROM NEW.action
               OR OLD.material_hash IS DISTINCT FROM NEW.material_hash
               OR OLD.expires_at IS DISTINCT FROM NEW.expires_at
               OR OLD.diffs IS DISTINCT FROM NEW.diffs
               OR OLD.material_refs IS DISTINCT FROM NEW.material_refs
               OR OLD.safe_reason IS DISTINCT FROM NEW.safe_reason
               OR OLD.open_request_id IS DISTINCT FROM NEW.open_request_id
               OR OLD.open_request_sha256 IS DISTINCT FROM NEW.open_request_sha256
               OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                RAISE EXCEPTION 'agent interaction material is immutable';
            END IF;
            IF OLD.status IN ('applied','expired') THEN
                RAISE EXCEPTION 'agent interaction is terminal';
            END IF;
            IF NEW.status = OLD.status THEN
                RAISE EXCEPTION 'agent interaction update must change status';
            END IF;
            IF NOT (
                (OLD.status = 'preparing' AND NEW.status IN ('pending','expired')) OR
                (OLD.status = 'pending' AND NEW.status IN ('answered','expired')) OR
                (OLD.status = 'answered' AND NEW.status IN ('applied','expired'))
            ) THEN
                RAISE EXCEPTION 'invalid agent interaction transition';
            END IF;
            IF NEW.state_version <> OLD.state_version + 1 THEN
                RAISE EXCEPTION 'agent interaction state version must advance by one';
            END IF;

            -- 已写入的阶段时间不可改写或清空；否则可在合法迁移中擦除发布/响应历史。
            IF OLD.published_at IS NOT NULL
               AND NEW.published_at IS DISTINCT FROM OLD.published_at THEN
                RAISE EXCEPTION 'agent interaction stage time is immutable';
            END IF;
            IF OLD.responded_at IS NOT NULL
               AND NEW.responded_at IS DISTINCT FROM OLD.responded_at THEN
                RAISE EXCEPTION 'agent interaction stage time is immutable';
            END IF;
            IF OLD.applied_at IS NOT NULL
               AND NEW.applied_at IS DISTINCT FROM OLD.applied_at THEN
                RAISE EXCEPTION 'agent interaction stage time is immutable';
            END IF;
            IF OLD.expired_at IS NOT NULL
               AND NEW.expired_at IS DISTINCT FROM OLD.expired_at THEN
                RAISE EXCEPTION 'agent interaction stage time is immutable';
            END IF;

            -- 每个合法迁移只允许首次写入对应阶段时间，不能提前写未来阶段，
            -- 也不能在过期时凭空补出未发生的发布/响应事实。
            IF OLD.status = 'preparing' AND NEW.status = 'pending' THEN
                IF NEW.published_at IS NULL
                   OR NEW.responded_at IS NOT NULL
                   OR NEW.applied_at IS NOT NULL
                   OR NEW.expired_at IS NOT NULL THEN
                    RAISE EXCEPTION 'agent interaction stage time does not match transition';
                END IF;
            ELSIF OLD.status = 'pending' AND NEW.status = 'answered' THEN
                IF NEW.published_at IS DISTINCT FROM OLD.published_at
                   OR NEW.published_at IS NULL
                   OR NEW.responded_at IS NULL
                   OR NEW.applied_at IS NOT NULL
                   OR NEW.expired_at IS NOT NULL THEN
                    RAISE EXCEPTION 'agent interaction stage time does not match transition';
                END IF;
            ELSIF OLD.status = 'answered' AND NEW.status = 'applied' THEN
                IF NEW.published_at IS DISTINCT FROM OLD.published_at
                   OR NEW.responded_at IS DISTINCT FROM OLD.responded_at
                   OR NEW.applied_at IS NULL
                   OR NEW.expired_at IS NOT NULL THEN
                    RAISE EXCEPTION 'agent interaction stage time does not match transition';
                END IF;
            ELSIF NEW.status = 'expired' THEN
                IF NEW.published_at IS DISTINCT FROM OLD.published_at
                   OR NEW.responded_at IS DISTINCT FROM OLD.responded_at
                   OR NEW.applied_at IS DISTINCT FROM OLD.applied_at
                   OR NEW.expired_at IS NULL THEN
                    RAISE EXCEPTION 'agent interaction stage time does not match transition';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_interactions_validate_update
        BEFORE UPDATE ON agent_interactions
        FOR EACH ROW EXECUTE FUNCTION validate_agent_interaction_update();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_agent_interaction_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'agent interaction history is immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_interactions_no_delete
        BEFORE DELETE ON agent_interactions
        FOR EACH ROW EXECUTE FUNCTION reject_agent_interaction_delete();
        """
    )

    # 反馈和取消映射是追加审计事实，不允许改写或删除；反馈是否已应用由待办状态表达。
    op.execute(
        """
        CREATE FUNCTION reject_agent_review_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'agent review history is immutable';
        END;
        $$;
        """
    )
    for table in ("agent_interaction_feedback", "agent_run_cancel_requests"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_agent_review_history_mutation();
            """
        )

    # 消息正文/序号/请求键不可改；只允许 worker 把 applied_at 从空推进一次。
    op.execute(
        """
        CREATE FUNCTION validate_agent_message_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF (to_jsonb(OLD) - 'applied_at') IS DISTINCT FROM (to_jsonb(NEW) - 'applied_at') THEN
                RAISE EXCEPTION 'agent message content is immutable';
            END IF;
            IF OLD.applied_at IS NULL THEN
                IF NEW.applied_at IS NULL THEN
                    RAISE EXCEPTION 'agent message update must apply';
                END IF;
            ELSIF NEW.applied_at IS DISTINCT FROM OLD.applied_at THEN
                RAISE EXCEPTION 'agent message applied watermark is immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_user_messages_validate_update
        BEFORE UPDATE ON agent_user_messages
        FOR EACH ROW EXECUTE FUNCTION validate_agent_message_update();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_user_messages_no_delete
        BEFORE DELETE ON agent_user_messages
        FOR EACH ROW EXECUTE FUNCTION reject_agent_review_history_mutation();
        """
    )


# 前向迁移拒绝回退，避免删除审核、消息和取消历史。
def downgrade() -> None:
    raise NotImplementedError("Agent 人工审核迁移不可逆，禁止删除审核与消息历史")
