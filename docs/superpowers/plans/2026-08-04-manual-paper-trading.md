# 手动触发的可审计模拟盘 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为本地研究工作台提供一个可持久化、可审计、由手动意图或 SMA 策略评估驱动的 BTCUSDT 模拟盘账户，且不产生真实交易。

**Architecture:** 新增 `paper_trading` 领域，以活动账户 ID 作为既有 `TradeIntent.run_id` 的内部执行上下文。服务端固定一次公开行情快照，纯领域引擎将意图交给既有确定性风控与模拟撮合器，再由单事务 PostgreSQL 仓储保存账户状态、不可变订单/成交/账本/审计。前端仅通过 `WorkbenchApi` 委托真实 HTTP；Mock 模式明确不可用。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、SQLAlchemy async、Alembic、PostgreSQL、pytest、Ruff、Pyright；React 19、TypeScript、Zod、TanStack Query、Vitest。

## Global Constraints

- 仅支持 `BTCUSDT`、单一活动模拟账户和单一净多仓；不支持做空、杠杆、多资产、限价单、挂单、部分平仓、自动轮询或后台任务。
- 手动开多、手动平多、策略评估和风险退出都必须先形成结构化 `TradeIntent`，再由确定性 `RiskEngine` 放行；LLM、浏览器和请求参数不能绕过风控。
- 公开行情只经现有 Binance USDⓈ-M 公共适配器读取；不得添加私有端点、账户读取、API Key、Secret、Passphrase、真实下单、撤单、资金划转或提现能力。
- 公开行情快照不可用时安全失败，不伪造成交，也不降级为 Mock 数据。
- 所有金额、数量、价格、费率、现金、权益和盈亏使用 `Decimal` 与 `NUMERIC(38,18)`；HTTP 用规范十进制字符串；禁止 `float`。
- 所有时间必须是带时区的 UTC；历史回测继续保持“收盘决策、下一根开盘成交”，模拟盘使用固定行情快照即时模拟市价成交。
- 订单、成交、行情快照、账本与审计事件必须追加式不可变；账户只能从 `active` 变为 `archived`，且归档前必须空仓。
- 数据库集成测试只能使用 `TEST_DATABASE_URL` 创建的隔离 schema；不得修改 `.env`、凭证、生产连接或用户现有数据。
- 不新增生产依赖；保留工作区中用户已有的 `frontend/.env.example` 删除，不得暂存、恢复或提交该文件。

---

## File Structure

| 文件 | 责任 |
| --- | --- |
| `backend/src/app/strategy/contracts.py` | 扩展结构化意图来源，允许策略、手动与内部风险退出共用 `TradeIntent`。 |
| `backend/src/app/strategy/sma_crossover.py`、`backend/src/app/research/backtests/engine.py` | 显式标注策略/风险意图来源，保持既有回测语义。 |
| `backend/src/app/execution/contracts.py`、`backend/src/app/execution/simulator.py` | 定义冻结即时行情报价，并在不改变 K 线回测入口的前提下支持即时模拟成交。 |
| `backend/src/app/paper_trading/contracts.py` | 模拟账户、持仓、快照、账本、审计、动作结果与安全异常的 Pydantic 契约。 |
| `backend/src/app/paper_trading/engine.py` | 纯状态转换：盯市、日亏损重置、冷却期推进、风险退出、风控、模拟成交与账本增量。 |
| `backend/src/app/paper_trading/repository.py` | 应用层依赖的异步仓储协议。 |
| `backend/src/app/paper_trading/service.py` | 协调账户读取、一次公开报价、策略 K 线、幂等、纯引擎与持久化。 |
| `backend/src/app/infrastructure/persistence/models/paper_trading.py` | SQLAlchemy 模型。 |
| `backend/src/app/infrastructure/persistence/paper_trading_repository.py` | 带行锁、幂等读取和不可变事件写入的 PostgreSQL 仓储。 |
| `backend/alembic/versions/0006_create_paper_trading.py` | 建立模拟盘表、约束、索引与不可变性触发器。 |
| `backend/src/app/api/routes/paper_accounts.py` | 模拟账户 REST 请求/响应模型与路由。 |
| `backend/src/app/api/{router.py,errors.py}`、`backend/src/app/main.py` | 注册路由、错误信封和实际/不可用依赖注入。 |
| `backend/tests/{strategy,execution,paper_trading,persistence,api}/test_*.py` | 领域、服务、迁移、仓储和 API 的测试先行覆盖。 |
| `frontend/src/domain/paper-trading.ts` | 后端 JSON 边界的 Zod schema 与 TypeScript 类型。 |
| `frontend/src/shared/api/{workbench-api,http-workbench-api,hybrid-workbench-api,mock-workbench-api}.ts` | 模拟盘 Workbench API 契约及真实/Mock 委托行为。 |
| `frontend/src/features/paper-trading/*` | 创建账户、列表、详情、操作面板和审计时间线。 |
| `frontend/src/app/router.tsx`、`frontend/src/components/layout/Sidebar.tsx`、`frontend/src/styles/index.css` | 注册路由、导航与最小页面样式。 |
| `frontend/src/features/paper-trading/PaperTradingPages.test.tsx`、`frontend/src/shared/api/*test.ts` | UI 流程、重复提交和 HTTP 契约回归。 |
| `frontend/README.md` | 说明模拟盘启动条件、即时成交语义和与历史回测的差异。 |

## Task 1: 通用意图来源与即时模拟报价

**Files:**
- Modify: `backend/src/app/strategy/contracts.py`
- Modify: `backend/src/app/strategy/sma_crossover.py`
- Modify: `backend/src/app/research/backtests/engine.py`
- Modify: `backend/src/app/execution/contracts.py`
- Modify: `backend/src/app/execution/simulator.py`
- Modify: `backend/tests/strategy/test_sma_crossover.py`
- Modify: `backend/tests/execution/test_simulator.py`

