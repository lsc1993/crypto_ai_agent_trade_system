from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, field_validator, model_validator

from app.execution.contracts import (
    DEFAULT_EXECUTION_CONFIG,
    ExecutionConfig,
    ExecutionQuote,
    SimulatedFill,
    SimulatedOrder,
)
from app.market.contracts import ContractSymbol
from app.risk.contracts import DEFAULT_RISK_CONFIG, RiskConfig
from app.strategy.contracts import IntentAction, IntentSource


class PaperAccountStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class PaperEventKind(StrEnum):
    INTENT = "intent"
    NO_SIGNAL = "no_signal"
    MARKET_UNAVAILABLE = "market_unavailable"
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"
    RISK_EXIT = "risk_exit"
    ORDER = "order"
    FILL = "fill"
    ARCHIVED = "archived"


class PaperActionOutcomeKind(StrEnum):
    FILLED = "filled"
    RISK_REJECTED = "risk_rejected"
    NO_SIGNAL = "no_signal"
    RISK_EXIT = "risk_exit"


class PaperStorageUnavailableError(RuntimeError):
    """模拟盘存储不可用时对外暴露的安全错误。"""


class PaperAccountNotFoundError(LookupError):
    """指定的模拟账户不存在。"""


class PaperAccountStateError(ValueError):
    """模拟账户状态不允许当前操作。"""


class _PaperModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")
    return value.astimezone(UTC)


def _finite_decimal(value: Decimal, *, message: str, allow_zero: bool = True) -> Decimal:
    if not value.is_finite() or (value < Decimal("0") if allow_zero else value <= Decimal("0")):
        raise ValueError(message)
    return value


class PaperAccountCreate(_PaperModel):
    initial_cash: Decimal

    @field_validator("initial_cash", mode="before")
    @classmethod
    def reject_float_cash(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("浮点数不能作为模拟账户初始资金")
        return value

    @field_validator("initial_cash")
    @classmethod
    def validate_initial_cash(cls, value: Decimal) -> Decimal:
        return _finite_decimal(value, message="模拟账户初始资金必须为正", allow_zero=False)


class ManualPaperIntent(_PaperModel):
    client_request_id: UUID
    action: IntentAction

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: IntentAction) -> IntentAction:
        if value not in {IntentAction.OPEN_LONG, IntentAction.CLOSE_LONG}:
            raise ValueError("手动模拟盘仅支持开多或平多")
        return value


class PaperAccount(_PaperModel):
    id: UUID
    status: PaperAccountStatus
    symbol: ContractSymbol
    initial_cash: Decimal
    cash: Decimal
    equity: Decimal
    peak_equity: Decimal
    daily_start_equity: Decimal
    daily_realized_loss: Decimal
    daily_day: date
    cooldown_remaining: int
    last_closed_candle_at: datetime | None
    risk_config: RiskConfig = DEFAULT_RISK_CONFIG
    execution_config: ExecutionConfig = DEFAULT_EXECUTION_CONFIG
    created_at: datetime
    archived_at: datetime | None

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: ContractSymbol) -> ContractSymbol:
        if value is not ContractSymbol.BTCUSDT:
            raise ValueError("模拟盘仅支持 BTCUSDT")
        return value

    @field_validator(
        "initial_cash",
        "cash",
        "equity",
        "peak_equity",
        "daily_start_equity",
        "daily_realized_loss",
    )
    @classmethod
    def validate_money(cls, value: Decimal) -> Decimal:
        return _finite_decimal(value, message="模拟账户金额必须是有限非负十进制数")

    @field_validator("cooldown_remaining")
    @classmethod
    def validate_cooldown(cls, value: int) -> int:
        if value < 0:
            raise ValueError("模拟账户冷却根数不能为负数")
        return value

    @field_validator("last_closed_candle_at", "created_at", "archived_at")
    @classmethod
    def validate_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)

    @model_validator(mode="after")
    def validate_account_state(self) -> PaperAccount:
        if self.peak_equity < self.equity:
            raise ValueError("模拟账户峰值权益不能低于当前权益")
        if self.status is PaperAccountStatus.ACTIVE and self.archived_at is not None:
            raise ValueError("活动模拟账户不能具有归档时间")
        if self.status is PaperAccountStatus.ARCHIVED and self.archived_at is None:
            raise ValueError("归档模拟账户必须具有归档时间")
        return self


class PaperPosition(_PaperModel):
    account_id: UUID
    quantity: Decimal
    average_entry_price: Decimal | None
    remaining_entry_cost: Decimal
    opened_at: datetime | None
    updated_at: datetime

    @field_validator("quantity", "remaining_entry_cost")
    @classmethod
    def validate_nonnegative_value(cls, value: Decimal) -> Decimal:
        return _finite_decimal(value, message="模拟仓位数值必须是有限非负十进制数")

    @field_validator("average_entry_price")
    @classmethod
    def validate_average_entry_price(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return _finite_decimal(value, message="模拟仓位均价必须为正", allow_zero=False)

    @field_validator("opened_at", "updated_at")
    @classmethod
    def validate_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)

    @model_validator(mode="after")
    def validate_position_state(self) -> PaperPosition:
        is_open = self.quantity > Decimal("0")
        if is_open and (
            self.average_entry_price is None
            or self.remaining_entry_cost <= Decimal("0")
            or self.opened_at is None
        ):
            raise ValueError("开仓模拟仓位必须具有均价、成本和开仓时间")
        if not is_open and (
            self.average_entry_price is not None
            or self.remaining_entry_cost != Decimal("0")
            or self.opened_at is not None
        ):
            raise ValueError("空仓模拟仓位不得保留开仓状态")
        return self


