# 单账户模拟盘绩效报告 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每个本地模拟盘账户提供可审计、独立口径的绩效快照与权益曲线，并在账户详情页展示。

**Architecture:** 后端在每次账户创建或确定性状态转换时，于现有模拟盘事务内追加账户估值记录。一个纯领域聚合器从账户、持仓、估值、成交、账本与审计事件生成只读 `PaperPerformanceSnapshot`；API 和前端只读取此快照。现有手工日志、全局复盘统计与回测保持不变。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、SQLAlchemy async、Alembic、PostgreSQL、pytest、Ruff、Pyright；React、TypeScript strict、TanStack Query、Zod、Vitest、decimal.js。

## Global Constraints

- 所有金额、数量、价格、手续费和中间计算使用 `Decimal`；前端仅接受规范十进制字符串。
- 所有时间必须是带时区的 UTC 时间；不得把本地时间写入估值、API 或测试夹具。
- 所有交易状态仍只能由 `TradeIntent -> RiskEngine -> SimulatedExecutionService` 推进；本功能是只读统计，不可创建交易意图或绕过风控。
- 不接入交易所私有 API、真实账户、凭证、真实下单、资金操作、后台采集或定时任务。
- 不修改 `.env`、凭证或生产配置；迁移与持久化测试仅使用 `TEST_DATABASE_URL` 的临时 schema。
- `paper_account_valuations`、行情快照、订单、成交、账本与审计事件均为追加式记录；幂等重试不得重复写入估值。
- 不把模拟盘、手工交易日志和回测的指标合并或比较；首期不创建多账户看板。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `backend/src/app/paper_trading/contracts.py` | 增加估值、历史状态、绩效输入和输出 Pydantic 契约。 |
| `backend/src/app/paper_trading/performance.py` | 纯 `Decimal` 绩效聚合，不依赖 HTTP、ORM 或行情网关。 |
| `backend/src/app/paper_trading/repository.py` | 定义读取绩效源数据和追加估值的仓储协议。 |
| `backend/src/app/infrastructure/persistence/models/paper_trading.py` | 映射 `paper_account_valuations`。 |
| `backend/src/app/infrastructure/persistence/paper_trading_repository.py` | 在现有事务中保存估值并一致性读取绩效源数据。 |
| `backend/alembic/versions/0007_create_paper_account_valuations.py` | 创建不可变估值表、索引、触发器，并安全回填迁移基线。 |
| `backend/src/app/paper_trading/service.py` | 暴露只读的 `get_performance` 服务方法。 |
| `backend/src/app/api/routes/paper_accounts.py` | 增加绩效响应模型和 `GET /performance` 路由。 |
| `backend/src/app/main.py` | 让不可用仓储完整实现新增协议。 |
| `frontend/src/domain/paper-trading.ts` | 以 Zod 定义绩效 API 数据契约。 |
| `frontend/src/shared/api/*.ts` | 将绩效读取加入 HTTP、混合、Mock 和公共 API 契约。 |
| `frontend/src/features/paper-trading/PaperPerformancePanel.tsx` | 仅负责 KPI、权益曲线、统计与历史完整性提示。 |
| `frontend/src/features/paper-trading/PaperAccountDetailPage.tsx` | 在账户详情中请求、失效并显示绩效区块。 |
| `frontend/src/styles/index.css` | 添加复用现有研究面板视觉语言的绩效布局样式。 |

## Task 1: 定义不可变绩效契约与纯聚合器

**Files:**
- Modify: `backend/src/app/paper_trading/contracts.py`
- Create: `backend/src/app/paper_trading/performance.py`
- Create: `backend/tests/paper_trading/test_performance.py`

**Interfaces:**
- Consumes: 既有 `PaperAccount`、`PaperPosition`、`PaperLedgerEntry`、`PaperAuditEvent` 与 `SimulatedFill`。
- Produces: `PaperAccountValuation`、`PaperPerformanceData`、`PaperPerformanceSnapshot` 和 `aggregate_paper_performance(data, *, generated_at)`，供仓储、服务和 API 使用。

- [ ] **Step 1: 写出失败的纯聚合测试**