**Interfaces:**
- Produces `IntentSource.STRATEGY | MANUAL | RISK` and a frozen `TradeIntent` whose `run_id` remains the internal execution-context ID.
- Produces `ExecutionQuote(symbol, price, observed_at, fetched_at, source)` and `SimulatedExecutionService.submit_and_fill_at_quote(order, quote)`.
- Preserves `SimulatedExecutionService.submit_and_fill(order, candle)` for historical backtest callers.

- [ ] **Step 1: 写入意图来源与即时成交的失败测试**

```python
def test_manual_intent_is_valid_without_strategy_metadata() -> None:
    intent = TradeIntent(
        run_id=ACCOUNT_ID,
        symbol=ContractSymbol.BTCUSDT,
        action=IntentAction.OPEN_LONG,
        decision_at=NOW,
        source=IntentSource.MANUAL,
        idempotency_key="account:manual:request-1",
    )
    assert intent.source is IntentSource.MANUAL
    assert intent.strategy_id is None


def test_quote_fill_uses_quote_time_and_adverse_slippage() -> None:
    fill = SimulatedExecutionService(DEFAULT_EXECUTION_CONFIG).submit_and_fill_at_quote(
        _order(IntentAction.OPEN_LONG),
        ExecutionQuote(
            symbol=ContractSymbol.BTCUSDT,
            price=Decimal("100"),
            observed_at=NOW,
            fetched_at=NOW,
            source="binance_usdm_public",
        ),
    )
    assert fill.price == Decimal("100.0500")
    assert fill.filled_at == NOW
```

- [ ] **Step 2: 运行测试确认接口尚不存在**

Run: `uv run pytest tests/strategy/test_sma_crossover.py tests/execution/test_simulator.py -v`（在 `backend/`）

Expected: FAIL，指出 `IntentSource` 或 `ExecutionQuote` 尚未定义。

- [ ] **Step 3: 实现最小通用契约与报价成交入口**

```python
class IntentSource(StrEnum):
    STRATEGY = "strategy"
    MANUAL = "manual"
    RISK = "risk"


class TradeIntent(BaseModel):
    run_id: UUID
    symbol: ContractSymbol
    action: IntentAction
    decision_at: datetime
    source: IntentSource = IntentSource.STRATEGY
    strategy_id: str | None = None
    strategy_version: str | None = None
    idempotency_key: str
```

为 `TradeIntent` 添加模型校验：`STRATEGY` 必须有非空 `strategy_id` 与 `strategy_version`；`MANUAL` 和 `RISK` 必须没有策略元数据。`SmaCrossoverStrategy` 明确设置 `source=IntentSource.STRATEGY`，回测的风险退出明确设置 `source=IntentSource.RISK`。

```python
class ExecutionQuote(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    symbol: ContractSymbol
    price: Decimal
    observed_at: datetime
    fetched_at: datetime
    source: str


def submit_and_fill_at_quote(
    self, order: SimulatedOrder, quote: ExecutionQuote
) -> SimulatedFill:
    # 用 quote.price 计算双向不利滑点、手续费和 fill_ratio；filled_at 为 quote.observed_at。
```

让原 `submit_and_fill` 从 K 线开盘价构造报价后调用新方法，保证历史回测现有断言不变。

- [ ] **Step 4: 补齐来源校验、卖出滑点和回测兼容回归**

```python
with pytest.raises(ValidationError, match="策略意图"):
    TradeIntent(
        run_id=ACCOUNT_ID,
        symbol=ContractSymbol.BTCUSDT,
        action=IntentAction.OPEN_LONG,
        decision_at=NOW,
        source=IntentSource.STRATEGY,
        idempotency_key="missing-meta",
    )

sell_fill = service.submit_and_fill_at_quote(_order(IntentAction.CLOSE_LONG), quote)
assert sell_fill.price == Decimal("99.9500")

assert service.submit_and_fill(_order(IntentAction.OPEN_LONG), candle).filled_at == candle.open_at
```

Run: `uv run pytest tests/strategy/test_sma_crossover.py tests/execution/test_simulator.py tests/research/backtests/test_engine.py -v`

Expected: PASS；回测仍以下一根 K 线开盘成交。

- [ ] **Step 5: 提交任务**

```powershell
git add -- backend/src/app/strategy/contracts.py backend/src/app/strategy/sma_crossover.py backend/src/app/research/backtests/engine.py backend/src/app/execution/contracts.py backend/src/app/execution/simulator.py backend/tests/strategy/test_sma_crossover.py backend/tests/execution/test_simulator.py
git commit -m "feat: support sourced intents and quote fills"
```

## Task 2: 模拟盘领域契约与纯状态转换引擎

**Files:**
- Create: `backend/src/app/paper_trading/__init__.py`
- Create: `backend/src/app/paper_trading/contracts.py`
- Create: `backend/src/app/paper_trading/engine.py`
- Create: `backend/tests/paper_trading/test_contracts.py`
- Create: `backend/tests/paper_trading/test_engine.py`

**Interfaces:**
- Produces immutable `PaperAccount`, `PaperPosition`, `PaperMarketSnapshot`, `PaperLedgerEntry`, `PaperAuditEvent`, `PaperActionOutcome`, `PaperTransition`, `PaperAccountPage` and typed paper-trading exceptions.
- Produces `PaperTradingEngine.apply(account, position, intent, quote, latest_closed_candle_at) -> PaperTransition` without database or HTTP access.
- Consumes `RiskEngine`, `ExecutionQuote`, `SimulatedExecutionService`, `TradeIntent`, `DEFAULT_RISK_CONFIG` and `DEFAULT_EXECUTION_CONFIG`.

