# T12 复审请求：确定性数量、成本、保证金和操作分支

- 任务/审查单元：**T12**（D4-P 的第一段；只做纯计算与人工清单，不含计划采纳）。
- 执行模型：DeepSeek `deepseek-flash`（`PI_PROVIDER=deepseek`、`PI_MODEL=deepseek-flash`、`PI_REASONING_LEVEL=max`）；具体模型版本、推理实现和供应商侧版本未知。
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；质量验证说明、维护指南与运行边界以当前仓库提交为准。
- 首轮审查：**`changes_requested`**（2 P1 + 6 P2，报告 `docs/superpowers/reviews/manual-agent/T12-review-result.md`；受审范围 `c33613d..ef198f8`，tree `136c688`）。
- 当前自测状态：**`verified`**（F1–F8 修复、报告反例回归、T12 聚焦、阶段 SQL/安全、quick、独立 PostgreSQL full、Ruff/格式/Pyright/架构/迁移链完成；不等于正式审查通过）。
- 当前正式审查状态：**`awaiting_review`**（等待原审查助手对修复版本复审；开发自测不替代正式结论）。
- 日期：2026-11-20。

## 1. 工作区、分支与提交范围

| 项目 | 记录 |
| --- | --- |
| 主工作区 | `D:/project_git/crypto_ai_agent_trade_system`（`main` tip `c33613d`，工作区干净） |
| 隔离工作区 | `D:/project_git/t12` |
| 分支 | `t12-deterministic-planning`（未推送、未合并、未部署） |
| base | `c33613d2c081e95df64b90fa7f09a8bc5f6d9240`（`main`） |
| 首轮 implementation tip | `ef198f871da811cb29894a19580cb04f76ac99af`（tree `136c688`） |
| 当前 implementation tip | `d0f5aeeb02a43119248139a1922fd526939f5ddc`（tree `e310be4`；`fix: bind and complete deterministic planning checks`） |
| 当前代码/规范范围 | `c33613d..d0f5aee`，25 个文件，+4451/-23（含首轮实现、首轮审查请求/进度 docs、F1–F8 修复；不含本次复审请求/进度更新） |
| 首轮审查后修复范围 | `e870d27..d0f5aee`，18 个文件，+860/-112（源码、测试、契约/计划/状态同步；不含 docs 审查请求更新） |
| 本次 docs 提交 | 本复审请求、进度更新与首轮审查报告归档在代码提交之后单独提交；具体 hash 见最终交付回复，不写入 `implementation tip` |
| review_status | `awaiting_review`（修复后待原审查助手复审） |
| reviewed_tip | 尚无（当前修复版本未取得复审通过） |

主工作区未因本轮改动；未修改 `.env`、凭证、业务库、生产配置、模拟盘资金/风控或交易执行链路。未调用真实模型、真实 MCP、私有账户或交易接口。

### 1.1 文件指纹（implementation tip `d0f5aee`）