在 `backend/tests/paper_trading/test_performance.py` 中使用固定 UTC 时间和 `Decimal` 构造数据。覆盖初始账户、带未实现盈亏的持仓、带已实现亏损的平仓账本、手续费、最大回撤、策略/风险事件和迁移基线：

```python
snapshot = aggregate_paper_performance(
    _data(
        account=_account(cash="8000", equity="9500"),
        position=_position(quantity="10", remaining_entry_cost="1400"),
        valuations=(
            _valuation(0, "initial", "10000"),
            _valuation(1, "market_valuation", "11000"),
            _valuation(2, "market_valuation", "9500"),
        ),
        ledger_entries=(
            _ledger("open_long", realized_pnl="0"),
            _ledger("close_long", realized_pnl="-600"),
        ),
        fills=(_fill("open_long", fee="3"), _fill("close_long", fee="4")),
        events=(_manual_intent(), _strategy_no_signal(), _risk_rejected()),
    ),
    generated_at=NOW,
)

assert snapshot.net_pnl == Decimal("-500")
assert snapshot.return_fraction == Decimal("-0.05")
assert snapshot.realized_pnl == Decimal("-600")
assert snapshot.unrealized_pnl == Decimal("100")
assert snapshot.total_fee == Decimal("7")
assert snapshot.max_drawdown_amount == Decimal("1500")
assert snapshot.max_drawdown_fraction == Decimal("1500") / Decimal("11000")
assert snapshot.close_win_rate == Decimal("0")
assert snapshot.decision_stats.manual_intent_count == 1
assert snapshot.decision_stats.strategy_evaluation_count == 1
assert snapshot.decision_stats.no_signal_count == 1
assert snapshot.decision_stats.risk_rejected_count == 1
```

添加第二个测试，传入含 `migration_baseline` 的估值序列，断言 `history_status is PaperHistoryStatus.PARTIAL`；没有平仓时断言平仓计数和胜率为零，并且零分母不会抛出异常。

- [ ] **Step 2: 运行测试，确认当前没有聚合器实现**

Run: `uv run pytest tests/paper_trading/test_performance.py -v`（工作目录：`backend`）  
Expected: FAIL，提示无法导入 `app.paper_trading.performance` 或 `PaperAccountValuation`。

- [ ] **Step 3: 在领域契约中加入估值与报告类型**

在 `contracts.py` 中沿用 `_PaperModel`、UTC 验证器和有限 `Decimal` 验证器，定义下列稳定名称：

```python
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
```

验证 `sequence >= 0`、所有余额/数量非负、`peak_equity >= equity`、时间为 UTC；`INITIAL` 必须没有 `snapshot_id`，`MARKET_VALUATION` 必须有关联快照，`MIGRATION_BASELINE` 仅在旧账户拥有最新已存快照时关联它。再定义 `PaperPerformanceData`（账户、持仓、估值、成交、账本、事件），曲线点、决策统计和 `PaperPerformanceSnapshot`。报告字段固定为 `account_id`、`initial_cash`、`current_equity`、`net_pnl`、`return_fraction`、`realized_pnl`、`unrealized_pnl`、`total_fee`、`max_drawdown_amount`、`max_drawdown_fraction`、开/平仓及胜负计数、`close_win_rate`、`decision_stats`、`history_status`、`history_started_at`、`history_ended_at`、`equity_curve`、`generated_at`。

- [ ] **Step 4: 实现最小纯聚合器**

在新模块实现一个不访问 I/O 的入口：

```python
def aggregate_paper_performance(
    data: PaperPerformanceData,
    *,
    generated_at: datetime,
) -> PaperPerformanceSnapshot:
    ordered = tuple(sorted(data.valuations, key=lambda value: value.sequence))
    _validate_valuation_history(data.account, ordered)
    net_pnl = data.account.equity - data.account.initial_cash
    realized_pnl = sum((entry.realized_pnl for entry in data.ledger_entries), Decimal("0"))
    unrealized_pnl = (
        data.account.equity
        - data.account.cash
        - data.position.remaining_entry_cost
    )
    return _snapshot_from_values(
        data,
        ordered=ordered,
        net_pnl=net_pnl,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        generated_at=generated_at,
    )
```