- [ ] **Step 1: 写入账户生命周期、风控退出和账本的失败测试**

```python
def test_engine_opens_at_risk_limited_quote_and_appends_balanced_ledger() -> None:
    transition = PaperTradingEngine().apply(
        account=_account(cash="10000"),
        position=PaperPosition.empty(ACCOUNT_ID),
        intent=_manual_intent(IntentAction.OPEN_LONG),
        quote=_quote("100"),
        latest_closed_candle_at=HOUR_CLOSE,
    )
    assert transition.position.quantity > Decimal("0")
    assert transition.account.cash < Decimal("10000")
    assert [event.kind for event in transition.events] == [
        PaperEventKind.INTENT,
        PaperEventKind.RISK_APPROVED,
        PaperEventKind.ORDER,
        PaperEventKind.FILL,
    ]


def test_engine_closes_an_existing_position_as_risk_exit_before_manual_open() -> None:
    transition = PaperTradingEngine().apply(
        account=_account(cash="500"),
        position=_open_position(quantity="1", entry_price="100"),
        intent=_manual_intent(IntentAction.OPEN_LONG),
        quote=_quote("94"),
        latest_closed_candle_at=HOUR_CLOSE,
    )
    assert transition.outcome.kind is PaperActionOutcomeKind.RISK_EXIT
    assert transition.position.quantity == Decimal("0")
    assert transition.account.cooldown_remaining == 3
```

- [ ] **Step 2: 运行纯领域测试确认模块尚不存在**

Run: `uv run pytest tests/paper_trading/test_contracts.py tests/paper_trading/test_engine.py -v`

Expected: FAIL，因为 `app.paper_trading` 尚未定义。

- [ ] **Step 3: 实现冻结契约和无副作用引擎**

在 `contracts.py` 定义下列枚举与模型：

```python
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

class ManualPaperIntent(BaseModel):
    client_request_id: UUID
    action: Literal[IntentAction.OPEN_LONG, IntentAction.CLOSE_LONG]
```

`PaperAccount` 保存现金、权益、峰值权益、UTC 日起始权益、当日已实现损失、当前冷却根数、最后观察的 1h 收盘时间、固定风险/执行配置与状态。`PaperPosition` 保存数量、平均入场价、剩余入场成本与开仓时间。所有模型拒绝 `float`、非 UTC 时间和未知字段。

`PaperTradingEngine.apply` 必须按以下顺序执行：以报价盯市并在 UTC 日变更时重置日损失；根据最新新增 1h 收盘数递减冷却；若已有仓位触发止损或回撤熔断，生成 `IntentSource.RISK` 的平仓意图、即时成交、设置冷却期并将原手动/策略意图标记为被风险退出取代；否则评估传入意图，写入风控决定、订单、成交和现金/持仓账本。无意图时仅写入 `NO_SIGNAL` 事件与报价盯市结果。

- [ ] **Step 4: 覆盖边界状态并运行测试**

```python
rejected_close = PaperTradingEngine().apply(
    account=_account(cash="10000"),
    position=PaperPosition.empty(ACCOUNT_ID),
    intent=_manual_intent(IntentAction.CLOSE_LONG),
    quote=_quote("100"),
    latest_closed_candle_at=HOUR_CLOSE,
)
assert rejected_close.events[-1].kind is PaperEventKind.RISK_REJECTED

invalid_quote = PaperTradingEngine().apply(
    account=_account(cash="10000"),
    position=PaperPosition.empty(ACCOUNT_ID),
    intent=_manual_intent(IntentAction.OPEN_LONG),
    quote=_quote("0"),
    latest_closed_candle_at=HOUR_CLOSE,
)
assert invalid_quote.outcome.reason == "invalid_mark_price"
assert transition_after_three_new_hour_closes.account.cooldown_remaining == 0
assert transition_after_new_utc_day.account.daily_realized_loss == Decimal("0")
```

同时断言开多使用最大敞口、平多关闭全部仓位、手续费计入现金与已实现盈亏、账户权益不以 `float` 计算。

Run: `uv run pytest tests/paper_trading/test_contracts.py tests/paper_trading/test_engine.py -v`

Expected: PASS。

- [ ] **Step 5: 提交任务**

```powershell
git add -- backend/src/app/paper_trading backend/tests/paper_trading
git commit -m "feat: add deterministic paper trading engine"
```

## Task 3: 模拟盘 PostgreSQL Schema 与不可变性迁移

**Files:**
- Create: `backend/alembic/versions/0006_create_paper_trading.py`
- Create: `backend/src/app/infrastructure/persistence/models/paper_trading.py`
- Modify: `backend/src/app/infrastructure/persistence/models/__init__.py`
- Modify: `backend/tests/persistence/test_migrations.py`

**Interfaces:**
- Produces ORM records `PaperAccountRecord`, `PaperPositionRecord`, `PaperMarketSnapshotRecord`, `PaperOrderRecord`, `PaperFillRecord`, `PaperLedgerEntryRecord`, `PaperAuditEventRecord`.
- Produces migration revision `0006_create_paper_trading` whose `down_revision` is `0005_create_backtests`.
- Enforces one active account, a single position per account, unique intent event idempotency, and immutability of snapshots/orders/fills/ledger/events.

- [ ] **Step 1: 写入隔离迁移与约束的失败测试**

