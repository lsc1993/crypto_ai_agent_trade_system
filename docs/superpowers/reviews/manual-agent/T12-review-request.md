# T12 审查请求：确定性数量、成本、保证金和操作分支

- 任务/审查单元：**T12**（D4-P 的第一段；只做纯计算与人工清单，不含计划采纳）。
- 执行模型：DeepSeek `deepseek-flash`（`PI_PROVIDER=deepseek`、`PI_MODEL=deepseek-flash`、`PI_REASONING_LEVEL=max`）；具体模型版本、推理实现和供应商侧版本未知。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；质量验证说明、维护指南与运行边界以当前仓库提交为准。
- 自测状态：**`verified`**（实现、T12 聚焦、阶段 SQL/安全、quick、独立 PostgreSQL full、Ruff/格式/Pyright/架构/迁移链完成；不等于正式审查通过）。
- 正式审查状态：**`awaiting_review`**（尚未取得原审查助手对当前版本的正式结论；开发自测不替代该结论）。
- 日期：2026-11-20。

## 1. 工作区、分支与提交范围

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:/project_git/crypto_ai_agent_trade_system`（`main` tip `c33613d`，工作区干净；T11 已合并） |
| 隔离工作区 | `D:/project_git/t12`（从 `main` 的 `c33613d` 创建） |
| 分支 | `t12-deterministic-planning`（未推送、未合并、未部署） |
| base | `c33613d2c081e95df64b90fa7f09a8bc5f6d9240`（`main`，`docs: record T11 merge into main`） |
| implementation tip | `ef198f871da811cb29894a19580cb04f76ac99af`（`feat: calculate deterministic manual trade plans`） |
| implementation tree | `136c688be9bcb811acffb9b933b13573c9fcfef2` |
| 代码/文档范围 | `c33613d..ef198f8`，21 个文件，+3451/-15（T12 源码、测试、规范/计划/状态同步；不含本审查请求和进度 docs 提交） |
| diff 指纹 | `78f802675de590f3e01c222ac2d53c76413397ff4d02a4824739f6b3b40bf309`（`git diff c33613d..ef198f8` 的 SHA-256） |
| review_status | `awaiting_review` |
| reviewed_tip | 尚无 |
| docs 提交 | 本审查请求与进度更新在代码提交之后单独提交；具体 hash 见最终交付回复；不把 docs 自身提交号写入 `implementation tip` |

主工作区未因本轮改动；未修改 `.env`、凭证、业务库、生产配置、模拟盘资金/风控或交易执行链路。未调用真实模型、真实 MCP、私有账户或交易接口。

### 1.1 文件指纹（implementation tip `ef198f8`）

| 文件 | SHA-256 |
| --- | --- |
| `backend/src/app/trade_planning/contracts.py` | `c70039a6df9b58012c76a9cf5feb0a7822dbfedb16ccca8414910ab179b6261b` |
| `backend/src/app/trade_planning/sizing.py` | `978b8f28bfaa958b8078597b583e97fc3bd14a497c83c8d1016febcd962587b9` |
| `backend/src/app/trade_planning/order_rules.py` | `14f354b62f135b1a7d67fd2a64444f1e375c78f879f56bfd2e29aed1e6939669` |
| `backend/src/app/trade_planning/margin.py` | `3e70b72df79dd143323f158ddf72e8e00c9ea1278dd0c51343b685d1651d84d1` |
| `backend/src/app/trade_planning/risk_checks.py` | `09e10f8fa7a91de72f398d957bc67c18f94380475e30bcaef059a8c27d068ffb` |
| `backend/src/app/trade_planning/checklist.py` | `00089d3c9da797b0b16a6f2a66c9e1d97db457f1161feb6f3bf4ef56d053985d` |
| `backend/src/app/trade_planning/__init__.py` | `e94919b80fe50926a252ef3841d11f4e7175ec23578c8d1ac632c4c6f6be12a6` |
| `backend/tests/trade_planning/planning_fixtures.py` | `d96752d1b620cb3a2a088e894669a770fc8faa4367f8497e31021484d96c2459` |
| `backend/tests/trade_planning/test_sizing.py` | `41b7845128a5e3d99c6f5195d6e220318a7b414ccd0a3fcdab3c75a84dc635ec` |
| `backend/tests/trade_planning/test_risk_checks.py` | `cffa8adf46fdc339ab1430c708e18f1e92c68856abb26b52d44be612ef855ae0` |
| `backend/tests/trade_planning/test_margin.py` | `33e78463cae2ea44e2c693a1df2a6e3b4c196d89a7131a9d0b09a987f8f44fb8` |
| `backend/tests/trade_planning/test_order_rules.py` | `83cd87db9dff1596db1b57deade6b9f4e5e8754c02cccace486edd1fe6920398` |
| `backend/tests/trade_planning/test_checklist.py` | `27d235115a4d304fd12938327d4297bf6cd4d286003f6b4b6e6082ea590bc3b3` |
| `backend/tests/trade_planning/__init__.py` | `309ef7a150058af9b3754bb4298caf68b882e2a8863c1d0ffcd4d85134ffd588` |
| `AGENTS.md` | `a57c8a9e4a4cc247234fe5a708d1db6932a66f8b563002ab981bae225b2e3b45` |
| `backend/AGENTS.md` | `27dd630bf2c515f0435500d57a96b8abf193199d0cc2bd2370f89d7bd59c7d5e` |
| `docs/ai-maintenance.md` | `71101060789e9af7794cc8271e778a33d669130ced84bf664537b338058b7fd2` |
| `docs/operational-boundaries.md` | `6a7254fc86719248bda3187e35822ce0a9e4245dc2a0cc1c57697f186b7ecf45` |
| `docs/project-status.md` | `9b5b74b3edaf975a682c918a044a812650569303e5e94f16b7116157a43910ee` |
| `docs/superpowers/plans/2026-11-06-manual-trading-agent-implementation.md` | `ef39e7bba41dcf4abfab754cb20e0de071c8582d082f305b191b70f4bdc0633f` |
| `docs/superpowers/plans/2026-11-06-manual-trading-agent-contracts.md` | `27dae55249be992937d052e3404aa74bbbe618221a68e8eb3039e5d7d8a73edc` |

## 2. 本轮范围与 FR/AC/HN 映射

### 2.1 范围

实现 C7 的纯计算与人工清单：

- `contracts.py`：`PlanningRequest`、`PlanningQuote`、`PriceGeometry`、`SizingResult`、`ValidationCheck`、`ManualChecklist`、`PlanningReason` 和 Decimal 量化辅助。
- `sizing.py`：`calculate_size(request) -> SizingResult`；风险额度、单单位成本、数量上限、步长向下取整、保证金/名义额/风险复验。
- `order_rules.py`：限价/有界市价价格几何、tick 向内取整、止损/目标 strict/保守一格、订单类型/TIF、数量过滤器。
- `margin.py`：初始保证金、用户预览一致性、强平方向核对。
- `risk_checks.py`：`evaluate_planning_risk(request, size) -> tuple[ValidationCheck, ...]`；完整/时效/冷却熔断/产品/占用/杠杆/价格/订单/数量/风险/盈亏比/保证金检查。
- `checklist.py`：`build_manual_checklist(request, size, checks) -> ManualChecklist`；操作步骤、异常分支、阻断项与来源分层。

本轮**不**实现：`ManualPlanningService.build/revalidate`、readiness/采纳、资金池占用、`ManualPlanRepository`、HTTP/SSE/前端、生产 lifespan、业务库迁移、真实公开规则持续可用性、真实模型、订单或私有账户。T12 不生成 `TradeIntent`，不访问模拟/真实订单服务。

### 2.2 映射与证明范围

| 需求/不变量 | T12 证明 | 证据/限制 |
| --- | --- | --- |
| FR-09（决策辅助与手动计划，部分） | 候选价格来自 T01，数量/资金/费用/风险由纯函数计算；模型不能填数（本模块无模型入口） | `test_sizing.py`、`test_risk_checks.py`；候选选择/模型解释仍待 T11/T13/T14 |
| FR-14（手动资金与风险，部分） | 消费 C3 资料/政策；未知值不按零；风险额度取多项最小；冷却/熔断/日损/杠杆检查 | `test_sizing.py`、`test_risk_checks.py`；资料录入/持久化属 T03/T13 |
| FR-15（市场规则与可实施校验） | tick/step/min 过滤器、订单类型/TIF、市价上界、费用/保证金证据、舍入后复验 | `test_order_rules.py`、`test_margin.py`、`test_sizing.py` |
| FR-16（手动实施清单与状态，部分） | 人工步骤、未成交/部分成交/跳价/超时/到期分支、manual 模式、无订单对象 | `test_checklist.py`；readiness/采纳/导出属 T13/T16 |
| AC-21（正常候选+完整资料） | 数量/成本/保证金/风险/清单确定性计算 | `test_long_sizing...`、`test_complete_synthetic_request...`；未验证真实用户资料/交易所 |
| AC-22（缺项/过期） | 缺资料/过期/跨日声明为 unknown/fail，不标可实施 | `test_missing_profile...`、`test_stale_inputs...` |
| AC-23（舍入/最小订单冲突） | 只向下取整；min qty/notional 冲突 blocked，不加大风险 | `test_minimum_order_conflict...`、`test_minimum_notional...` |
| AC-24（日损/冷却/熔断/仓位/杠杆） | 确定性 fail；已有仓位/挂单/未知占用阻断 | `test_cooldown_breaker...`、`test_missing_and_existing_exposure...` |
| AC-25（费用/规则/保证金不明） | 费用上界、规则时效、保证金档位/预览 unknown/fail | `test_nonzero_costs...`、`test_incomplete_margin...` |
| AC-26（部分成交/未成交/跳价/到期） | 清单分支覆盖且系统不自动发/撤单 | `test_checklist_covers...`、`test_checklist_has_no_order...` |
| AC-29（财务/只读边界，部分） | T12 无模型/网络/订单依赖，类型只在本地规划域 | 架构门禁；HTTP/事件投影仍待 T14 |
| HN-13（可实施状态仅由资料/规则/风险/时效/采纳成立） | T12 提供确定性 required 检查，不提供 adoption/readiness | **部分**：`ValidationCheck`/`ManualChecklist`；T13 必须补 readiness/采纳/占用 |
| HN-14（财务值不进 LLM/RAG/日志） | 本模块不调用 LLM/RAG/日志；测试夹具为合成值 | 模块边界证；T14 必须验证 API/事件投影 |

T12 不声称完整满足 HN-13 或产品手动实施闭环；它只交付可在后续服务中复用的纯计算/检查/清单基础。

## 3. 改动清单与关键取舍

### 3.1 改动清单

**新增源码**
- `backend/src/app/trade_planning/contracts.py`：C7 纯契约、材料指纹、18 位量化、检查/清单完整性约束。
- `backend/src/app/trade_planning/sizing.py`：风险额度、单位成本、数量上限、步长/量化/回退。
- `backend/src/app/trade_planning/order_rules.py`：tick 向内取整、限价/有界市价、止损/目标容差、订单类型/TIF、数量过滤器。
- `backend/src/app/trade_planning/margin.py`：初始保证金、预览一致性、强平方向。
- `backend/src/app/trade_planning/risk_checks.py`：逐项确定性检查。
- `backend/src/app/trade_planning/checklist.py`：人工步骤/异常分支/阻断项。

**新增测试**
- `backend/tests/trade_planning/planning_fixtures.py`：合成 C3/T01 输入、固定时钟、多空/成本/保证金覆盖。
- `test_sizing.py`（19）、`test_risk_checks.py`（10）、`test_margin.py`（5）、`test_order_rules.py`（11）、`test_checklist.py`（8），共 53 项。

**修改**
- 根 `AGENTS.md`、`backend/AGENTS.md`：记录 T12 纯规划模块边界与测试入口。
- `docs/ai-maintenance.md`、`docs/operational-boundaries.md`、`docs/project-status.md`：当前能力/未接入边界。
- 实施计划 T12 步骤与契约 C7 实现细节同步。

### 3.2 关键取舍（请重点审查）

1. **成本公式与上界**：L/W 使用 `slippage_upper_bound + spread_upper_bound` 对出场价做不利调整，入场费/止损退出费/目标退出费按各自名义额计算，持有成本按 `holding_cost_upper_bound * 入场名义额` 计一次。限价入场用限价，市价入场用最大不利成交价，不重复加入第二次入场滑点。C3 没有持有期限/资金费时间模型，因此持有成本是声明的情景总费率，不是按时间累计；请确认该解释是否与契约一致。
2. **风险额度**：R 取 `policy.max_risk_per_trade`、`policy.max_daily_loss`、`policy.max_portfolio_risk`、`profile.remaining_single_trade_risk`、`remaining_daily_loss`、`remaining_portfolio_risk` 的最小值。请确认是否应把政策的 `max_daily_loss`/`max_portfolio_risk` 作为上限参与单笔 R，而不仅使用剩余额度。
3. **最小净盈亏比的位置**：数量求解只保证风险/名义额/保证金/数量上限；低于政策最小净盈亏比由 required `reward_risk_ratio_met` 检查 fail，保留数值草案供审阅，不把数量强制归零。C7 文本“则阻断”可能指 readiness 阻断；当前实现把阻断留给 T13 的 readiness。请确认该分离是否可接受；若要求 `calculate_size` 直接 blocked，需要改变返回契约/T13 草案展示。
4. **价格格点**：入场带按 tick 向内取整（下界 ceil、上界 floor），触发价必须落在取整后区间；止损/目标 strict 必须对齐，conservative_one_tick 只向风险不利方向移动。请确认入场带移动与触发价限制是否符合 C7“允许区间内的 tick 格点”。
5. **市价单边界**：必须有 `max_adverse_price`，位于取整后入场带，并与当前报价及声明的滑点/价差上界一致（多单 >= quote、<= quote*(1+penalty)；空单相反）。这比“仅要求非空”更严格；请确认是否应允许更宽的用户上界。
6. **保证金预览**：要求 `applicable_notional == notional` 且 `required_margin == initial_margin` 精确匹配；数量变化后旧预览直接 unknown/fail。强平只检查止损位于参考价安全一侧，不做简化强平公式或安全距离。请确认 exact-match 与方向核对是否足够保守。
7. **材料指纹**：`PlanningRequest.material_sha256` 不含 `evaluated_at`，只绑定候选/版本/报价/操作；同一材料在有效期内重读保持同一指纹，时效由 T13 `now` 判断。请确认这与“材料/条件实质变化新版本”一致。
8. **阻断结果**：`SizingResult` blocked 时数量/风险/收益为零，原因稳定码；不返回部分数量。清单不提供 `ready_for_manual_execution` 布尔值，只列 `blocking_checks`。请确认 T13 能从该结构派生 needs_inputs/blocked/ready。
9. **单位/乘数**：`quantity_unit=base_asset` 时要求 `contract_multiplier=1`；其他乘数/单位组合当前不自动推断。请确认首期 Binance USDT 线性永续限制是否合理。
10. **检查集合**：required 检查覆盖完整/时效/日损声明/冷却熔断/产品/占用/杠杆/价格/订单/数量/风险/盈亏比/保证金/强平/退出分配；缺项 unknown，确定性冲突 fail。请重点确认检查语义、unknown/fail 分类及 `ValidationCheck` 字段是否足以供 T13 使用。

## 4. 公共接口、依赖与迁移影响

### 4.1 新增公共接口

- `trade_planning.contracts`：`PlanningRequest`、`PlanningQuote`、`PriceGeometry`、`SizingResult`、`ValidationCheck`、`ManualChecklist`、`PlanningReason`、`SizingStatus`、`OrderOperation`、`CheckStatus`、`CheckBasis`、`ChecklistVerification`、`PlanningCalculationError`、`quantize_decimal`。
- `trade_planning.sizing.calculate_size(request: PlanningRequest) -> SizingResult`。
- `trade_planning.risk_checks.evaluate_planning_risk(request: PlanningRequest, size: SizingResult) -> tuple[ValidationCheck, ...]`。
- `trade_planning.checklist.build_manual_checklist(request, size, checks) -> ManualChecklist`。
- `trade_planning.order_rules`：`resolve_prices`、`floor_to_step`、`price_on_tick`、`order_type_for`、`order_type_supported`、`time_in_force_supported`、数量过滤器函数。
- `trade_planning.margin`：`initial_margin_for`、`margin_capacity`、`margin_preview_reasons`、`liquidation_distance_ok`。

未修改 T01/T03/T11 公共类型；未改变 `TradeIntent`、Risk Engine、Execution/Paper Trading 或现有报告/API。

### 4.2 依赖与迁移

- 无新增依赖。
- 无新增 Alembic 迁移；迁移 head 仍为 `0027_agent_segments`。
- 未迁移业务库；未修改 `.env`、凭证、生产配置或真实账户资料。

## 5. 测试执行与证据

所有命令在隔离工作区 `D:/project_git/t12` 执行；后端命令目录为 `D:/project_git/t12/backend`，统一入口目录为 `D:/project_git/t12`。

| 检查 | 完整命令 | 退出码 | 实际结果 | 证据路径 |
| --- | --- | --- | --- | --- |
| 预期红 | `uv run --locked --no-sync pytest tests/trade_planning/test_sizing.py tests/trade_planning/test_risk_checks.py tests/trade_planning/test_margin.py tests/trade_planning/test_order_rules.py tests/trade_planning/test_checklist.py -q --basetemp=../.tmp/pytest/t12-red-1` | 2 | 5 个 collection error（缺少 contracts/sizing/risk_checks/margin/order_rules/checklist）；符合测试先行预期 | 终端输出；`.tmp/pytest/t12-red-1` |
| T12 聚焦 | 同命令，`--basetemp=../.tmp/pytest/t12-green-15` | 0 | 68 passed（含既有 T03 trade_planning 15 项；T12 新增 53 项）/ 0 failed / 0 skipped | `.tmp/pytest/t12-green-15` |
| 阶段（T01/T03 SQL + 安全） | `TEST_DATABASE_URL` 进程注入；`uv run --locked --no-sync pytest tests/trade_planning tests/research/strategies tests/persistence/test_strategy_catalog.py tests/persistence/test_planning_inputs.py tests/security -q --basetemp=../.tmp/pytest/t12-final-stage-1` | 0 | 180 passed / 0 failed / 0 skipped | `.tmp/pytest/t12-final-stage-1` |
| 后端 quick | `uv run --project backend --locked --no-sync python scripts/verify.py quick --component backend --report .tmp/quality/t12-final-quick-backend.json` | 0 | `verification=passed`；1249 collected / 1249 passed / 0 failed / 0 skipped / 0 collection errors | `.tmp/quality/t12-final-quick-backend.json` |
| 独立 PostgreSQL full | `TEST_DATABASE_URL` 进程注入；`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/t12-final-full-backend.json` | 0 | `verification=passed`；1488 collected / 1488 passed / 0 failed / 0 skipped / 0 collection errors | `.tmp/quality/t12-final-full-backend.json` |
| Ruff | `uv run --locked --no-sync ruff check .` | 0 | All checks passed | 终端输出 |
| 格式 | `uv run --locked --no-sync ruff format --check .` | 0 | 416 files already formatted | 终端输出 |
| Pyright | `uv run --locked --no-sync pyright` | 0 | 0 errors / 0 warnings | 终端输出 |
| 架构门禁 | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=93`，`findings=[]` | 终端输出 |
| 迁移链 | `uv run --locked --no-sync alembic heads` | 0 | `0027_agent_segments (head)` | 终端输出 |

