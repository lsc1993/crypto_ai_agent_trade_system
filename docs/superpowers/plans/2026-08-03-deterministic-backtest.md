# 首期确定性策略回测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能够以真实 BTCUSDT 1h 历史 K 线运行内置均线交叉策略，并在前端查看已持久化、可审计的确定性回测报告。

**Architecture:** 在既有公开 Binance 行情边界上补充受限的历史 K 线读取；策略只能输出 `TradeIntent`，确定性风险引擎将其转换为模拟订单，模拟撮合器在下一根 K 线开盘成交。回测编排器冻结 K 线快照、追加审计事件并经 PostgreSQL 仓储持久化，现有 `WorkbenchApi` 再把列表、详情和创建能力带到新的前端页面。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、SQLAlchemy async、Alembic、PostgreSQL、pytest、Ruff、Pyright；React 19、TypeScript、Zod、TanStack Query、Vitest。

## Global Constraints

- 首期仅支持 `BTCUSDT` 与 `1h`；不接入新交易所、私有 API、凭证或新的生产依赖。
- 所有金额、价格、数量、费率和权益使用 Python `Decimal`、PostgreSQL `NUMERIC(38,18)`、HTTP 十进制字符串；禁止 `float`。
- 所有时间为带时区 UTC；策略在收盘时决策，订单只在下一根 K 线开盘后按模拟规则成交。
- 策略只能产生 `TradeIntent`；最终放行只能来自确定性风险代码；模拟执行不得有真实下单入口。
- 真实历史行情不可用、存在缺口或请求非法时返回安全错误，不得降级到 Mock 数据。
- 新增的 K 线快照和审计事件追加后不可修改或删除；运行状态可从 `pending` 转至 `completed` 或 `failed`。
- 数据库集成测试仅使用 `TEST_DATABASE_URL` 创建的临时 schema；不得修改 `.env` 或用户数据库。
- 保留工作区中现有的 `frontend/.env.example` 删除，不得暂存、恢复或提交它。

---

## File Structure

| 文件 | 责任 |
| --- | --- |
| `backend/src/app/market/gateway.py` | 新增只读 `HistoricalCandleGateway` 协议。 |
| `backend/src/app/market/binance_usdm.py` | 在既有固定 Binance 公共边界内，按 UTC 范围取得并过滤已收盘的 1h K 线。 |
| `backend/src/app/strategy/contracts.py`、`sma_crossover.py` | 定义无金额的 `TradeIntent` 与 20/50 均线交叉基准策略。 |
| `backend/src/app/risk/contracts.py`、`engine.py` | 定义配置、组合快照、批准/拒绝结果与确定性风险规则。 |
| `backend/src/app/execution/contracts.py`、`simulator.py` | 定义模拟订单/成交并以开盘价、滑点、手续费和填充比例处理订单。 |
| `backend/src/app/research/backtests/contracts.py`、`engine.py` | 定义回测请求、结果、审计事件和纯回放/指标编排。 |
| `backend/src/app/research/backtests/repository.py`、`service.py` | 定义持久化协议并协调行情读取、运行状态和仓储调用。 |
| `backend/src/app/infrastructure/persistence/models/backtests.py`、`backtest_repository.py` | SQLAlchemy 映射和 PostgreSQL 回测仓储。 |
| `backend/alembic/versions/0005_create_backtests.py` | 建立回测运行、K 线快照和不可变审计事件表。 |
| `backend/src/app/api/routes/backtests.py`、`backend/src/app/api/errors.py`、`backend/src/app/api/router.py`、`backend/src/app/main.py` | 暴露 API、安装安全异常处理，并注入真实/不可用依赖。 |
| `frontend/src/domain/backtest.ts` | 后端 DTO 的 Zod 边界、十进制字符串和 UTC 字符串校验。 |
| `frontend/src/shared/api/{workbench-api,http-workbench-api,hybrid-workbench-api,mock-workbench-api}.{ts}` | 为 `api` 与 `market-api` 委托真实回测端点；Mock 模式明确报不可用而非伪造回测。 |
| `frontend/src/features/backtests/*` | 创建表单、列表、详情及对应 Vitest 覆盖。 |
| `frontend/src/app/router.tsx`、`frontend/src/components/layout/Sidebar.tsx`、`frontend/src/app/App.test.tsx`、`frontend/src/styles/index.css` | 注册路由、导航、可访问性断言和最小页面样式。 |

## Task 1: 受限历史 K 线读取边界

**Files:**
- Modify: `backend/src/app/market/gateway.py`
- Modify: `backend/src/app/market/binance_usdm.py`
- Modify: `backend/tests/market/test_binance_usdm.py`
- Create: `backend/tests/market/test_historical_candles.py`

**Interfaces:**
- Produces: `HistoricalCandleGateway.load_closed_candles(symbol, timeframe, *, start_at, end_at) -> tuple[Candle, ...]`。
- Consumes: 既有 `Candle`、`ContractSymbol`、`MarketTimeframe`、`MarketDataUnavailableError` 和固定的 `/fapi/v1/klines` allowlist。
- Contract: 只接受 `MarketTimeframe.H1`、UTC `start_at < end_at`；最多返回 1,049 根（1,000 根表现区间加 49 根预热）；返回严格升序、无重复且 `close_at <= now` 的 K 线。

