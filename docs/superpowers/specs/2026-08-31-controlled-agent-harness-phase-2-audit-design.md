# Controlled Harness Phase 2：追加式审计设计

**日期：** 2026-08-31
**状态：** 已确认设计，待用户审阅后编写实施计划
**前置条件：** Phase 1 受限市场研究 Harness 已完成；`run_id` 与市场研究 `analysis_id` 相同。

## 1. 决策摘要

本阶段为现有、用户手动发起的 `market_research` Harness 增加可持久化、不可修改的运行审计。新增 `harness_runs`、`harness_run_events` 和 `harness_evaluations` 三张 PostgreSQL 表，以及位于 `app.harness` 的窄审计端口和位于 `app.infrastructure.persistence` 的 SQLAlchemy 适配器。

审计记录采用“不可变运行信封 + 追加事件流 + 追加评估结果”，不使用可更新的运行状态行。`harness_runs` 保存一次请求及其静态策略快照；运行状态由事件流的最后一条事件确定。这样可以同时保留被拒绝、失败、完成和降级运行的真实过程，并与项目现有不可变研究和模拟盘审计模型保持一致。

市场研究报告的 `completed` / `degraded` 终态事件由数据库触发器在 `agent_analysis_runs` 插入的同一事务中追加，避免报告已经提交而成功终态审计缺失。策略拒绝和未持久化的工作流异常由 HarnessRuntime 记录。系统不自动重试、不引入后台 worker，也不增加任何交易、账户或执行能力。

## 2. 背景与问题

Phase 1 已对 `market_research` 建立固定策略、注册工作流和安全生命周期日志，但这些日志只存在于运行时。现有 `agent_analysis_runs` 仅记录最终完成或降级的 LangGraph 研究报告；它不能表达：

- 研究请求何时进入 Harness；
- 策略校验是否通过，或为何在委派前被拒绝；
- 哪个固定策略版本和能力集合授权了本次运行；
- 未能形成报告的工作流异常；
- 独立于领域报告的、可追加读取的 Harness 评估轨迹。

因此不能改写 `agent_analysis_runs` 来承载 Harness 语义：它具有报告外键、只接受 `completed` / `degraded`，且已是不可变历史事实。Phase 2 应新增并关联审计投影，而不是迁移、回填、更新或删除任何现有记录。

## 3. 范围与非目标

### 本阶段范围

1. 为当前的手动市场研究 Harness 保存请求、策略授权、工作流开始和终态的追加式审计记录。
2. 保存确定性策略授权评估的名称、版本、结论和稳定原因码。
3. 以 `run_id == analysis_id` 关联 Harness 记录与既有报告、证据、LangGraph checkpoint 和 `agent_analysis_runs`。
4. 通过数据库约束、前进式迁移和禁止更新/删除触发器保证审计记录不可修改。
5. 提供仅供应用内部和测试使用的只读追踪查询端口；不新增 HTTP 或前端查询接口。

### 明确不包含

- 新的 Agent 类型、策略 Agent、`TradeIntent` 变更、自动模拟执行或任何实盘能力。
- 私有账户、交易所私有 API、CCXT、浏览器、Shell、文件、MCP 或任意网络工具。
- 后台任务、队列、定时器、自动恢复、自动重试、数据回填或历史记录改写。
- 用户身份、租户、会话内容、原始提示词、模型原始响应、新闻 HTML、完整外部内容、数据库 URL、密钥或任何凭证。
- 审计查询 API、管理 UI、数据保留清理任务或跨工作流分析报表。这些以后单独审查。

## 4. 方案选择

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| 只增加事件表 | 不采用 | 缺少不可变请求/策略快照，按策略版本和标的查询成本高。 |
| **运行信封 + 事件 + 评估（采用）** | 采用 | 三种事实分别建模，满足不可变性、失败审计和未来第二类工作流的扩展需要。 |
| 可更新的运行状态主表 | 不采用 | 更新会抹平中间状态，也不符合现有审计表禁止修改的边界。 |

