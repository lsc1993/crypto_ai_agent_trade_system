# T03 审查请求：规划资料、政策与受支持产品规则

- 任务/审查单元：T03（D1；C3 本地财务输入、风险政策、成本/保证金证据、公开规则快照与单资金池代次）
- 轮次：首轮开发交审
- 生成日期：2026-11-09
- 执行模型：DeepSeek Harness 驱动的 `deepseek-flash`（会话标注；上游精确构建版本未知）
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；质量验证以仓库当前 `docs/quality-verification.md` 为准。
- 自测状态：`verified`（实现、聚焦、阶段回归、迁移/并发回归、静态检查和后端 full 已完成）
- 正式审查状态：`awaiting_review`（尚未收到原审查助手结论；本文件不预填通过）
- 下一审查单元：T03 未获正式通过前不开始 T04；本轮停止新增模块开发。

## 1. 固定点与工作区

| 项目 | 值 |
| --- | --- |
| 工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t03` |
| 分支 | `task/manual-agent-t03` |
| base | `6fb08b5d455cfb6bca40e636a932e1edc46c855c`（`main`，T02 合并后；T03 开始时工作区干净） |
| implementation tip | `144e5019b904a7194d42bac9eaf55dab4d8c6162`（`feat: add local planning inputs and venue rule snapshots`） |
| tree | `979dfe32d0711030d5a0784a88f7848666d758cb` |
| 实现范围 | `6fb08b5..144e501`，17 个文件，+4108 / -15 |
| 代码 tip 处未提交文件 | 无；实现与测试均已提交。本审查包及进度/状态文档位于代码之后的 docs-only 提交；不记录自身提交号，避免自引用。 |
| 主工作区 | `main` 保持干净，未夹带 T03 或其他任务改动 |

`git diff --check main..144e501` 通过。T03 未修改 `.env`、凭证、业务库、前端、依赖锁文件或运行配置；未访问私有账户、真实资金或付费模型。

### 文件 SHA256（`144e501`）

| 文件 | SHA256 |
| --- | --- |
| `backend/alembic/versions/0021_planning_inputs.py` | `0d31ae9b025ca61b3c490fc06a45a8a81b43bfa04dc85c34f4509ae116a672c0` |
| `backend/src/app/infrastructure/market_rules/__init__.py` | `a370e330e85c709c0b48b2f1a082e9af3aa2ce88a7309fb24a30f4119ebe7f3a` |
| `backend/src/app/infrastructure/market_rules/binance_usdm.py` | `84d1d15572b6e05b169ddf9dda6824a5cf66877a5041cf0047d9a7b85cb3f62a` |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | `83a8b1c1c1f4a7ce84b02e64b642be288dfdac7d5e859dd8a68ce2a39056e337` |
| `backend/src/app/infrastructure/persistence/models/planning_inputs.py` | `f01a9702f0b91229e07f22293fc2fa498d59efa97132d73423f14411e6a72329` |
| `backend/src/app/infrastructure/persistence/planning_input_repository.py` | `f23e55931170a096d6bbf99e1a37ee7116151819759f5cb9a7d4bf65ca710374` |
| `backend/src/app/market/binance_usdm.py` | `07b6a5c7be45a8680baed4c340550605d85e0b6eea5fb93f8a3d825a72d8260c` |
| `backend/src/app/trade_planning/__init__.py` | `640b85c69e8d5e4e388af1a6200204dc8ec0da1988aebee780b78dcd558c11ec` |
| `backend/src/app/trade_planning/input_repository.py` | `401d3cf0e3c8440c4e22c7a3b6250d22869542a63bf8d46c15f83bb1a6635dcd` |
| `backend/src/app/trade_planning/input_service.py` | `288641aa71e7815871076081696914ad91f5ef33b22fa61acf2b5aa354c8aac8` |
| `backend/src/app/trade_planning/inputs.py` | `dd833d5e06aa3a27450f8f18d1ad59a58732b88b71fe478436b838793bbb874a` |
| `backend/src/app/trade_planning/product_support.py` | `8c99e43bf1ecc9e3619067f9e23edace246295dd0f6d3fa5f2ea50868ac3bc13` |
| `backend/tests/market/test_planning_rules.py` | `2ad2dd91b6b8da15daed1113aa6aa66bbfa3b3d730cfdb52855c6413b3dc81d7` |
| `backend/tests/persistence/test_planning_inputs.py` | `87e211f2efa46ccb5e01fee83e7c5125c7a94c092867c84f67fff5d0d0e3a6d8` |
| `backend/tests/trade_planning/__init__.py` | `4c81a3f6bd9854cf61ab42c8fd8198861b995b1750d377866f38bd9bbfdf24cb` |
| `backend/tests/trade_planning/test_inputs.py` | `aaa8595e336c5c408343445f3a3c9a8e92e6941b0446c7cf3eebfcf4d83e6b79` |
| `backend/tests/trade_planning/test_product_support.py` | `99506c57e78900a5ab245abd81ffc021c7479d1bcc3bd887b9c8b64979044b76` |

## 2. 改动清单

| 文件 | 作用 |
| --- | --- |
| `backend/src/app/trade_planning/inputs.py` | C3 不可变契约：资料/政策/成本/保证金/公开规则/引用、支持模式、有效期、内容指纹、稳定错误码与待补项 |
| `backend/src/app/trade_planning/input_repository.py` | `PlanningInputRepository`、`PublicRuleReader` 协议与 `PlanningPool`/`CurrentPlanningInputs` |
| `backend/src/app/trade_planning/input_service.py` | `PlanningInputService`：产品范围、规则刷新、创建资料/政策、完整引用组合 |
| `backend/src/app/trade_planning/product_support.py` | 首期支持目录与确定性支持判断（产品、模式、已有仓位/挂单、订单类型） |
| `backend/src/app/infrastructure/market_rules/binance_usdm.py` | 固定公开 `exchangeInfo` 到 `VenueRuleSnapshot` 的真实过滤器解析 |
| `backend/src/app/infrastructure/persistence/models/planning_inputs.py` | 资金池、资料、政策、成本、规则版本和请求幂等 ORM |
| `backend/src/app/infrastructure/persistence/planning_input_repository.py` | 单池 generation、请求幂等、并发行锁、不可变读取与一致性组合 |
| `backend/alembic/versions/0021_planning_inputs.py` | 6 张前向表、唯一工作台池、版本/请求不可变触发器；downgrade 明确拒绝 |
| `backend/src/app/market/binance_usdm.py` | 新增类型化 `PublicExchangeSymbol`/过滤器读取与 `get_exchange_symbol_rules`；旧 `get_exchange_info` 六字段行为兼容 |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | 注册规划输入模型 |
| `backend/tests/trade_planning/test_inputs.py` | 十进制拒绝、未知占用、时效、嵌套指纹、政策/保证金/规则/引用契约 |
| `backend/tests/trade_planning/test_product_support.py` | 产品/模式/未知或非零占用/订单类型支持判断 |
| `backend/tests/market/test_planning_rules.py` | tick/step/最小名义额、缺失/重复过滤器、产品/结算混用、非交易状态与时效 |
| `backend/tests/persistence/test_planning_inputs.py` | 真实 PostgreSQL 单池代次、请求重放、并发首建、完整引用、规则版本、过期/跨日与不可变触发器 |

## 3. FR/AC/HN 映射

| 标识 | 本轮落地 | 证明边界 |
| --- | --- | --- |
| FR-14 手动资金与风险资料 | 资料/政策版本；规划资金、可用保证金、单笔/日损/组合剩余风险、已有仓位/挂单名义额/保证金/风险、当日损益日期、冷却、熔断、杠杆/保证金/持仓模式；未知保留为 `None`；15 分钟本地有效期；UTC 跨日需重新声明 | 未实现数量/风险计算、计划采纳、占用释放或用户资料界面；`resolve_refs` 只做输入齐备/时效判断 |
| FR-15 市场规则与可实施校验 | `VenueRuleSnapshot` 绑定产品、乘数/数量单位、`PRICE_FILTER`/`LOT_SIZE`/`MARKET_LOT_SIZE`/`MIN_NOTIONAL`、交易状态、订单/触发/有效期、来源/观测/60 分钟有效期；公开规则读取只走受控 `exchangeInfo` | 未实现 tick/step 舍入、最小额冲突、保证金/强平计算、订单可实施性；这些由 T12/T13 完成 |
| AC-21 正常候选与完整资料 | 提供资料/政策/成本/保证金/规则引用基础 | 未实现程序数量、成本、风险、操作清单或用户审核；不宣称 AC-21 完整通过 |
| AC-22 缺项/过期 | `missing_fields`、`resolve_refs` 返回 `None`；成本/保证金/资料过期和跨日不自动恢复；不补零 | 后续计划状态与待补文案在 T12/T13/T16 |
| AC-23/AC-24 | 未实现舍入、最小额、日损/冷却/熔断/仓位/杠杆阻断计算 | 明确留给 T12/T13；T03 只拒绝关闭止损/冷却/熔断的策略标志 |
| AC-25 规则/成本/保证金缺项 | 缺失/重复过滤器、非 USDT/非永续规则、非法十进制明确不可用；缺少维持保证金/强平依据时资料不完整；非交易状态保留并可判定 | 不调用私有档位接口，不把缺失当零；真实官方复验留 T18 |
| AC-29 财务资料与只读边界 | 完整财务值只在受限 `trade_planning` 契约和规划表；无模型/RAG/通用事件/日志投影；无签名或私有账户接口 | 未接 HTTP/前端/模型；本轮没有事件投影路径，审计投影在后续任务验证 |
| AC-30 多任务共用资金池 | 每工作台唯一池、共享 generation、profile/policy/rules 变更递增、profile/policy 乐观代次拒绝旧写 | 未实现“同池仅一份待实施计划”、采纳互斥、未知占用保留/承接；这些由 T13/T17 完成 |
| HN-13 可实施状态不可由模型声明 | 输入完整性/时效/版本/代次由确定性服务和 DB 约束决定 | 可实施状态本身在 T12/T13；T03 不生成 `ready_for_manual_execution` |
| HN-14 财务/预算隔离 | 财务资料不进入 Agent、RAG、通用事件或模型 DTO；本任务无模型调用 | 未接上下文/事件/API，后续任务需继续验证投影 |
| HN-15 单池占用与代次 | 唯一工作台池、generation 递增、代次冲突拒绝、请求幂等和不可变版本 | 未实现唯一待实施计划、采纳占用或用户声明承接 |

未宣称：FR-09/FR-16/FR-17 的完整计划、操作清单、采纳与反馈；T12/T13 的计算和资金池互斥；真实收益、策略质量或产品已发布可用。

## 4. 关键实现取舍

1. **内容指纹覆盖嵌套值与引用**：资料快照的 `ref.sha256` 覆盖产品、全部财务字段、保证金证据、成本 ref、时间和来源；成本/政策/规则快照同理。构造后重新序列化校验，嵌套保证金或根对象额外字段被修改都会使旧 ref 失效。
2. **未知不补零**：所有关键财务字段为 `Decimal | None`；未知占用、未知当日日期、未知熔断状态保留 `None`。`resolve_refs` 只在完整、时效内且当日声明匹配时组合引用。显式零才表示已确认无占用。
3. **单池 generation 与 CAS**：`planning_pools.workspace_id` 唯一；创建资料/政策/规则均在池行锁内递增 generation。资料/政策写入要求 `expected_generation`，过期写入拒绝；规则刷新作为新的公开规则版本也递增 generation，使旧核验失效。
4. **请求幂等与锁后时间**：写方法先取 `pg_advisory_xact_lock(hashtextextended(request_id,0))`，再读幂等记录；请求结果、版本行和池代次同事务提交。业务时间在请求锁/池行锁后采样。`refresh_venue_rules` 的请求指纹只覆盖产品，因此同一 request_id 的重试复用首次快照；需要新规则时必须使用新 request_id。
5. **真实过滤器而非精度字段**：规则适配器只使用 `PRICE_FILTER.tickSize/minPrice/maxPrice`、`LOT_SIZE`/`MARKET_LOT_SIZE` 的 `stepSize/minQty/maxQty` 和 `MIN_NOTIONAL.notional`；`pricePrecision`/`quantityPrecision` 只作为可选元数据保留，不参与 tick/step 推导。缺失/重复过滤器、非 USDT/非永续、非法十进制明确失败。
6. **规则状态与时效分离**：非 `TRADING` 状态仍可作为不可变快照保存，但 `is_trading == False`；有效期 60 分钟，后续可实施核验必须检查，不在输入层假装可交易。
7. **首期产品目录有限**：仅 BTCUSDT/ETHUSDT、Binance USDT 线性永续、逐仓、单向；产品、结算、合约类型和数量单位不一致拒绝。支持判断要求已有仓位/挂单的名义额、保证金、风险六个字段都显式；任一未知或非零即阻断，避免同品种合并风险未实现时假定空仓。
8. **政策是硬约束**：金额、名义额、数量、杠杆、最小净盈亏比、日损、组合风险无默认值；缺项政策可保存但不完整。止损、冷却和熔断强制标志显式设为 `False` 时模型直接拒绝，不能由用户审核绕过。
9. **不可变迁移**：资料/政策/成本/规则/请求行拒绝 UPDATE/DELETE；资金池允许代次更新但拒绝删除。`0021` 为前向迁移，downgrade 明确拒绝删除历史版本。

## 5. 接口、依赖与迁移影响

- 公共 Python 类型：`PlanningProfileDraft`、`PlanningProfileSnapshot`、`PlanningRiskPolicyDraft`、`PlanningRiskPolicy`、`CostAssumptionsDraft`、`CostAssumptions`、`MarginEvidenceDraft`、`MarginEvidence`、`VenueRuleSnapshot`、`PlanningRefs`、`MarginMode`、`PositionMode`、`QuantityUnit` 及规划错误码。
- 服务/仓储协议：`PlanningInputService.create_profile/create_policy/refresh_venue_rules/resolve_refs/get_pool`；`PlanningInputRepository`；`PublicRuleReader`；`SqlAlchemyPlanningInputRepository`；`BinanceUsdmPublicRuleReader`。
- 公开行情网关新增 `PublicExchangeFilter`、`PublicExchangeSymbol`、`get_exchange_symbol_rules`；旧 `get_exchange_info` 仍返回原六字段，既有目录准入测试保持通过。
- 契约差异：C3 文本只列出 `create_profile`/`create_policy`/`resolve_refs`。本轮额外提供 `refresh_venue_rules` 和 `get_pool`，因为规则快照必须由服务端受控读取并持久化，代次也必须可查询；两者不改变业务语义，T12/T15 可直接消费。`PlanningInputRepository` 另提供按精确 ref 的历史读取，便于 T12 解析已保存引用。
- HTTP/API、前端、`WorkbenchApi`、Agent 工具循环、模型上下文：本轮未改动；没有新增路由、DTO、能力开关或前端页面。
- 持久化：新增 `planning_pools`、`planning_profiles`、`planning_risk_policies`、`planning_costs`、`planning_venue_rules`、`planning_input_requests`；迁移 head 为 `0021_planning_inputs`。未迁移业务库；downgrade 拒绝删除历史。
- 依赖：无新增生产/开发依赖；未升级锁定版本。
- 安全/配置：未修改 `.env`、凭证、业务库、运行配置、自动交易限制或默认审核；未新增交易所、MCP、外部服务或付费调用。

## 6. 测试执行与证据

执行目录除特别注明外为隔离工作区 `backend/`。数据库测试使用独立临时 PostgreSQL 17 容器（本机回环、受限角色 `crypto_research_test_runner`），先通过 `check_test_database` 只读身份/权限预检；未指向业务库。full 从隔离工作区根目录执行。

| 检查 | 命令 | 退出码 | 实际结果 |
| --- | --- | --- | --- |
| 首轮纯契约预期红 | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py tests/trade_planning/test_product_support.py tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-red-pure-20261109` | 1 | 3 collection errors（缺少 `app.trade_planning` / `app.infrastructure.market_rules`），符合测试先行预期 |
| 首轮 SQL 预期红 | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --basetemp=../.tmp/pytest/t03-red-db-20261109` | 1 | 1 collection error（缺少 `models.planning_inputs`），符合测试先行预期 |
| 最终纯契约/规则聚焦 | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py tests/trade_planning/test_product_support.py tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-final-pure-20261109` | 0 | 15 passed；覆盖 Decimal/NaN/指数/31 位、未知占用、15/60 分钟时效、嵌套指纹、政策硬约束、产品目录、tick/step/最小名义额解析 |
| 最终 SQL 聚焦 | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --basetemp=../.tmp/pytest/t03-final-db-20261109` | 0 | 9 passed；覆盖单池代次、同请求重放、并发首建、完整引用、规则刷新重放、过期/跨日、不可变触发器 |
| D1 阶段回归 | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/persistence/test_planning_inputs.py tests/persistence/test_migrations.py tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t03-stage2-20261109` | 0 | 168 passed；含 T01 策略目录、T02 知识索引、迁移链、既有行情网关/技术引擎回归 |
| 后端 full（implementation tip） | 从隔离工作区根目录：`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t03-full-backend-tip2.json` | 0 | `verification=passed`；后端 1113 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t03-full-backend-tip2.json` |
| 架构门禁 | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=38`，`findings=[]` |
| 静态检查 | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 0 | 全部通过；pyright 0 errors / 0 warnings |
| 迁移链 | `uv run --locked --no-sync alembic heads` | 0 | `0021_planning_inputs (head)` |