- [ ] **Step 1: 写入失败的历史行情契约测试**

```python
@pytest.mark.asyncio
async def test_load_closed_candles_uses_utc_range_and_excludes_open_candle() -> None:
    gateway, transport = _gateway_with_klines(_rows_including_one_open_candle())
    candles = await gateway.load_closed_candles(
        ContractSymbol.BTCUSDT,
        MarketTimeframe.H1,
        start_at=datetime(2026, 7, 1, tzinfo=UTC),
        end_at=datetime(2026, 7, 3, tzinfo=UTC),
    )
    assert [candle.open_at for candle in candles] == [
        datetime(2026, 7, 1, tzinfo=UTC),
        datetime(2026, 7, 1, 1, tzinfo=UTC),
    ]
    assert transport.requests[0].url.params["startTime"] == "1782864000000"
    assert all(candle.close_at <= NOW for candle in candles)
```

- [ ] **Step 2: 运行新测试确认失败**

Run: `uv run pytest tests/market/test_historical_candles.py -v`（在 `backend` 目录）
Expected: FAIL，因为协议和 `load_closed_candles` 尚未定义。

- [ ] **Step 3: 增加协议和最小实现**

```python
class HistoricalCandleGateway(Protocol):
    async def load_closed_candles(
        self,
        symbol: ContractSymbol,
        timeframe: MarketTimeframe,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[Candle, ...]: ...
```

在 `BinanceUsdmPublicMarketGateway` 中实现该方法：验证 UTC 和 `H1`、以 `startTime`/`endTime` 请求既有 K 线端点、限定 `limit=1049`、解析后过滤 `close_at <= self._now()`，再按 `open_at` 排序并拒绝重复时间。不能把范围读失败转换为空数据或最近 200 根 K 线。

- [ ] **Step 4: 加入范围、上限和上游失败回归测试并运行**

```python
with pytest.raises(ValueError, match="UTC"):
    await gateway.load_closed_candles(
        ContractSymbol.BTCUSDT,
        MarketTimeframe.H1,
        start_at=datetime(2026, 7, 1),
        end_at=datetime(2026, 7, 2, tzinfo=UTC),
    )

with pytest.raises(MarketDataUnavailableError, match="公开行情"):
    await rate_limited_gateway.load_closed_candles(
        ContractSymbol.BTCUSDT, MarketTimeframe.H1, start_at=START, end_at=END
    )
```

Run: `uv run pytest tests/market/test_binance_usdm.py tests/market/test_historical_candles.py -v`
Expected: PASS。

- [ ] **Step 5: 提交本任务**

```powershell
git add -- backend/src/app/market/gateway.py backend/src/app/market/binance_usdm.py backend/tests/market/test_binance_usdm.py backend/tests/market/test_historical_candles.py
git commit -m "feat: load bounded closed candles for backtests"
```

### Task 2: 策略契约与确定性均线交叉

**Files:**
- Create: `backend/src/app/strategy/__init__.py`
- Create: `backend/src/app/strategy/contracts.py`
- Create: `backend/src/app/strategy/sma_crossover.py`
- Create: `backend/tests/strategy/test_sma_crossover.py`

**Interfaces:**
- Produces: `IntentAction.OPEN_LONG | CLOSE_LONG`、`TradeIntent`、`SmaCrossoverStrategy.decide(run_id, candles, position_is_open) -> TradeIntent | None`。
- Consumes: 按时间升序的已收盘 `Candle`；策略不接收现金、仓储、HTTP 客户端或下单适配器。
- Contract: `TradeIntent` 含运行 ID、标的、决策时点、动作、策略 ID/版本和不可重复的幂等键，但不含订单价格、金额或数量。

- [ ] **Step 1: 写入策略的失败测试**

```python
def test_sma_crossover_emits_open_only_after_observable_upward_cross() -> None:
    intent = SmaCrossoverStrategy().decide(
        run_id=RUN_ID,
        candles=_candles_for_cross(previous_fast="99", previous_slow="100", fast="101", slow="100"),
        position_is_open=False,
    )
    assert intent is not None
    assert intent.action is IntentAction.OPEN_LONG
    assert intent.decision_at == datetime(2026, 7, 2, 12, tzinfo=UTC)
    assert intent.idempotency_key.startswith(f"{RUN_ID}:sma_crossover:v1:")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/strategy/test_sma_crossover.py -v`
Expected: FAIL，因为策略模块不存在。

- [ ] **Step 3: 实现严格类型的策略契约和最小策略**

```python
class IntentAction(StrEnum):
    OPEN_LONG = "open_long"
    CLOSE_LONG = "close_long"

class TradeIntent(BaseModel):
    run_id: UUID
    symbol: ContractSymbol
    action: IntentAction
    decision_at: datetime
    strategy_id: Literal["sma_crossover"]
    strategy_version: Literal["v1"]
    idempotency_key: str
```

`SmaCrossoverStrategy` 只在 20/50 均线已拥有前一时点与当前时点时发出信号：未持仓时向上穿越开仓，已持仓时向下穿越平仓。它从 `candle.close_price` 计算，不访问后续 K 线。