## 5. 总体架构与依赖边界

```text
API（既有手动端点）
  → HarnessedMarketResearchService
  → HarnessRuntime
      → HarnessAuditRepository（端口）
      → MarketResearchWorkflow
          → AgentResearchService / 固定 LangGraph
              → AgentAnalysisReportRepository

infrastructure.persistence
  ├─ SqlAlchemyHarnessAuditRepository
  ├─ Harness*Record SQLAlchemy 模型
  └─ PostgreSQL 迁移、不可变触发器、报告终态审计触发器
```

`app.harness` 只声明 Pydantic 契约、审计端口、运行时行为和安全异常；它不得导入 SQLAlchemy、ORM、Alembic、风险、执行、模拟盘、交易所适配器或模型 SDK。持久化实现只能位于 `app.infrastructure.persistence`。`agent`、`risk`、`execution` 和 `paper_trading` 不反向依赖 Harness。

运行时将要求一个审计端口实例。生产环境在已配置数据库且创建真实 Agent 服务时注入 SQLAlchemy 适配器；测试使用显式内存 fake。没有可用审计存储时，真实 Harness 研究不得开始。原有测试注入和确定性报告回退路径保持其既有语义，且不伪造 Harness 审计记录。

## 6. 审计契约

### 6.1 静态策略标识

`HarnessPolicy` 增加不可变 `version: str`，市场研究固定为 `market_research_v1`。运行时计算 `policy_sha256`：对策略版本、运行类型、保持声明顺序的允许标的和允许能力作 canonical JSON 序列化后计算 SHA-256。若注册表缺少请求的运行类型，Runtime 以固定审计哨兵 `unregistered` 和其 canonical SHA-256 创建被拒绝的运行信封；该哨兵不是可执行策略，也不允许委派工作流。

运行时还计算 `request_sha256`：仅覆盖 `run_id`、运行类型、标的、UTC 请求时间和策略版本。该请求没有自由文本或机密字段；哈希用于检测审计行与其请求契约是否不一致，而非保存原始请求内容。

### 6.2 领域模型和端口

`app.harness.audit` 定义冻结且 `extra="forbid"` 的 Pydantic 模型：

- `HarnessAuditRun`：运行信封；
- `HarnessAuditEvent`：追加事件；
- `HarnessEvaluation`：确定性评估结果；
- `HarnessAuditTrace`：只读组合视图；
- `HarnessAuditStorageUnavailableError`：安全的审计存储异常；
- `HarnessAuditRepository`：异步写入和只读查询端口。

端口操作按可提交的事实划分：

```python
class HarnessAuditRepository(Protocol):
    async def create_requested_run(
        self,
        run: HarnessAuditRun,
        event: HarnessAuditEvent,
    ) -> None: ...

    async def append_policy_evaluation(
        self,
        evaluation: HarnessEvaluation,
        event: HarnessAuditEvent,
    ) -> None: ...

    async def append_event(self, event: HarnessAuditEvent) -> None: ...

    async def get_trace(self, run_id: UUID) -> HarnessAuditTrace | None: ...
```

前三个写入操作各自使用短事务；前两个操作分别保证“运行信封 + requested 事件”和“评估 + 评估结论事件”一起写入。端口不会提供 update、delete、replace、upsert、bulk repair 或自动 retry 方法。

所有时间必须为带时区 UTC；所有模型均拒绝额外字段；错误码只接受小写字母、数字与下划线；哈希必须为 64 位小写 SHA-256。`details` 只接收具体的安全 Pydantic 计数模型序列化结果，绝不接收任意字典、异常消息或原始业务载荷。

### 6.3 固定事件序列

每个当前市场研究运行最多使用以下固定序列位置：

