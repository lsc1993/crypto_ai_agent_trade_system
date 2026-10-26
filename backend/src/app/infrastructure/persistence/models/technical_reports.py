# 声明 技术报告版本文档及冻结证据哈希 的 PostgreSQL ORM 映射。
# 字段、外键与索引供仓储构造查询及关联；导入模型只注册元数据，不执行数据库迁移。
# JSONB 保留结构化载荷，时间列按 timezone 声明；不可变触发器等数据库保护以已应用迁移为准。
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


# analysis_id 唯一关联 Harness 运行；版本文档、冻结证据和证据摘要同记录保存便于历史复核。
class TechnicalReportRecord(Base):
    __tablename__ = "technical_reports"
    __table_args__ = (Index("ix_technical_reports_symbol_created", "symbol", "created_at"),)
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        ForeignKey("harness_runs.run_id", name="fk_technical_reports_run"),
        unique=True,
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    frozen_evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
