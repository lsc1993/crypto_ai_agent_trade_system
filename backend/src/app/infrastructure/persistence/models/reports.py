# 声明 综合报告摘要及关联冻结证据 的 PostgreSQL ORM 映射。
# 字段、外键与索引供仓储构造查询及关联；导入模型只注册元数据，不执行数据库迁移。
# JSONB 保留结构化载荷，时间列按 timezone 声明；不可变触发器等数据库保护以已应用迁移为准。
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


# analysis_id 唯一定位综合研究运行，摘要按事实、推断、风险和限制分别保存以支持安全展示。
class AnalysisReportRecord(Base):
    __tablename__ = "analysis_reports"
    __table_args__ = (
        Index("ix_analysis_reports_symbol_created_at", "symbol", "created_at"),
        Index("ix_analysis_reports_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, unique=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    facts: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    inferences: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    risks: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# 证据 UUID 与报告外键绑定，保存原始结构化载荷和哈希；HTTP 层只能投影允许展示的字段。
class AnalysisEvidenceRecord(Base):
    __tablename__ = "analysis_evidences"
    __table_args__ = (Index("ix_analysis_evidences_report_id", "analysis_report_id"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    analysis_report_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_reports.id", name="fk_analysis_evidences_report"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
