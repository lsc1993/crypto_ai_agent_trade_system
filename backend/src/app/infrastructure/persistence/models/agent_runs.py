# 声明 C4 Agent 持久任务的 PostgreSQL ORM 映射：会话线程、任务、不可变修订、请求映射、
# 安全事件、证据 epoch、产物引用和队列单例锁。真实 schema 由 0022 迁移创建。
# 任务行保存可变生命周期、owner/租约和消息水位；修订/请求/事件/证据/产物为不可变历史。
# 本文件只注册元数据，不执行迁移、模型调用、工具调用或交易请求。
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

_TERMINAL_SQL = "'completed','degraded','failed','cancelled','expired'"


# 用户会话线程；工作台范围由服务端注入，客户端不能通过猜测线程标识跨范围读取。
class AgentThreadRecord(Base):
    __tablename__ = "agent_threads"
    __table_args__ = (Index("ix_agent_threads_workspace_created", "workspace_id", "created_at"),)
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 可变任务行是业务生命周期的唯一权威；图检查点不能替代这里的已提交状态。
class AgentRunRecord(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','waiting_input','waiting_approval',"
            "'completed','degraded','failed','cancelled','expired')",
            name="ck_agent_run_status",
        ),
        CheckConstraint("revision >= 1", name="ck_agent_run_revision"),
        CheckConstraint("state_version >= 0", name="ck_agent_run_state_version"),
        CheckConstraint(
            "received_message_seq >= 0 AND applied_message_seq >= 0 AND "
            "applied_message_seq <= received_message_seq",
            name="ck_agent_run_message_watermarks",
        ),
        CheckConstraint(
            "(status = 'running' AND owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'running' AND owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_agent_run_lease",
        ),
        CheckConstraint("lease_epoch >= 0", name="ck_agent_run_lease_epoch"),
        CheckConstraint(
            f"(status IN ({_TERMINAL_SQL})) = (finished_at IS NOT NULL)",
            name="ck_agent_run_terminal",
        ),
        CheckConstraint(
            "parent_run_id IS NULL OR parent_run_id <> id",
            name="ck_agent_run_parent",
        ),
        CheckConstraint(
            "result_quality IS NULL OR result_quality IN ('complete','degraded','unknown')",
            name="ck_agent_run_result_quality",
        ),
        CheckConstraint(
            "jsonb_typeof(result_refs) = 'array'",
            name="ck_agent_run_result_refs",
        ),
        Index("ix_agent_runs_workspace_created", "workspace_id", "created_at"),
        Index("ix_agent_runs_thread", "thread_id", "created_at"),
        Index(
            "ix_agent_runs_runnable",
            "status",
            postgresql_where=text("status IN ('queued','running')"),
        ),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    thread_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_threads.id", name="fk_agent_runs_thread"),
        nullable=False,
    )
    parent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_runs_parent")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    received_message_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_message_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    current_interaction_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    result_refs: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    result_quality: Mapped[str | None] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64))
    owner: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# 任务输入修订不可变；revision=1 在创建事务内与任务、请求映射和事件一同提交。
class AgentRunRevisionRecord(Base):
    __tablename__ = "agent_run_revisions"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_agent_run_revision_number"),
        CheckConstraint("char_length(sha256) = 64", name="ck_agent_run_revision_sha"),
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_run_revisions_run"),
        primary_key=True,
    )
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    input: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 请求键映射按工作台隔离；同一 UUID 在不同工作台可对应不同任务，不构成跨范围授权。
class AgentRunRequestRecord(Base):
    __tablename__ = "agent_run_requests"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_agent_run_requests_run"),
        CheckConstraint("char_length(request_sha256) = 64", name="ck_agent_run_request_sha"),
    )
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_run_requests_run"),
        nullable=False,
    )
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 任务内单调事件；seq 从 1 开始，按任务独立分配，payload 只保存应用层白名单投影。
class AgentRunEventRecord(Base):
    __tablename__ = "agent_run_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_agent_run_event_sequence"),
        CheckConstraint("revision >= 1", name="ck_agent_run_event_revision"),
        CheckConstraint("projection_version >= 1", name="ck_agent_run_event_projection"),
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_run_events_run"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    projection_version: Mapped[int] = mapped_column(Integer, nullable=False)


# 证据 epoch 为 T08 预留；T04 只建立不可变表，不写入占位成功内容。
class AgentEvidenceEpochRecord(Base):
    __tablename__ = "agent_evidence_epochs"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_agent_evidence_epoch_revision"),
        CheckConstraint("char_length(sha256) = 64", name="ck_agent_evidence_epoch_sha"),
        Index("ix_agent_evidence_epochs_run_revision", "run_id", "revision", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_evidence_epochs_run"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 不可变产物为 T14 预留；完整财务计划只存受限后端表，查询投影另行裁剪。
class AgentArtifactRecord(Base):
    __tablename__ = "agent_artifacts"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_agent_artifact_revision"),
        CheckConstraint("char_length(sha256) = 64", name="ck_agent_artifact_sha"),
        Index("ix_agent_artifacts_run_revision", "run_id", "revision", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_artifacts_run"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quality: Mapped[str | None] = mapped_column(String(16))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    parent_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_artifacts.id", name="fk_agent_artifacts_parent")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 队列单例行；仓储获取行锁后检查全局可运行容量，避免并发第 21 个任务越过上限。
class AgentRunQueueRecord(Base):
    __tablename__ = "agent_run_queue"
    __table_args__ = (CheckConstraint("id = 1", name="ck_agent_run_queue_singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


__all__ = [
    "AgentArtifactRecord",
    "AgentEvidenceEpochRecord",
    "AgentRunEventRecord",
    "AgentRunQueueRecord",
    "AgentRunRecord",
    "AgentRunRequestRecord",
    "AgentRunRevisionRecord",
    "AgentThreadRecord",
]
