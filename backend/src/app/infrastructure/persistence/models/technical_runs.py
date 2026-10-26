# 声明 可变技术任务、客户端请求映射及队列单例锁记录 的 PostgreSQL ORM 映射。
# 字段、外键与索引供仓储构造查询及关联；导入模型只注册元数据，不执行数据库迁移。
# JSONB 保留结构化载荷，时间列按 timezone 声明；不可变触发器等数据库保护以已应用迁移为准。
"""Durable queue records separate from immutable report history."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


# 保存可变排队状态及阶段、owner 和过期时间；analysis_id 与 report_id 分别关联研究和最终报告。
class TechnicalRunRecord(Base):
    __tablename__ = "technical_report_runs"
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), unique=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report_id: Mapped[UUID | None] = mapped_column(ForeignKey("technical_reports.id"))
    error_code: Mapped[str | None] = mapped_column(String(32))


# 客户端 requestId 到运行 ID 的持久映射，使重放请求复用同一任务。
class TechnicalRequestRecord(Base):
    __tablename__ = "technical_report_requests"
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("technical_report_runs.id"), nullable=False)


# 队列单例协调表；仓储锁定 ID 为 1 的行以串行检查活跃任务数量和领取。
class TechnicalQueueRecord(Base):
    __tablename__ = "technical_report_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
