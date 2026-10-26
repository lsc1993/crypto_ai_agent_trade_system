# 声明 Agent 运行元数据、有限校验诊断及报告定性详情 的 PostgreSQL ORM 映射。
# 字段、外键与索引供仓储构造查询及关联；导入模型只注册元数据，不执行数据库迁移。
# JSONB 保留结构化载荷，时间列按 timezone 声明；不可变触发器等数据库保护以已应用迁移为准。
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


# 以 analysis_id 唯一关联综合报告，保存生成器类型、起止时刻和有限校验失败诊断；不保存模型原文。
class AgentAnalysisRunRecord(Base):
    __tablename__ = "agent_analysis_runs"
    __table_args__ = (
        Index("ix_agent_analysis_runs_symbol_completed_at", "symbol", "completed_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("analysis_reports.analysis_id", name="fk_agent_runs_analysis"),
        nullable=False,
        unique=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generator_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    model_validation_attempt_count: Mapped[int | None] = mapped_column()
    model_validation_issue_count: Mapped[int | None] = mapped_column()
    model_validation_field_paths: Mapped[list[str] | None] = mapped_column(JSONB)
    model_validation_error_categories: Mapped[list[str] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# 以报告 ID 为主键保存定性分析、双周期叙事和确定性专题；可空字段兼容旧版历史。
class AgentReportDetailRecord(Base):
    __tablename__ = "agent_report_details"

    analysis_report_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("analysis_reports.id", name="fk_agent_report_details_report"),
        primary_key=True,
    )
    horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    outlook: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    trend_alignment: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    support_zones: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    resistance_zones: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    catalysts: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    risks_and_invalidation: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    data_quality: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    market_overview: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    short_term_view: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    long_term_view: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    market_metrics: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    factor_analysis: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