```python
async def test_paper_trading_migration_creates_one_active_account_constraint(
    migrated_database: MigratedDatabase,
) -> None:
    async with migrated_database.session_factory.begin() as session:
        await session.execute(
            text(
                "INSERT INTO paper_accounts (id, status, symbol, initial_cash, cash, equity, "
                "peak_equity, daily_start_equity, daily_realized_loss, daily_day, "
                "cooldown_remaining, risk_config, execution_config, created_at) "
                "VALUES (:id, 'active', 'BTCUSDT', 10000, 10000, 10000, 10000, 10000, 0, "
                "DATE '2026-08-04', 0, '{}'::jsonb, '{}'::jsonb, :created_at)"
            ),
            {"id": ACCOUNT_ID, "created_at": NOW},
        )
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO paper_accounts (id, status, symbol, initial_cash, cash, equity, "
                    "peak_equity, daily_start_equity, daily_realized_loss, daily_day, "
                    "cooldown_remaining, risk_config, execution_config, created_at) "
                    "VALUES (:id, 'active', 'BTCUSDT', 5000, 5000, 5000, 5000, 5000, 0, "
                    "DATE '2026-08-04', 0, '{}'::jsonb, '{}'::jsonb, :created_at)"
                ),
                {"id": SECOND_ACCOUNT_ID, "created_at": NOW},
            )
```

在同一测试模块中断言向 `paper_audit_events` 写入两个 `kind = 'intent'`、相同账户和幂等键的记录违反唯一索引，并断言对 `paper_market_snapshots`、`paper_orders`、`paper_fills`、`paper_ledger_entries`、`paper_audit_events` 的 `UPDATE` 与 `DELETE` 触发 `DBAPIError`。

- [ ] **Step 2: 运行迁移测试确认表尚不存在**

Run: `uv run pytest tests/persistence/test_migrations.py -v`

Expected: FAIL，指出 `paper_accounts` 或其约束不存在。

- [ ] **Step 3: 建立迁移和 SQLAlchemy 映射**

迁移创建以下字段：

```text
paper_accounts: id, status, symbol, initial_cash, cash, equity, peak_equity,
  daily_start_equity, daily_realized_loss, daily_day, cooldown_remaining,
  last_closed_candle_at, risk_config, execution_config, created_at, archived_at
paper_positions: account_id, quantity, average_entry_price, remaining_entry_cost, opened_at, updated_at
paper_market_snapshots: id, account_id, price, source, observed_at, fetched_at, payload_hash
paper_orders: id, account_id, snapshot_id, action, source, idempotency_key, submitted_at, requested_quantity, status
paper_fills: id, order_id, account_id, quantity, price, fee, filled_at, status
paper_ledger_entries: account_id, sequence, occurred_at, kind, cash_delta, position_delta, realized_pnl, fee, cash_after, quantity_after
paper_audit_events: account_id, sequence, kind, occurred_at, idempotency_key, payload
```

`paper_accounts` 以部分唯一索引 `WHERE status = 'active'` 限制单一活动账户；所有账户强制 `symbol = 'BTCUSDT'`。`paper_positions` 的数量、现金、权益和时间字段有非负/UTC/状态检查约束。为 `paper_audit_events` 建立部分唯一索引 `WHERE kind = 'intent'`，实现包括拒绝和无信号在内的幂等动作定位。

对五类不可变表创建独立 PL/pgSQL 函数与 `BEFORE UPDATE OR DELETE` 触发器；`paper_accounts` 和 `paper_positions` 保持可控的当前状态记录，由仓储行锁更新。

- [ ] **Step 4: 运行迁移回归并验证降级路径**

Run: `uv run pytest tests/persistence/test_migrations.py tests/persistence/test_backtest_repository.py -v`

Expected: PASS；新迁移没有改变既有回测触发器或迁移隔离行为。

- [ ] **Step 5: 提交任务**

```powershell
git add -- backend/alembic/versions/0006_create_paper_trading.py backend/src/app/infrastructure/persistence/models/paper_trading.py backend/src/app/infrastructure/persistence/models/__init__.py backend/tests/persistence/test_migrations.py
git commit -m "feat: add immutable paper trading schema"
```

## Task 4: 事务性 PostgreSQL 模拟盘仓储

**Files:**
- Create: `backend/src/app/paper_trading/repository.py`
- Create: `backend/src/app/infrastructure/persistence/paper_trading_repository.py`
- Create: `backend/tests/persistence/test_paper_trading_repository.py`

**Interfaces:**
- Produces `PaperTradingRepository` with `create_account`, `list`, `get_by_id`, `find_outcome`, `apply_transition`, `record_market_failure` and `archive` coroutine methods.
- `apply_transition(account_id, expected_idempotency_key, transition) -> PaperAccountDetail` locks the account row and returns the stored result if an intent event already owns the key.
- `archive(account_id, occurred_at) -> PaperAccountDetail` rejects any nonzero position.

- [ ] **Step 1: 写入仓储原子性、幂等和归档的失败测试**

```python
async def test_repository_persists_one_transition_and_reuses_its_idempotent_outcome(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyPaperTradingRepository(migrated_database.session_factory)
    account = await repository.create_account(_create_request(), occurred_at=NOW)
    first = await repository.apply_transition(account.id, "manual:1", _open_transition(), occurred_at=NOW)
    replay = await repository.apply_transition(account.id, "manual:1", _open_transition(), occurred_at=NOW)
    assert replay == first
    assert await _count_rows(migrated_database, "paper_fills") == 1


async def test_repository_rejects_archive_while_position_is_open(
    migrated_database: MigratedDatabase,
) -> None:
    repository = SqlAlchemyPaperTradingRepository(migrated_database.session_factory)
    account = await repository.create_account(_create_request(), occurred_at=NOW)
    await repository.apply_transition(account.id, "manual:open", _open_transition(), occurred_at=NOW)
    with pytest.raises(PaperAccountStateError, match="持仓"):
        await repository.archive(account.id, occurred_at=NOW)
```

- [ ] **Step 2: 运行测试确认仓储接口尚不存在**

Run: `uv run pytest tests/persistence/test_paper_trading_repository.py -v`