`.tmp/` 不随 Git 传递；上述命令可在同一 base/tip 上复现。未执行前端 lint/typecheck/Vitest/build、浏览器 e2e、HTTP e2e、完整生产 lifespan、真实模型/真实 MCP、业务库迁移或真实用户资料验证；原因是 T12 未接入这些路径，不能把未执行称为通过。

## 6. 未验证项、已知风险与重点审查位置

### 6.1 未验证/未交付

- `ManualPlanningService.build/revalidate`、readiness/采纳、资金池占用/代次、`ManualPlanRepository`、HTTP/SSE/API DTO、前端、生产 lifespan：全部属于 T13/T14，本轮未实现。
- 真实公开规则持续可用性、真实交易所产品变更、真实用户资料/保证金界面、真实成交/部分成交/费用：仅使用合成夹具；未访问私有账户或下单。
- 真实模型语义质量、真实 MCP、T14 财务投影/日志隔离：T12 模块不调用这些路径，未声称已验收。
- 前端/浏览器/HTTP e2e 未执行；T12 无前端改动。

### 6.2 已知风险/临时限制

- 成本模型是“声明上界的一次性情景”，没有持有期限/资金费时间累计；可能低估长期持有成本，需在 T13/T18/真实资料流程中明确。
- 最小净盈亏比在 T12 是检查失败而非 quantity 归零；若审查认为 C7 要求 `calculate_size` 直接 blocked，需要调整契约与 T13 草案展示。
- `calculate_size` 以 `profile.missing_fields` 作为完整性门控；保证金档位/强平参考缺失（或整个 MarginEvidence 缺失）会同时使数量求解返回 `blocked`/`planning_inputs_incomplete`，而 `margin_evidence_*`/`liquidation_*` 检查仍按 unknown 报告。这样更保守，但不显示“可补充保证金预览的数值草案”。若产品要求保留该草案，需缩小求解完整性门控并把缺口完全交给检查/T13 readiness。
- 保证金预览 exact-match 可能要求用户在数量确定后重新填写预览；这是保守设计，但增加交互步骤。
- 强平只做方向核对，不是安全距离/真实强平公式；不能据此保证不会强平。
- 价格取整只在 `conservative_one_tick` 下移动止损/目标一格；入场带向内取整可能拒绝触发价落在原区间边缘的候选。
- 数量量化在 18 位边界最多回退两步；极端精度输入可能 blocked，不会静默截断。
- `ValidationCheck` 名称/原因码/`ManualChecklist` 字段将成为 T13 的公共消费面；本轮未与 T13 实现联调。