`_snapshot_from_values` 必须从估值曲线计算历史峰值、`peak - equity` 的最大金额回撤和 `(peak - equity) / peak` 的最大比例回撤；只要估值序列含有 `MIGRATION_BASELINE` 就返回 `history_status=partial`，否则返回 `complete`；从 `fills` 累加手续费并按 `IntentAction` 计入开/平仓；从 `close_long` 账本项计算正、负、零平仓与仅由正/负平仓组成的胜率；从事件 `kind` 和受限的 `payload["source"]` 计算手动意图、策略意图/无信号、风控拒绝和风控退出。未知 payload 来源不得提高任何计数。

- [ ] **Step 5: 运行领域测试，确认计算通过**

Run: `uv run pytest tests/paper_trading/test_performance.py -v`（工作目录：`backend`）  
Expected: PASS，包含完整与部分历史、回撤、盈亏、手续费、胜率和事件计数断言。

- [ ] **Step 6: 提交领域契约与聚合器**

```powershell
git add -- backend/src/app/paper_trading/contracts.py backend/src/app/paper_trading/performance.py backend/tests/paper_trading/test_performance.py
git commit -m "feat: add paper performance aggregation"
```

## Task 2: 迁移并在模拟盘事务内追加估值

**Files:**
- Create: `backend/alembic/versions/0007_create_paper_account_valuations.py`
- Modify: `backend/src/app/infrastructure/persistence/models/paper_trading.py`
- Modify: `backend/src/app/paper_trading/repository.py`
- Modify: `backend/src/app/infrastructure/persistence/paper_trading_repository.py`
- Create: `backend/tests/persistence/test_paper_performance_migration.py`
- Modify: `backend/tests/persistence/test_paper_trading_repository.py`

**Interfaces:**
- Consumes: Task 1 的 `PaperAccountValuation` 与 `PaperPerformanceData`。
- Produces: `PaperTradingRepository.get_performance_data(account_id) -> PaperPerformanceData | None`；账户创建和状态转换后的不可变估值记录。

- [ ] **Step 1: 写失败的持久化与迁移测试**

在 `test_paper_trading_repository.py` 中，在创建账户后查询估值记录并断言只有一条：`sequence=0`、`kind=initial`、无快照、现金和权益等于初始资金。应用一次 `_open_transition` 后断言新增 `sequence=1`、`kind=market_valuation`、关联快照、现金/仓位/权益等于转换后账户；重放相同幂等键仍为两条而非三条。

在新 `test_paper_performance_migration.py` 中创建独立临时 schema，先升级至 `0006_create_paper_trading`，插入一个旧账户、持仓和最新行情快照，再升级到 `head`。查询估值表并断言：

```python
assert [(item.sequence, item.kind) for item in valuations] == [
    (0, "initial"),
    (1, "migration_baseline"),
]
assert valuations[0].equity == Decimal("10000")
assert valuations[1].equity == Decimal("9750")
assert valuations[1].snapshot_id == latest_snapshot_id
```

迁移测试使用 `alembic.command.upgrade` 与现有 `TEST_DATABASE_URL` 临时 schema，不接触 `DATABASE_URL`。随后对估值表执行 `UPDATE`，断言 PostgreSQL 拒绝不可变记录。

- [ ] **Step 2: 运行测试，确认表和仓储方法尚不存在**

Run: `uv run pytest tests/persistence/test_paper_trading_repository.py tests/persistence/test_paper_performance_migration.py -v`（工作目录：`backend`）  
Expected: FAIL，提示 `PaperAccountValuationRecord`、`0007` 表或估值写入尚未实现。

- [ ] **Step 3: 编写 `0007` 迁移与 ORM 映射**

在迁移中创建 `paper_account_valuations`，主键为 `(account_id, sequence)`，包含 `kind`、可空 `snapshot_id`、`valued_at`、`cash`、`position_quantity`、`equity`、`peak_equity`。添加：