- [ ] **Step 4: 补充无未来泄漏、平仓和无交叉测试**

```python
def test_strategy_does_not_emit_from_warmup_or_future_candle() -> None:
    assert SmaCrossoverStrategy().decide(RUN_ID, _first_50_candles(), False) is None
    assert SmaCrossoverStrategy().decide(RUN_ID, _candles_before_cross(), False) is None

def test_downward_cross_only_closes_an_open_position() -> None:
    assert SmaCrossoverStrategy().decide(RUN_ID, _downward_cross(), True).action is IntentAction.CLOSE_LONG
    assert SmaCrossoverStrategy().decide(RUN_ID, _downward_cross(), False) is None
```

Run: `uv run pytest tests/strategy/test_sma_crossover.py -v`
Expected: PASS。

- [ ] **Step 5: 提交本任务**

```powershell
git add -- backend/src/app/strategy backend/tests/strategy/test_sma_crossover.py
git commit -m "feat: add deterministic sma crossover strategy"
```

### Task 3: 确定性风险引擎

**Files:**
- Create: `backend/src/app/risk/__init__.py`
- Create: `backend/src/app/risk/contracts.py`
- Create: `backend/src/app/risk/engine.py`
- Create: `backend/tests/risk/test_engine.py`

**Interfaces:**
- Produces: `RiskConfig`、`PortfolioSnapshot`、`RiskDecision`、`RiskEngine.evaluate(intent, portfolio, close_price)`。
- Consumes: `TradeIntent`；返回的批准决策包含风险计算出的目标数量，拒绝决策包含稳定的 `RiskRejectionCode`。
- Contract: 默认配置为最大敞口 95%、收盘价止损 5%、单日已实现亏损 3%、峰值回撤熔断 15%、风险退出后冷却 3 根；不做空、不加杠杆、一次只允许一个净仓位。

- [ ] **Step 1: 写入风险拒绝和熔断失败测试**

```python
def test_risk_rejects_new_long_after_daily_loss_limit() -> None:
    decision = RiskEngine(DEFAULT_RISK).evaluate(
        _open_intent(),
        PortfolioSnapshot(
            cash=Decimal("9700"),
            equity=Decimal("9700"),
            daily_start_equity=Decimal("10000"),
            daily_realized_loss=Decimal("300"),
        ),
        close_price=Decimal("100"),
    )
    assert decision.approved is False
    assert decision.reason is RiskRejectionCode.DAILY_LOSS_LIMIT

def test_drawdown_circuit_breaker_allows_only_close_intent() -> None:
    assert RiskEngine(DEFAULT_RISK).evaluate(_open_intent(), _halted_portfolio(), Decimal("100")).approved is False
    assert RiskEngine(DEFAULT_RISK).evaluate(_close_intent(), _halted_portfolio(), Decimal("100")).approved is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/risk/test_engine.py -v`
Expected: FAIL，因为风险模块不存在。

- [ ] **Step 3: 实现风险配置、状态和批准计算**

```python
class RiskDecision(BaseModel):
    approved: bool
    reason: RiskRejectionCode | None = None
    quantity: Decimal | None = None
    risk_exit: bool = False

def evaluate(
    self, intent: TradeIntent, portfolio: PortfolioSnapshot, close_price: Decimal
) -> RiskDecision: ...
```

开仓数量必须为 `floor((equity * max_exposure_fraction) / close_price)` 的正 `Decimal`，且不能超过现金；平仓使用当前实际持仓数量。先判定熔断、做空/重复开仓、冷却、日亏损、止损与敞口，再返回结果。拒绝不改变组合状态。

- [ ] **Step 4: 补充最大敞口、止损、冷却和单一仓位测试**

```python
def test_stop_loss_requests_close_only_after_closed_price_threshold() -> None:
    decision = RiskEngine(DEFAULT_RISK).risk_exit_for(_open_portfolio(entry_price="100"), Decimal("95"))
    assert decision.action is IntentAction.CLOSE_LONG

def test_open_is_rejected_during_three_candle_cooldown() -> None:
    assert RiskEngine(DEFAULT_RISK).evaluate(_open_intent(), _cooling_portfolio(), Decimal("100")).reason is RiskRejectionCode.COOLDOWN
```

Run: `uv run pytest tests/risk/test_engine.py -v`
Expected: PASS。

- [ ] **Step 5: 提交本任务**

```powershell
git add -- backend/src/app/risk backend/tests/risk/test_engine.py
git commit -m "feat: add deterministic backtest risk engine"
```

### Task 4: 模拟订单状态机与撮合器

**Files:**
- Create: `backend/src/app/execution/__init__.py`
- Create: `backend/src/app/execution/contracts.py`
- Create: `backend/src/app/execution/simulator.py`
- Create: `backend/tests/execution/test_simulator.py`

**Interfaces:**
- Produces: `SimulatedOrder`、`OrderStatus`、`SimulatedFill`、`SimulatedExecutionService.submit_and_fill(order, candle)`。
- Consumes: 经批准的 `RiskDecision`、下一根 `Candle` 的开盘价和冻结的 `ExecutionConfig`。
- Contract: 买入成交价为 `open_price * (1 + slippage_rate)`，卖出为 `open_price * (1 - slippage_rate)`；手续费为 `filled_quantity * fill_price * fee_rate`；填充量为请求量乘以确定性 `fill_ratio`。

