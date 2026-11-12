# 声明 T06 人工审核、反馈、连续消息与取消幂等的 PostgreSQL ORM 映射。
# 待办内容/材料在创建后不可变，只有状态/状态号/发布响应应用时间可受控推进；
# 反馈和取消请求是追加审计事实，消息正文不可改写。真实 schema 由 0026 迁移创建。
# 本文件只注册元数据，不执行模型、工具、计划采纳、账户访问或交易请求。
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

_INTERACTION_STATUS_SQL = "'preparing','pending','answered','applied','expired'"
_INTERACTION_ACTION_SQL = (
    "'clarify','adopt_manual_plan','change_strategy','change_parameters',"
    "'expand_scope','increase_budget','adopt_revised_plan','enable_monitoring'"
)
_DECISION_SQL = "'approve','reject','request_changes','provide_input'"


# 人工待办；材料哈希/差异/引用在创建后不可变，状态推进由仓储 CAS 与触发器共同约束。
class AgentInteractionRecord(Base):
    __tablename__ = "agent_interactions"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_INTERACTION_STATUS_SQL})",
            name="ck_agent_interaction_status",
        ),
        CheckConstraint(
            f"action IN ({_INTERACTION_ACTION_SQL})",
            name="ck_agent_interaction_action",
        ),
        CheckConstraint("revision >= 1", name="ck_agent_interaction_revision"),
        CheckConstraint("state_version >= 0", name="ck_agent_interaction_state_version"),
        CheckConstraint(
            "char_length(material_hash) = 64",
            name="ck_agent_interaction_material_sha",
        ),
        CheckConstraint(
            "char_length(open_request_sha256) = 64",
            name="ck_agent_interaction_open_request_sha",
        ),
        CheckConstraint("expires_at > created_at", name="ck_agent_interaction_expiry"),
        CheckConstraint("jsonb_typeof(diffs) = 'array'", name="ck_agent_interaction_diffs"),
        CheckConstraint(
            "jsonb_typeof(material_refs) = 'array'",
            name="ck_agent_interaction_material_refs",
        ),
        CheckConstraint(
            "safe_reason ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_agent_interaction_reason",
        ),
        CheckConstraint(
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
        Index("ix_agent_interactions_workspace_run", "workspace_id", "run_id", "created_at"),
        Index(
            "ux_agent_interactions_active",
            "run_id",
            unique=True,
            postgresql_where=text("status IN ('preparing','pending','answered')"),
        ),
        UniqueConstraint(
            "workspace_id",
            "open_request_id",
            name="uq_agent_interactions_open_request",
        ),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_interactions_run"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    material_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    diffs: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    material_refs: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    safe_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    open_request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    open_request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# 审核反馈追加表；request_id 是工作台内幂等键，记录后不可改写或删除。
class AgentInteractionFeedbackRecord(Base):
    __tablename__ = "agent_interaction_feedback"
    __table_args__ = (
        CheckConstraint(
            f"decision IN ({_DECISION_SQL})",
            name="ck_agent_interaction_feedback_decision",
        ),
        CheckConstraint(
            "char_length(reviewed_payload_hash) = 64",
            name="ck_agent_interaction_feedback_material_sha",
        ),
        CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_agent_interaction_feedback_request_sha",
        ),
        CheckConstraint(
            "jsonb_typeof(changes) = 'array'",
            name="ck_agent_interaction_feedback_changes",
        ),
        UniqueConstraint(
            "workspace_id",
            "request_id",
            name="uq_agent_interaction_feedback_request",
        ),
        Index("ix_agent_interaction_feedback_run", "run_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_interaction_feedback_run"),
        nullable=False,
    )
    interaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_interactions.id", name="fk_agent_interaction_feedback_interaction"),
        nullable=False,
    )
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewed_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str | None] = mapped_column(String(4_000))
    changes: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 用户消息；正文/引用和序号不可变，只有 applied_at 能由当前 worker 从空推进一次。
class AgentUserMessageRecord(Base):
    __tablename__ = "agent_user_messages"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_agent_user_message_sequence"),
        CheckConstraint("kind IN ('text','planning_ref')", name="ck_agent_user_message_kind"),
        CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_agent_user_message_request_sha",
        ),
        CheckConstraint(
            "(kind = 'text' AND text IS NOT NULL AND planning_ref IS NULL) OR "
            "(kind = 'planning_ref' AND text IS NULL AND planning_ref IS NOT NULL)",
            name="ck_agent_user_message_content",
        ),
        CheckConstraint(
            "planning_ref IS NULL OR jsonb_typeof(planning_ref) = 'object'",
            name="ck_agent_user_message_planning_ref",
        ),
        CheckConstraint(
            "applied_at IS NULL OR applied_at >= received_at",
            name="ck_agent_user_message_applied_at",
        ),
        UniqueConstraint(
            "workspace_id",
            "request_id",
            name="uq_agent_user_message_request",
        ),
        UniqueConstraint("run_id", "sequence", name="uq_agent_user_message_sequence"),
        Index("ix_agent_user_messages_run", "run_id", "sequence"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_user_messages_run"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str | None] = mapped_column(String(4_000))
    # JSONB 默认会把 Python None 写成 JSON 'null'；消息空引用必须是 SQL NULL，
    # 否则内容形状 CHECK 会把它误判为已提供规划资料。none_as_null=True 明确这一语义。
    planning_ref: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# 取消请求映射只用于幂等重放，不授予取消交易所订单的能力。
class AgentRunCancelRequestRecord(Base):
    __tablename__ = "agent_run_cancel_requests"
    __table_args__ = (
        CheckConstraint(
            "char_length(request_sha256) = 64",
            name="ck_agent_run_cancel_request_sha",
        ),
        Index("ix_agent_run_cancel_requests_run", "run_id", "created_at"),
    )
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_run_cancel_requests_run"),
        nullable=False,
    )
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "AgentInteractionFeedbackRecord",
    "AgentInteractionRecord",
    "AgentRunCancelRequestRecord",
    "AgentUserMessageRecord",
]