| 文件 | SHA-256 |
| --- | --- |
| `backend/src/app/trade_planning/contracts.py` | `476e1b6bbb7d0d7336d4642111fe8999aa0acb48626b39eee226326908e1466d` |
| `backend/src/app/trade_planning/sizing.py` | `209a1e06b9a2e4d74b2f7f3af5e28269fb674120fbe1e2abaf06174bd61a215c` |
| `backend/src/app/trade_planning/order_rules.py` | `98f039351d3e5176dc2dbf3b293f3e5ff297e971946858de78a5b195e9b77e48` |
| `backend/src/app/trade_planning/margin.py` | `04aa40f3897ff772c725ac7ca8deb93a05764a08063f2f3ec41550ec235f2ab1` |
| `backend/src/app/trade_planning/risk_checks.py` | `5fa16beeab241bd7f9ef0aeeeb66c26dca0379abe1f11897ff508677c58475c4` |
| `backend/src/app/trade_planning/checklist.py` | `78f1e7a683f8a63293e28b8c6444d0618d2759b630897dadadd040b522da28be` |
| `backend/src/app/trade_planning/inputs.py` | `eada6972f4018d8df9bad5443f47544843dae50f2e997334eb20b2c4558113f6` |
| `backend/src/app/infrastructure/persistence/planning_input_repository.py` | `ab214615d8b8641cccd65792e20c7c880fb50350b9f54c77def96d78e017b601` |
| `backend/tests/trade_planning/planning_fixtures.py` | `c4499f38d0309e3656336be04daa0e364ab526c2c0a7d0be01e045f1f6a76733` |
| `backend/tests/trade_planning/test_sizing.py` | `845a70d441e46f5f20f9c68fbaa3f2dc49fd12705119e78c7812c32767834a0e` |
| `backend/tests/trade_planning/test_risk_checks.py` | `fd73fa294eecdced6541bf7b2d0a1e56266cbf41421e332ef37da2ca3ad1d841` |
| `backend/tests/trade_planning/test_margin.py` | `f248ac5298cd11e7677543daee75351f902287d73f40ef0313965387aabd281f` |
| `backend/tests/trade_planning/test_order_rules.py` | `188613de3bdfd9bbe09548453885daf973a8ed76dc1f925d78077fb22d81eefa` |
| `backend/tests/trade_planning/test_checklist.py` | `f5f478c49794843f9da5085ec599f318b3fdc982a84e5695cc13e0ef6e770d49` |
| `AGENTS.md` | `a57c8a9e4a4cc247234fe5a708d1db6932a66f8b563002ab981bae225b2e3b45` |
| `backend/AGENTS.md` | `27dd630bf2c515f0435500d57a96b8abf193199d0cc2bd2370f89d7bd59c7d5e` |
| `docs/ai-maintenance.md` | `5713f91732add2222b15c3c1bada815f710714714e3775bdf4c8844b5d96fc04` |
| `docs/operational-boundaries.md` | `6a7254fc86719248bda3187e35822ce0a9e4245dc2a0cc1c57697f186b7ecf45` |
| `docs/project-status.md` | `281a1cab8046d4b0210569d9875fe08294790b25ddc345c8f95ae6d37fda5633` |
| `docs/superpowers/plans/2026-11-06-manual-trading-agent-implementation.md` | `017c0ff4a16f9854c966b2005d3cc8686e2f851da725b40ad93c41773744da45` |
| `docs/superpowers/plans/2026-11-06-manual-trading-agent-contracts.md` | `153559a90f8ea3d7d77d482e4a26551d4396d95669b2695f040ab53a516aae15` |

## 2. 首轮审查 F1–F8 与修复映射

| 发现 | 修复 | 回归证据 |
| --- | --- | --- |
| F1/P1 只校验入场订单类型/数量过滤器 | 新增 `exit_order_types_supported` 要求规则声明 `STOP_MARKET` + `TAKE_PROFIT_MARKET`；`stop_exit_quantity_valid`/`target_exit_quantity_valid` 逐腿使用 `MARKET_LOT_SIZE` 的 step/min/max，并按该退出价复核 `min_notional`；`exit_allocation_complete` 要求止损/目标均覆盖全量 | `test_exit_order_types_and_market_exit_filters_are_validated`（LIMIT-only、market step=1 两个反例） |
| F2/P1 SizingResult 未绑定材料 | `SizingResult.material_hash` 绑定 `PlanningRequest.material_sha256()`；risk checks 新增 required `sizing_material_matches`，不匹配时所有 size 相关项 unknown；清单入口也拒绝旧 size | `test_sizing_result_binds_request_material`、`test_mismatched_sizing_material_blocks_required_checks`、`test_checklist_rejects_size_from_another_material` |
| F3/P2 清单接受不完整检查集合 | `PLANNING_CHECK_NAMES` 固定完整名称/顺序；`ManualChecklist` 验证完整集合、唯一性、以及按 `order_operation` 的 required 语义（LIMIT 的 TIF、MARKET 的市价上界）；`build_manual_checklist` 校验 size/check 材料 | `test_checklist_rejects_incomplete_check_set`、`test_checklist_rejects_required_downgrade` |
| F4/P2 比率未按最终结算金额复算 | 先量化 `rounded_loss`（向上）/`rounded_reward`（向下），再由二者在显式 80 位上下文复算比率；任一结算值为零返回稳定 blocked 原因，不抛 Pydantic ValidationError | `test_ratio_uses_final_quantized_settlement_amounts`、`test_zero_quantized_reward_blocks_without_validation_error`、`test_reported_final_settlement_ratio_case` |
| F5/P2 缺项被归为 fail | 缺 `daily_risk_as_of`、`margin_mode`/`position_mode`、市价最大不利价分别返回 unknown/`profile_incomplete`/`market_price_bound_missing`，不再传播为过期/模式不支持/硬冲突 | `test_missing_inputs_are_unknown_not_hard_failures` |
| F6/P2 日损检查跨 UTC 午夜 | `daily_risk_current.expires_at = min(profile.expires_at, 下一 UTC 零点)` | `test_daily_risk_check_expires_at_next_utc_midnight` |
| F7/P2 保证金预览未绑定实际入场价/数量 | `MarginEvidenceFields` 新增可选 `applicable_product`/`applicable_direction`/`applicable_entry_price`/`applicable_quantity`；预览要求六项（产品、方向、入场价、数量、名义额、初始保证金）一致，缺失为 unknown；T03 历史快照/请求按 `fields_set` 不物化新字段，旧 ref/request_id 保持兼容 | `test_preview_binds_entry_price_and_quantity`、`test_preview_binds_product_and_direction`、T03 `test_planning_inputs` SQL 重放回归 |
| F8/P2 市价边界依赖调用方 Decimal 精度 | 市价上界加乘/比较放入显式 80 位 `localcontext`；低精度调用方不能放宽或错误拒绝边界 | `test_reported_market_boundary_is_precision_independent`、`test_market_bound_is_independent_of_caller_decimal_precision`、`test_sizing_is_independent_of_caller_decimal_precision` |

