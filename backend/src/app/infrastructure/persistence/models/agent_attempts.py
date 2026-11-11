# 声明 C5 步骤账本的 PostgreSQL ORM 映射：逻辑步骤、实际尝试、预算授权与 meter 预留。
# 步骤保存可复用的成功结果引用；每次真实发送有独立 attempt；预算计量行按 meter 追加。
# 真实 schema 由 0023 迁移创建；本文件只注册元数据，不执行迁移、模型、工具或交易请求。
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base

_STEP_STATUS_SQL = "'prepared','in_flight','succeeded','failed','unknown'"
_ATTEMPT_STATUS_SQL = _STEP_STATUS_SQL
_METER_SQL = (
    "'model_calls','tool_calls','transport_calls','input_tokens','output_tokens','activity_seconds'"
)


# 逻辑步骤按 (run, revision, action_sequence) 唯一；同一成功步骤的结果引用可安全复用。
class AgentStepRecord(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "revision",
            "action_sequence",
            name="uq_agent_steps_run_revision_sequence",
        ),
        CheckConstraint("revision >= 1", name="ck_agent_step_revision"),
        CheckConstraint("action_sequence >= 1", name="ck_agent_step_action_sequence"),
        CheckConstraint("char_length(input_sha256) = 64", name="ck_agent_step_input_sha"),
        CheckConstraint(
            "category IN ('model','tool','transport')",
            name="ck_agent_step_category",
        ),
        CheckConstraint(
            f"status IN ({_STEP_STATUS_SQL})",
            name="ck_agent_step_status",
        ),
        CheckConstraint(
            "result_ref IS NULL OR jsonb_typeof(result_ref) = 'object'",
            name="ck_agent_step_result_ref",
        ),
        CheckConstraint(
            "(status = 'succeeded' AND result_ref IS NOT NULL) OR "
            "(status <> 'succeeded' AND result_ref IS NULL)",
            name="ck_agent_step_result_status",
        ),
        Index("ix_agent_steps_run_status", "run_id", "status"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_steps_run"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_ref: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 每次实际发送独立 attempt；prepared 状态下允许新片段接管，发送后围栏字段冻结。
class AgentAttemptRecord(Base):
    __tablename__ = "agent_attempts"
    __table_args__ = (
        UniqueConstraint(
            "step_id",
            "attempt_number",
            name="uq_agent_attempts_step_number",
        ),
        CheckConstraint("revision >= 1", name="ck_agent_attempt_revision"),
        CheckConstraint("action_sequence >= 1", name="ck_agent_attempt_action_sequence"),
        CheckConstraint(
            "attempt_number IN (1,2)",
            name="ck_agent_attempt_number",
        ),
        CheckConstraint("lease_epoch >= 0", name="ck_agent_attempt_lease_epoch"),
        CheckConstraint("char_length(input_sha256) = 64", name="ck_agent_attempt_input_sha"),
        CheckConstraint(
            "category IN ('model','tool','transport')",
            name="ck_agent_attempt_category",
        ),
        CheckConstraint(
            f"status IN ({_ATTEMPT_STATUS_SQL})",
            name="ck_agent_attempt_status",
        ),
        CheckConstraint(
            "(status = 'prepared' AND sent_at IS NULL AND settled_at IS NULL) OR "
            "(status = 'in_flight' AND sent_at IS NOT NULL AND settled_at IS NULL) OR "
            "(status = 'failed' AND settled_at IS NOT NULL) OR "
            "(status IN ('succeeded','unknown') AND sent_at IS NOT NULL "
            "AND settled_at IS NOT NULL)",
            name="ck_agent_attempt_timestamps",
        ),
        Index("ix_agent_attempts_run_status", "run_id", "status"),
        Index("ix_agent_attempts_run_category", "run_id", "category"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    step_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_steps.id", name="fk_agent_attempts_step"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_attempts_run"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    owner: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    action_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_receipt: Mapped[str | None] = mapped_column(String(256))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 追加式预算授权；initial 每个 run 一行，append 记录 AP-05 的新绝对上限与授权引用。
class BudgetAuthorizationRecord(Base):
    __tablename__ = "budget_authorizations"
    __table_args__ = (
        UniqueConstraint("run_id", "authorization_ref", name="uq_budget_authorizations_ref"),
        Index(
            "uq_budget_authorizations_initial",
            "run_id",
            unique=True,
            postgresql_where=text("kind = 'initial'"),
        ),
        CheckConstraint("kind IN ('initial','append')", name="ck_budget_authorization_kind"),
        CheckConstraint("model_calls BETWEEN 1 AND 32", name="ck_budget_authorization_model"),
        CheckConstraint("tool_calls BETWEEN 1 AND 48", name="ck_budget_authorization_tool"),
        CheckConstraint(
            "input_tokens BETWEEN 1 AND 393216",
            name="ck_budget_authorization_input",
        ),
        CheckConstraint(
            "output_tokens BETWEEN 1 AND 131072",
            name="ck_budget_authorization_output",
        ),
        CheckConstraint(
            "active_seconds BETWEEN 1 AND 1800",
            name="ck_budget_authorization_active",
        ),
        CheckConstraint(
            "transport_calls BETWEEN 1 AND 256",
            name="ck_budget_authorization_transport",
        ),
        CheckConstraint(
            "(kind = 'initial' AND authorization_ref IS NULL AND reason IS NULL) OR "
            "(kind = 'append' AND authorization_ref IS NOT NULL AND reason IS NOT NULL "
            "AND char_length(reason) BETWEEN 1 AND 256)",
            name="ck_budget_authorization_shape",
        ),
        Index("ix_budget_authorizations_run", "run_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_budget_authorizations_run"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    active_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    transport_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_ref: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# meter 行是预算权威账本：reserved 是发送前上限，actual 是已知结算值，未知保留预留。
# activity 行没有 attempt_id，按片段唯一，防止重放活动时长重复累计。
class BudgetReservationRecord(Base):
    __tablename__ = "budget_reservations"
    __table_args__ = (
        CheckConstraint(f"meter IN ({_METER_SQL})", name="ck_budget_reservation_meter"),
        CheckConstraint(
            "state IN ('reserved','charged','settled','unknown','released')",
            name="ck_budget_reservation_state",
        ),
        CheckConstraint("reserved_amount >= 0", name="ck_budget_reservation_reserved"),
        CheckConstraint(
            "actual_amount IS NULL OR actual_amount >= 0",
            name="ck_budget_reservation_actual",
        ),
        # meter/state 决定 actual 的合法形状；INSERT 与 UPDATE 都受 CHECK 约束。
        # 次数 meter 在 charged 时允许 actual=1；未结算 Token 不得提前写 actual。
        CheckConstraint(
            "(meter = 'activity_seconds' AND attempt_id IS NULL AND state = 'settled' "
            "AND reserved_amount = 0 AND actual_amount IS NOT NULL) OR "
            "(meter IN ('model_calls','tool_calls','transport_calls') AND attempt_id IS NOT NULL "
            "AND ((state IN ('reserved','unknown','released') AND actual_amount IS NULL) "
            "OR (state = 'charged' AND (actual_amount IS NULL OR actual_amount = 1)) "
            "OR (state = 'settled' AND actual_amount = 1))) OR "
            "(meter IN ('input_tokens','output_tokens') AND attempt_id IS NOT NULL "
            "AND ((state IN ('reserved','charged','unknown','released') "
            "AND actual_amount IS NULL) "
            "OR (state = 'settled' AND actual_amount IS NOT NULL)))",
            name="ck_budget_reservation_shape",
        ),
        CheckConstraint(
            "(attempt_id IS NULL AND meter = 'activity_seconds') OR "
            "(attempt_id IS NOT NULL AND meter <> 'activity_seconds')",
            name="ck_budget_reservation_attempt_meter",
        ),
        Index("ix_budget_reservations_run_meter", "run_id", "meter", "state"),
        Index(
            "uq_budget_reservations_attempt_meter",
            "attempt_id",
            "meter",
            unique=True,
            postgresql_where=text("attempt_id IS NOT NULL"),
        ),
        Index(
            "uq_budget_reservations_activity_segment",
            "run_id",
            "segment_id",
            unique=True,
            postgresql_where=text("meter = 'activity_seconds'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_attempts.id", name="fk_budget_reservations_attempt")
    )
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_budget_reservations_run"),
        nullable=False,
    )
    segment_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    meter: Mapped[str] = mapped_column(String(24), nullable=False)
    reserved_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_amount: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "AgentAttemptRecord",
    "AgentStepRecord",
    "BudgetAuthorizationRecord",
    "BudgetReservationRecord",
]
