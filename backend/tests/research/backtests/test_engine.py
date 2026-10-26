# 验证收盘决策、下一根开盘成交的确定性回测时间线。
# 固定策略替身分别产生开仓、重复意图和无仓平仓，观察事件与成交。
# 未来数据、缺失小时、风控拒绝、熔断和部分成交都需显式处理；末尾持仓按收盘估值。
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.execution.contracts import DEFAULT_EXECUTION_CONFIG, ExecutionConfig
from app.market.contracts import Candle, ContractSymbol, MarketTimeframe
from app.research.backtests.contracts import BacktestEventKind, BacktestRequest
from app.research.backtests.engine import DeterministicBacktestEngine
from app.risk.contracts import DEFAULT_RISK_CONFIG, RiskConfig
from app.strategy.contracts import IntentAction, TradeIntent

RUN_ID = UUID("00000000-0000-0000-0000-000000000701")
START = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)


# 决策可见窗口截止当前收盘，成交推迟到下一根开盘，避免使用未来价格。
def test_engine_executes_a_signal_on_the_next_candle_open_without_future_access() -> None:
    strategy = _OpenOnFirstPerformanceCandle()
    result = DeterministicBacktestEngine(strategy=strategy).run(
        RUN_ID,
        _request(),
        _candles(next_open="110", final_close="110"),
    )
    fill = next(event for event in result.events if event.kind is BacktestEventKind.FILL)

    assert strategy.observed_open_times == tuple(
        START - timedelta(hours=49) + timedelta(hours=index) for index in range(50)
    )
    assert strategy.observed_last_open_times == (START,)
    assert fill.occurred_at == START + timedelta(hours=1)
    assert fill.payload["price"] == "110.0550"
    assert result.summary.candle_count == 2


def test_engine_marks_an_open_position_to_the_last_close_instead_of_forcing_an_exit() -> None:
    result = DeterministicBacktestEngine(strategy=_OpenOnFirstPerformanceCandle()).run(
        RUN_ID,
        _request(),
        _candles(next_open="110", final_close="120"),
    )

    assert result.summary.open_position_quantity > Decimal("0")
    assert result.summary.unrealized_pnl > Decimal("0")
    assert result.summary.closed_trade_count == 0


def test_engine_rejects_missing_hour_before_strategy_execution() -> None:
    candles = _candles(next_open="110", final_close="110")
    broken_candles = candles[:20] + candles[21:]

    try:
        DeterministicBacktestEngine(strategy=_OpenOnFirstPerformanceCandle()).run(
            RUN_ID,
            _request(),
            broken_candles,
        )
    except ValueError as error:
        assert "连续" in str(error)
    else:
        raise AssertionError("有缺口的 K 线不应进入策略执行")


# 同一意图重复出现只允许一个订单和成交，并在审计中保持可追溯。
def test_duplicate_idempotency_key_creates_one_order_and_one_fill() -> None:
    result = DeterministicBacktestEngine(strategy=_DuplicateOpenSignals()).run(
        RUN_ID,
        _request(hours=3),
        _candles_for_performance(("100", "100"), ("100", "100"), ("100", "100")),
    )

    assert sum(event.kind is BacktestEventKind.ORDER for event in result.events) == 1
    assert sum(event.kind is BacktestEventKind.FILL for event in result.events) == 1
    assert sum(event.kind is BacktestEventKind.RISK_REJECTED for event in result.events) == 1


def test_risk_rejection_is_audited_without_a_simulated_fill() -> None:
    result = DeterministicBacktestEngine(strategy=_CloseWithoutPosition()).run(
        RUN_ID,
        _request(),
        _candles(next_open="100", final_close="100"),
    )
    rejection = next(
        event for event in result.events if event.kind is BacktestEventKind.RISK_REJECTED
    )

    assert rejection.payload["reason"] == "no_open_position"
    assert all(event.kind is not BacktestEventKind.FILL for event in result.events)


def test_circuit_breaker_audits_and_schedules_a_risk_exit_on_the_next_open() -> None:
    result = DeterministicBacktestEngine(strategy=_OpenOnFirstPerformanceCandle()).run(
        RUN_ID,
        _request(
            hours=3,
            risk_config=DEFAULT_RISK_CONFIG.model_copy(
                update={"stop_loss_fraction": Decimal("0.5")}
            ),
        ),
        _candles_for_performance(("100", "100"), ("100", "80"), ("80", "80")),
    )

    assert any(event.kind is BacktestEventKind.CIRCUIT_BREAKER for event in result.events)
    assert any(event.kind is BacktestEventKind.RISK_EXIT for event in result.events)
    fills = tuple(event for event in result.events if event.kind is BacktestEventKind.FILL)
    assert fills[-1].payload["action"] == "close_long"
    assert fills[-1].occurred_at == START + timedelta(hours=2)