补充：触发价明确为**人工观察阈值**，允许不在 tick 格点，但必须位于取整后的可执行入场带；只有实际入场价、止损和目标价格是交易所订单参数。回归 `test_off_grid_trigger_is_a_manual_observation_threshold`。首轮审查报告位于 `T12-review-result.md`。

## 3. 本轮范围与 FR/AC/HN 映射

### 3.1 范围

- `contracts.py`：C7 契约、材料指纹、完整检查名称、18 位量化、检查/清单完整性。
- `sizing.py`：风险额度、单位成本、数量上限、步长/量化/回退、最终结算比率。
- `order_rules.py`：入场带 tick 向内取整、限价/有界市价、止损/目标容差、订单类型/TIF、数量过滤器、退出类型常量。
- `margin.py`：初始保证金、预览产品/方向/入场价/数量一致性、强平方向。
- `risk_checks.py`：`evaluate_planning_risk`，包含 F1/F2/F5/F6/F7/F8 相关检查。
- `checklist.py`：完整检查集合、required 语义、人工步骤/异常分支。
- `inputs.py` + `planning_input_repository.py`：保证 T12 预览绑定字段兼容 T03 历史快照/请求指纹。

本轮**不**实现：`ManualPlanningService.build/revalidate`、readiness/采纳、资金池占用、`ManualPlanRepository`、HTTP/SSE/前端、生产 lifespan、业务库迁移、真实公开规则持续可用性、真实模型、订单或私有账户。T12 不生成 `TradeIntent`。

### 3.2 映射与证明范围