- [ ] **Step 1: 写入手续费、滑点、部分成交的失败测试**

```python
def test_buy_fill_applies_adverse_slippage_fee_and_partial_ratio() -> None:
    fill = SimulatedExecutionService(_config(fill_ratio="0.5")).submit_and_fill(
        _buy_order(quantity="2"), _candle(open_price="100")
    )
    assert fill.price == Decimal("100.05")
    assert fill.quantity == Decimal("1")
    assert fill.fee == Decimal("0.10005")
    assert fill.status is OrderStatus.PARTIALLY_FILLED
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/execution/test_simulator.py -v`
Expected: FAIL，因为模拟执行模块不存在。

- [ ] **Step 3: 实现纯模拟成交模型**

```python
class SimulatedExecutionService:
    def submit_and_fill(self, order: SimulatedOrder, candle: Candle) -> SimulatedFill:
        signed_slippage = self._config.slippage_rate if order.is_buy else -self._config.slippage_rate
        price = candle.open_price * (Decimal("1") + signed_slippage)
        quantity = order.requested_quantity * self._config.fill_ratio
        return SimulatedFill.from_order(order, price=price, quantity=quantity, fee=quantity * price * self._config.fee_rate)
```

校验填充比例在 `(0, 1]`、订单量与价格为正，拒绝意图不得进入该服务。成交记录需保留订单幂等键、下单/成交 UTC 时间、请求量、成交量、价格、手续费和状态。

- [ ] **Step 4: 补充卖出、全额成交、非正输入与幂等键保留测试**

```python
def test_sell_fill_uses_downward_slippage() -> None:
    assert SimulatedExecutionService(DEFAULT_EXECUTION).submit_and_fill(
        _sell_order(), _candle(open_price="100")
    ).price == Decimal("99.95")
```

Run: `uv run pytest tests/execution/test_simulator.py -v`
Expected: PASS。

- [ ] **Step 5: 提交本任务**

```powershell
git add -- backend/src/app/execution backend/tests/execution/test_simulator.py
git commit -m "feat: add auditable simulated execution"
```

### Task 5: 纯回放编排器、指标与无未来泄漏验证

**Files:**
- Create: `backend/src/app/research/__init__.py`
- Create: `backend/src/app/research/backtests/__init__.py`
- Create: `backend/src/app/research/backtests/contracts.py`
- Create: `backend/src/app/research/backtests/engine.py`
- Create: `backend/src/app/research/backtests/repository.py`
- Create: `backend/tests/research/backtests/test_engine.py`

**Interfaces:**
- Produces: `BacktestRequest`、`BacktestRunStatus`、`BacktestAuditEvent`、`BacktestSummary`、`BacktestResult`、`ExpectedBacktestFailure`、`BacktestRepository`、`BacktestStorageUnavailableError`、`BacktestNotFoundError` 与 `DeterministicBacktestEngine.run(run_id, request, candles)`。
- Consumes: 策略、风险引擎、模拟执行服务和已验证的 K 线元组。
- Contract: 输入前 49 根可作预热；回放区间最多 1,000 根连续的 1h K 线；意图在当前收盘产生、下一根开盘才进入模拟执行；最后持仓按最后收盘价盯市。

- [ ] **Step 1: 写入回放顺序和结果失败测试**

```python
def test_engine_executes_a_signal_on_the_next_candle_open_without_future_access() -> None:
    result = _engine().run(RUN_ID, _request(), _candles_with_cross_then_open("110"))
    fill = next(event for event in result.events if event.kind is BacktestEventKind.FILL)
    assert fill.occurred_at == datetime(2026, 7, 2, 13, tzinfo=UTC)
    assert fill.payload["price"] == "110.055"
    assert result.summary.candle_count == 1

def test_engine_marks_open_position_to_last_close_instead_of_forcing_an_exit() -> None:
    result = _engine().run(RUN_ID, _request(), _candles_that_leave_long_open())
    assert result.summary.open_position_quantity > Decimal("0")
    assert result.summary.unrealized_pnl is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/research/backtests/test_engine.py -v`
Expected: FAIL，因为回测编排器不存在。

- [ ] **Step 3: 实现连续性校验、事件序列和指标计算**

```python
class ExpectedBacktestFailure(RuntimeError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message

class BacktestRequest(BaseModel):
    symbol: Literal[ContractSymbol.BTCUSDT]
    timeframe: Literal[MarketTimeframe.H1]
    start_at: datetime
    end_at: datetime
    initial_cash: Decimal

    @property
    def warmup_start_at(self) -> datetime:
        return self.start_at - timedelta(hours=49)

class BacktestRepository(Protocol):
    async def create_pending(self, request: BacktestRequest, *, occurred_at: datetime) -> PersistedBacktestRun: ...
    async def complete(self, run_id: UUID, result: BacktestResult, candles: tuple[Candle, ...], *, occurred_at: datetime) -> PersistedBacktestRun: ...
    async def fail(self, run_id: UUID, *, code: str, message: str, occurred_at: datetime) -> PersistedBacktestRun: ...
    async def list(self, filters: BacktestFilters) -> BacktestPage: ...
    async def get_by_id(self, run_id: UUID) -> PersistedBacktestRun: ...

class DeterministicBacktestEngine:
    def run(self, run_id: UUID, request: BacktestRequest, candles: tuple[Candle, ...]) -> BacktestResult:
        self._validate_contiguous_h1_candles(candles, request)
        for index, candle in enumerate(candles):
            self._fill_orders_scheduled_for(candle.open_at, candle)
            self._evaluate_close(candles[: index + 1], candle)
        return self._build_result(last_close=candles[-1].close_price)
```

