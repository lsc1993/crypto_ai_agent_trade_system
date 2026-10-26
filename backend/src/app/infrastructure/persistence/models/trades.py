# 声明 交易日志、有效/失效事实、标签及修改审计 的 PostgreSQL ORM 映射。
# 字段、外键与索引供仓储构造查询及关联；导入模型只注册元数据，不执行数据库迁移。
# 金额列使用 Numeric 映射 Decimal，时间列按 timezone 声明；持久化约束仍以已应用迁移为准。
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.persistence.base import Base


# 保存交易日志当前摘要及收益计算结果，可空报告外键只关联研究背景；archived_at 控制归档可见性。
class TradeRecord(Base):
    __tablename__ = "trades"
    __table_args__ = (
        Index("ix_trades_active_updated_at", "archived_at", "updated_at"),
        Index("ix_trades_symbol_status", "symbol", "status"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    analysis_report_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("analysis_reports.id", name="fk_trades_analysis_report"),
        nullable=True,
    )
    leverage: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    review: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    gross_realized_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    total_fees: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    total_funding_cashflow: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 保存分腿价格、数量、费用及稳定序号；voided_at 表示已被更正替换，历史记录仍保留。
class TradeLegRecord(Base):
    __tablename__ = "trade_legs"
    __table_args__ = (
        Index("ix_trade_legs_active_trade_executed", "trade_id", "voided_at", "executed_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    trade_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("trades.id", name="fk_trade_legs_trade"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# 保存独立现金流及原因，voided_at 与交易腿一样用于更正历史，不混同为模拟成交。
class TradeCashflowRecord(Base):
    __tablename__ = "trade_cashflows"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    trade_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("trades.id", name="fk_trade_cashflows_trade"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# 标签文本具有唯一约束，多个交易日志可以复用同一标签定义。
class TagRecord(Base):
    __tablename__ = "tags"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    value: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


# 以 trade_id/tag_id 复合主键保存日志标签关联，避免同一标签被重复关联。
class TradeTagRecord(Base):
    __tablename__ = "trade_tags"
    __table_args__ = (UniqueConstraint("trade_id", "tag_id", name="uq_trade_tags_scope"),)

    trade_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("trades.id", name="fk_trade_tags_trade"),
        primary_key=True,
    )
    tag_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tags.id", name="fk_trade_tags_tag"),
        primary_key=True,
    )


# 保留日志操作、关联 correlation_id 和前后 JSON 快照，创建时 before_snapshot 可空。
class TradeAuditEventRecord(Base):
    __tablename__ = "trade_audit_events"
    __table_args__ = (Index("ix_trade_audit_events_trade_occurred", "trade_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    trade_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("trades.id", name="fk_trade_audit_events_trade"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    before_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    after_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