| 需求/不变量 | T12 证明 | 证据/限制 |
| --- | --- | --- |
| FR-09（决策辅助与手动计划，部分） | 候选价格来自 T01，数量/资金/费用/风险由纯函数计算；本模块无模型入口 | `test_sizing.py`、`test_risk_checks.py`；候选选择/模型解释待 T11/T13/T14 |
| FR-14（手动资金与风险，部分） | 消费 C3；未知值不按零；风险额度多项最小；冷却/熔断/日损/杠杆检查 | `test_sizing.py`、`test_risk_checks.py`；资料录入/持久化属 T03/T13 |
| FR-15（市场规则与可实施校验） | tick/step/min 过滤器、入场/退出订单类型、市价上界、费用/保证金证据、舍入后复验 | `test_order_rules.py`、`test_margin.py`、`test_sizing.py` |
| FR-16（手动实施清单与状态，部分） | 人工步骤、未成交/部分成交/跳价/超时/到期分支、manual 模式、无订单对象 | `test_checklist.py`；readiness/采纳/导出属 T13/T16 |
| AC-21（正常候选+完整资料） | 数量/成本/保证金/风险/清单确定性计算 | `test_long_sizing...`、`test_complete_synthetic_request...`；未验证真实资料/交易所 |
| AC-22（缺项/过期） | 缺资料/过期/跨日声明为 unknown/fail，不标可实施 | `test_missing_profile...`、`test_stale_inputs...`、`test_missing_inputs...` |
| AC-23（舍入/最小订单冲突） | 只向下取整；min qty/notional 冲突 blocked，不加大风险 | `test_minimum_order_conflict...`、`test_reported_final_settlement_ratio_case` |
| AC-24（日损/冷却/熔断/仓位/杠杆） | 确定性 fail；已有仓位/挂单/未知占用阻断；日界截断 | `test_cooldown_breaker...`、`test_missing_and_existing_exposure...`、`test_daily_risk_check...` |
| AC-25（费用/规则/保证金不明） | 费用上界、规则时效、保证金档位/预览/绑定 unknown/fail | `test_nonzero_costs...`、`test_incomplete_margin...`、`test_preview_binds...` |
| AC-26（部分成交/未成交/跳价/到期） | 清单分支覆盖且系统不自动发/撤单 | `test_checklist_covers...`、`test_checklist_has_no_order...` |
| AC-29（财务/只读边界，部分） | T12 无模型/网络/订单依赖，类型只在本地规划域 | 架构门禁；HTTP/事件投影仍待 T14 |
| HN-13（可实施状态仅由资料/规则/风险/时效/采纳成立） | T12 提供确定性 required 检查，不提供 adoption/readiness | **部分**：T13 必须补 readiness/采纳/占用 |
| HN-14（财务值不进 LLM/RAG/日志） | 本模块不调用 LLM/RAG/日志；测试夹具为合成值 | 模块边界证；T14 必须验证 API/事件投影 |

## 4. 关键取舍（复审重点）

1. **退出腿**：首期固定止损 `STOP_MARKET`、目标 `TAKE_PROFIT_MARKET`，逐腿检查规则能力、MARKET_LOT_SIZE 的 step/min/max 和退出价名义额；仅声明 LIMIT 或粗步长会阻断。请确认触发类型/退出分配语义是否符合 C7。
2. **材料绑定**：`SizingResult.material_hash` 只证明结果声称对应请求材料；纯函数入口仍可在内存中构造任意值。当前边界用于发现跨请求复用，不是跨进程签名。请确认是否需要更强的结果字段指纹或 T13 持久化时再校验。
3. **检查集合与 required**：`PLANNING_CHECK_NAMES` 固定 34 项顺序；`ManualChecklist` 校验完整集合、唯一性和按订单操作的 required 语义（LIMIT 的 TIF、MARKET 的市价上界）。请确认该公共集合是否应作为 T13 的 readiness 输入契约。
4. **最终比率**：使用量化后的止损损失/目标收益复算；低于政策最小比率保留数值草案但 required 检查 fail。请确认这与“阻断 readiness 而非数量归零”的取舍一致。
5. **缺项分类**：缺日损日期/账户模式/市价上界返回 unknown；已过期、明确不支持、越界仍 fail。请确认 `profile_complete` 与具体检查的 unknown 组合足以让 T13 区分 needs_inputs/blocked。
6. **日界**：日损检查在下一 UTC 零点到期；其他检查仍按各自来源有效期。请确认 T13 会读取该 expires_at，而不是只看 profile 有效期。
7. **保证金预览绑定**：新增 C3 可选字段，要求产品/方向/入场价/数量/名义额/初始保证金一致；历史快照按 `fields_set` 保持原 ref/request_id。这是 T03 公共输入的细化，请重点审查向后兼容和是否应把绑定缺失列入 `missing_fields`。
8. **市场精度**：统一 80 位上下文；允许申报上界比“报价+滑点”更紧，但不得更宽。请确认市价上界与情景成本的语义、以及超出情景时清单的人工分支（当前未实现独立分支）。
9. **触发价**：明确为人工观察阈值，允许离格；仅入场/止损/目标使用 tick 格点。请确认清单/前端不会把它作为交易所订单参数。
10. **成本/持有成本**：使用声明上界，持有成本按入场名义额计一次情景费率；没有期限/资金费时间累计。请确认该解释与 C3 字段一致。