```python
sa.CheckConstraint("sequence >= 0", name="ck_paper_valuations_nonnegative_sequence")
sa.CheckConstraint(
    "kind IN ('initial', 'market_valuation', 'migration_baseline')",
    name="ck_paper_valuations_kind",
)
sa.CheckConstraint("cash >= 0", name="ck_paper_valuations_nonnegative_cash")
sa.CheckConstraint("position_quantity >= 0", name="ck_paper_valuations_nonnegative_quantity")
sa.CheckConstraint("equity >= 0", name="ck_paper_valuations_nonnegative_equity")
sa.CheckConstraint("peak_equity >= equity", name="ck_paper_valuations_peak_equity")
sa.CheckConstraint(
    "(kind = 'initial' AND snapshot_id IS NULL) OR "
    "(kind = 'market_valuation' AND snapshot_id IS NOT NULL) OR "
    "kind = 'migration_baseline'",
    name="ck_paper_valuations_snapshot_kind",
)
```

添加账户/快照外键、`(account_id, valued_at, sequence)` 索引，以及与 `0006` 相同模式的 `prevent_paper_valuation_mutation` 函数与 `BEFORE UPDATE OR DELETE` 触发器。迁移创建表后先插入每个已有账户的初始点，再为每个旧账户插入 `migration_baseline`：用 `DISTINCT ON (account_id)` 的最新行情快照及其观察时间（若存在），否则使用账户创建时间；两种路径都使用当前账户/仓位状态。这样历史状态可由基线稳定标记为 `partial`，但没有快照时不会伪造价格。降级按“触发器、函数、索引、表”的逆序删除。

在 ORM 模型加入 `PaperAccountValuationRecord`，字段与约束对应迁移定义；在模型导出模块加入此类，确保 Alembic 导入仍可建立 metadata。

- [ ] **Step 4: 扩展仓储协议并实现追加与一致性读取**

在协议中新增：

```python
async def get_performance_data(
    self,
    account_id: UUID,
) -> PaperPerformanceData | None: ...
```

在 `create_account` 的现有事务中，在账户和空仓 `flush` 后追加：

```python
PaperAccountValuationRecord(
    account_id=account_id,
    sequence=0,
    kind=PaperValuationKind.INITIAL.value,
    snapshot_id=None,
    valued_at=occurred_at,
    cash=request.initial_cash,
    position_quantity=Decimal("0"),
    equity=request.initial_cash,
    peak_equity=request.initial_cash,
)
```

在 `apply_transition` 中保存 `snapshot_id` 后，调用 `_next_valuation_sequence` 并按 `transition.account`、`transition.position`、`transition.snapshot.observed_at` 追加 `MARKET_VALUATION`。追加代码必须在幂等事件检查之后，且和账户、持仓、快照、订单、成交、账本、事件处于相同 `session_factory.begin()` 事务。

实现 `get_performance_data`：在一次只读 session 内读取账户、仓位、估值（按 `sequence ASC`）、成交（按时间/ID）、账本（按序号）和审计事件（按序号），转换为 Task 1 的领域对象；账户不存在返回 `None`。不要把估值塞进既有 `PaperAccountDetail`，避免改变既有详情接口负载。

- [ ] **Step 5: 运行迁移和持久化测试，确认可审计性与幂等性**

Run: `uv run pytest tests/persistence/test_paper_trading_repository.py tests/persistence/test_paper_performance_migration.py -v`（工作目录：`backend`）  
Expected: PASS；迁移基线、初始估值、转换估值、不可变触发器和幂等重试均被验证。

- [ ] **Step 6: 提交迁移与仓储改动**

```powershell
git add -- backend/alembic/versions/0007_create_paper_account_valuations.py backend/src/app/infrastructure/persistence/models/paper_trading.py backend/src/app/infrastructure/persistence/models/__init__.py backend/src/app/paper_trading/repository.py backend/src/app/infrastructure/persistence/paper_trading_repository.py backend/tests/persistence/test_paper_trading_repository.py backend/tests/persistence/test_paper_performance_migration.py
git commit -m "feat: persist paper account valuations"
```

## Task 3: 公开只读绩效服务与 API

**Files:**
- Modify: `backend/src/app/paper_trading/service.py`
- Modify: `backend/src/app/api/routes/paper_accounts.py`
- Modify: `backend/src/app/main.py`
- Modify: `backend/tests/api/test_paper_accounts.py`
- Create: `backend/tests/paper_trading/test_performance_service.py`

