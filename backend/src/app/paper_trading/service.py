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


class PaperTradingService:
    """协调公开行情、确定性模拟盘引擎与持久化仓储。"""

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

    async def create_account(self, request: PaperAccountCreate) -> PaperAccountDetail:
        return await self._repository.create_account(request, occurred_at=self._now())

    async def list_accounts(self, filters: PaperAccountFilters) -> PaperAccountPage:
        return await self._repository.list(filters)

    async def get_account(self, account_id: UUID) -> PaperAccountDetail:
        return await self._require_account(account_id)

    async def get_performance(self, account_id: UUID) -> PaperPerformanceSnapshot:
        data = await self._repository.get_performance_data(account_id)
        if data is None:
            raise PaperAccountNotFoundError("未找到模拟账户")
        return aggregate_paper_performance(data, generated_at=self._now())

    async def submit_manual_intent(
        self,
        account_id: UUID,
        request: ManualPaperIntent,
    ) -> PaperAccountDetail:
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

    async def evaluate_strategy(self, account_id: UUID) -> PaperAccountDetail:
        detail = await self._require_account(account_id)
        try:
            quote = await self._quote()
            latest_closed_candle_at = _latest_closed_candle_at(quote)
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

    async def archive_account(self, account_id: UUID) -> PaperAccountDetail:
        return await self._repository.archive(account_id, occurred_at=self._now())

    async def _require_account(self, account_id: UUID) -> PaperAccountDetail:
        detail = await self._repository.get_by_id(account_id)
        if detail is None:
            raise PaperAccountNotFoundError("未找到模拟账户")
        return detail

    async def _quote(self) -> ExecutionQuote:
        detail = await self._market.get_market(
            ContractSymbol.BTCUSDT,
            (MarketTimeframe.H1,),
        )
        return _quote_from_market(detail)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("模拟盘服务时钟必须返回 UTC 带时区时间")
        return value.astimezone(UTC)


def _quote_from_market(detail: MarketDetail) -> ExecutionQuote:
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


def _latest_closed_candle_at(quote: ExecutionQuote) -> datetime:
    return quote.observed_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _strategy_idempotency_key(account_id: UUID, latest_closed_candle_at: datetime) -> str:
    return (
        f"{account_id}:{_SMA_STRATEGY_ID}:{_SMA_STRATEGY_VERSION}:"
        f"{latest_closed_candle_at.isoformat()}:evaluation"
    )


def _validate_strategy_candles(
    candles: tuple[Candle, ...],
    latest_closed_candle_at: datetime,
) -> None:
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