`BacktestAuditEvent.payload` 只保存 JSON 值且所有 `Decimal` 先格式化为字符串。摘要至少含初始资金、最终权益、净/已实现/未实现盈亏、收益率、最大回撤、胜率、已平仓交易数、成交数、拒绝数、当前仓位和快照哈希；无亏损样本时利润因子为 `null`。

- [ ] **Step 4: 补充缺口、重复意图、拒绝审计、熔断与部分成交集成测试**

```python
def test_engine_rejects_missing_hour_before_strategy_execution() -> None:
    with pytest.raises(ValueError, match="连续"):
        _engine().run(RUN_ID, _request(), _candles_with_one_hour_gap())

def test_duplicate_idempotency_key_creates_one_order_and_one_fill() -> None:
    result = _engine(strategy=_duplicate_signal_strategy()).run(RUN_ID, _request(), _candles())
    assert sum(event.kind is BacktestEventKind.FILL for event in result.events) == 1
```

Run: `uv run pytest tests/research/backtests/test_engine.py tests/strategy tests/risk tests/execution -v`
Expected: PASS。

- [ ] **Step 5: 提交本任务**

```powershell
git add -- backend/src/app/research backend/tests/research/backtests/test_engine.py
git commit -m "feat: add deterministic candle replay engine"
```

### Task 6: 回测 PostgreSQL 模型、迁移和仓储

**Files:**
- Create: `backend/alembic/versions/0005_create_backtests.py`
- Create: `backend/src/app/infrastructure/persistence/models/backtests.py`
- Create: `backend/src/app/infrastructure/persistence/backtest_repository.py`
- Create: `backend/tests/persistence/test_backtest_repository.py`
- Modify: `backend/tests/persistence/test_migrations.py`

**Interfaces:**
- Produces: `SqlAlchemyBacktestRepository` 对 Task 5 `BacktestRepository` 的 `create_pending`、`complete`、`fail`、`list`、`get_by_id` 实现。
- Consumes: `BacktestRequest`、`BacktestResult`、`BacktestAuditEvent`、`Candle` 和既有 `async_sessionmaker[AsyncSession]`。
- Contract: `backtest_runs` 保存配置/哈希/摘要，`backtest_candles` 保存有唯一 `(run_id, sequence)` 的 OHLCV，`backtest_events` 保存有唯一 `(run_id, sequence)` 的追加式事件；K 线和事件使用数据库触发器阻止 `UPDATE`/`DELETE`。

- [ ] **Step 1: 写入迁移与仓储失败测试**

```python
@pytest.mark.asyncio
async def test_repository_completes_run_with_immutable_snapshot_and_events(migrated_database) -> None:
    repository = SqlAlchemyBacktestRepository(migrated_database.session_factory)
    pending = await repository.create_pending(_request(), occurred_at=NOW)
    completed = await repository.complete(pending.id, _result(), _candles(), occurred_at=NOW)
    assert completed.status is BacktestRunStatus.COMPLETED
    with pytest.raises(DBAPIError):
        async with migrated_database.session_factory.begin() as session:
            await session.execute(text("DELETE FROM backtest_events"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/persistence/test_backtest_repository.py -v`
Expected: FAIL，因为迁移、ORM 模型和仓储不存在。

- [ ] **Step 3: 建立 `0005` 迁移与 ORM 映射**

```python
revision = "0005_create_backtests"
down_revision = "0004_create_trade_journal"

op.create_table(
    "backtest_runs",
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("status", sa.String(length=16), nullable=False),
    sa.Column("strategy_id", sa.String(length=64), nullable=False),
    sa.Column("strategy_version", sa.String(length=32), nullable=False),
    sa.Column("parameters", postgresql.JSONB(), nullable=False),
    sa.Column("risk_config", postgresql.JSONB(), nullable=False),
    sa.Column("execution_config", postgresql.JSONB(), nullable=False),
    sa.Column("metrics", postgresql.JSONB(), nullable=True),
    sa.Column("failure_code", sa.String(length=64), nullable=True),
)
```

在同一迁移中创建 `backtest_candles`（UTC OHLCV、`NUMERIC(38,18)`）与 `backtest_events`（枚举字符串、JSONB 载荷），建立外键、唯一/查询索引、检查约束和两个不可变触发器；`downgrade()` 以相反顺序删除专属触发器、表和索引。ORM 模型字段必须与迁移一致。

- [ ] **Step 4: 实现仓储原子状态转换并扩展迁移测试**