Expected: FAIL，因为 `PaperTradingRepository` 与 `SqlAlchemyPaperTradingRepository` 尚未定义。

- [ ] **Step 3: 实现仓储协议和 SQLAlchemy 实现**

```python
class PaperTradingRepository(Protocol):
    async def create_account(self, request: PaperAccountCreate, *, occurred_at: datetime) -> PaperAccountDetail:
        raise NotImplementedError

    async def find_outcome(self, account_id: UUID, idempotency_key: str) -> PaperActionOutcome | None:
        raise NotImplementedError

    async def apply_transition(
        self, account_id: UUID, idempotency_key: str, transition: PaperTransition, *, occurred_at: datetime
    ) -> PaperAccountDetail:
        raise NotImplementedError
```

`apply_transition` 进入 `async with session_factory.begin()`，以 `SELECT * FROM paper_accounts WHERE id = :account_id FOR UPDATE` 锁定账户和仓位；先读取 `kind='intent'` 的相同幂等键，存在时反序列化并返回原动作结果。不存在时先写入 intent 事件，再插入快照、订单、成交、账本和其余事件，最后更新账户与仓位状态。数据库唯一约束冲突时重新读取既有 intent，不能将并发重试转换为重复成交。

将 SQLAlchemy 异常包装为 `PaperStorageUnavailableError`，但不吞掉 `PaperAccountNotFoundError`、`PaperAccountStateError` 或领域校验错误。

- [ ] **Step 4: 覆盖读取、不可变记录、并发和归档后只读**

```python
left, right = await asyncio.gather(
    repository.apply_transition(account.id, "manual:concurrent", _open_transition(), occurred_at=NOW),
    repository.apply_transition(account.id, "manual:concurrent", _open_transition(), occurred_at=NOW),
)
assert left.action_outcome == right.action_outcome
assert await _count_rows(migrated_database, "paper_orders") == 1
```

再断言列表按 `created_at DESC, id DESC` 分页、归档账户拒绝新的 transition、空仓归档保留全部账本和审计记录。

Run: `uv run pytest tests/persistence/test_paper_trading_repository.py tests/persistence/test_migrations.py -v`

Expected: PASS。

- [ ] **Step 5: 提交任务**

```powershell
git add -- backend/src/app/paper_trading/repository.py backend/src/app/infrastructure/persistence/paper_trading_repository.py backend/tests/persistence/test_paper_trading_repository.py
git commit -m "feat: persist auditable paper accounts"
```

## Task 5: 公开行情协调、手动意图与策略评估服务

**Files:**
- Create: `backend/src/app/paper_trading/service.py`
- Create: `backend/tests/paper_trading/test_service.py`

**Interfaces:**
- Produces `PaperTradingService.create_account`, `list_accounts`, `get_account`, `submit_manual_intent`, `evaluate_strategy` and `archive_account`。
- Consumes `PublicMarketGateway`, `HistoricalCandleGateway`, `PaperTradingRepository`, `PaperTradingEngine` and `SmaCrossoverStrategy`.
- Every manual call uses one `get_market(BTCUSDT, (H1,))` response as its execution quote; every strategy evaluation additionally loads exactly 51 closed H1 candles ending at the latest closed hour.

- [ ] **Step 1: 写入服务层的失败测试**

```python
@pytest.mark.asyncio
async def test_manual_open_uses_one_public_quote_and_persists_manual_intent() -> None:
    service, market, repository = _service(detail=_market_detail(last_price="100"))
    result = await service.submit_manual_intent(ACCOUNT_ID, ManualPaperIntent(
        client_request_id=REQUEST_ID,
        action=IntentAction.OPEN_LONG,
    ))
    assert market.get_market_calls == 1
    assert result.action_outcome.source is IntentSource.MANUAL
    assert repository.transitions[0].snapshot.price == Decimal("100")


@pytest.mark.asyncio
async def test_strategy_without_cross_persists_no_signal_without_order() -> None:
    result = await service.evaluate_strategy(ACCOUNT_ID)
    assert result.action_outcome.kind is PaperActionOutcomeKind.NO_SIGNAL
    assert result.orders == ()
```

- [ ] **Step 2: 运行测试确认服务尚不存在**

Run: `uv run pytest tests/paper_trading/test_service.py -v`

Expected: FAIL，因为 `PaperTradingService` 尚未定义。

- [ ] **Step 3: 实现服务的固定市场读取与状态转换编排**

```python
class PaperTradingService:
    async def submit_manual_intent(
        self, account_id: UUID, request: ManualPaperIntent
    ) -> PaperAccountDetail:
        raise NotImplementedError

    async def evaluate_strategy(self, account_id: UUID) -> PaperAccountDetail:
        raise NotImplementedError
```

在任何外部请求前调用 `repository.find_outcome`；命中时直接返回既有账户详情。未命中时读取账户、请求一次公开市场详情并从 `detail.summary.last_price`、`detail.summary.freshness` 构造 `ExecutionQuote` 与 `PaperMarketSnapshot`。手动操作构造 `run_id=account_id`、`source=MANUAL` 的 `TradeIntent`；策略操作加载 51 根严格连续且已收盘的 H1 K 线，以账户当前持仓调用 `SmaCrossoverStrategy.decide`，并用账户、策略版本、最新 K 线收盘时间生成幂等键。

两条路径都将最新已收盘 H1 时间传给纯引擎以推进冷却期和 UTC 日损失状态。`MarketDataUnavailableError` 时调用 `record_market_failure` 写入安全审计事件后重新抛出；若存储不可用，仅抛出 `PaperStorageUnavailableError`，不得宣称事件已保存。

- [ ] **Step 4: 覆盖策略幂等、风险退出、失败与数据范围**

