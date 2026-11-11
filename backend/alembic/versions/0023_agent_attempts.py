# 建立 C5 步骤账本 schema：逻辑步骤、独立实际尝试、追加预算授权与 meter 预留。
# 迁移只新增表和约束/触发器，不改写旧任务、事件、证据、报告或审计记录。
# 步骤/尝试/授权/预留均为审计历史：禁止删除；尝试与预留只允许声明的状态迁移。
# 0023 尚未应用到业务库；回退会删除预算与调用历史，因此明确拒绝。
"""Persistent agent attempt ledger, budget authorizations and meter reservations."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023_agent_attempts"
down_revision: str | None = "0022_agent_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 按依赖顺序创建步骤 -> 尝试 -> 授权 -> meter 预留；外键只指向已存在表。
def upgrade() -> None:
    op.create_table(
        "agent_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_steps_run"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action_sequence", sa.Integer(), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result_ref", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "revision",
            "action_sequence",
            name="uq_agent_steps_run_revision_sequence",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_agent_step_revision"),
        sa.CheckConstraint("action_sequence >= 1", name="ck_agent_step_action_sequence"),
        sa.CheckConstraint("char_length(input_sha256) = 64", name="ck_agent_step_input_sha"),
        sa.CheckConstraint(
            "category IN ('model','tool','transport')",
            name="ck_agent_step_category",
        ),
        sa.CheckConstraint(
            "status IN ('prepared','in_flight','succeeded','failed','unknown')",
            name="ck_agent_step_status",
        ),
        sa.CheckConstraint(
            "result_ref IS NULL OR jsonb_typeof(result_ref) = 'object'",
            name="ck_agent_step_result_ref",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded' AND result_ref IS NOT NULL) OR "
            "(status <> 'succeeded' AND result_ref IS NULL)",
            name="ck_agent_step_result_status",
        ),
    )
    op.create_index("ix_agent_steps_run_status", "agent_steps", ["run_id", "status"])

    op.create_table(
        "agent_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_steps.id", name="fk_agent_attempts_step"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_agent_attempts_run"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("action_sequence", sa.Integer(), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("provider_receipt", sa.String(256)),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "step_id",
            "attempt_number",
            name="uq_agent_attempts_step_number",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_agent_attempt_revision"),
        sa.CheckConstraint("action_sequence >= 1", name="ck_agent_attempt_action_sequence"),
        sa.CheckConstraint("attempt_number IN (1,2)", name="ck_agent_attempt_number"),
        sa.CheckConstraint("lease_epoch >= 0", name="ck_agent_attempt_lease_epoch"),
        sa.CheckConstraint("char_length(input_sha256) = 64", name="ck_agent_attempt_input_sha"),
        sa.CheckConstraint(
            "category IN ('model','tool','transport')",
            name="ck_agent_attempt_category",
        ),
        sa.CheckConstraint(
            "status IN ('prepared','in_flight','succeeded','failed','unknown')",
            name="ck_agent_attempt_status",
        ),
        sa.CheckConstraint(
            "(status = 'prepared' AND sent_at IS NULL AND settled_at IS NULL) OR "
            "(status = 'in_flight' AND sent_at IS NOT NULL AND settled_at IS NULL) OR "
            "(status IN ('succeeded','failed','unknown') AND sent_at IS NOT NULL "
            "AND settled_at IS NOT NULL)",
            name="ck_agent_attempt_timestamps",
        ),
    )
    op.create_index("ix_agent_attempts_run_status", "agent_attempts", ["run_id", "status"])
    op.create_index("ix_agent_attempts_run_category", "agent_attempts", ["run_id", "category"])

    op.create_table(
        "budget_authorizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_budget_authorizations_run"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("active_seconds", sa.Integer(), nullable=False),
        sa.Column("transport_calls", sa.Integer(), nullable=False),
        sa.Column("authorization_ref", postgresql.UUID(as_uuid=True)),
        sa.Column("reason", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "authorization_ref",
            name="uq_budget_authorizations_ref",
        ),
        sa.CheckConstraint("kind IN ('initial','append')", name="ck_budget_authorization_kind"),
        sa.CheckConstraint("model_calls BETWEEN 1 AND 32", name="ck_budget_authorization_model"),
        sa.CheckConstraint("tool_calls BETWEEN 1 AND 48", name="ck_budget_authorization_tool"),
        sa.CheckConstraint(
            "input_tokens BETWEEN 1 AND 393216",
            name="ck_budget_authorization_input",
        ),
        sa.CheckConstraint(
            "output_tokens BETWEEN 1 AND 131072",
            name="ck_budget_authorization_output",
        ),
        sa.CheckConstraint(
            "active_seconds BETWEEN 1 AND 1800",
            name="ck_budget_authorization_active",
        ),
        sa.CheckConstraint(
            "transport_calls BETWEEN 1 AND 256",
            name="ck_budget_authorization_transport",
        ),
        sa.CheckConstraint(
            "(kind = 'initial' AND authorization_ref IS NULL AND reason IS NULL) OR "
            "(kind = 'append' AND authorization_ref IS NOT NULL AND reason IS NOT NULL "
            "AND char_length(reason) BETWEEN 1 AND 256)",
            name="ck_budget_authorization_shape",
        ),
    )
    op.create_index(
        "ix_budget_authorizations_run",
        "budget_authorizations",
        ["run_id", "created_at"],
    )
    # 每个任务只有一个初始档；追加授权可以有多行。
    op.create_index(
        "uq_budget_authorizations_initial",
        "budget_authorizations",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'initial'"),
    )

    op.create_table(
        "budget_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_attempts.id", name="fk_budget_reservations_attempt"),
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", name="fk_budget_reservations_run"),
            nullable=False,
        ),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meter", sa.String(24), nullable=False),
        sa.Column("reserved_amount", sa.Integer(), nullable=False),
        sa.Column("actual_amount", sa.Integer()),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "meter IN ('model_calls','tool_calls','transport_calls','input_tokens',"
            "'output_tokens','activity_seconds')",
            name="ck_budget_reservation_meter",
        ),
        sa.CheckConstraint(
            "state IN ('reserved','charged','settled','unknown')",
            name="ck_budget_reservation_state",
        ),
        sa.CheckConstraint("reserved_amount >= 0", name="ck_budget_reservation_reserved"),
        sa.CheckConstraint(
            "actual_amount IS NULL OR actual_amount >= 0",
            name="ck_budget_reservation_actual",
        ),
        sa.CheckConstraint(
            "(attempt_id IS NULL AND meter = 'activity_seconds') OR "
            "(attempt_id IS NOT NULL AND meter <> 'activity_seconds')",
            name="ck_budget_reservation_attempt_meter",
        ),
    )
    op.create_index(
        "ix_budget_reservations_run_meter",
        "budget_reservations",
        ["run_id", "meter", "state"],
    )
    op.create_index(
        "uq_budget_reservations_attempt_meter",
        "budget_reservations",
        ["attempt_id", "meter"],
        unique=True,
        postgresql_where=sa.text("attempt_id IS NOT NULL"),
    )
    op.create_index(
        "uq_budget_reservations_activity_segment",
        "budget_reservations",
        ["run_id", "segment_id"],
        unique=True,
        postgresql_where=sa.text("meter = 'activity_seconds'"),
    )

    # 历史事实禁止删除；预算授权只能追加，不能回写历史授权。
    op.execute(
        """
        CREATE FUNCTION reject_agent_ledger_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'agent ledger history is immutable';
        END;
        $$;
        """
    )
    for table in (
        "agent_steps",
        "agent_attempts",
        "budget_authorizations",
        "budget_reservations",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_no_delete
            BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_agent_ledger_delete();
            """
        )

    # 逻辑步骤身份不可变；succeeded 为终态，unknown 只允许被回执结算为成功/失败。
    op.execute(
        """
        CREATE FUNCTION reject_agent_step_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.run_id IS DISTINCT FROM OLD.run_id
               OR NEW.revision IS DISTINCT FROM OLD.revision
               OR NEW.action_sequence IS DISTINCT FROM OLD.action_sequence
               OR NEW.input_sha256 IS DISTINCT FROM OLD.input_sha256
               OR NEW.category IS DISTINCT FROM OLD.category
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'agent step identity is immutable';
            END IF;
            IF OLD.status = 'succeeded' THEN
                RAISE EXCEPTION 'agent step is terminal';
            ELSIF OLD.status = 'prepared'
                  AND NEW.status NOT IN ('prepared','in_flight','failed') THEN
                RAISE EXCEPTION 'invalid agent step transition';
            ELSIF OLD.status = 'in_flight'
                  AND NEW.status NOT IN ('in_flight','succeeded','failed','unknown') THEN
                RAISE EXCEPTION 'invalid agent step transition';
            ELSIF OLD.status = 'unknown'
                  AND NEW.status NOT IN ('unknown','succeeded','failed') THEN
                RAISE EXCEPTION 'invalid agent step transition';
            ELSIF OLD.status = 'failed'
                  AND NEW.status NOT IN ('failed','prepared') THEN
                RAISE EXCEPTION 'invalid agent step transition';
            END IF;
            IF NEW.status = 'succeeded' AND NEW.result_ref IS NULL THEN
                RAISE EXCEPTION 'succeeded agent step requires result reference';
            END IF;
            IF NEW.status <> 'succeeded' AND NEW.result_ref IS NOT NULL THEN
                RAISE EXCEPTION 'non-succeeded agent step cannot carry result reference';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_steps_mutation
        BEFORE UPDATE ON agent_steps
        FOR EACH ROW EXECUTE FUNCTION reject_agent_step_mutation();
        """
    )

    # 尝试身份不可变；prepared 允许新片段接管围栏，发送后 owner/segment/epoch 冻结。
    op.execute(
        """
        CREATE FUNCTION reject_agent_attempt_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.step_id IS DISTINCT FROM OLD.step_id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.run_id IS DISTINCT FROM OLD.run_id
               OR NEW.revision IS DISTINCT FROM OLD.revision
               OR NEW.attempt_number IS DISTINCT FROM OLD.attempt_number
               OR NEW.category IS DISTINCT FROM OLD.category
               OR NEW.action_sequence IS DISTINCT FROM OLD.action_sequence
               OR NEW.input_sha256 IS DISTINCT FROM OLD.input_sha256
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'agent attempt identity is immutable';
            END IF;
            IF OLD.status = 'prepared' THEN
                IF NEW.status NOT IN ('prepared','in_flight','failed') THEN
                    RAISE EXCEPTION 'invalid agent attempt transition';
                END IF;
            ELSIF OLD.status = 'in_flight' THEN
                IF NEW.status NOT IN ('in_flight','succeeded','failed','unknown') THEN
                    RAISE EXCEPTION 'invalid agent attempt transition';
                END IF;
            ELSIF OLD.status = 'unknown' THEN
                IF NEW.status NOT IN ('unknown','succeeded','failed') THEN
                    RAISE EXCEPTION 'invalid agent attempt transition';
                END IF;
            ELSE
                RAISE EXCEPTION 'agent attempt is terminal';
            END IF;
            IF OLD.status <> 'prepared'
               AND (NEW.segment_id IS DISTINCT FROM OLD.segment_id
                    OR NEW.owner IS DISTINCT FROM OLD.owner
                    OR NEW.lease_epoch IS DISTINCT FROM OLD.lease_epoch) THEN
                RAISE EXCEPTION 'sent agent attempt fence is immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_attempts_mutation
        BEFORE UPDATE ON agent_attempts
        FOR EACH ROW EXECUTE FUNCTION reject_agent_attempt_mutation();
        """
    )

    # 预算授权是追加历史，任何 UPDATE 都拒绝。
    op.execute(
        """
        CREATE FUNCTION reject_budget_authorization_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'budget authorization is immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_budget_authorizations_mutation
        BEFORE UPDATE ON budget_authorizations
        FOR EACH ROW EXECUTE FUNCTION reject_budget_authorization_mutation();
        """
    )

    # meter 预留身份不可变；unknown/settled 终态不得回写，实际用量只允许结算一次。
    op.execute(
        """
        CREATE FUNCTION reject_budget_reservation_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.attempt_id IS DISTINCT FROM OLD.attempt_id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.run_id IS DISTINCT FROM OLD.run_id
               OR NEW.segment_id IS DISTINCT FROM OLD.segment_id
               OR NEW.meter IS DISTINCT FROM OLD.meter
               OR NEW.reserved_amount IS DISTINCT FROM OLD.reserved_amount
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'budget reservation identity is immutable';
            END IF;
            IF OLD.state = 'settled' THEN
                RAISE EXCEPTION 'budget reservation is terminal';
            ELSIF OLD.state = 'unknown'
                  AND NEW.state NOT IN ('unknown','settled') THEN
                RAISE EXCEPTION 'invalid budget reservation transition';
            ELSIF OLD.state = 'reserved'
                  AND NEW.state NOT IN ('reserved','charged','settled','unknown') THEN
                RAISE EXCEPTION 'invalid budget reservation transition';
            ELSIF OLD.state = 'charged'
                  AND NEW.state NOT IN ('charged','settled','unknown') THEN
                RAISE EXCEPTION 'invalid budget reservation transition';
            END IF;
            IF NEW.state = 'settled' AND NEW.actual_amount IS NULL THEN
                RAISE EXCEPTION 'settled budget reservation requires actual amount';
            END IF;
            IF NEW.state = 'unknown' AND NEW.actual_amount IS NOT NULL THEN
                RAISE EXCEPTION 'unknown budget reservation cannot carry actual amount';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_budget_reservations_mutation
        BEFORE UPDATE ON budget_reservations
        FOR EACH ROW EXECUTE FUNCTION reject_budget_reservation_mutation();
        """
    )


# 前向迁移拒绝回退，避免删除步骤、尝试与预算历史。
def downgrade() -> None:
    raise NotImplementedError("Agent 尝试与预算迁移不可逆，禁止删除审计历史")