```python
async def fail(self, run_id: UUID, *, code: str, message: str, occurred_at: datetime) -> PersistedBacktestRun:
    async with self._session_factory.begin() as session:
        record = await _get_pending_run_for_update(session, run_id)
        record.status = BacktestRunStatus.FAILED.value
        record.failure_code = code
        record.failure_message = message
        record.finished_at = occurred_at
        return _to_persisted_run(record)
```

验证：测试临时 schema 中三张表存在、数值列为 `numeric`、快照/事件不可变、完成操作完整写入或回滚、失败记录不含成交/摘要、列表按创建时间倒序且详情返回稳定序列。

Run: `uv run pytest tests/persistence/test_migrations.py tests/persistence/test_backtest_repository.py -v`
Expected: PASS。

- [ ] **Step 5: 提交本任务**

```powershell
git add -- backend/alembic/versions/0005_create_backtests.py backend/src/app/infrastructure/persistence/models/backtests.py backend/src/app/infrastructure/persistence/backtest_repository.py backend/tests/persistence/test_migrations.py backend/tests/persistence/test_backtest_repository.py
git commit -m "feat: persist auditable backtest runs"
```

### Task 7: 回测服务、FastAPI 端点与应用注入

**Files:**
- Create: `backend/src/app/research/backtests/service.py`
- Create: `backend/src/app/api/routes/backtests.py`
- Create: `backend/tests/api/test_backtests.py`
- Modify: `backend/src/app/api/router.py`
- Modify: `backend/src/app/api/errors.py`
- Modify: `backend/src/app/main.py`

**Interfaces:**
- Produces: `BacktestService.start(request) -> PersistedBacktestRun`、`BacktestService.list(filters)`、`BacktestService.get(run_id)`；`POST /api/v1/backtests`、`GET /api/v1/backtests`、`GET /api/v1/backtests/{run_id}`。
- Consumes: `HistoricalCandleGateway`、`BacktestRepository` 和 `DeterministicBacktestEngine`。
- Contract: `create_app` 允许为测试注入历史行情、仓储和时钟；缺少 `DATABASE_URL` 时使用不可用仓储并返回安全 `503`；找不到运行返回 `404`。

- [ ] **Step 1: 写入 API 的失败测试**

```python
@pytest.mark.asyncio
async def test_backtest_routes_create_list_and_detail() -> None:
    app = _app(FakeHistoricalGateway(), FakeBacktestRepository())
    created = await _request(app, "POST", "/api/v1/backtests", _payload())
    listed = await _request(app, "GET", "/api/v1/backtests?page=1&page_size=20")
    detail = await _request(app, "GET", f"/api/v1/backtests/{created.json()['id']}")
    assert created.status_code == 201
    assert created.json()["status"] == "completed"
    assert listed.json()["total"] == 1
    assert detail.json()["events"][0]["kind"] == "decision"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/api/test_backtests.py -v`
Expected: FAIL，因为路由与服务不存在。

- [ ] **Step 3: 实现协调服务和 Pydantic API 边界**

```python
class BacktestService:
    async def start(self, request: BacktestRequest) -> PersistedBacktestRun:
        pending = await self._repository.create_pending(request, occurred_at=self._clock())
        try:
            candles = await self._history.load_closed_candles(
                request.symbol, request.timeframe, start_at=request.warmup_start_at, end_at=request.end_at
            )
            result = self._engine.run(pending.id, request, candles)
            return await self._repository.complete(pending.id, result, candles, occurred_at=self._clock())
        except MarketDataUnavailableError as error:
            await self._repository.fail(pending.id, code=error.code, message=str(error), occurred_at=self._clock())
            raise
        except ExpectedBacktestFailure as error:
            return await self._repository.fail(pending.id, code=error.code, message=error.safe_message, occurred_at=self._clock())
```

`POST` 只接受 `BTCUSDT`、`1h`、最多 1,000 根表现 K 线和正初始资金；响应、列表和详情都使用显式 Pydantic DTO。将 `BacktestStorageUnavailableError` 注册为 `503`，将 `BacktestNotFoundError` 注册为既有安全 `404`，并把历史行情的 `MarketDataUnavailableError` 保持为 `503`。

- [ ] **Step 4: 增加注入、验证和安全失败测试**

```python
assert (await _request(app, "POST", "/api/v1/backtests", _payload(symbol="ETHUSDT"))).status_code == 422
unavailable = await _request(create_app(), "POST", "/api/v1/backtests", _payload())
assert unavailable.status_code == 503
assert "postgres" not in unavailable.text.lower()
```

Run: `uv run pytest tests/api/test_backtests.py tests/api/test_market.py tests/api/test_trades.py -v`
Expected: PASS。

- [ ] **Step 5: 提交本任务**

```powershell
git add -- backend/src/app/research/backtests/repository.py backend/src/app/research/backtests/service.py backend/src/app/api/routes/backtests.py backend/src/app/api/router.py backend/src/app/api/errors.py backend/src/app/main.py backend/tests/api/test_backtests.py
git commit -m "feat: expose deterministic backtest API"
```

### Task 8: 前端领域模型与真实 HTTP/Hybrid 委托