```python
first = await service.evaluate_strategy(ACCOUNT_ID)
second = await service.evaluate_strategy(ACCOUNT_ID)
assert second == first
assert market.history_calls == 1

with pytest.raises(MarketDataUnavailableError, match="公开行情"):
    await unavailable_service.submit_manual_intent(ACCOUNT_ID, _manual_open())
assert unavailable_repository.failure_events[0].code == "public_market_unavailable"
```

补充断言：策略收到少于 51 根、非连续或未收盘 K 线时安全失败；报价与账户标的不一致时拒绝；已触发止损的仓位先执行风险平仓，原操作不再产生第二笔成交。

Run: `uv run pytest tests/paper_trading/test_service.py tests/paper_trading/test_engine.py -v`

Expected: PASS。

- [ ] **Step 5: 提交任务**

```powershell
git add -- backend/src/app/paper_trading/service.py backend/tests/paper_trading/test_service.py
git commit -m "feat: add manual paper trading service"
```

## Task 6: 模拟账户 FastAPI 契约与应用注入

**Files:**
- Create: `backend/src/app/api/routes/paper_accounts.py`
- Create: `backend/tests/api/test_paper_accounts.py`
- Modify: `backend/src/app/api/router.py`
- Modify: `backend/src/app/api/errors.py`
- Modify: `backend/src/app/main.py`

**Interfaces:**
- Exposes `POST/GET /api/v1/paper-accounts`, `GET /api/v1/paper-accounts/{account_id}`, `POST /manual-intents`, `POST /strategy-evaluations` and `POST /archive`.
- Returns camelCase Pydantic response models; accepts only a strict initial-cash string, strict manual request UUID/action and no extra fields.
- Maps absent database configuration to `503 paper_storage_unavailable`; maps unknown account to `404 not_found`; maps state conflicts to safe `409` envelopes.

- [ ] **Step 1: 写入路由、校验和安全失败的测试**

```python
@pytest.mark.asyncio
async def test_paper_account_routes_create_manual_action_list_and_detail() -> None:
    app = _app(FakePaperTradingService())
    created = await _request(app, "POST", "/api/v1/paper-accounts", {"initialCash": "10000"})
    action = await _request(app, "POST", f"/api/v1/paper-accounts/{created.json()['id']}/manual-intents", {
        "clientRequestId": str(REQUEST_ID), "action": "open_long",
    })
    assert created.status_code == 201
    assert action.status_code == 200
    assert action.json()["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_paper_account_routes_do_not_expose_storage_details_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.main.AppSettings", lambda: AppSettings(database_url=None))
    response = await _request(create_app(), "GET", "/api/v1/paper-accounts")
    assert response.json()["code"] == "paper_storage_unavailable"
    assert "postgres" not in response.text.lower()
```

- [ ] **Step 2: 运行 API 测试确认路由不存在**

Run: `uv run pytest tests/api/test_paper_accounts.py -v`

Expected: FAIL，响应为路由未找到或导入错误。

- [ ] **Step 3: 实现 API 模型、路由和真实/不可用依赖**

```python
router = APIRouter(prefix="/paper-accounts", tags=["paper-trading"])

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_paper_account(
    payload: PaperAccountCreateRequest,
    service: PaperTradingService = Depends(_service),
) -> PaperAccountDetailResponse:
    account = await service.create_account(PaperAccountCreate(initial_cash=Decimal(payload.initial_cash)))
    return _to_detail_response(account)

@router.post("/{account_id}/manual-intents")
async def submit_manual_intent(
    account_id: UUID,
    payload: ManualPaperIntentRequest,
    service: PaperTradingService = Depends(_service),
) -> PaperAccountDetailResponse:
    account = await service.submit_manual_intent(
        account_id,
        ManualPaperIntent(client_request_id=payload.client_request_id, action=payload.action),
    )
    return _to_detail_response(account)
```

沿用 `backtests.py` 的 `_ApiModel` 别名规则与 `DecimalValue`/`UtcDateTime` 约束。`main.create_app` 接收可注入的 `paper_repository`、`paper_clock` 和可选公开市场/历史 K 线依赖；`DATABASE_URL` 缺失时安装 `_UnavailablePaperTradingRepository`。将真实 `SqlAlchemyPaperTradingRepository` 和 `PaperTradingService` 放入 `app.state`，注册路由与专用异常处理器。

- [ ] **Step 4: 覆盖边界请求和既有路由回归**

```python
invalid = await _request(app, "POST", "/api/v1/paper-accounts", {"initialCash": 10000})
assert invalid.status_code == 422

archived = await _request(app, "POST", f"/api/v1/paper-accounts/{ACCOUNT_ID}/archive")
assert archived.status_code == 409
assert archived.json()["code"] == "paper_account_state_invalid"
```

Run: `uv run pytest tests/api/test_paper_accounts.py tests/api/test_backtests.py tests/api/test_health.py -v`

Expected: PASS；错误信封不泄露数据库或上游正文。

- [ ] **Step 5: 提交任务**

```powershell
git add -- backend/src/app/api/routes/paper_accounts.py backend/src/app/api/router.py backend/src/app/api/errors.py backend/src/app/main.py backend/tests/api/test_paper_accounts.py
git commit -m "feat: expose safe paper trading API"
```

## Task 7: 前端领域模型与真实 API 委托

**Files:**
- Create: `frontend/src/domain/paper-trading.ts`
- Create: `frontend/src/domain/paper-trading.test.ts`
- Modify: `frontend/src/shared/api/workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.ts`
- Modify: `frontend/src/shared/api/hybrid-workbench-api.ts`
- Modify: `frontend/src/shared/api/mock-workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.test.ts`
- Modify: `frontend/src/shared/api/hybrid-workbench-api.test.ts`
- Modify: `frontend/src/shared/api/mock-workbench-api.test.ts`