**Interfaces:**
- Consumes: `PaperTradingRepository.get_performance_data` 与 `aggregate_paper_performance`。
- Produces: `PaperTradingService.get_performance(account_id) -> PaperPerformanceSnapshot` 和 `GET /api/v1/paper-accounts/{account_id}/performance`。

- [ ] **Step 1: 写失败的服务与路由测试**

在 `test_performance_service.py` 使用返回 `PaperPerformanceData` 的 fake 仓储，断言服务以注入 UTC 时钟调用聚合器，并在仓储返回 `None` 时抛出 `PaperAccountNotFoundError`。同时断言该调用没有触发市场网关方法。

在 `test_paper_accounts.py` 的 `FakePaperTradingService` 增加可记录的 `get_performance`，然后添加 API 测试：

```python
response = await _request(
    app,
    "GET",
    f"/api/v1/paper-accounts/{ACCOUNT_ID}/performance",
)

assert response.status_code == 200
assert response.json()["netPnl"] == "-500"
assert response.json()["historyStatus"] == "complete"
assert response.json()["equityCurve"][0]["at"] == "2026-08-04T12:00:00Z"
```

再添加未知 UUID 返回现有 paper 404 错误信封、无数据库时返回 `paper_storage_unavailable` 503 的测试。

- [ ] **Step 2: 运行服务和 API 测试，确认路由尚不存在**

Run: `uv run pytest tests/paper_trading/test_performance_service.py tests/api/test_paper_accounts.py -v`（工作目录：`backend`）  
Expected: FAIL，提示 `get_performance` 或 `/performance` 路由缺失。

- [ ] **Step 3: 实现服务、Pydantic API 响应和路由**

在服务中添加：

```python
async def get_performance(self, account_id: UUID) -> PaperPerformanceSnapshot:
    data = await self._repository.get_performance_data(account_id)
    if data is None:
        raise PaperAccountNotFoundError("未找到模拟账户")
    return aggregate_paper_performance(data, generated_at=self._now())
```

在 `paper_accounts.py` 新增与领域模型一一对应的响应模型：曲线点、决策统计、完整绩效响应。继续使用 `_ApiModel`、`DecimalValue`、`UtcDateTime` 和 camelCase 序列化。将静态绩效路由置于 `@router.get("/{account_id}")` 之前，避免 FastAPI 将 `performance` 解析为 UUID：

```python
@router.get("/{account_id}/performance", response_model=PaperPerformanceResponse)
async def get_paper_performance(...):
    return _to_performance_response(await service.get_performance(account_id))
```

在 `_UnavailablePaperTradingRepository` 实现同签名的 `get_performance_data`，仅调用 `_raise_paper_storage_unavailable()`；不创建新的异常类型。

- [ ] **Step 4: 运行服务和 API 测试，确认安全响应正确**

Run: `uv run pytest tests/paper_trading/test_performance_service.py tests/api/test_paper_accounts.py -v`（工作目录：`backend`）  
Expected: PASS；成功路径只读取本地数据，404/503 均不泄露存储细节。

- [ ] **Step 5: 提交后端服务与 API**

```powershell
git add -- backend/src/app/paper_trading/service.py backend/src/app/api/routes/paper_accounts.py backend/src/app/main.py backend/tests/paper_trading/test_performance_service.py backend/tests/api/test_paper_accounts.py
git commit -m "feat: expose paper performance API"
```

## Task 4: 前端领域契约与 API 客户端

**Files:**
- Modify: `frontend/src/domain/paper-trading.ts`
- Modify: `frontend/src/domain/paper-trading.test.ts`
- Modify: `frontend/src/shared/api/workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.ts`
- Modify: `frontend/src/shared/api/http-workbench-api.test.ts`
- Modify: `frontend/src/shared/api/hybrid-workbench-api.ts`
- Modify: `frontend/src/shared/api/hybrid-workbench-api.test.ts`
- Modify: `frontend/src/shared/api/mock-workbench-api.ts`
- Modify: `frontend/src/shared/mocks/mock-workbench-api.test.ts`

**Interfaces:**
- Consumes: Task 3 的 camelCase HTTP 响应。
- Produces: `PaperPerformanceSnapshot` TypeScript 类型和 `WorkbenchApi.getPaperPerformance(accountId)`。