**Files:**
- Create: `frontend/src/domain/backtest.ts`
- Create: `frontend/src/domain/backtest.test.ts`
- Modify: `frontend/src/shared/api/workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.ts`
- Modify: `frontend/src/shared/api/hybrid-workbench-api.ts`
- Modify: `frontend/src/shared/api/mock-workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.test.ts`
- Modify: `frontend/src/shared/api/hybrid-workbench-api.test.ts`

**Interfaces:**
- Produces: `BacktestRequest`、`BacktestRunSummary`、`BacktestRunDetail`、`BacktestFilters` 与 `WorkbenchApi.startBacktest/listBacktests/getBacktest`。
- Consumes: `/api/v1/backtests` 的 snake_case 分页响应和 camelCase DTO 响应。
- Contract: `HttpWorkbenchApi` 和 `HybridWorkbenchApi` 的回测操作一律调用远端；`MockWorkbenchApi` 对这些操作拒绝并说明需连接本地后端，绝不生成回测内容。

- [ ] **Step 1: 写入 Zod/HTTP 的失败测试**

```ts
it("posts a validated backtest request and parses decimal strings", async () => {
  const api = new HttpWorkbenchApi({ baseUrl: "http://localhost:8000" });
  await expect(api.startBacktest(backtestRequest)).resolves.toMatchObject({
    status: "completed",
    summary: { finalEquity: "10123.45" },
  });
  expect(fetchMock).toHaveBeenCalledWith(
    new URL("/api/v1/backtests", "http://localhost:8000"),
    expect.objectContaining({ method: "POST" }),
  );
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- --run src/domain/backtest.test.ts src/shared/api/http-workbench-api.test.ts src/shared/api/hybrid-workbench-api.test.ts`（在 `frontend` 目录）
Expected: FAIL，因为回测领域模型和 API 方法不存在。

- [ ] **Step 3: 实现前端契约和客户端调用**

```ts
export interface WorkbenchApi {
  startBacktest(input: BacktestRequest): Promise<BacktestRunDetail>;
  listBacktests(filters: BacktestFilters): Promise<Page<BacktestRunSummary>>;
  getBacktest(backtestId: string): Promise<BacktestRunDetail>;
}

startBacktest(input: BacktestRequest): Promise<BacktestRunDetail> {
  const payload = backtestRequestSchema.parse(input);
  return this.transport.request("/api/v1/backtests", backtestRunDetailSchema, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
}
```

`backtest.ts` 必须复用 `positiveDecimalStringSchema`、`utcIsoStringSchema`、`uuidSchema` 和 `paginationSchema`，校验 `symbol === "BTCUSDT"`、`timeframe === "1h"`、开始时间早于结束时间，并为所有从 API 返回的金额保留字符串。

- [ ] **Step 4: 测试远端失败不会变为 Mock**

```ts
await expect(
  new HybridWorkbenchApi(new MockWorkbenchApi(), remoteApi({ listBacktests: async () => Promise.reject(unavailable) }))
    .listBacktests({ page: 1, pageSize: 20 }),
).rejects.toBe(unavailable);

await expect(new MockWorkbenchApi().startBacktest(backtestRequest)).rejects.toThrow(
  "策略回测需要连接本地后端",
);
```

Run: `npm run test -- --run src/domain/backtest.test.ts src/shared/api/http-workbench-api.test.ts src/shared/api/hybrid-workbench-api.test.ts`
Expected: PASS。

- [ ] **Step 5: 提交本任务**

```powershell
git add -- frontend/src/domain/backtest.ts frontend/src/domain/backtest.test.ts frontend/src/shared/api/workbench-api.ts frontend/src/shared/api/http-workbench-api.ts frontend/src/shared/api/hybrid-workbench-api.ts frontend/src/shared/api/mock-workbench-api.ts frontend/src/shared/api/http-workbench-api.test.ts frontend/src/shared/api/hybrid-workbench-api.test.ts
git commit -m "feat: connect backtest API clients"
```

### Task 9: 策略回测页面、详情与导航

**Files:**
- Create: `frontend/src/features/backtests/backtest-form-schema.ts`
- Create: `frontend/src/features/backtests/BacktestForm.tsx`
- Create: `frontend/src/features/backtests/BacktestListPage.tsx`
- Create: `frontend/src/features/backtests/BacktestDetailPage.tsx`
- Create: `frontend/src/features/backtests/BacktestPages.test.tsx`
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `frontend/src/styles/index.css`

**Interfaces:**
- Produces: `/backtests` 创建/列表页和 `/backtests/:backtestId` 详情页；导航名称为“策略回测”。
- Consumes: Task 8 的 `WorkbenchApi` 回测方法和领域 schema。
- Contract: 表单只有开始时间（UTC）、结束时间（UTC）和初始资金可编辑；20/50、费用 0.1%、滑点 0.05% 和风险限制只读显示；页面不出现“下单”“开仓”“自动交易”作为可执行操作。

- [ ] **Step 1: 写入页面的失败测试**

```tsx
it("submits a UTC range, then renders the persisted result summary", async () => {
  const user = userEvent.setup();
  renderBacktests(new RecordingBacktestApi());
  await user.clear(screen.getByLabelText("开始时间（UTC）"));
  await user.type(screen.getByLabelText("开始时间（UTC）"), "2026-06-01T00:00:00Z");
  await user.click(screen.getByRole("button", { name: "运行历史回测" }));
  expect(await screen.findByText("最大回撤")).toBeVisible();
  expect(screen.getByText("历史模拟，不等同于模拟盘或实盘")).toBeVisible();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- --run src/features/backtests/BacktestPages.test.tsx src/app/App.test.tsx`