class PaperMarketSnapshot(_PaperModel):
    symbol: ContractSymbol
    price: Decimal
    source: str
    observed_at: datetime
    fetched_at: datetime
    payload_hash: str

    @field_validator("price")
    @classmethod
    def validate_price(cls, value: Decimal) -> Decimal:
        return _finite_decimal(value, message="模拟盘行情价格必须为正", allow_zero=False)

    @field_validator("source", "payload_hash")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("模拟盘行情元数据不能为空")
        return normalized

    @field_validator("observed_at", "fetched_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def validate_fetch_order(self) -> PaperMarketSnapshot:
        if self.fetched_at < self.observed_at:
            raise ValueError("模拟盘行情获取时间不能早于观察时间")
        return self

    @classmethod
    def from_quote(cls, quote: ExecutionQuote, *, payload_hash: str) -> PaperMarketSnapshot:
        return cls(
            symbol=quote.symbol,
            price=quote.price,
            source=quote.source,
            observed_at=quote.observed_at,
            fetched_at=quote.fetched_at,
            payload_hash=payload_hash,
        )


class PaperLedgerEntry(_PaperModel):
    occurred_at: datetime
    kind: IntentAction
    cash_delta: Decimal
    position_delta: Decimal
    realized_pnl: Decimal
    fee: Decimal
    cash_after: Decimal
    quantity_after: Decimal

    @field_validator("occurred_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator(
        "cash_delta",
        "position_delta",
        "realized_pnl",
        "fee",
        "cash_after",
        "quantity_after",
    )
    @classmethod
    def validate_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("模拟盘账本数值必须是有限十进制数")
        return value


class PaperAuditEvent(_PaperModel):
    sequence: int
    kind: PaperEventKind
    occurred_at: datetime
    idempotency_key: str | None
    payload: dict[str, JsonValue]

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, value: int) -> int:
        if value < 0:
            raise ValueError("模拟盘审计序号不能为负数")
        return value

    @field_validator("occurred_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _require_utc(value)


class PaperActionOutcome(_PaperModel):
    kind: PaperActionOutcomeKind
    source: IntentSource | None
    idempotency_key: str | None
    reason: str | None = None


class PaperTransition(_PaperModel):
    account: PaperAccount
    position: PaperPosition
    snapshot: PaperMarketSnapshot
    orders: tuple[SimulatedOrder, ...]
    fills: tuple[SimulatedFill, ...]
    ledger_entries: tuple[PaperLedgerEntry, ...]
    events: tuple[PaperAuditEvent, ...]
    outcome: PaperActionOutcome


class PaperAccountSummary(_PaperModel):
    id: UUID
    status: PaperAccountStatus
    symbol: ContractSymbol
    cash: Decimal
    equity: Decimal
    position_quantity: Decimal
    created_at: datetime
    archived_at: datetime | None


class PaperAccountDetail(_PaperModel):
    account: PaperAccount
    position: PaperPosition
    latest_snapshot: PaperMarketSnapshot | None
    orders: tuple[SimulatedOrder, ...]
    fills: tuple[SimulatedFill, ...]
    ledger_entries: tuple[PaperLedgerEntry, ...]
    events: tuple[PaperAuditEvent, ...]
    action_outcome: PaperActionOutcome | None


class PaperValuationKind(StrEnum):
    INITIAL = "initial"
    MARKET_VALUATION = "market_valuation"
    MIGRATION_BASELINE = "migration_baseline"


class PaperHistoryStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class PaperAccountValuation(_PaperModel):
    account_id: UUID
    sequence: int
    kind: PaperValuationKind
    snapshot_id: UUID | None
    valued_at: datetime
    cash: Decimal
    position_quantity: Decimal
    equity: Decimal
    peak_equity: Decimal

    @field_validator("sequence")
    @classmethod
    def validate_sequence(cls, value: int) -> int:
        if value < 0:
            raise ValueError("模拟账户估值序号不能为负数")
        return value

    @field_validator("valued_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("cash", "position_quantity", "equity", "peak_equity")
    @classmethod
    def validate_value(cls, value: Decimal) -> Decimal:
        return _finite_decimal(value, message="模拟账户估值必须是有限非负十进制数")

    @model_validator(mode="after")
    def validate_snapshot_and_equity(self) -> PaperAccountValuation:
        if self.peak_equity < self.equity:
            raise ValueError("模拟账户估值峰值权益不能低于权益")
        if self.kind is PaperValuationKind.INITIAL and self.snapshot_id is not None:
            raise ValueError("初始模拟账户估值不得关联行情快照")
        if self.kind is PaperValuationKind.MARKET_VALUATION and self.snapshot_id is None:
            raise ValueError("市场模拟账户估值必须关联行情快照")
        return self


class PaperPerformanceData(_PaperModel):
    account: PaperAccount
    position: PaperPosition
    valuations: tuple[PaperAccountValuation, ...]
    fills: tuple[SimulatedFill, ...]
    ledger_entries: tuple[PaperLedgerEntry, ...]
    events: tuple[PaperAuditEvent, ...]

    @model_validator(mode="after")
    def validate_account_scope(self) -> PaperPerformanceData:
        if self.position.account_id != self.account.id:
            raise ValueError("模拟盘绩效仓位必须属于账户")
        if any(value.account_id != self.account.id for value in self.valuations):
            raise ValueError("模拟盘绩效估值必须属于账户")
        if any(fill.run_id != self.account.id for fill in self.fills):
            raise ValueError("模拟盘绩效成交必须属于账户")
        return self


class PaperPerformancePoint(_PaperModel):
    at: datetime
    cash: Decimal
    position_quantity: Decimal
    equity: Decimal
    net_pnl: Decimal

    @field_validator("at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("cash", "position_quantity", "equity")
    @classmethod
    def validate_nonnegative_value(cls, value: Decimal) -> Decimal:
        return _finite_decimal(value, message="模拟盘绩效曲线数值必须是有限非负十进制数")

    @field_validator("net_pnl")
    @classmethod
    def validate_net_pnl(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("模拟盘绩效净盈亏必须是有限十进制数")
        return value


class PaperDecisionStats(_PaperModel):
    manual_intent_count: int
    strategy_evaluation_count: int
    no_signal_count: int
    risk_rejected_count: int
    risk_exit_count: int
    order_count: int
    fill_count: int

    @field_validator(
        "manual_intent_count",
        "strategy_evaluation_count",
        "no_signal_count",
        "risk_rejected_count",
        "risk_exit_count",
        "order_count",
        "fill_count",
    )
    @classmethod
    def validate_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("模拟盘绩效计数不能为负数")
        return value


class PaperPerformanceSnapshot(_PaperModel):
    account_id: UUID
    initial_cash: Decimal
    current_equity: Decimal
    net_pnl: Decimal
    return_fraction: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_fee: Decimal
    max_drawdown_amount: Decimal
    max_drawdown_fraction: Decimal
    open_fill_count: int
    close_fill_count: int
    profitable_close_count: int
    unprofitable_close_count: int
    break_even_close_count: int
    close_win_rate: Decimal
    decision_stats: PaperDecisionStats
    history_status: PaperHistoryStatus
    history_started_at: datetime
    history_ended_at: datetime
    equity_curve: tuple[PaperPerformancePoint, ...]
    generated_at: datetime

    @field_validator("initial_cash")
    @classmethod
    def validate_initial_cash(cls, value: Decimal) -> Decimal:
        return _finite_decimal(value, message="模拟盘绩效初始资金必须为正", allow_zero=False)

    @field_validator("current_equity", "total_fee", "max_drawdown_amount")
    @classmethod
    def validate_nonnegative_value(cls, value: Decimal) -> Decimal:
        return _finite_decimal(value, message="模拟盘绩效数值必须是有限非负十进制数")

    @field_validator("max_drawdown_fraction", "close_win_rate")
    @classmethod
    def validate_fraction(cls, value: Decimal) -> Decimal:
        value = _finite_decimal(value, message="模拟盘绩效比例必须是有限非负十进制数")
        if value > Decimal("1"):
            raise ValueError("模拟盘绩效比例不能超过一")
        return value

    @field_validator("net_pnl", "return_fraction", "realized_pnl", "unrealized_pnl")
    @classmethod
    def validate_signed_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("模拟盘绩效数值必须是有限十进制数")
        return value

    @field_validator(
        "open_fill_count",
        "close_fill_count",
        "profitable_close_count",
        "unprofitable_close_count",
        "break_even_close_count",
    )
    @classmethod
    def validate_count(cls, value: int) -> int:
        if value < 0:
            raise ValueError("模拟盘绩效计数不能为负数")
        return value

    @field_validator("history_started_at", "history_ended_at", "generated_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def validate_history(self) -> PaperPerformanceSnapshot:
        if not self.equity_curve:
            raise ValueError("模拟盘绩效必须包含至少一个估值点")
        if self.history_ended_at < self.history_started_at:
            raise ValueError("模拟盘绩效历史结束时间不能早于开始时间")
        return self


class PaperAccountFilters(_PaperModel):
    page: int = 1
    page_size: int = 20

    @field_validator("page", "page_size")
    @classmethod
    def validate_pagination(cls, value: int) -> int:
        if value < 1:
            raise ValueError("分页参数必须为正整数")
        return value


class PaperAccountPage(_PaperModel):
    items: tuple[PaperAccountSummary, ...]
    page: int
    page_size: int
    total: int