### 6.3 重点审查位置

1. `contracts.py`：`PlanningRequest.material_sha256` 的绑定范围、`SizingResult` blocked 语义、`ValidationCheck`/`ManualChecklist` 完整性约束、18 位量化。
2. `sizing.py`：`_risk_budget`、`_unit_costs`（费用/滑点/持有成本是否重复或遗漏）、`_preliminary_quantity`、最小订单冲突与回退循环。
3. `order_rules.py`：入场带 tick 向内取整、触发价限制、`conservative_one_tick` 方向、市价最大不利价与报价/滑点一致性、基础资产乘数约束。
4. `margin.py`：预览 exact-match、强平方向、缺失保持 unknown。
5. `risk_checks.py`：`_quantity_checks` 的 fail/unknown 分类、`_risk_and_margin_checks` 的保证金时效/预览/强平、required 集合是否覆盖 AC-21 至 AC-26。
6. `checklist.py`：异常分支/来源分层/阻断项是否足以支持 T13/T16 的人工清单，且没有订单执行暗示。
7. 文档：确认当前能力/未接入边界没有把纯计算称为可实施计划或产品闭环。

## 7. 审查状态声明

- 自测状态：**`verified`**（上述命令与结果）。
- 正式审查状态：**`awaiting_review`**。本请求不预填审查通过；开发模型及本地自动检查不替代原审查助手对当前 tip 的正式结论。
- 未进入 T13；在收到并处理正式审查意见前停止新增模块开发。