Expected: FAIL，因为页面、路由与导航不存在。

- [ ] **Step 3: 实现表单、列表和详情的安全状态**

```tsx
const runsQuery = useQuery({
  queryKey: ["backtests", { page: 1, pageSize: 20 }],
  queryFn: () => api.listBacktests({ page: 1, pageSize: 20 }),
});

const startMutation = useMutation({
  mutationFn: (input: BacktestRequest) => api.startBacktest(input),
  onSuccess: (run) => void navigate(`/backtests/${encodeURIComponent(run.id)}`),
});
```

复用 `PageState` 处理加载、空、错误和不可用状态；错误文案只显示中文通用提示，不回显 HTTP 细节。详情按固定顺序显示运行配置、行情快照元数据、摘要、已平仓交易、未平仓盯市（如有）和审计事件。为表格提供中文 `aria-label`。

- [ ] **Step 4: 加入导航和可访问性回归测试**

```tsx
expect(screen.getByRole("link", { name: "策略回测" })).toHaveAttribute("href", "/backtests");
expect(await screen.findByRole("table", { name: "回测运行记录" })).toBeVisible();
expect(screen.getByRole("link", { name: "查看回测详情" })).toHaveAttribute("href", "/backtests/00000000-0000-0000-0000-000000000701");
```

Run: `npm run test -- --run src/features/backtests/BacktestPages.test.tsx src/app/App.test.tsx`
Expected: PASS。

- [ ] **Step 5: 提交本任务**

```powershell
git add -- frontend/src/features/backtests frontend/src/app/router.tsx frontend/src/components/layout/Sidebar.tsx frontend/src/app/App.test.tsx frontend/src/styles/index.css
git commit -m "feat: add auditable backtest workbench pages"
```

### Task 10: 全量验证、真实服务人工检查与差异说明复核

**Files:**
- Modify only when a test exposes a defect: only a file already owned by Tasks 1–9.
- Verify: `backend/tests/**`、`frontend/src/**` 与回测设计说明。

**Interfaces:**
- Consumes: 已完成的 API、迁移和前端页面。
- Produces: 可复现的验证记录；不新增功能、不更改账户权限、不执行真实交易。

- [ ] **Step 1: 执行后端全量静态检查和测试**

```powershell
uv run ruff check .
uv run pyright
uv run pytest
```

在 `backend` 目录依次执行。Expected: 每条命令退出码为 0；若失败，先按 `superpowers:systematic-debugging` 定位根因、添加或调整最小回归测试，再重复本步骤。

- [ ] **Step 2: 执行前端全量静态检查、测试和构建**

```powershell
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

在 `frontend` 目录依次执行。Expected: 每条命令退出码为 0；测试不得依赖真实 Binance、PostgreSQL 生产数据库或浏览器的本地时间。

- [ ] **Step 3: 在独立测试数据库进行迁移与 API 冒烟检查**

```powershell
$originalDatabaseUrl = $env:DATABASE_URL
$testDatabaseUrl = uv run python -c "from app.shared.config import AppSettings; print(AppSettings().test_database_url.get_secret_value())"
$env:DATABASE_URL = $testDatabaseUrl
try {
  uv run alembic upgrade head
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
} finally {
  $env:DATABASE_URL = $originalDatabaseUrl
}
```

只在已配置的 `TEST_DATABASE_URL` 环境中运行迁移，并使用本地前端的 `VITE_DATA_MODE=market-api` 或 `api` 创建一个短区间 BTCUSDT 1h 回测。确认列表与详情可见、返回的行情故障不会出现 Mock 结果、页面显示“历史模拟，不等同于模拟盘或实盘”。完成后停止本地服务；不删除任何用户数据。

- [ ] **Step 4: 复核范围和提交验证修复（如存在）**

```powershell
git status --short
git diff --check
git diff --cached --check
```

确认不会暂存 `frontend/.env.example`，不会出现凭证或连接串。仅当步骤 1–3 产生修复时，按实际文件精确暂存并提交：

```powershell
git commit -m "fix: verify deterministic backtest workflow"
```

在该提交命令前，逐个写出并复查 `git status --short` 报出的回测文件路径；若没有修复，不创建空提交。

## Plan Self-Review

- 规格中的真实 `BTCUSDT` 1h 数据、预热、下一根开盘、`TradeIntent`、风险规则、滑点/手续费/部分成交、盯市、审计快照、PostgreSQL、API、前端和模拟盘差异说明，分别由 Tasks 1–9 实现。
- 无未来数据泄漏、费用/滑点/部分成交、风控拒绝/熔断、幂等与审计关联、迁移/API 和前端真实失败行为均有具体测试任务。
- 所有公共接口均在前置任务中命名，后续任务仅消费这些接口；所有金额和时间边界与设计说明一致。
- 本计划不添加依赖、不改 `.env`、不触及真实交易，并将现有用户删除的前端环境示例排除在每个提交之外。
