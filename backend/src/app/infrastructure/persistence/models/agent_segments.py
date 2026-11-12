# 声明 T07 执行片段的 PostgreSQL ORM 映射：唯一 Harness run、图 namespace、租约与结果。
# 片段身份（工作台/任务/修订/owner/代次/namespace）不可变，只有心跳和结束字段可受控推进。
# 本文件只注册元数据，不执行迁移、模型、工具、账户访问或交易请求。
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

_SEGMENT_STATUS_SQL = (
    "'running','waiting_input','waiting_approval','completed','degraded',"
    "'failed','cancelled','interrupted'"
)
_OUTCOME_KIND_SQL = "'wait_input','wait_approval','completed','degraded','failed','cancelled'"


# 一个业务任务同一时刻只允许一个 running 片段；终态片段保留 owner/epoch 供审计追踪。
class AgentSegmentRecord(Base):
    __tablename__ = "agent_segments"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_agent_segment_revision"),
        CheckConstraint("lease_epoch >= 0", name="ck_agent_segment_lease_epoch"),
        CheckConstraint(
            f"status IN ({_SEGMENT_STATUS_SQL})",
            name="ck_agent_segment_status",
        ),
        CheckConstraint(
            f"outcome_kind IS NULL OR outcome_kind IN ({_OUTCOME_KIND_SQL})",
            name="ck_agent_segment_outcome_kind",
        ),
        CheckConstraint(
            "graph_namespace ~ '^ir:[0-9a-f-]{36}:[0-9]+:[0-9a-f-]{36}$'",
            name="ck_agent_segment_namespace",
        ),
        CheckConstraint(
            "safe_reason IS NULL OR safe_reason ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_agent_segment_reason",
        ),
        CheckConstraint(
            "(status = 'running' AND finished_at IS NULL AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'running' AND finished_at IS NOT NULL AND lease_expires_at IS NULL)",
            name="ck_agent_segment_shape",
        ),
        CheckConstraint("jsonb_typeof(outcome) = 'object'", name="ck_agent_segment_outcome"),
        UniqueConstraint("graph_namespace", name="uq_agent_segment_namespace"),
        Index("ix_agent_segments_run_started", "run_id", "started_at"),
        Index(
            "ux_agent_segments_active",
            "run_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_agent_segments_status_lease", "status", "lease_expires_at"),
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", name="fk_agent_segments_run"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    owner: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    lease_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome_kind: Mapped[str | None] = mapped_column(String(16))
    outcome: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    safe_reason: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["AgentSegmentRecord"]