- [ ] **Step 1: 写失败的 Zod 和 HTTP 客户端测试**

在领域测试中解析完整 wire fixture，断言规范字段通过；用数值型 `netPnl`、无时区 `generatedAt` 与非法 `historyStatus` 分别断言失败。

在 HTTP 客户端测试中添加：

```ts
await expect(api.getPaperPerformance(accountId)).resolves.toMatchObject({
  netPnl: "-500",
  historyStatus: "complete",
  equityCurve: [{ equity: "9500", netPnl: "-500" }],
});

expect(new URL(fetchImpl.mock.calls[0]?.[0] as URL).pathname).toBe(
  `/api/v1/paper-accounts/${accountId}/performance`,
);
```

在混合客户端测试中断言该方法转发给 `remoteApi`；在 Mock 客户端测试中断言拒绝消息仍为“模拟盘需要本地 API 与数据库”，而不是生成虚假报告。

- [ ] **Step 2: 运行前端 API 测试，确认类型与方法缺失**

Run: `npm run test -- --run src/domain/paper-trading.test.ts src/shared/api/http-workbench-api.test.ts src/shared/api/hybrid-workbench-api.test.ts src/shared/mocks/mock-workbench-api.test.ts`（工作目录：`frontend`）  
Expected: FAIL，提示 `getPaperPerformance` 与 `paperPerformanceSnapshotSchema` 尚未定义。

- [ ] **Step 3: 定义 schema 并实现所有 API 适配器**

在 `paper-trading.ts` 中定义 `paperPerformancePointSchema`、`paperDecisionStatsSchema`、`paperPerformanceSnapshotSchema`，复用 `decimalStringSchema`、`nonNegativeDecimalStringSchema`、`utcIsoStringSchema` 和 `uuidSchema`。曲线点必须至少含 `at`、`cash`、`positionQuantity`、`equity`、`netPnl`；报告的正负盈亏和总收益率使用 `decimalStringSchema`，余额、手续费、回撤金额、回撤比例与胜率使用非负十进制 schema。

将下列方法以完全相同签名添加至 `WorkbenchApi`、`RemoteWorkbenchApi`、`HybridWorkbenchApi` 与 `MockWorkbenchApi`：

```ts
getPaperPerformance(accountId: string): Promise<PaperPerformanceSnapshot>;
```

HTTP 实现先用 `uuidSchema.parse(accountId)`，再请求：

```ts
return this.transport.request(
  `/api/v1/paper-accounts/${encodeURIComponent(parsedAccountId)}/performance`,
  paperPerformanceSnapshotSchema,
);
```

混合实现仅转发 remote 方法；Mock 实现仅拒绝既有 `PAPER_TRADING_REQUIRES_BACKEND_MESSAGE`。

- [ ] **Step 4: 运行前端 API 测试，确认契约和路由正确**

Run: `npm run test -- --run src/domain/paper-trading.test.ts src/shared/api/http-workbench-api.test.ts src/shared/api/hybrid-workbench-api.test.ts src/shared/mocks/mock-workbench-api.test.ts`（工作目录：`frontend`）  
Expected: PASS；不合法 payload 被 Zod 拒绝，所有数据模式实现相同接口。

- [ ] **Step 5: 提交前端数据契约与客户端**

```powershell
git add -- frontend/src/domain/paper-trading.ts frontend/src/domain/paper-trading.test.ts frontend/src/shared/api/workbench-api.ts frontend/src/shared/api/http-workbench-api.ts frontend/src/shared/api/http-workbench-api.test.ts frontend/src/shared/api/hybrid-workbench-api.ts frontend/src/shared/api/hybrid-workbench-api.test.ts frontend/src/shared/api/mock-workbench-api.ts frontend/src/shared/mocks/mock-workbench-api.test.ts
git commit -m "feat: add paper performance API client"
```

## Task 5: 在账户详情页显示独立绩效报告