def test_partial_execution_is_retained_in_the_backtest_audit() -> None:
    result = DeterministicBacktestEngine(strategy=_OpenOnFirstPerformanceCandle()).run(
        RUN_ID,
        _request(
            execution_config=ExecutionConfig(
                fee_rate=Decimal("0.001"),
                slippage_rate=Decimal("0.0005"),
                fill_ratio=Decimal("0.5"),
            )
        ),
        _candles(next_open="100", final_close="100"),
    )
    fill = next(event for event in result.events if event.kind is BacktestEventKind.FILL)

    assert fill.payload["status"] == "partially_filled"
    assert result.summary.open_position_quantity == Decimal("47.5000000")


class _OpenOnFirstPerformanceCandle:
    def __init__(self) -> None:
        self.observed_open_times: tuple[datetime, ...] = ()
        self.observed_last_open_times: tuple[datetime, ...] = ()

    def decide(
        self,
        *,
        run_id: UUID,
        candles: tuple[Candle, ...],
        position_is_open: bool,
    ) -> TradeIntent | None:
        self.observed_open_times = tuple(candle.open_at for candle in candles)
        self.observed_last_open_times += (candles[-1].open_at,)
        if candles[-1].open_at != START or position_is_open:
            return None
        return TradeIntent(
            run_id=run_id,
            symbol=ContractSymbol.BTCUSDT,
            action=IntentAction.OPEN_LONG,
            decision_at=candles[-1].close_at,
            strategy_id="sma_crossover",
            strategy_version="v1",
            idempotency_key=f"{run_id}:first-open",
        )


class _DuplicateOpenSignals:
    def decide(
        self,
        *,
        run_id: UUID,
        candles: tuple[Candle, ...],
        position_is_open: bool,
    ) -> TradeIntent:
        return TradeIntent(
            run_id=run_id,
            symbol=ContractSymbol.BTCUSDT,
            action=IntentAction.OPEN_LONG,
            decision_at=candles[-1].close_at,
            strategy_id="sma_crossover",
            strategy_version="v1",
            idempotency_key=f"{run_id}:duplicate-open",
        )


class _CloseWithoutPosition:
    def decide(
        self,
        *,
        run_id: UUID,
        candles: tuple[Candle, ...],
        position_is_open: bool,
    ) -> TradeIntent:
        return TradeIntent(
            run_id=run_id,
            symbol=ContractSymbol.BTCUSDT,
            action=IntentAction.CLOSE_LONG,
            decision_at=candles[-1].close_at,
            strategy_id="sma_crossover",
            strategy_version="v1",
            idempotency_key=f"{run_id}:close-without-position",
        )


def _request(
    *,
    hours: int = 2,
    execution_config: ExecutionConfig = DEFAULT_EXECUTION_CONFIG,
    risk_config: RiskConfig = DEFAULT_RISK_CONFIG,
) -> BacktestRequest:
    return BacktestRequest(
        symbol=ContractSymbol.BTCUSDT,
        timeframe=MarketTimeframe.H1,
        start_at=START,
        end_at=START + timedelta(hours=hours),
        initial_cash=Decimal("10000"),
        execution_config=execution_config,
        risk_config=risk_config,
    )


def _candles(*, next_open: str, final_close: str) -> tuple[Candle, ...]:
    return _candles_for_performance(("100", "100"), (next_open, final_close))


def _candles_for_performance(
    *performance_prices: tuple[str, str],
) -> tuple[Candle, ...]:
    warmup_start = START - timedelta(hours=49)
    warmup = tuple(
        _candle(warmup_start + timedelta(hours=index), "100", "100")
        for index in range(49)
    )
    performance = tuple(
        _candle(START + timedelta(hours=index), open_price, close_price)
        for index, (open_price, close_price) in enumerate(performance_prices)
    )
    return warmup + performance


def _candle(open_at: datetime, open_price: str, close_price: str) -> Candle:
    open_decimal = Decimal(open_price)
    close_decimal = Decimal(close_price)
    return Candle(
        symbol=ContractSymbol.BTCUSDT,
        timeframe=MarketTimeframe.H1,
        open_at=open_at,
        close_at=open_at + timedelta(hours=1),
        open_price=open_decimal,
        high_price=max(open_decimal, close_decimal),
        low_price=min(open_decimal, close_decimal),
        close_price=close_decimal,
        volume=Decimal("1"),
        observed_at=open_at + timedelta(hours=1),
        fetched_at=open_at + timedelta(hours=1),
    )
