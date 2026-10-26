# 回测契约：限定 BTCUSDT、小时周期和区间长度，定义冻结请求、审计、成交统计及持久化运行状态。
# 历史回测领域：先冻结连续行情，再按收盘决策与下一根开盘成交回放；保留输入哈希和审计。
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

# 预热样本只服务均线计算，不计入性能 K 线数量与交易区间。
WARMUP_CANDLE_COUNT = 49
MAX_PERFORMANCE_CANDLE_COUNT = 1_000


# BacktestRunStatus 固定可用枚举值：PENDING、COMPLETED、FAILED；外部数据不能自行增加状态或动作。
class BacktestRunStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


# BacktestEventKind 固定可用枚举值：DECISION、RISK_APPROVED、RISK_REJECTED、ORDER、FILL、
# RISK_EXIT、CIRCUIT_BREAKER、COMPLETED；外部数据不能自行增加状态或动作。
class BacktestEventKind(StrEnum):
    DECISION = "decision"
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"
    ORDER = "order"
    FILL = "fill"
    RISK_EXIT = "risk_exit"
    CIRCUIT_BREAKER = "circuit_breaker"
    COMPLETED = "completed"


# 可预期回测输入或领域失败，保存稳定错误码和安全提示。
class ExpectedBacktestFailure(ValueError):
    # 初始化本实例依赖和配置；输入 code、safe_message。
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


# 回测存储不可用时对外暴露的安全错误。
class BacktestStorageUnavailableError(RuntimeError):
    """回测存储不可用时对外暴露的安全错误。"""


# 未找到指定的回测运行。
class BacktestNotFoundError(LookupError):
    """未找到指定的回测运行。"""


# 回测冻结契约公共基类，拒绝额外字段。
class _BacktestModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC 且带时区")
    return value.astimezone(UTC)


# 在领域类型转换之前拒绝浮点输入，避免金融数值被二进制误差污染。
def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("浮点数不能作为回测领域输入")
    return value


# 固定标的、小时周期与最多千根性能区间的回测请求，冻结资金、策略、风控和撮合配置。
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

    # 校验symbol 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：首期回测仅支持 BTCUSDT。
    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: ContractSymbol) -> ContractSymbol:
        if value is not ContractSymbol.BTCUSDT:
            raise ValueError("首期回测仅支持 BTCUSDT")
        return value

    # 校验timeframe 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：首期回测仅支持 1h K 线。
    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, value: MarketTimeframe) -> MarketTimeframe:
        if value is not MarketTimeframe.H1:
            raise ValueError("首期回测仅支持 1h K 线")
        return value

    # 校验start_at、end_at 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    @field_validator("start_at", "end_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    # 校验initial_cash 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 先拒绝浮点输入，避免二进制小数误差被转换为金融领域数值。
    @field_validator("initial_cash", mode="before")
    @classmethod
    def reject_float_cash(cls, value: object) -> object:
        return _reject_float(value)

    # 校验initial_cash 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：初始资金必须为正的有限十进制数。
    @field_validator("initial_cash")
    @classmethod
    def validate_initial_cash(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= Decimal("0"):
            raise ValueError("初始资金必须为正的有限十进制数")
        return value

    # 校验strategy_id、strategy_version 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：策略元数据不能为空。
    @field_validator("strategy_id", "strategy_version")
    @classmethod
    def validate_strategy_metadata(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("策略元数据不能为空")
        return normalized

    # 校验当前模型的跨字段约束，返回规范化值或模型；不满足约束时抛出验证错误。
    # 拒绝条件包括：回测开始时间必须早于结束时间；回测区间不能超过 1000 根 1h K 线。
    @model_validator(mode="after")
    def validate_range(self) -> BacktestRequest:
        if self.start_at >= self.end_at:
            raise ValueError("回测开始时间必须早于结束时间")
        if self.end_at - self.start_at > timedelta(hours=MAX_PERFORMANCE_CANDLE_COUNT):
            raise ValueError("回测区间不能超过 1000 根 1h K 线")
        return self

    # 在性能区间开始之前追加固定 49 根小时 K 线，为均线计算提供预热数据。
    @property
    def warmup_start_at(self) -> datetime:
        return self.start_at - timedelta(hours=WARMUP_CANDLE_COUNT)


# 回测事件序号、K 线位置和幂等键关联的审计载荷，保留 UTC 发生时刻。
class BacktestAuditEvent(_BacktestModel):
    sequence: Annotated[int, Field(ge=0)]
    kind: BacktestEventKind
    occurred_at: datetime
    candle_sequence: Annotated[int, Field(ge=0)] | None = None
    idempotency_key: str | None = None
    payload: dict[str, JsonValue]

    # 校验occurred_at 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        return _require_utc(value)


# 完整平仓交易的开闭时刻、数量与净盈亏，用于胜率及盈亏比。
class BacktestClosedTrade(_BacktestModel):
    opened_at: datetime
    closed_at: datetime
    quantity: Decimal
    net_pnl: Decimal

    # 校验opened_at、closed_at 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    @field_validator("opened_at", "closed_at")
    @classmethod
    def validate_trade_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    # 校验quantity、net_pnl 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    # 先拒绝浮点输入，避免二进制小数误差被转换为金融领域数值。
    @field_validator("quantity", "net_pnl", mode="before")
    @classmethod
    def reject_float_value(cls, value: object) -> object:
        return _reject_float(value)


# 回测统计与残留仓位摘要，输入哈希绑定精确历史行情样本。
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


# 回放引擎的统计、审计与完整平仓记录结果。
class BacktestResult(_BacktestModel):
    summary: BacktestSummary
    events: tuple[BacktestAuditEvent, ...]
    closed_trades: tuple[BacktestClosedTrade, ...]


# 保存的回测请求与运行终态，关联计算结果或安全失败信息。
class PersistedBacktestRun(_BacktestModel):
    id: UUID
    status: BacktestRunStatus
    request: BacktestRequest
    created_at: datetime
    finished_at: datetime | None = None
    result: BacktestResult | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    # 校验created_at、finished_at 字段，返回规范化值或模型；不满足约束时抛出验证错误。
    @field_validator("created_at", "finished_at")
    @classmethod
    def validate_run_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc(value)


# 回测列表受限的分页输入。
class BacktestFilters(_BacktestModel):
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]


# 回测运行分页结果及总数。
class BacktestPage(_BacktestModel):
    items: tuple[PersistedBacktestRun, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]


# 将完整 K 线序列转换为 JSON 领域载荷，以便计算回测输入哈希。
def candle_snapshot_payload(candles: tuple[Candle, ...]) -> dict[str, JsonValue]:
    return {
        "candles": [candle.model_dump(mode="json") for candle in candles],
    }
