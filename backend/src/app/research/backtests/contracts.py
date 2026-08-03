from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.execution.contracts import DEFAULT_EXECUTION_CONFIG, ExecutionConfig
from app.market.contracts import Candle, ContractSymbol, MarketTimeframe
from app.risk.contracts import DEFAULT_RISK_CONFIG, RiskConfig

WARMUP_CANDLE_COUNT = 49
MAX_PERFORMANCE_CANDLE_COUNT = 1_000


class BacktestRunStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class BacktestEventKind(StrEnum):
    DECISION = "decision"
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"
    ORDER = "order"
    FILL = "fill"
    RISK_EXIT = "risk_exit"
    CIRCUIT_BREAKER = "circuit_breaker"
    COMPLETED = "completed"


class ExpectedBacktestFailure(ValueError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class BacktestStorageUnavailableError(RuntimeError):
    """回测存储不可用时对外暴露的安全错误。"""


class BacktestNotFoundError(LookupError):
    """未找到指定的回测运行。"""


class _BacktestModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")
    return value.astimezone(UTC)


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("浮点数不能作为回测领域输入")
    return value


class BacktestRequest(_BacktestModel):
    symbol: ContractSymbol = ContractSymbol.BTCUSDT
    timeframe: MarketTimeframe = MarketTimeframe.H1
    start_at: datetime
    end_at: datetime
    initial_cash: Decimal
    strategy_id: str = "sma_crossover"
    strategy_version: str = "v1"
    risk_config: RiskConfig = DEFAULT_RISK_CONFIG
    execution_config: ExecutionConfig = DEFAULT_EXECUTION_CONFIG

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: ContractSymbol) -> ContractSymbol:
        if value is not ContractSymbol.BTCUSDT:
            raise ValueError("首期回测仅支持 BTCUSDT")
        return value

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value: MarketTimeframe) -> MarketTimeframe:
        if value is not MarketTimeframe.H1:
            raise ValueError("首期回测仅支持 1h K 线")
        return value

    @field_validator("start_at", "end_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("initial_cash", mode="before")
    @classmethod
    def reject_float_cash(cls, value: object) -> object:
        return _reject_float(value)

    @field_validator("initial_cash")
    @classmethod
    def validate_initial_cash(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= Decimal("0"):
            raise ValueError("初始资金必须为正的有限十进制数")
        return value

    @field_validator("strategy_id", "strategy_version")
    @classmethod
    def validate_strategy_metadata(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("策略元数据不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_range(self) -> BacktestRequest:
        if self.start_at >= self.end_at:
            raise ValueError("回测开始时间必须早于结束时间")
        if self.end_at - self.start_at > timedelta(hours=MAX_PERFORMANCE_CANDLE_COUNT):
            raise ValueError("回测区间不能超过 1000 根 1h K 线")
        return self

    @property
    def warmup_start_at(self) -> datetime:
        return self.start_at - timedelta(hours=WARMUP_CANDLE_COUNT)


class BacktestAuditEvent(_BacktestModel):
    sequence: Annotated[int, Field(ge=0)]
    kind: BacktestEventKind
    occurred_at: datetime
    candle_sequence: Annotated[int, Field(ge=0)] | None = None
    idempotency_key: str | None = None
    payload: dict[str, JsonValue]

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        return _require_utc(value)


class BacktestClosedTrade(_BacktestModel):
    opened_at: datetime
    closed_at: datetime
    quantity: Decimal
    net_pnl: Decimal

    @field_validator("opened_at", "closed_at")
    @classmethod
    def validate_trade_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("quantity", "net_pnl", mode="before")
    @classmethod
    def reject_float_value(cls, value: object) -> object:
        return _reject_float(value)


class BacktestSummary(_BacktestModel):
    initial_cash: Decimal
    final_equity: Decimal
    net_pnl: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    return_fraction: Decimal
    max_drawdown_fraction: Decimal
    win_rate: Decimal
    profit_factor: Decimal | None
    closed_trade_count: Annotated[int, Field(ge=0)]
    fill_count: Annotated[int, Field(ge=0)]
    rejection_count: Annotated[int, Field(ge=0)]
    open_position_quantity: Decimal
    candle_count: Annotated[int, Field(ge=1, le=MAX_PERFORMANCE_CANDLE_COUNT)]
    snapshot_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class BacktestResult(_BacktestModel):
    summary: BacktestSummary
    events: tuple[BacktestAuditEvent, ...]
    closed_trades: tuple[BacktestClosedTrade, ...]


class PersistedBacktestRun(_BacktestModel):
    id: UUID
    status: BacktestRunStatus
    request: BacktestRequest
    created_at: datetime
    finished_at: datetime | None = None
    result: BacktestResult | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    @field_validator("created_at", "finished_at")
    @classmethod
    def validate_run_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)


class BacktestFilters(_BacktestModel):
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


class BacktestPage(_BacktestModel):
    items: tuple[PersistedBacktestRun, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]


def candle_snapshot_payload(candles: tuple[Candle, ...]) -> dict[str, JsonValue]:
    return {
        "candles": [candle.model_dump(mode="json") for candle in candles],
    }