| sequence | 事件 | 写入方 | 说明 |
| ---: | --- | --- | --- |
| 0 | `requested` | HarnessRuntime | 运行信封与请求事件在策略校验前原子写入。 |
| 1 | `policy_authorized` 或 `policy_rejected` | HarnessRuntime | 与 `policy_allowlist` 评估一同写入。 |
| 2 | `workflow_started` | HarnessRuntime | 仅当策略已经授权后写入。 |
| 3 | `workflow_completed`、`workflow_degraded` 或 `workflow_failed` | 数据库触发器或 Runtime | 终态；每个运行最多一条。 |

策略拒绝在 sequence 1 终止；不会出现 `workflow_started`。成功或降级研究在 `agent_analysis_runs` 插入时由触发器写入 sequence 3。未能产生领域持久化结果的异常由 Runtime 写入 `workflow_failed`。没有取消、超时或自动重试事件，因为本阶段不引入这些运行能力。

### 6.4 评估语义

Phase 2 只登记一个共享、确定性的评估器：

```text
name: policy_allowlist
version: 1
decision: passed | rejected
```

它覆盖已注册运行类型、允许标的和声明能力是否均受当前固定策略允许。通过记录 `declared_capability_count` 与 `allowed_capability_count`；拒绝记录稳定原因码 `run_kind_not_registered`、`symbol_not_allowed` 或 `capability_not_allowed`。它不重新声称 Agent 内部已完成的证据、模型或显示文本校验；这些仍属于 `app.agent` 现有确定性验证与领域报告事实。

## 7. 数据库模型与约束

### 7.1 `harness_runs`

该表是不可变请求信封，而不是可更新状态表。

| 列 | 约束与含义 |
| --- | --- |
| `run_id` | UUID 主键；Phase 2 市场研究中等于 `analysis_id`。不建报告外键，以允许拒绝/失败且没有报告的运行。 |
| `run_kind` | `VARCHAR(64)`；检查为 `market_research`。 |
| `policy_version` | `VARCHAR(64)`；本阶段允许 `market_research_v1`，以及仅用于注册缺失拒绝的审计哨兵 `unregistered`。 |
| `policy_sha256` | `CHAR(64)`；小写 SHA-256。 |
| `symbol` | `VARCHAR(12)`；检查为 `BTCUSDT` 或 `ETHUSDT`。 |
| `requested_at` | `TIMESTAMPTZ NOT NULL`。 |
| `initiator_kind` | `VARCHAR(32)`；固定 `manual_api`。 |
| `request_sha256` | `CHAR(64)`；小写 SHA-256。 |
| `created_at` | `TIMESTAMPTZ`，服务器默认当前时间。 |

索引为 `(run_kind, symbol, requested_at DESC, run_id)`，用于按市场研究和标的追踪手动运行。

### 7.2 `harness_run_events`

| 列 | 约束与含义 |
| --- | --- |
| `run_id`, `sequence` | 复合主键；`run_id` 外键引用 `harness_runs`；sequence 检查在 0 至 3。 |
| `event_kind` | 固定为第 6.3 节列出的七种事件。 |
| `occurred_at` | `TIMESTAMPTZ NOT NULL`。 |
| `duration_ms` | 非负整数；请求和授权事件为 0，终态为从请求开始的单调耗时。 |
| `error_code` | 可空稳定原因码；仅拒绝与失败事件可填写。 |
| `details` | `JSONB NOT NULL`，仅安全计数/枚举事实。 |

索引为 `(run_id, occurred_at, sequence)` 与 `(event_kind, occurred_at DESC, run_id)`。应用层验证事件种类与 sequence 的对应关系，并验证成功/降级事件没有错误码。

### 7.3 `harness_evaluations`

| 列 | 约束与含义 |
| --- | --- |
| `run_id`, `sequence` | 复合主键；本阶段只使用 sequence 0，为后续不同评估器预留追加空间。 |
| `evaluator_name`, `evaluator_version` | 固定 `policy_allowlist` / `1`。 |
| `decision` | `passed` 或 `rejected`。 |
| `reason_code` | 通过时为空；拒绝时为安全稳定原因码。 |
| `evaluated_at` | `TIMESTAMPTZ NOT NULL`。 |
| `details` | 与事件表相同的受限 JSONB 规则。 |