**Interfaces:**
- Produces Zod schemas and types `PaperAccountSummary`, `PaperAccountDetail`, `PaperAccountCreate`, `ManualPaperIntent`, `PaperAccountFilters` and paper audit/ledger/snapshot types.
- Adds `createPaperAccount`, `listPaperAccounts`, `getPaperAccount`, `submitPaperManualIntent`, `evaluatePaperStrategy` and `archivePaperAccount` to `WorkbenchApi` and `RemoteWorkbenchApi`.
- `HttpWorkbenchApi` maps camelCase UI contracts to `/api/v1/paper-accounts`; `HybridWorkbenchApi` delegates them; `MockWorkbenchApi` rejects every paper operation with one explicit backend-required message.

- [ ] **Step 1: 写入 Zod 边界和 HTTP 映射的失败测试**

```ts
it("serializes a manual paper intent with its client request id", async () => {
  await api.submitPaperManualIntent(accountId, {
    clientRequestId: "00000000-0000-0000-0000-000000000901",
    action: "open_long",
  });
  expect(new URL(calls[0]![0] as URL).pathname).toBe(
    `/api/v1/paper-accounts/${accountId}/manual-intents`,
  );
});

it("does not invent a mock paper account", async () => {
  await expect(mockApi.listPaperAccounts({ page: 1, pageSize: 20 })).rejects.toThrow(
    "模拟盘需要本地 API 与数据库",
  );
});
```

- [ ] **Step 2: 运行前端 API 测试确认方法不存在**

Run: `npm run test -- --run src/domain/paper-trading.test.ts src/shared/api/http-workbench-api.test.ts`（在 `frontend/`）

Expected: FAIL，因为纸面账户 schema 与 API 方法尚未定义。

- [ ] **Step 3: 实现严格领域 schema 与客户端方法**

```ts
export const paperAccountCreateSchema = z.object({
  initialCash: positiveDecimalStringSchema,
});

export const manualPaperIntentSchema = z.object({
  clientRequestId: uuidSchema,
  action: z.enum(["open_long", "close_long"]),
});
```

详情 schema 必须校验 BTCUSDT、`active | archived`、所有十进制字符串、UTC 时间、订单/成交/账本/审计事件和固定快照元数据。HTTP 客户端对 POST 传递 `Content-Type: application/json`，对分页使用既有 `createWirePageSchema`，并用 `encodeURIComponent` 包裹 UUID 路径段。Hybrid 与 HTTP 的响应都必须再次通过 Zod parse。

- [ ] **Step 4: 覆盖错误传播、归档与现有 API 回归**

```ts
await expect(api.archivePaperAccount(accountId)).rejects.toMatchObject({
  name: "WorkbenchHttpError",
  code: "paper_account_state_invalid",
});

await expect(hybridApi.evaluatePaperStrategy(accountId)).resolves.toMatchObject({
  id: accountId,
});
```

Run: `npm run test -- --run src/domain/paper-trading.test.ts src/shared/api/http-workbench-api.test.ts src/shared/api/hybrid-workbench-api.test.ts src/shared/api/mock-workbench-api.test.ts`

Expected: PASS，Mock 不生成虚构资金、订单或收益。

- [ ] **Step 5: 提交任务**

```powershell
git add -- frontend/src/domain/paper-trading.ts frontend/src/domain/paper-trading.test.ts frontend/src/shared/api/workbench-api.ts frontend/src/shared/api/http-workbench-api.ts frontend/src/shared/api/hybrid-workbench-api.ts frontend/src/shared/api/mock-workbench-api.ts frontend/src/shared/api/http-workbench-api.test.ts frontend/src/shared/api/hybrid-workbench-api.test.ts frontend/src/shared/api/mock-workbench-api.test.ts
git commit -m "feat: connect paper trading API clients"
```

## Task 8: 模拟盘页面、导航和交互回归

**Files:**
- Create: `frontend/src/features/paper-trading/paper-account-form-schema.ts`
- Create: `frontend/src/features/paper-trading/PaperAccountForm.tsx`
- Create: `frontend/src/features/paper-trading/PaperAccountListPage.tsx`
- Create: `frontend/src/features/paper-trading/PaperAccountDetailPage.tsx`
- Create: `frontend/src/features/paper-trading/PaperTradingPages.test.tsx`
- Modify: `frontend/src/app/router.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/styles/index.css`
- Modify: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Exposes `/paper-trading` and `/paper-trading/:accountId` routes plus a “模拟盘”主导航项。
- `PaperAccountForm` accepts a positive decimal initial balance and submits `PaperAccountCreate`.
- Detail page has separate manual open/close, strategy-evaluate and archive mutations; each invalidates its account/list queries after success and disables only its own in-flight action.

- [ ] **Step 1: 写入创建、操作、无信号、归档与重复提交的失败测试**

```tsx
it("creates an account and navigates to its persistent detail", async () => {
  renderAt("/paper-trading", apiWithCreateResult(account));
  await user.type(screen.getByLabelText("初始资金（USDT）"), "10000");
  await user.click(screen.getByRole("button", { name: "创建模拟账户" }));
  expect(await screen.findByRole("heading", { name: "模拟账户详情" })).toBeVisible();
});

it("disables the strategy button while the same evaluation is pending", async () => {
  renderAt(`/paper-trading/${account.id}`, apiWithPendingStrategy());
  await user.click(screen.getByRole("button", { name: "评估 SMA 策略" }));
  expect(screen.getByRole("button", { name: "正在评估策略" })).toBeDisabled();
});
```

- [ ] **Step 2: 运行页面测试确认组件和路由尚不存在**

Run: `npm run test -- --run src/features/paper-trading/PaperTradingPages.test.tsx src/app/App.test.tsx`