证据路径位于隔离工作区 `.tmp/`（不随 Git 传递，按上表命令可复现）：`.tmp/quality/manual-agent-t03-full-backend-tip2.json`；pytest 临时目录为 `.tmp/pytest/t03-*`。full 报告只保存安全计数与检查状态，不包含连接串、环境变量、原始异常或财务数据。

环境说明：验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`、`GIT_CONFIG_COUNT`；未修改 `.env` 或业务配置。测试资金、费率、保证金和规则均为合成资料；未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易。

## 7. 未验证项

- 未运行前端 lint/typecheck/Vitest/build、浏览器 e2e 或 http-e2e；本轮无前端改动，full 使用 `--component backend`。
- 未调用真实模型或付费服务；未验证真实模型质量、上下文/RAG 工具接入或模型财务值隔离投影（本轮尚无这些路径）。
- 未对真实 Binance 公开源执行 T18 的只读官方复验；规则测试使用固定合成 `exchangeInfo` 样本。未证明规则字段在真实公网长期稳定、`MIN_NOTIONAL` 字段名未被上游调整或所有交易状态可解析。
- 未迁移业务库、未部署；`0021` 仅在临时测试 schema 验证，未应用到任何业务库。
- 未实现 T12/T13 的数量/成本/保证金/风险/可实施状态计算、采纳互斥、同池待实施计划唯一约束、未知占用保留/承接或用户声明释放。
- 未实现 T15/T16 的 HTTP API、错误码映射、前端表单/授权视图或财务投影。
- 未做多进程/高并发压力、长时间运行、规则缓存命中率或性能评估；本轮只做真实 PostgreSQL 双会话并发和受控临时实例验证。
- 未验证严格数据库提交时可得；快照时间是服务端决策/观测时间，不是 PostgreSQL 提交时间。
- 未提供策略收益、产品已发布可用或实盘可实施声明。

## 8. 已知风险与重点审查位置

1. **公开规则观测时间**：`VenueRuleSnapshot.observed_at` 是规则适配器从受控网关取回后冻结快照的服务端时间；底层 `exchangeInfo` 网关有 5 分钟缓存，上游响应本身没有统一服务器时间字段。请核对这是否符合“规则时刻”要求，或应把网关抓取时间纳入快照来源。
2. **`MIN_NOTIONAL` 兼容性**：适配器优先读 `notional`，否则读 `minNotional`；未覆盖未来可能的 `NOTIONAL` 过滤器类型。`PRICE_FILTER`/`LOT_SIZE`/`MARKET_LOT_SIZE`/`MIN_NOTIONAL` 任一缺失即拒绝。T18 官方复验前不宣称产品规则已发布验收。
3. **数量单位与乘数**：首期对 Binance USDT-M 线性永续固定 `quantity_unit=base_asset`、`contract_multiplier=1`。请确认该假设在首期产品范围内正确，以及反向/币本位被 `ProductKey` 和规则适配器双重拒绝是否足够。
4. **generation 语义**：profile、policy 和 rules refresh 都递增池代次；profile/policy 使用 `expected_generation` CAS，rules refresh 不使用 expected generation。请核对规则刷新与并发 profile/policy 写入的锁顺序、是否会出现用户未预期地使旧检查失效，以及 T13 如何消费该代次。
5. **规则刷新幂等指纹**：同一 request_id 的规则刷新只按产品复用首次快照，不比较新抓取内容；这是为避免重新抓取时间变化导致重试冲突。请核对是否满足“同键同参复用、需要新规则用新请求键”的契约，以及跨工作台/不同产品冲突处理。
6. **完整引用门槛**：`resolve_refs` 要求资料包含成本版本和完整保证金证据（维持保证金依据 + 强平参考 + 触发基准 + 当前日损益声明）。这可能比 T12 允许的“草案 + 待补”更严格；请核对该服务应只作为“可规划引用”门槛，还是应返回带缺项的引用。
7. **不支持模式的存储边界**：模型层直接拒绝 cross/hedge 和关闭止损/冷却/熔断的策略；如果未来需要存储“不支持模式”用于诊断，需要单独设计，当前选择是明确拒绝而非保存后由计算层阻断。
8. **已有占用判断**：产品支持现在要求六个占用字段全部显式；风险为零但名义额/保证金非零也会阻断。请核对是否与 T13 的占用承接、未知占用保留和同品种合并规则一致。
9. **版本不可变触发器**：`planning_pools` 允许 UPDATE、拒绝 DELETE；版本/请求表拒绝 UPDATE/DELETE。请核对触发器和请求幂等记录的组合是否会影响未来归档/清理，以及是否需要在 T13 增加池锁的更多约束。
10. **测试替身边界**：`test_planning_rules.py` 使用固定 `PublicExchangeSymbol` 替身，只证明解析和失败分支；真实 HTTP 边界、缓存和公网规则由既有 `market` 测试与 T18 分别证明。SQL 测试证明 PostgreSQL 行为，不证明生产并发吞吐。

## 9. 自测与正式审查状态

- 自测状态：`verified`。实现、测试先行红、纯契约 15 passed、SQL 9 passed、D1 阶段回归 168 passed、后端 full 1113 passed / 0 failed / 0 skipped、静态检查、架构门禁和迁移 head 均已完成；上述未验证项不计入通过。
- 正式审查状态：`awaiting_review`。尚未收到原审查助手对 `144e5019b904a7194d42bac9eaf55dab4d8c6162` 的正式结论；开发自测不替代正式审查，不预填 `approved`。
- 审查范围：`6fb08b5..144e501`，17 个文件，+4108/-15；重点为 `inputs.py`、`planning_input_repository.py`、`binance_usdm.py`（规则适配）、`0021_planning_inputs.py` 及对应测试。本审查包文档提交只改进度/状态/契约标注和本文件，不夹带代码或其他任务改动；最终回复提供文档提交 hash。
- T03 未获正式审查通过前停止新增模块开发，不进入 T04。