索引为 `(run_id, evaluated_at, sequence)`。数据库检查 `passed` 必须没有原因码，`rejected` 必须有合法原因码。

### 7.4 不可变性与迁移

新增一个位于当前 Alembic head 之后的前进式迁移。它创建三张表、索引、检查约束与三个 `BEFORE UPDATE OR DELETE` 触发器；任何修改或删除均抛出含“immutable”的数据库异常。迁移 `downgrade()` 直接抛出 `NotImplementedError`，且在抛出前不得执行 schema mutation。

迁移不得执行 `UPDATE`、`DELETE`、历史回填、数据迁移或修改既有表数据。所有迁移 revision 长度保持不超过当前 Alembic version 列支持的 32 个字符。

## 8. 与研究报告的原子终态关联

`SqlAlchemyAnalysisReportRepository.persist_agent()` 已在单个数据库事务中写入报告、`agent_analysis_runs` 和详情。新增一个 `AFTER INSERT` 数据库触发器挂在 `agent_analysis_runs`：

1. 仅当 `NEW.analysis_id` 在 `harness_runs.run_id` 中存在时执行；非 Harness 或现有历史研究不受影响。
2. 插入 sequence 3 的事件：`completed` 映射为 `workflow_completed`，`degraded` 映射为 `workflow_degraded`。
3. 使用 `NEW.completed_at` 作为事件时间，以 `harness_runs.requested_at` 计算非负 `duration_ms`。
4. 从 `NEW.error_code` 复制稳定错误码；事件 details 只写报告状态和安全的 `generator_kind` 枚举，不读取报告文本、证据或模型输出。

触发器与报告提交在同一事务中，因此任一方失败都会使该事务回滚。它不更新 `harness_runs`，不改写 `agent_analysis_runs`，也不为不存在的 Harness 信封创建记录。

## 9. 运行时流程、失败语义与 API 行为

```text
生成 run_id
  → create_requested_run(run, requested[0])
  → 执行固定策略校验
      → append_policy_evaluation(evaluation, authorized/rejected[1])
  → 若被拒绝：抛出既有 HarnessPolicyViolation，绝不委派工作流
  → append_event(workflow_started[2])
  → 运行固定 MarketResearchWorkflow
      → 持久化报告 / agent_analysis_runs
          → 数据库触发器原子写入终态[3]
  → 返回既有报告响应
```

审计存储不可用时的语义：

- 请求、策略评估或工作流开始事件无法持久化时，Runtime 抛出 `HarnessAuditStorageUnavailableError`，映射为不含内部细节的 HTTP 503；工作流不会开始。
- 工作流抛出意外异常时，Runtime 先尝试追加 `workflow_failed`。成功写入后重新抛出原有异常，既有通用安全错误处理保持负责响应；写入失败则改抛安全的审计存储 503 并记录仅含 run ID、枚举和异常类型的日志。
- 报告成功持久化后，终态事件由同一事务触发，无需运行时第二次写入，也不允许自动重跑。

新增异常处理器的响应固定为：`code = "harness_audit_unavailable"`、`message = "Harness 审计存储不可用"`、`details = {}`。既有研究创建与重试 HTTP schema、返回字段和显式重试产生新 run ID 的行为不改变。

## 10. 实现组织