## 5. 公共接口、依赖与迁移影响

### 5.1 新增/修改接口

- `trade_planning.contracts`：新增 `PLANNING_CHECK_NAMES`、`SizingResult.material_hash`、退出/材料绑定原因；`ManualChecklist` 校验完整检查集合和 required 语义。
- `trade_planning.inputs.MarginEvidenceFields`：新增可选 `applicable_product`/`applicable_direction`/`applicable_entry_price`/`applicable_quantity`；不加入 `missing_fields`，T12 预览检查负责缺失/绑定判断；历史字段集合按 `fields_set` 保持原指纹。
- `trade_planning.margin.margin_preview_reasons`：增加 `entry_price`/`quantity` 参数并检查产品/方向/数量/入场价。
- `trade_planning.order_rules`：新增 `EXIT_ORDER_TYPES`、`exit_order_types_supported`、`quantity_on_step`。
- `risk_checks.evaluate_planning_risk`：固定 34 项检查，包括 `sizing_material_matches`、`exit_order_types_supported` 和逐退出腿检查。
- `infrastructure/persistence/planning_input_repository.py`：请求指纹草稿载荷按 `fields_set` 删除未提供的预览绑定字段，兼容 T03 历史 request_id。

未修改 T01/T03/T11 的已发布业务类型语义；未改变 `TradeIntent`、Risk Engine、Execution/Paper Trading 或现有报告/API。

### 5.2 依赖与迁移

- 无新增依赖。
- 无新增 Alembic 迁移；迁移 head 仍为 `0027_agent_segments`。
- 未迁移业务库；未修改 `.env`、凭证、生产配置或真实账户资料。

## 6. 测试执行与证据

所有命令在隔离工作区 `D:/project_git/t12` 执行；后端命令目录为 `D:/project_git/t12/backend`，统一入口目录为 `D:/project_git/t12`。

