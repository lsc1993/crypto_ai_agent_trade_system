# 声明 模拟账户、仓位、估值、模拟订单成交、账本与事件 的 PostgreSQL ORM 映射。
# 字段、外键与索引供仓储构造查询及关联；导入模型只注册元数据，不执行数据库迁移。
# 金额列使用 Numeric 映射 Decimal，时间列按 timezone 声明；持久化约束仍以已应用迁移为准。
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.infrastructure.persistence.base import Base


# 保存模拟账户当前余额及风险状态；部分唯一索引只允许一个 active 账户。
class PaperAccountRecord(Base):
    __tablename__ = "paper_accounts"
    __table_args__ = (
        Index("ix_paper_accounts_created_at", "created_at", "id"),
        Index(
            "uq_paper_accounts_one_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    peak_equity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    daily_start_equity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    daily_realized_loss: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    daily_day: Mapped[date] = mapped_column(Date, nullable=False)
    cooldown_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    last_closed_candle_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    risk_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    execution_config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# 以 account_id 一对一保存当前模拟仓位；均价可空表示无持仓，剩余入场成本单独记录。
class PaperPositionRecord(Base):
    __tablename__ = "paper_positions"

    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("paper_accounts.id", name="fk_paper_positions_account"),
        primary_key=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    average_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    remaining_entry_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# 保存模拟决策使用的公开价格、来源、观测和抓取时间及输入哈希，用于回溯成交依据。
class PaperMarketSnapshotRecord(Base):
    __tablename__ = "paper_market_snapshots"
    __table_args__ = (
        Index("ix_paper_snapshots_account_observed_at", "account_id", "observed_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("paper_accounts.id", name="fk_paper_snapshots_account"),
        nullable=False,
    )
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)


# 按账户和递增 sequence 保存估值历史，可关联当次价格快照；初始估值无需快照。
class PaperAccountValuationRecord(Base):
    __tablename__ = "paper_account_valuations"
    __table_args__ = (
        Index(
            "ix_paper_valuations_account_valued_at",
            "account_id",
            "valued_at",
            "sequence",
        ),
    )

    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("paper_accounts.id", name="fk_paper_valuations_account"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("paper_market_snapshots.id", name="fk_paper_valuations_snapshot"),
        nullable=True,
    )
    valued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    position_quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    peak_equity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)


# 记录模拟订单请求数量、动作、来源及价格快照；这是模拟事实，不是交易所私有订单。
class PaperOrderRecord(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        Index("ix_paper_orders_account_submitted_at", "account_id", "submitted_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("paper_accounts.id", name="fk_paper_orders_account"),
        nullable=False,
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("paper_market_snapshots.id", name="fk_paper_orders_snapshot"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


# 通过 order_id 关联模拟订单，唯一约束限制每个订单一条成交；实际数量、费用及状态独立保存。
class PaperFillRecord(Base):
    __tablename__ = "paper_fills"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_paper_fills_order"),
        Index("ix_paper_fills_account_filled_at", "account_id", "filled_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("paper_orders.id", name="fk_paper_fills_order"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("paper_accounts.id", name="fk_paper_fills_account"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


# 按账户和 sequence 保存现金及仓位增量、已实现收益与余额，作为模拟账本对账依据。
class PaperLedgerEntryRecord(Base):
    __tablename__ = "paper_ledger_entries"
    __table_args__ = (
        Index("ix_paper_ledger_account_occurred_at", "account_id", "occurred_at", "sequence"),
    )

    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("paper_accounts.id", name="fk_paper_ledger_account"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    cash_delta: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    position_delta: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    cash_after: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    quantity_after: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)


# 按账户和 sequence 保存审计；intent 的幂等键具有部分唯一索引，其他事件不共用该约束。
class PaperAuditEventRecord(Base):
    __tablename__ = "paper_audit_events"
    __table_args__ = (
        Index("ix_paper_events_account_occurred_at", "account_id", "occurred_at", "sequence"),
        Index(
            "uq_paper_events_intent_idempotency",
            "account_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("kind = 'intent'"),
        ),
    )

    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("paper_accounts.id", name="fk_paper_events_account"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