| 路径 | 职责 |
| --- | --- |
| `backend/src/app/harness/audit.py` | 冻结审计契约、哈希函数、异步仓储端口与安全异常。 |
| `backend/src/app/harness/contracts.py` | 增加静态 `policy.version`，不添加工具、上下文或自由载荷字段。 |
| `backend/src/app/harness/runtime.py` | 在既有授权与委派边界写入审计事实；不直接引用 ORM。 |
| `backend/src/app/infrastructure/persistence/models/harness.py` | 三张审计表的 SQLAlchemy 映射。 |
| `backend/src/app/infrastructure/persistence/harness_audit_repository.py` | SQLAlchemy 追加写入与只读追踪实现。 |
| `backend/alembic/versions/` | 前进式 schema、不可变触发器与报告终态触发器。 |
| `backend/src/app/main.py` | 在真实 Agent 组装路径中注入审计仓储；不将其暴露到 `app.state`。 |
| `backend/src/app/api/errors.py` | 安全的审计不可用 503 映射。 |
| `backend/tests/harness/` | 契约、Runtime 记录、拒绝、失败、哈希和无委派测试。 |
| `backend/tests/persistence/` | 迁移、不可变性、触发器原子关联、仓储读取与数据库约束测试。 |
| `backend/tests/api/` | 503 信封及既有报告 HTTP 契约回归测试。 |
| `backend/tests/security/` | Harness 无 ORM/风险/执行/工具/机密依赖的静态边界检查。 |

## 11. 测试与验收

实现必须测试先行，并至少覆盖：

1. 所有审计模型拒绝非 UTC 时间、额外字段、非法哈希、未知枚举、错误 sequence 与不安全 details。
2. 成功研究留下四条有序事件、一条通过评估和一条运行信封；`run_id` 可关联至现有报告与 checkpoint。
3. 策略拒绝仅留下 requested、rejected 事件和拒绝评估，且 Agent delegate 调用次数为零。
4. 工作流异常留下 failed 终态；不能泄露异常消息、原始错误或凭证。
5. 每张新表的 UPDATE 和 DELETE 均被数据库触发器拒绝；迁移 downgrade 在 schema 变更前失败。
6. `agent_analysis_runs` 插入可在同一事务追加完成或降级终态；缺少 `harness_runs` 信封时不产生 Harness 事件。
7. 审计存储不可用时返回安全 503 并在委派前失败；既有 API 成功与重试响应字段保持不变。
8. 既有 Phase 1、市场研究、风险、执行、模拟盘、回测、手续费、滑点、部分成交、幂等性和无未来数据泄漏测试继续通过。

质量门保持：

```powershell
Set-Location backend
uv run ruff check .
uv run pyright
uv run pytest
```

迁移与仓储测试使用隔离的测试 schema；不得接触生产数据、运行真实交易或使用任何真实账户凭证。

## 12. 实施前的确认清单

- 本文只授权 Phase 2 的设计，尚未授权代码、迁移或数据库写入。
- 实施计划必须按测试驱动方式拆分，并在开始迁移前列出精确的 schema 影响与不可逆性。
- 每项提交只能包含本阶段新增的 Harness 审计文件、相关测试、迁移或文档；不得混入既有工作树改动。
- Phase 3 策略研究、自动模拟执行、私有数据和实盘能力仍需要独立的业务与安全确认。

## Phase 2 实施记录

日期：2026-09-01。

- `harness_runs`、`harness_run_events`、`harness_evaluations` 三张追加式审计表已经存在。
- 后续迁移 `0013_harness_event_lifecycle` 以 PostgreSQL CHECK 约束强制事件种类与固定 sequence 的一一映射：requested 为 0，策略事件为 1，workflow_started 为 2，终态事件为 3；Pydantic 审计契约执行相同校验。
- 真实组装路径中的手动 `market_research` 运行会记录本文声明的请求、策略评估与工作流开始审计事实。
- completed 与 degraded 报告的终态事件会随报告事务插入，终态 details 为受限空 JSON 对象；没有 Harness 信封的报告不会创建 Harness 事件。
- 未新增报告 HTTP schema、自动任务、策略 Agent、模拟执行、私有 API 或实盘能力。
- 2026-09-01 全量后端质量门结果：Ruff 通过；Pyright 为 0 errors、0 warnings；pytest 收集 379 项，其中 376 passed、3 skipped。