**Files:**
- Create: `frontend/src/features/paper-trading/PaperPerformancePanel.tsx`
- Create: `frontend/src/features/paper-trading/PaperPerformancePanel.test.tsx`
- Modify: `frontend/src/features/paper-trading/PaperAccountDetailPage.tsx`
- Modify: `frontend/src/features/paper-trading/PaperTradingPages.test.tsx`
- Modify: `frontend/src/styles/index.css`

**Interfaces:**
- Consumes: Task 4 的 `WorkbenchApi.getPaperPerformance` 与 `PaperPerformanceSnapshot`。
- Produces: 账户详情内的独立、可失败降级的绩效区块；成功操作后与账户详情一起刷新。

- [ ] **Step 1: 写失败的绩效面板和详情交互测试**

在 `PaperPerformancePanel.test.tsx` 中提供返回完整历史快照的 fake `WorkbenchApi` 并渲染组件，断言展示“模拟盘绩效报告”、净盈亏、总收益率、累计手续费、最大回撤、权益曲线文本表和决策计数。令 fake 返回 `historyStatus: "partial"` 时断言可见“仅覆盖迁移基线之后的可用记录”；令 `getPaperPerformance` reject 时断言只显示区块错误文案。

在 `PaperTradingPages.test.tsx` 的 `PaperAccountsApi` 增加 `performanceReads` 计数和 `getPaperPerformance` 覆盖。新增测试点击成功的“运行 SMA 策略评估”后，等待查询失效并断言绩效读取次数增加，同时账户操作仍可用：

```ts
await user.click(await screen.findByRole("button", { name: "运行 SMA 策略评估" }));
api.resolveEvaluation?.(api.account);
await waitFor(() => expect(api.performanceReads).toBeGreaterThan(1));
expect(screen.getByRole("heading", { name: "模拟盘详情" })).toBeVisible();
```

- [ ] **Step 2: 运行组件与页面测试，确认面板尚不存在**

Run: `npm run test -- --run src/features/paper-trading/PaperPerformancePanel.test.tsx src/features/paper-trading/PaperTradingPages.test.tsx`（工作目录：`frontend`）  
Expected: FAIL，提示无法解析 `PaperPerformancePanel` 或缺少绩效读取方法。

- [ ] **Step 3: 实现独立的绩效查询与展示组件**

在 `PaperPerformancePanel.tsx` 内部使用：

```tsx
const performanceQuery = useQuery({
  queryKey: ["paper-performance", accountId],
  queryFn: () => api.getPaperPerformance(accountId),
});
```

加载时仅渲染该区块的 `PageState state="loading"`；失败时渲染 `PageState state="error" message="无法读取模拟盘绩效，请稍后重试。"`；成功时渲染 KPI 定义列表、事件统计定义列表和权益曲线。将绩效曲线投影为现有 `PnlChart` 所需的 `{ at, equity, netPnl }[]`，并在区块文案中说明图形只用于显示、不改变 `Decimal` 原始数据。不要调用全局复盘统计接口。

在 `PaperAccountDetailPage.tsx` 的账户/持仓概览之后插入 `PaperPerformancePanel`。将已有 `invalidateAccount` 扩展为：

```ts
void queryClient.invalidateQueries({
  queryKey: ["paper-performance", account.id],
});
```

因此手动开仓、平仓、策略评估和归档成功都会刷新报告。绩效查询失败不得阻塞账户、持仓、审计事件和操作按钮。

在 `styles/index.css` 添加仅限 `.paper-performance` 的网格、KPI、统计列表和完整性提示样式，复用现有 CSS 变量、`research-panel`、`table-scroll`、窄屏折行规则；不得覆盖其他页面的通用图表样式。

- [ ] **Step 4: 运行组件与页面测试，确认展示与刷新通过**

Run: `npm run test -- --run src/features/paper-trading/PaperPerformancePanel.test.tsx src/features/paper-trading/PaperTradingPages.test.tsx`（工作目录：`frontend`）  
Expected: PASS；完整/部分历史、区块失败隔离和操作后刷新均通过。

- [ ] **Step 5: 提交前端绩效页面**

```powershell
git add -- frontend/src/features/paper-trading/PaperPerformancePanel.tsx frontend/src/features/paper-trading/PaperPerformancePanel.test.tsx frontend/src/features/paper-trading/PaperAccountDetailPage.tsx frontend/src/features/paper-trading/PaperTradingPages.test.tsx frontend/src/styles/index.css
git commit -m "feat: show paper performance report"
```