Expected: FAIL，因为模拟盘组件、导航和路由尚未定义。

- [ ] **Step 3: 实现页面与安全交互**

列表页在无活动账户时显示 `PaperAccountForm`、初始资金默认 `10000` 与“仅模拟，不连接真实账户或产生真实订单”说明；有历史账户时显示状态、现金、权益、持仓和详情入口。详情页展示现金、权益、已实现/未实现盈亏、最大回撤、BTCUSDT 当前持仓、行情来源/抓取时间、手续费/滑点/风控配置。

```tsx
const strategyMutation = useMutation({
  mutationFn: () => api.evaluatePaperStrategy(accountId),
  onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["paper-account", accountId] }),
});
```

手动按钮只显示“手动开多”“手动平多”；为每次点击创建 `crypto.randomUUID()` 作为 `clientRequestId`。详情页显示订单、成交、账本和审计事件表；无信号、风控拒绝、行情失败与 API 不可用使用 `PageState` 或可访问的 `role="alert"` 安全消息。归档按钮仅在空仓、活动账户时可用，并通过浏览器确认框后二次提交；历史账户无操作按钮。

- [ ] **Step 4: 补齐 Mock 不可用、错误展示和导航回归**

```tsx
renderAt("/paper-trading", rejectingMockApi());
expect(await screen.findByText("模拟盘需要本地 API 与数据库")).toBeVisible();

expect(screen.getByRole("link", { name: "模拟盘" })).toHaveAttribute("href", "/paper-trading");
```

同时断言策略无信号仍显示最新审计事件、风险拒绝不显示成交、归档确认取消时不调用 API、手动请求失败后按钮重新可用。

Run: `npm run test -- --run src/features/paper-trading/PaperTradingPages.test.tsx src/app/App.test.tsx`

Expected: PASS。

- [ ] **Step 5: 提交任务**

```powershell
git add -- frontend/src/features/paper-trading frontend/src/app/router.tsx frontend/src/components/layout/Sidebar.tsx frontend/src/styles/index.css frontend/src/app/App.test.tsx
git commit -m "feat: add auditable paper trading pages"
```

## Task 9: 使用说明、全量验证与受限真实行情检查

**Files:**
- Modify: `frontend/README.md`
- Modify: `docs/superpowers/specs/2026-08-04-manual-paper-trading-design.md`（仅把状态改为“已实施并验证”，并记录验证结果）

**Interfaces:**
- Documents the local HTTP prerequisites, the manual-only trigger model, immediate snapshot-fill semantics, safety exclusions and difference from historical backtests.
- Does not introduce any deployment change, private credential, automatic worker or real trade surface.

- [ ] **Step 1: 写入文档断言或阅读回归测试**

```ts
it("does not expose a live execution label in the application shell", () => {
  render(<App />);
  expect(screen.queryByText(/真实下单|连接交易所账户|自动执行/)).not.toBeInTheDocument();
});
```

在现有 `App.test.tsx` 添加上述断言，确保新增页面不弱化现有安全边界。

- [ ] **Step 2: 运行安全文案测试确认基线**

Run: `npm run test -- --run src/app/App.test.tsx`

Expected: PASS；该步骤确认新增测试的安全边界基线。

- [ ] **Step 3: 更新本地使用说明与设计状态**

在 `frontend/README.md` 增加“模拟盘”章节：要求后端、PostgreSQL 与 `VITE_DATA_MODE=api` 或 `market-api` 可用；说明创建账户、手动操作、策略评估均由用户点击触发；声明即时行情快照成交与历史回测下一根开盘成交不可直接比较；明确没有真实账户或下单功能。设计文档只记录实际执行过的命令与结果，不记录 URL 连接串、密码或用户账户内容。

- [ ] **Step 4: 执行完整质量门槛和一次受限手工检查**

Run in `backend/`:

```powershell
uv run ruff check .
uv run pyright
uv run pytest
```

Run in `frontend/`:

```powershell
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

仅在本地后端、PostgreSQL 与公开 Binance 行情可用时：创建一个模拟账户，手动触发一次策略评估，并验证页面显示的是“无信号、风控结果或模拟成交”之一且包含来源/快照时间。不得调用任何私有交易所端点、真实账户或真实订单接口。

- [ ] **Step 5: 记录验证、检查工作区并提交任务**

```powershell
git diff --check
git status --short
git add -- frontend/README.md frontend/src/app/App.test.tsx docs/superpowers/specs/2026-08-04-manual-paper-trading-design.md
git commit -m "docs: verify manual paper trading workflow"
```

确认暂存列表不含 `frontend/.env.example`；若质量检查失败，保留失败证据并修复根因后重新运行相同命令。

## Plan Self-Review

- 设计中的共享账户、手动/策略来源、BTCUSDT 限制、即时快照成交、归档空仓约束、不可变审计、Mock 行为、API、界面与验证均至少映射到一个任务。
- 第 1 任务定义的 `IntentSource`、`ExecutionQuote` 和成交方法被第 2、5 任务一致使用；第 2 任务的 `PaperTransition` 被第 4、5 任务一致持久化与编排；第 7 任务的前端 API 方法被第 8 任务一致调用。
- 所有测试步骤先于对应实现，所有迁移测试使用隔离测试 schema；每项提交均列出精确暂存范围，排除用户已有的环境示例文件删除。
- 计划没有新增外部依赖、后台任务、真实账户访问或真实交易入口。

## Execution Handoff

本计划保存在 `docs/superpowers/plans/2026-08-04-manual-paper-trading.md`。实现将使用当前会话的逐任务内联执行方式，每个任务完成后运行其列出的验证命令并进行提交；不分派代理，确保工作保持在用户批准的 `main` 分支范围内。