| 检查 | 完整命令 | 退出码 | 实际结果 | 证据路径 |
| --- | --- | --- | --- | --- |
| 首轮审查反例复现（修复前） | `uv run --locked --no-sync pytest tests/trade_planning/test_sizing.py tests/trade_planning/test_risk_checks.py tests/trade_planning/test_margin.py tests/trade_planning/test_order_rules.py tests/trade_planning/test_checklist.py -q --basetemp=../.tmp/pytest/t12-r1-red-1` | 1 | 11 failed / 69 passed；F1–F8 对应反例在修复前失败 | `.tmp/pytest/t12-r1-red-1` |
| T12 五文件聚焦 | 同命令（修复后，`--basetemp=../.tmp/pytest/t12-r1-focused-final`） | 0 | 71 passed / 0 failed / 0 skipped | `.tmp/pytest/t12-r1-focused-final` |
| 全部 trade_planning | `uv run --locked --no-sync pytest tests/trade_planning -q --basetemp=../.tmp/pytest/t12-r1-green-11` | 0 | 86 passed（含 T03 既有 15 项；T12 新增 71 项） | `.tmp/pytest/t12-r1-green-11` |
| 阶段（T01/T03 SQL + 安全） | `TEST_DATABASE_URL` 进程注入；`uv run --locked --no-sync pytest tests/trade_planning tests/research/strategies tests/persistence/test_strategy_catalog.py tests/persistence/test_planning_inputs.py tests/security -q --basetemp=../.tmp/pytest/t12-r1-stage-sql-3` | 0 | 198 passed / 0 failed / 0 skipped | `.tmp/pytest/t12-r1-stage-sql-3` |
| 后端 quick | `uv run --project backend --locked --no-sync python scripts/verify.py quick --component backend --report .tmp/quality/t12-r1-final-quick-backend.json` | 0 | `verification=passed`；1267 collected / 1267 passed / 0 failed / 0 skipped / 0 collection errors | `.tmp/quality/t12-r1-final-quick-backend.json` |
| 独立 PostgreSQL full | `TEST_DATABASE_URL` 进程注入；`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/t12-r1-final-full-backend.json` | 0 | `verification=passed`；1506 collected / 1506 passed / 0 failed / 0 skipped / 0 collection errors | `.tmp/quality/t12-r1-final-full-backend.json` |
| Ruff / 格式 / Pyright / 架构 | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright`；`python -m scripts.check_architecture` | 0 | Ruff/格式通过；Pyright 0 errors/0 warnings；architecture `status=passed`，`files_scanned=93`，`findings=[]` | 终端输出 |
| 迁移链 | `uv run --locked --no-sync alembic heads` | 0 | `0027_agent_segments (head)` | 终端输出 |

`.tmp/` 不随 Git 传递；上述命令可在同一 base/tip 上复现。未执行前端 lint/typecheck/Vitest/build、浏览器 e2e、HTTP e2e、完整生产 lifespan、真实模型/真实 MCP、业务库迁移或真实用户资料验证；原因是 T12 未接入这些路径，不能把未执行称为通过。

## 7. 未验证项、已知风险与重点审查位置

### 7.1 未验证/未交付

- `ManualPlanningService.build/revalidate`、readiness/采纳、资金池占用/代次、`ManualPlanRepository`、HTTP/SSE/API DTO、前端、生产 lifespan：全部属于 T13/T14，本轮未实现。
- 真实公开规则持续可用性、真实交易所产品变更、真实用户资料/保证金界面、真实成交/部分成交/费用：仅使用合成夹具；未访问私有账户或下单。
- 真实模型语义质量、真实 MCP、T14 财务投影/日志隔离：T12 模块不调用这些路径，未声称已验收。
- 前端/浏览器/HTTP e2e 未执行；T12 无前端改动。

### 7.2 已知风险/临时限制

- 成本模型是“声明上界的一次性情景”，没有持有期限/资金费时间累计；可能低估长期持有成本，需在 T13/T18/真实资料流程中明确。
- `calculate_size` 以 `profile.missing_fields` 作为完整性门控；保证金档位/强平参考缺失（或整个 MarginEvidence 缺失）会使数量求解返回 blocked，而保证金检查仍按 unknown 报告；不显示“可补充保证金预览的数值草案”。
- 保证金预览 exact-match 可能要求用户在数量确定后重新填写预览；产品/方向/入场价/数量/名义额/初始保证金任一不一致即不适配。
- 强平只做方向核对，不是安全距离/真实强平公式；不能据此保证不会强平。
- 价格取整只在 `conservative_one_tick` 下移动止损/目标一格；入场带向内取整可能拒绝触发价落在原区间边缘的候选。
- 数量量化在 18 位边界最多回退两步；极端精度输入可能 blocked，不会静默截断。
- `SizingResult.material_hash` 是内存绑定，不是跨进程签名；T13 持久化/读取仍需校验材料与时效。
- `PLANNING_CHECK_NAMES`、检查原因码和 `ManualChecklist` 字段将成为 T13 的公共消费面；本轮未与 T13 实现联调。

### 7.3 重点审查位置

1. `contracts.py`：`PLANNING_CHECK_NAMES`、`SizingResult.material_hash`、`ManualChecklist` 完整/required 校验、18 位量化。
2. `sizing.py`：`_risk_budget`、`_unit_costs`、`_preliminary_quantity`、最终结算比率/零值 blocked、低精度独立性。
3. `order_rules.py`：退出订单类型/数量过滤器、入场带 tick 向内取整、市价精度、触发价人工阈值语义。
4. `margin.py` + `inputs.py`：预览产品/方向/入场价/数量绑定、历史 `fields_set` 指纹兼容、强平方向。
5. `risk_checks.py`：`sizing_material_matches`、`exit_order_types_supported`、逐退出腿检查、缺项 unknown、日界截断。
6. `checklist.py`：完整检查集合、required 降级、材料绑定、人工分支不含订单执行暗示。
7. `planning_input_repository.py`：旧 request_id 请求指纹兼容是否只是在字段未提供时删除新字段，未放宽其他内容冲突。

## 8. 审查状态声明

- 自测状态：**`verified`**（上述命令与结果）。
- 正式审查状态：**`awaiting_review`**。首轮审查已判定 `changes_requested`；当前修复版本尚未取得复审通过，不预填结论。
- 开发模型及本地自动检查不替代原审查助手对当前 tip 的正式结论；未进入 T13。