## Task 6: 全量验证、迁移前向检查与文档记录

**Files:**
- Modify: `docs/superpowers/specs/2026-08-06-paper-trading-performance-design.md`

**Interfaces:**
- Consumes: Tasks 1–5 的已提交实现及本地 `TEST_DATABASE_URL`。
- Produces: 已实施状态与可复核验证记录；不变更 `.env`、真实数据库数据或账户状态。

- [ ] **Step 1: 先运行后端静态检查与全量测试**

Run: `uv run ruff check .`（工作目录：`backend`）  
Expected: PASS。

Run: `uv run pyright`（工作目录：`backend`）  
Expected: 0 errors、0 warnings。

Run: `uv run pytest`（工作目录：`backend`）  
Expected: PASS；临时 schema 会由 pytest fixture 自动创建和清理。

- [ ] **Step 2: 执行开发数据库前向迁移，但不创建或删除账户**

Run: `uv run alembic upgrade head`（工作目录：`backend`）  
Expected: 输出包含 `0007_create_paper_account_valuations`，且不报错。

随后仅用只读 SQL 核实表和迁移版本，例如：

```powershell
docker exec Crypto_trade psql -U <postgres_user> -d crypto_research -c "SELECT version_num FROM alembic_version;"
docker exec Crypto_trade psql -U <postgres_user> -d crypto_research -c "SELECT to_regclass('public.paper_account_valuations');"
```

将 `<postgres_user>` 替换为用户已经配置在本地连接串中的数据库用户名；不要打印或修改连接串、密码或 `.env`。两条命令只读，不清空、删除或重置数据。

- [ ] **Step 3: 运行前端全量质量门槛**

Run: `npm run lint`（工作目录：`frontend`）  
Expected: PASS。

Run: `npm run typecheck`（工作目录：`frontend`）  
Expected: PASS。

Run: `npm run test -- --run`（工作目录：`frontend`）  
Expected: PASS。

Run: `npm run build`（工作目录：`frontend`）  
Expected: PASS。

- [ ] **Step 4: 记录已验证状态并提交文档**

在设计文档把状态改为“已实施并验证”，并追加实际的命令结果、迁移 revision、前端/后端测试数量，以及以下安全确认：仅使用本地 PostgreSQL 与公开行情快照；未读取真实账户、未使用凭证、未调用交易所私有接口、未产生真实订单或资金操作。只在所有命令通过后写入这些结果。

```powershell
git add -- docs/superpowers/specs/2026-08-06-paper-trading-performance-design.md
git commit -m "docs: verify paper performance reports"
```

## Plan Self-Review

### Spec coverage

- 单账户、模拟盘独立口径、没有多账户比较或全局统计改动：Tasks 1、3、5。
- 追加式估值、初始/转换估值、迁移基线与历史完整性：Task 2。
- `Decimal`、UTC、收益/盈亏/手续费/回撤/平仓/事件指标：Task 1。
- 只读本地 API、404/503 安全错误、无市场网关读取：Task 3。
- Zod、HTTP/混合/Mock 契约、详情页 KPI/曲线/失败隔离/刷新：Tasks 4、5。
- 单元、持久化、迁移、API、前端和全量质量验证：Tasks 1–6。
- 不触碰真实账户、凭证、交易所私有 API、自动执行或环境文件：全局约束与 Task 6。

### Placeholder scan

已检查计划，不含占位标记、延后实现语句或未指明边界的处理描述。所有任务给出了文件路径、消费/产出接口、失败测试、实现要点、验证命令和提交范围。

### Type consistency

- 后端统一使用 `PaperAccountValuation`、`PaperPerformanceData`、`PaperPerformanceSnapshot`、`PaperHistoryStatus` 和 `aggregate_paper_performance`。
- 仓储、服务和 API 统一使用 `get_performance_data(account_id)` / `get_performance(account_id)`；前端统一使用 `getPaperPerformance(accountId)`。
- API 使用 camelCase 字段（`historyStatus`、`equityCurve`、`generatedAt`），前端 Zod schema 与组件使用相同字段名。
