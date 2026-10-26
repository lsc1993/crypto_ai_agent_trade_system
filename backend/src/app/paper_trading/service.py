# 模拟盘服务：接收账户与手工意图或一次策略评估，读取公开报价和已收盘行情，
# 经领域引擎后按幂等键保存转换。
# 模拟盘领域：手动请求或单次策略评估推进本地账户、仓位和审计；仅支持当前静态标的契约。
"""模拟盘应用服务。

数据流：账户请求或策略评估 → 公开市场报价/已收盘 K 线校验 → PaperTradingEngine
transition → 带幂等键的仓储事务。系统只支持 BTCUSDT 模拟盘，不连接真实下单接口。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.execution.contracts import ExecutionQuote
from app.market.contracts import (
    Candle,
    ContractSymbol,
    FreshnessStatus,
    MarketDataUnavailableError,
    MarketDetail,
    MarketTimeframe,
)
from app.market.gateway import HistoricalCandleGateway, PublicMarketGateway
from app.paper_trading.contracts import (
    ManualPaperIntent,
    PaperAccountCreate,
    PaperAccountDetail,
    PaperAccountFilters,
    PaperAccountNotFoundError,
    PaperAccountPage,
    PaperPerformanceSnapshot,
)
from app.paper_trading.engine import PaperTradingEngine
from app.paper_trading.performance import aggregate_paper_performance
from app.paper_trading.repository import PaperTradingRepository
from app.strategy.contracts import IntentSource, TradeIntent
from app.strategy.sma_crossover import SmaCrossoverStrategy

_SMA_STRATEGY_ID = "sma_crossover"
_SMA_STRATEGY_VERSION = "v1"
_SMA_CANDLE_COUNT = 51


# 协调公开行情、确定性模拟盘引擎与持久化仓储。
class PaperTradingService:
    """协调公开行情、确定性模拟盘引擎与持久化仓储。"""

    # 初始化本实例依赖和配置；输入 market、history、repository、clock、engine、strategy。
    def __init__(
        self,
        *,
        market: PublicMarketGateway,
        history: HistoricalCandleGateway,
        repository: PaperTradingRepository,
        clock: Callable[[], datetime],
        engine: PaperTradingEngine | None = None,
        strategy: SmaCrossoverStrategy | None = None,
    ) -> None:
        self._market = market
        self._history = history
        self._repository = repository
        self._clock = clock
        self._engine = PaperTradingEngine() if engine is None else engine
        self._strategy = SmaCrossoverStrategy() if strategy is None else strategy

    # 创建模拟账户及其初始仓位、估值和审计状态。
    async def create_account(self, request: PaperAccountCreate) -> PaperAccountDetail:
        """创建模拟账户及其初始仓位、估值和审计状态。"""
        return await self._repository.create_account(request, occurred_at=self._now())

    # 按筛选条件分页读取模拟账户，不计算额外市场数据。
    async def list_accounts(self, filters: PaperAccountFilters) -> PaperAccountPage:
        """按筛选条件分页读取模拟账户，不计算额外市场数据。"""
        return await self._repository.list(filters)

    # 读取一个模拟账户的当前领域状态，不存在时抛出领域未找到错误。
    async def get_account(self, account_id: UUID) -> PaperAccountDetail:
        """读取一个模拟账户的当前领域状态，不存在时抛出领域未找到错误。"""
        return await self._require_account(account_id)

    # 聚合账户估值、账本、成交与事件为只读绩效快照。
    async def get_performance(self, account_id: UUID) -> PaperPerformanceSnapshot:
        """聚合账户估值、账本、成交与事件为只读绩效快照。"""
        data = await self._repository.get_performance_data(account_id)
        if data is None:
            raise PaperAccountNotFoundError("未找到模拟账户")
        return aggregate_paper_performance(data, generated_at=self._now())

    # 提交一条用户手工开/平仓意图并以客户端请求 ID 实现幂等。
    async def submit_manual_intent(
        self,
        account_id: UUID,
        request: ManualPaperIntent,
    ) -> PaperAccountDetail:
        """提交一条用户手工开/平仓意图并以客户端请求 ID 实现幂等。

        行情读取失败会记录独立市场失败事件；读取成功后由领域引擎执行风控和模拟
        撮合，服务层不绕过任何风险规则。
        """
        # 客户端重试同一请求时返回原账户状态，防止网络重试重复开仓或平仓。
        idempotency_key = f"{account_id}:manual:{request.client_request_id}"
        if await self._repository.find_outcome(account_id, idempotency_key) is not None:
            return await self._require_account(account_id)
        detail = await self._require_account(account_id)
        try:
            quote = await self._quote()
        except MarketDataUnavailableError as error:
            await self._repository.record_market_failure(
                account_id,
                idempotency_key,
                code=error.code,
                occurred_at=self._now(),
            )
            raise
        intent = TradeIntent(
            run_id=account_id,
            symbol=ContractSymbol.BTCUSDT,
            action=request.action,
            decision_at=quote.observed_at,
            source=IntentSource.MANUAL,
            idempotency_key=idempotency_key,
        )
        transition = self._engine.apply(
            account=detail.account,
            position=detail.position,
            intent=intent,
            quote=quote,
            latest_closed_candle_at=_latest_closed_candle_at(quote),
        )
        return await self._repository.apply_transition(
            account_id,
            idempotency_key,
            transition,
            occurred_at=self._now(),
        )

    # 对最新已收盘 1h K 线运行 SMA 策略，并将无信号也作为可审计结果保存。
    async def evaluate_strategy(self, account_id: UUID) -> PaperAccountDetail:
        """对最新已收盘 1h K 线运行 SMA 策略，并将无信号也作为可审计结果保存。"""
        detail = await self._require_account(account_id)
        try:
            quote = await self._quote()
            latest_closed_candle_at = _latest_closed_candle_at(quote)
            # 同一账户、同一根已收盘 K 线最多评估一次，策略任务可安全重试。
            idempotency_key = _strategy_idempotency_key(account_id, latest_closed_candle_at)
            if await self._repository.find_outcome(account_id, idempotency_key) is not None:
                return await self._require_account(account_id)
            candles = await self._history.load_closed_candles(
                ContractSymbol.BTCUSDT,
                MarketTimeframe.H1,
                start_at=latest_closed_candle_at - timedelta(hours=_SMA_CANDLE_COUNT),
                end_at=latest_closed_candle_at,
            )
            _validate_strategy_candles(candles, latest_closed_candle_at)
        except MarketDataUnavailableError as error:
            await self._repository.record_market_failure(
                account_id,
                _strategy_idempotency_key(
                    account_id,
                    self._now().replace(minute=0, second=0, microsecond=0),
                ),
                code=error.code,
                occurred_at=self._now(),
            )
            raise

        intent = self._strategy.decide(
            run_id=account_id,
            candles=candles,
            position_is_open=detail.position.quantity > 0,
        )
        # 策略产出的临时键不能跨服务边界；这里统一替换成按 K 线确定的持久化幂等键。
        if intent is not None:
            intent = intent.model_copy(update={"idempotency_key": idempotency_key})
        transition = self._engine.apply(
            account=detail.account,
            position=detail.position,
            intent=intent,
            quote=quote,
            latest_closed_candle_at=latest_closed_candle_at,
            no_signal_idempotency_key=None if intent is not None else idempotency_key,
            no_signal_source=None if intent is not None else IntentSource.STRATEGY,
        )
        return await self._repository.apply_transition(
            account_id,
            idempotency_key,
            transition,
            occurred_at=self._now(),
        )

    # 归档模拟账户，阻止其后续接收新的手工或策略意图。
    async def archive_account(self, account_id: UUID) -> PaperAccountDetail:
        """归档模拟账户，阻止其后续接收新的手工或策略意图。"""
        return await self._repository.archive(account_id, occurred_at=self._now())

    # 读取账户详情，并将空结果统一转换为 PaperAccountNotFoundError。
    async def _require_account(self, account_id: UUID) -> PaperAccountDetail:
        """读取账户详情，并将空结果统一转换为 PaperAccountNotFoundError。"""
        detail = await self._repository.get_by_id(account_id)
        if detail is None:
            raise PaperAccountNotFoundError("未找到模拟账户")
        return detail

    # 读取 BTCUSDT 的新鲜公开摘要并转换为模拟撮合使用的冻结报价。
    async def _quote(self) -> ExecutionQuote:
        """读取 BTCUSDT 的新鲜公开摘要并转换为模拟撮合使用的冻结报价。"""
        detail = await self._market.get_market(
            ContractSymbol.BTCUSDT,
            (MarketTimeframe.H1,),
        )
        return _quote_from_market(detail)

    # 校验输入或服务时钟为带时区 UTC 时间，使窗口过滤、审计排序与自然日聚合使用同一基准。
    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("模拟盘服务时钟必须返回 UTC 带时区时间")
        return value.astimezone(UTC)


# 验证公开市场详情的标的和新鲜度，再提取可用于模拟盘的报价。
def _quote_from_market(detail: MarketDetail) -> ExecutionQuote:
    """验证公开市场详情的标的和新鲜度，再提取可用于模拟盘的报价。"""
    summary = detail.summary
    if summary.symbol is not ContractSymbol.BTCUSDT:
        raise MarketDataUnavailableError("market_data_invalid_response", "公开行情标的不匹配")
    if summary.freshness.status is not FreshnessStatus.FRESH:
        raise MarketDataUnavailableError("public_market_unavailable", "公开行情当前不可用")
    return ExecutionQuote(
        symbol=summary.symbol,
        price=summary.price,
        observed_at=summary.freshness.observed_at,
        fetched_at=summary.freshness.fetched_at,
        source=summary.freshness.source,
    )


# 将行情观测时刻截断到小时边界，作为策略输入和幂等键对应的最近收盘 K 线。
def _latest_closed_candle_at(quote: ExecutionQuote) -> datetime:
    """将行情观测时刻截断到小时边界，作为策略输入和幂等键对应的最近收盘 K 线。"""
    return quote.observed_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


# 为账户、策略版本和单根已收盘 K 线生成稳定的策略评估幂等键。
def _strategy_idempotency_key(account_id: UUID, latest_closed_candle_at: datetime) -> str:
    """为账户、策略版本和单根已收盘 K 线生成稳定的策略评估幂等键。"""
    return (
        f"{account_id}:{_SMA_STRATEGY_ID}:{_SMA_STRATEGY_VERSION}:"
        f"{latest_closed_candle_at.isoformat()}:evaluation"
    )


# 要求准确的 51 根连续已收盘小时 K 线，拒绝缺失、错标的、错周期或未来输入。
def _validate_strategy_candles(
    candles: tuple[Candle, ...],
    latest_closed_candle_at: datetime,
) -> None:
    # SMA(20/50) 依赖连续的已收盘 1h K 线；缺失、跳跃或未来 K 线都使本次评估失效。
    expected_start = latest_closed_candle_at - timedelta(hours=_SMA_CANDLE_COUNT)
    if len(candles) != _SMA_CANDLE_COUNT:
        raise MarketDataUnavailableError("market_data_missing", "公开行情缺少足够的已收盘 1h K 线")
    for offset, candle in enumerate(candles):
        expected_open = expected_start + timedelta(hours=offset)
        if (
            candle.symbol is not ContractSymbol.BTCUSDT
            or candle.timeframe is not MarketTimeframe.H1
            or candle.open_at != expected_open
            or candle.close_at > latest_closed_candle_at
        ):
            raise MarketDataUnavailableError(
                "market_data_invalid_response",
                "公开行情未提供连续已收盘 1h K 线",
            )
