# T03 审查请求：规划资料、政策与受支持产品规则

- 任务/审查单元：T03（D1；C3 本地财务输入、风险政策、成本/保证金证据、公开规则快照与单资金池代次）
- 轮次：第 4 轮（第三轮复审 1 项 P2：旧请求重放兼容不完整，修复后复审）
- 生成日期：2026-11-10
- 执行模型：DeepSeek Harness 驱动的 `deepseek-flash`（会话标注；上游精确构建版本未知）
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；质量验证以仓库当前 `docs/quality-verification.md` 为准。
- 首轮正式审查结论：不通过（4 项 P2）
- 第二轮正式审查结论：不通过（1 项 P2：新增 cooldown_status 导致合法历史快照指纹失效）
- 第三轮正式审查结论：不通过（1 项 P2：首轮带冷却截止时间及第二轮显式 null 的旧请求重放兼容不完整）
- 最终正式审查结论：通过（用户于 2026-11-10 传回原审查助手结论；`reviewed_tip=8d75a7a`）
- 自测状态：`verified`（旧请求重放兼容修复、聚焦、阶段回归、迁移/并发回归、静态检查和后端 full 已完成）
- 正式审查状态：`approved`（用户于 2026-11-10 传回原审查助手正式通过结论；`reviewed_tip=8d75a7a`）
- 下一审查单元：T03 已放行；T04 等待用户明确指定，不自动开始。

## 1. 固定点与工作区

| 项目 | 值 |
| --- | --- |
| 工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t03` |
| 分支 | `task/manual-agent-t03` |
| base | `6fb08b5d455cfb6bca40e636a932e1edc46c855c`（`main`，T02 合并后；T03 开始时工作区干净） |
| 首轮 implementation tip | `144e5019b904a7194d42bac9eaf55dab4d8c6162`（4 项 P2 不通过） |
| 首轮审查包 docs-only | `efae1dd2926b6df6ef109b3b9c153afc952828dd` |
| 第二轮复审 tip | `4f0e7ae76a86c2281a47e1cb4bad52b008e9b842`（1 项历史快照 P2 不通过） |
| 第二轮复审包 docs-only | `127c247a06901d7106e9fb4abc20f6eac91df2a2` |
| 历史兼容修复 tip | `023e5a20425d674a72d96614417aa4eea2820b03`（1 项旧请求重放 P2 不通过） |
| 历史兼容修复包 docs-only | `6592f989e2f7d2f6811582955e06736bd436f0e6` |
| 旧请求重放兼容修复 tip | `8d75a7a14471c36e4a168c166e3f94b659ceb9e7`（`fix: replay legacy T03 profile requests`） |
| tree | `f19f00022a4c7aabb5cfe145e73afedbd0534b3d` |
| 首轮实现范围 | `6fb08b5..144e501`，17 个文件，+4108 / -15 |
| 第二轮修复范围 | `efae1dd..4f0e7ae`，9 个文件，+508 / -51 |
| 历史兼容修复范围 | `127c247..023e5a2`，7 个文件，+235 / -7（含 3 个首轮版本实际生成的合成 fixture） |
| 旧请求重放修复范围 | `6592f98..8d75a7a`，6 个文件，+301 / -19（含 2 个首轮/第二轮实际生成的请求 fixture） |
| 代码 tip 处未提交文件 | 无；实现、三轮修复与测试均已提交。本轮复审包及进度/状态文档位于修复代码之后的 docs-only 提交；不记录自身提交号，避免自引用。 |
| 主工作区 | `main` 保持干净，未夹带 T03 或其他任务改动 |

`git diff --check main..8d75a7a` 通过。T03 未修改 `.env`、凭证、业务库、前端、依赖锁文件或运行配置；未访问私有账户、真实资金或付费模型。

### 文件 SHA256（`8d75a7a`）

| 文件 | SHA256 |
| --- | --- |
| `backend/alembic/versions/0021_planning_inputs.py` | `0d31ae9b025ca61b3c490fc06a45a8a81b43bfa04dc85c34f4509ae116a672c0` |
| `backend/src/app/infrastructure/market_rules/__init__.py` | `a370e330e85c709c0b48b2f1a082e9af3aa2ce88a7309fb24a30f4119ebe7f3a` |
| `backend/src/app/infrastructure/market_rules/binance_usdm.py` | `7e3f530663eecde7dcc2f7e1ffda0fd0957ed50e0fc91f7cc2a4a0ef68d1a977` |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | `83a8b1c1c1f4a7ce84b02e64b642be288dfdac7d5e859dd8a68ce2a39056e337` |
| `backend/src/app/infrastructure/persistence/models/planning_inputs.py` | `f01a9702f0b91229e07f22293fc2fa498d59efa97132d73423f14411e6a72329` |
| `backend/src/app/infrastructure/persistence/planning_input_repository.py` | `0e156727ee8efd9981364c87801239c0bb4aae207ba5cdc87b0daa91e973cad5` |
| `backend/src/app/market/binance_usdm.py` | `8d36d2de09ce6d377540c41ecd0f5434c9bdb01e958586adf2c31c1eee8ca194` |
| `backend/src/app/trade_planning/__init__.py` | `640b85c69e8d5e4e388af1a6200204dc8ec0da1988aebee780b78dcd558c11ec` |
| `backend/src/app/trade_planning/input_repository.py` | `e47c1b793918a221734e16e6f42c72f2d1cc4a181e737d6ae9c19f3184808cee` |
| `backend/src/app/trade_planning/input_service.py` | `6ba97e184b7117960718649ca41ed26e21647a0ddb8266170b7b3f3d26e7ebb2` |
| `backend/src/app/trade_planning/inputs.py` | `cdb9d7d0aa761a3158369263ddd1e3a37a689895c78371cde94d408402ba23ca` |
| `backend/src/app/trade_planning/product_support.py` | `8c99e43bf1ecc9e3619067f9e23edace246295dd0f6d3fa5f2ea50868ac3bc13` |
| `backend/tests/market/test_planning_rules.py` | `4bf3985516cbf9b5a421c8616189f810c3a3d6d93907f531e88fd457a19819cd` |
| `backend/tests/persistence/test_planning_inputs.py` | `e6caeabbce3b3c09ee4f32088f12d62e704930b61ebcb7a0cd8e1a12426b3c82` |
| `backend/tests/trade_planning/__init__.py` | `4c81a3f6bd9854cf61ab42c8fd8198861b995b1750d377866f38bd9bbfdf24cb` |
| `backend/tests/trade_planning/test_inputs.py` | `6e1254c584677fae933f529912de752aec6d104ee3afd8a8021e1f3e0d1f6dcd` |
| `backend/tests/trade_planning/test_product_support.py` | `99506c57e78900a5ab245abd81ffc021c7479d1bcc3bd887b9c8b64979044b76` |
| `backend/tests/fixtures/v1_planning_request.json` | `7b280fa2c5d61eb057d6de9593f397e30116a9817bab0329e1c8d05f1f55b2f6` |
| `backend/tests/fixtures/v1_planning_request_with_cooldown.json` | `cbe2f2151befa288b80e731121d3f58c6a22d789b40dc0d536943710fbcf7f5a` |
| `backend/tests/fixtures/v2_planning_request_null_cooldown.json` | `3ab5cf8a73a43201935fa8a0386db1251fcbec7aeb9b71cd82093034ee28b73d` |
| `backend/tests/fixtures/v1_planning_profile_with_cooldown.json` | `7fa36eed209794e2242d1424bc9aa104c60e677f2576f13c7db2e3878b0bfa48` |
| `backend/tests/fixtures/v1_planning_profile.json` | `a1cd1c8af837deef96489cee9953d0d793cf5d54308e1ce4cbd4949504fa36ed` |

## 2. P2 修复对照（第 2、3 轮）

| 审查问题 | 根因 | 修复位置与内容 | 回归 |
| --- | --- | --- | --- |
| P2 未知冷却状态被判为资料完整 | `cooldown_until=None` 同时表示“未声明”和“确认无冷却”；`missing_fields` 没有要求冷却状态 | `inputs.py` 新增 `CooldownStatus`（未知 `None` / `none` / `active`）和 `cooldown_status`；未知不进入完整资料；`none` 不得携带截止时间；`active` 必须有截止时间且快照要求晚于声明时间。草稿、快照、`missing_fields`、服务和测试同步。历史缺失状态保持未知/不完整，不推断为安全、不回写旧版本。 | `test_cooldown_state_must_be_explicit`、`test_unknown_cooldown_blocks_refs_until_explicitly_declared` |
| P2 规则刷新重试在幂等重放前依赖公开源 | `PlanningInputService.refresh_venue_rules` 先调用 reader，后进入仓储重放 | `input_repository.py` 新增 `replay_venue_rules`；仓储在请求 advisory lock 下做参数冲突检查和已提交结果读取。服务先重放，未命中才采集；首次写入仍由 `record_venue_rules` 的请求锁、池行锁和事务保护。 | `test_rule_refresh_replay_precedes_public_reader`、`test_concurrent_same_key_rule_refresh_is_single_commit`；旧 tip 临时复现 1 failed |
| P2 缓存命中重置规则观测时间并延长有效期 | 网关缓存不保存 HTTP 抓取时间；规则适配器按本地读取时钟重算 `observed_at` | `market/binance_usdm.py` 的 `PublicExchangeSymbol` 增加 `fetched_at`，网关在真实 HTTP 返回后采样并在缓存命中时沿用；`market_rules/binance_usdm.py` 使用 `fetched_at` 作为来源时间，60 分钟有效期按来源时间计算。旧 `get_exchange_info` 六字段接口不变。 | `test_cache_hit_preserves_source_time_and_expiry_window`、`test_rule_expiry_boundary_is_sixty_minutes_from_source_time` |
| P2 网关异常未转换为规划领域错误 | 规则适配器未捕获 `MarketDataUnavailableError`，异常穿透 `PlanningInputService` | `market_rules/binance_usdm.py` 在网关边界只捕获 `MarketDataUnavailableError`，转换为稳定 `planning_rule_unavailable`；不宽泛吞异常、不回显上游正文或敏感信息。 | `test_gateway_errors_become_planning_rule_errors`、`test_service_caller_can_catch_planning_rule_error` |

### 2.1 历史载荷兼容

- 本轮没有 schema 变更；`cooldown_status` 位于不可变 profile JSONB 文档。
- `0021_planning_inputs` 仍未合并、未应用到任何业务库。
- 历史快照读取按 `cooldown_status` 是否实际出现在 `model_fields_set` 选择旧/新字段集合校验原始指纹；旧 `version_id`/`sha256` 原样保留，不重写不可变载荷。
- 历史载荷缺少 `cooldown_status` 时解析为未知并保持不完整；旧载荷只有 `cooldown_until` 而缺少状态时保留截止时间、状态仍未知，不推断为 `none` 或 `active`。
- 旧 `get_exchange_info` 六字段接口和既有研究目录准入行为保持兼容。

### 2.2 旧 tip 红基线说明

规则刷新重放的修复前失败使用旧 tip `144e501` 的临时工作树和临时测试 `test_t03_red_replay.py` 复现；该测试文件仅用于红基线，不在交付分支中。当前分支的等价回归是 `test_rule_refresh_replay_precedes_public_reader`，修复后与该临时复现覆盖同一路径。

### 2.3 历史快照指纹兼容（第二轮复审 P2）

| 项目 | 内容 |
| --- | --- |
| 根因 | 首轮 tip 的合法快照没有 `cooldown_status`，原 `ref.sha256` 按旧字段集合计算；新模型读取时补入默认 `None`，`content_sha256()` 把新字段一起序列化，导致旧 ref 失效。 |
| 修复 | `PlanningProfileSnapshot` 用 `model_fields_set` 判断历史快照是否实际包含 `cooldown_status`；历史分支按旧字段集合（排除 `cooldown_status`）计算/校验指纹，并允许旧载荷保留 `cooldown_until` 但状态未知。新增 `versioned_payload()`，历史快照序列化使用 `exclude_unset=True` 保留原字段集合；仓储 `_snapshot_payload` 对资料快照使用该方法。 |
| 请求指纹 | `create_profile` 同时计算第二轮显式 `cooldown_status:null` 与首轮缺字段两种历史格式的候选指纹，按已保存记录匹配；新写入使用显式字段格式。显式 `none`/`active` 仍进入指纹，新语义不会被旧请求误重放。 |
| 历史读取 | `get_profile`、`resolve_current`、请求结果解析均通过同一版本感知模型读取；旧快照保持原 `version_id`/`sha256`，缺状态时 `is_complete=False`，`resolve_refs` 不返回完整引用。 |
| 样本 | `backend/tests/fixtures/v1_planning_profile.json`、`v1_planning_profile_with_cooldown.json`、`v1_planning_request.json` 均由首轮 tip `144e501` 实际生成，包含原始 ref 和请求 sha；不是用新版 build 重算。 |
| 回归 | 纯契约：旧快照原 ref 读取、带 `cooldown_until` 但状态未知、序列化重读、财务/嵌套篡改拒绝；SQL：旧 profile 行 `get_profile`/`resolve_current`/`resolve_refs`、旧请求结果同键重放且 generation 不变。 |

### 2.4 旧请求重放兼容（第三轮复审 P2）

| 场景 | 根因 | 修复与回归 |
| --- | --- | --- |
| 首轮请求带 `cooldown_until`、缺少 `cooldown_status` | 新版 Draft 的严格冷却校验在构造阶段拒绝历史载荷，尚未进入仓储重放 | Draft 允许读取该历史形态（状态仍未知、不完整）；仓储先按旧/新格式候选指纹重放，命中后直接返回原结果。重放未命中时调用 `draft.require_current_semantics()` 执行新版严格校验，因此新请求键首次写入仍拒绝“未知状态 + 截止时间”。 |
| 第二轮请求显式包含 `cooldown_status:null` | 上一轮只移除 null，按首轮缺字段格式计算，导致与第二轮已保存指纹不一致 | `create_profile` 同时计算“显式 null”和“缺字段”两种历史请求指纹，按已保存记录匹配；新写入使用显式字段格式。财务值、嵌套资料、显式状态或工作台/操作变化仍由 SHA 与归属检查拒绝。 |

实现位置：`backend/src/app/trade_planning/inputs.py`（Draft 历史形态读取与 `require_current_semantics`）、`backend/src/app/infrastructure/persistence/planning_input_repository.py`（候选请求指纹、重放后严格首次写入检查）。回归使用首轮 `144e501` 和第二轮 `4f0e7ae` 实际生成的请求参数、原始 request sha 与结果；覆盖同键重放、原 ref 不变、generation 不变、财务/嵌套/状态变化拒绝、跨工作台/操作拒绝、新请求键严格校验、并发重放单次提交。

## 3. 改动清单

### 3.1 首轮实现（`6fb08b5..144e501`，17 个文件）

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
| `backend/src/app/market/binance_usdm.py` | 类型化 `PublicExchangeSymbol`/过滤器读取与 `get_exchange_symbol_rules`；旧 `get_exchange_info` 兼容 |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | 注册规划输入模型 |
| 四组测试 | 纯契约、产品支持、公开规则解析、真实 PostgreSQL 单池/幂等/并发/触发器 |

### 3.2 复审修复（`efae1dd..4f0e7ae`，9 个文件，+508 / -51）

| 文件 | 变化 |
| --- | --- |
| `backend/src/app/trade_planning/inputs.py` | `CooldownStatus` 三态、冷却状态/截止时间一致性、完整性与快照时效校验、导出 |
| `backend/src/app/trade_planning/input_repository.py` | 新增 `replay_venue_rules` 端口 |
| `backend/src/app/trade_planning/input_service.py` | 规则刷新先带锁重放，再读取公开源 |
| `backend/src/app/infrastructure/persistence/planning_input_repository.py` | `replay_venue_rules` 实现、规则请求指纹复用 |
| `backend/src/app/market/binance_usdm.py` | `PublicExchangeSymbol.fetched_at`，真实抓取时间随缓存保留 |
| `backend/src/app/infrastructure/market_rules/binance_usdm.py` | 使用来源抓取时间、网关类型化异常转换、移除本地时钟重算 |
| `backend/tests/trade_planning/test_inputs.py` | 冷却三态、未知/无冷却/有效截止、历史缺失语义回归 |
| `backend/tests/persistence/test_planning_inputs.py` | 未知冷却阻断完整引用、规则重放先于公开源、同键并发单次提交 |
| `backend/tests/market/test_planning_rules.py` | 缓存来源时间、60 分钟边界、MockTransport 结构/网络异常、服务错误捕获 |

### 3.3 历史快照兼容修复（`127c247..023e5a2`，7 个文件，+235 / -7）

| 文件 | 变化 |
| --- | --- |
| `backend/src/app/trade_planning/inputs.py` | `is_legacy_profile`、版本感知 `content_sha256()`、`versioned_payload()`；历史分支允许旧载荷保留 `cooldown_until` 但状态未知 |
| `backend/src/app/infrastructure/persistence/planning_input_repository.py` | 资料快照持久化使用 `versioned_payload()`；`create_profile` 请求指纹兼容缺失 `cooldown_status` 的旧请求 |
| `backend/tests/trade_planning/test_inputs.py` | 旧快照原 ref、带截止时间旧载荷、序列化重读、财务/嵌套篡改拒绝 |
| `backend/tests/persistence/test_planning_inputs.py` | 旧 profile 行 `get_profile`/`resolve_current`/`resolve_refs`、旧请求结果同键重放 |
| `backend/tests/fixtures/v1_planning_profile.json` | 首轮 tip `144e501` 实际生成的合成快照与原始 sha |
| `backend/tests/fixtures/v1_planning_profile_with_cooldown.json` | 首轮生成、只有 `cooldown_until` 而没有状态的合成快照 |
| `backend/tests/fixtures/v1_planning_request.json` | 首轮生成的 create_profile 请求结果与原始 request sha |

### 3.4 旧请求重放兼容修复（`6592f98..8d75a7a`，6 个文件，+301 / -19）

| 文件 | 变化 |
| --- | --- |
| `backend/src/app/trade_planning/inputs.py` | Draft 允许读取“未知状态 + 截止时间”的历史形态；新增 `require_current_semantics()`；`PlanningProfileSnapshot.build` 对新快照执行严格冷却语义 |
| `backend/src/app/infrastructure/persistence/planning_input_repository.py` | `create_profile` 计算首轮缺字段/第二轮显式 null 两种候选请求指纹；重放未命中才执行严格首次写入检查 |
| `backend/tests/trade_planning/test_inputs.py` | 历史 Draft 可读、`require_current_semantics`/build 严格拒绝，新版三态保持 |
| `backend/tests/persistence/test_planning_inputs.py` | 首轮带截止时间请求重放、第二轮显式 null 重放、财务/嵌套/状态冲突、跨工作台/操作、新键严格校验、并发重放 |
| `backend/tests/fixtures/v1_planning_request_with_cooldown.json` | 首轮 tip `144e501` 实际生成的带 `cooldown_until` 请求、原 request sha 与结果 |
| `backend/tests/fixtures/v2_planning_request_null_cooldown.json` | 第二轮 tip `4f0e7ae` 实际生成的显式 `cooldown_status:null` 请求、原 request sha 与结果 |

## 4. FR/AC/HN 映射

| 标识 | 本轮落地 | 证明边界 |
| --- | --- | --- |
| FR-14 手动资金与风险资料 | 资料/政策版本；规划资金、可用保证金、单笔/日损/组合剩余风险、已有仓位/挂单名义额/保证金/风险、当日损益日期、冷却三态、熔断、杠杆/保证金/持仓模式；未知保留为 `None`；15 分钟本地有效期；UTC 跨日需重新声明 | 未实现数量/风险计算、计划采纳、占用释放或用户资料界面；`resolve_refs` 只做输入齐备/时效判断 |
| FR-15 市场规则与可实施校验 | `VenueRuleSnapshot` 绑定产品、乘数/数量单位、真实过滤器、交易状态、订单/触发/有效期、来源抓取时间/60 分钟有效期；公开规则读取只走受控 `exchangeInfo`；网关异常转换为规划错误 | 未实现 tick/step 舍入、最小额冲突、保证金/强平计算、订单可实施性；这些由 T12/T13 完成 |
| AC-21 正常候选与完整资料 | 提供资料/政策/成本/保证金/规则引用基础 | 未实现程序数量、成本、风险、操作清单或用户审核；不宣称 AC-21 完整通过 |
| AC-22 缺项/过期 | `missing_fields`、`resolve_refs` 返回 `None`；冷却未知、成本/保证金/资料过期和跨日不自动恢复；不补零 | 后续计划状态与待补文案在 T12/T13/T16 |
| AC-23/AC-24 | 未实现舍入、最小额、日损/冷却/熔断/仓位/杠杆阻断计算 | 明确留给 T12/T13；T03 只拒绝关闭止损/冷却/熔断的策略标志 |
| AC-25 规则/成本/保证金缺项 | 缺失/重复过滤器、非 USDT/非永续规则、非法十进制明确不可用；缺少维持保证金/强平依据时资料不完整；非交易状态保留并可判定；网关异常统一为 planning 错误 | 不调用私有档位接口，不把缺失当零；真实官方复验留 T18 |
| AC-29 财务资料与只读边界 | 完整财务值只在受限 `trade_planning` 契约和规划表；无模型/RAG/通用事件/日志投影；无签名或私有账户接口 | 未接 HTTP/前端/模型；本轮没有事件投影路径，审计投影在后续任务验证 |
| AC-30 多任务共用资金池 | 每工作台唯一池、共享 generation、profile/policy/rules 变更递增、profile/policy 乐观代次拒绝旧写 | 未实现“同池仅一份待实施计划”、采纳互斥、未知占用保留/承接；这些由 T13/T17 完成 |
| HN-13 可实施状态不可由模型声明 | 输入完整性/时效/版本/代次由确定性服务和 DB 约束决定 | 可实施状态本身在 T12/T13；T03 不生成 `ready_for_manual_execution` |
| HN-14 财务/预算隔离 | 财务资料不进入 Agent、RAG、通用事件或模型 DTO；本任务无模型调用 | 未接上下文/事件/API，后续任务需继续验证投影 |
| HN-15 单池占用与代次 | 唯一工作台池、generation 递增、代次冲突拒绝、请求幂等和不可变版本 | 未实现唯一待实施计划、采纳占用或用户声明承接 |

历史兼容：首轮快照按旧字段集合保留原 ref 读取，缺少 `cooldown_status` 时仍为未知/不完整，不自动推断为 `none` 或 `active`；旧请求结果按同键同参重放，旧财务/嵌套字段篡改仍被拒绝。

未宣称：FR-09/FR-16/FR-17 的完整计划、操作清单、采纳与反馈；T12/T13 的计算和资金池互斥；真实收益、策略质量或产品已发布可用。

## 5. 关键实现取舍

1. **内容指纹覆盖嵌套值与引用**：资料快照的 `ref.sha256` 覆盖产品、全部财务字段、保证金证据、成本 ref、时间和来源；成本/政策/规则快照同理。构造后重新序列化校验，嵌套保证金或根对象额外字段被修改都会使旧 ref 失效。
2. **未知不补零**：所有关键财务字段为 `Decimal | None`；未知占用、未知当日日期、未知冷却状态、未知熔断状态保留 `None`。`resolve_refs` 只在完整、时效内且当日声明匹配时组合引用。显式零才表示已确认无占用；显式 `cooldown_status=none` 才表示确认无冷却。
3. **单池 generation 与 CAS**：`planning_pools.workspace_id` 唯一；创建资料/政策/规则均在池行锁内递增 generation。资料/政策写入要求 `expected_generation`，过期写入拒绝；规则刷新作为新的公开规则版本也递增 generation，使旧核验失效。
4. **请求幂等与锁后时间**：写方法先取 `pg_advisory_xact_lock(hashtextextended(request_id,0))`，再读幂等记录；请求结果、版本行和池代次同事务提交。业务时间在请求锁/池行锁后采样。规则刷新先通过同样加锁的 `replay_venue_rules` 检查已提交结果，避免依赖当前公开源可用性；首次写入仍由 `record_venue_rules` 的锁和事务完成，不能由无锁查询替代。
5. **真实过滤器而非精度字段**：规则适配器只使用 `PRICE_FILTER.tickSize/minPrice/maxPrice`、`LOT_SIZE`/`MARKET_LOT_SIZE` 的 `stepSize/minQty/maxQty` 和 `MIN_NOTIONAL.notional`；`pricePrecision`/`quantityPrecision` 只作为可选元数据保留，不参与 tick/step 推导。缺失/重复过滤器、非 USDT/非永续、非法十进制明确失败。
6. **规则来源时间贯穿缓存**：网关在真实 HTTP 返回后记录 `fetched_at`，缓存命中沿用该时刻；规则快照的 `observed_at` 和 60 分钟有效期均按来源时间计算，不按本地读取时钟重置。
7. **规则状态与时效分离**：非 `TRADING` 状态仍可作为不可变快照保存，但 `is_trading == False`；有效期 60 分钟，后续可实施核验必须检查，不在输入层假装可交易。
8. **首期产品目录有限**：仅 BTCUSDT/ETHUSDT、Binance USDT 线性永续、逐仓、单向；产品、结算、合约类型和数量单位不一致拒绝。支持判断要求已有仓位/挂单的名义额、保证金、风险六个字段都显式；任一未知或非零即阻断，避免同品种合并风险未实现时假定空仓。
9. **政策是硬约束**：金额、名义额、数量、杠杆、最小净盈亏比、日损、组合风险无默认值；缺项政策可保存但不完整。止损、冷却和熔断强制标志显式设为 `False` 时模型直接拒绝，不能由用户审核绕过。
10. **不可变迁移**：资料/政策/成本/规则/请求行拒绝 UPDATE/DELETE；资金池允许代次更新但拒绝删除。`0021` 为前向迁移，downgrade 明确拒绝删除历史版本。

## 6. 接口、依赖与迁移影响

- 公共 Python 类型：`PlanningProfileDraft`、`PlanningProfileSnapshot`、`PlanningRiskPolicyDraft`、`PlanningRiskPolicy`、`CostAssumptionsDraft`、`CostAssumptions`、`MarginEvidenceDraft`、`MarginEvidence`、`VenueRuleSnapshot`、`PlanningRefs`、`MarginMode`、`PositionMode`、`QuantityUnit`、`CooldownStatus` 及规划错误码。
- 服务/仓储协议：`PlanningInputService.create_profile/create_policy/refresh_venue_rules/resolve_refs/get_pool`；`PlanningInputRepository`（新增 `replay_venue_rules`）；`PublicRuleReader`；`SqlAlchemyPlanningInputRepository`；`BinanceUsdmPublicRuleReader`。
- 公开行情网关新增 `PublicExchangeFilter`、`PublicExchangeSymbol`（含 `fetched_at`）、`get_exchange_symbol_rules`；旧 `get_exchange_info` 仍返回原六字段，既有目录准入测试保持通过。
- 契约差异：C3 文本只列出 `create_profile`/`create_policy`/`resolve_refs`。本轮额外提供 `refresh_venue_rules`、`get_pool` 和仓储 `replay_venue_rules`：规则快照必须由服务端受控读取并持久化，代次必须可查询，已提交请求必须在公开源重读前重放；它们不改变业务语义，T12/T15 可直接消费。
- HTTP/API、前端、`WorkbenchApi`、Agent 工具循环、模型上下文：本轮未改动；没有新增路由、DTO、能力开关或前端页面。
- 持久化：新增 `planning_pools`、`planning_profiles`、`planning_risk_policies`、`planning_costs`、`planning_venue_rules`、`planning_input_requests`；迁移 head 为 `0021_planning_inputs`。未迁移业务库；downgrade 拒绝删除历史。
- 依赖：无新增生产/开发依赖；未升级锁定版本。
- 安全/配置：未修改 `.env`、凭证、业务库、运行配置、自动交易限制或默认审核；未新增交易所、MCP、外部服务或付费调用。

## 7. 测试执行与证据

执行目录除特别注明外为隔离工作区 `backend/`。数据库测试使用独立临时 PostgreSQL 17 容器（本机回环、受限角色 `crypto_research_test_runner`），先通过 `check_test_database` 只读身份/权限预检；未指向业务库。full 从隔离工作区根目录执行。

| 检查 | 命令 | 退出码 | 实际结果 |
| --- | --- | --- | --- |
| 首轮纯契约预期红 | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py tests/trade_planning/test_product_support.py tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-red-pure-20261109` | 1 | 3 collection errors（缺少新模块），符合测试先行预期 |
| 首轮 SQL 预期红 | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --basetemp=../.tmp/pytest/t03-red-db-20261109` | 1 | 1 collection error（缺少 `models.planning_inputs`），符合测试先行预期 |
| 首轮纯契约/规则绿 | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py tests/trade_planning/test_product_support.py tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-final-pure-20261109` | 0 | 15 passed |
| 首轮 SQL 绿 | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --basetemp=../.tmp/pytest/t03-final-db-20261109` | 0 | 9 passed |
| 首轮阶段回归 | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/persistence/test_planning_inputs.py tests/persistence/test_migrations.py tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t03-stage2-20261109` | 0 | 168 passed |
| 首轮 full | `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t03-full-backend-tip2.json` | 0 | 1113 passed / 0 failed / 0 skipped |
| **复审修复前纯契约/规则红** | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py tests/market/test_planning_rules.py -q --tb=short --basetemp=../.tmp/pytest/t03-fix-red-20261109` | 1 | 11 failed / 5 passed；冷却未知、抓取时间、网关异常转换和规则重放前置缺陷均复现 |
| **复审修复前旧 tip 重放红基线** | 旧 tip `144e501` 临时工作树 + 临时 PostgreSQL 17：`python -m pytest tests/persistence/test_t03_red_replay.py -q --tb=short --basetemp=../.tmp/pytest/t03-red-replay-20261109` | 1 | 1 failed；同一 request_id 第二次刷新在上游失败时直接抛 `PlanningRuleUnavailableError`，未进入重放 |
| **复审修复后纯契约/规则聚焦** | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-fix-green3-20261109` | 0 | 17 passed；含冷却三态、缓存来源时间、60 分钟边界、网关异常转换及服务捕获 |
| **复审修复后 SQL 聚焦** | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --basetemp=../.tmp/pytest/t03-fix-db2-20261109` | 0 | 12 passed；含未知冷却阻断、规则重放先于公开源、同键并发单次提交及既有代次/触发器回归 |
| **复审修复后阶段回归** | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/persistence/test_planning_inputs.py tests/persistence/test_migrations.py tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t03-fix-stage-20261109` | 0 | 176 passed；含 T01/T02、行情网关、迁移链和技术引擎回归 |
| **复审修复后后端 full** | 从隔离工作区根目录：`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t03-review-fix-full-backend-tip.json` | 0 | `verification=passed`；后端 1121 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t03-review-fix-full-backend-tip.json` |
| **历史兼容修复前纯契约红** | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py -q --tb=short --basetemp=../.tmp/pytest/t03-legacy-red-20261110` | 1 | 2 failed / 10 passed；旧快照读取报“规划版本指纹与内容不一致” |
| **历史兼容修复前 SQL 红** | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py::test_legacy_profile_and_request_replay_are_version_aware -q --tb=short --basetemp=../.tmp/pytest/t03-legacy-db-red2-20261110` | 1 | 1 failed；`get_profile` 解析旧资料行抛 `planning_integrity_violation` |
| **历史兼容修复后纯契约/规则聚焦** | `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-legacy-pure-green3-20261110` | 0 | 23 passed；含旧快照原 ref、带截止时间旧载荷、序列化重读、篡改拒绝及新版三态 |
| **历史兼容修复后 SQL 聚焦** | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --tb=short --basetemp=../.tmp/pytest/t03-legacy-db-green2-20261110` | 0 | 13 passed；含旧 profile 行读取、resolve_current/resolve_refs、旧请求结果重放与 generation 不变 |
| **历史兼容修复后阶段回归** | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/persistence/test_planning_inputs.py tests/persistence/test_migrations.py tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t03-legacy-stage-20261110` | 0 | 180 passed；含 T01/T02、行情网关、迁移链和技术引擎回归 |
| **历史兼容修复后后端 full** | 从隔离工作区根目录：`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t03-legacy-full-backend-tip.json` | 0 | `verification=passed`；后端 1125 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t03-legacy-full-backend-tip.json` |
| **旧请求重放修复前纯契约红** | `uv run --locked --no-sync pytest tests/trade_planning/test_inputs.py::test_cooldown_state_must_be_explicit -q --tb=short --basetemp=../.tmp/pytest/t03-req-red-pure-20261110` | 1 | 1 failed；首轮“未知状态 + 截止时间”Draft 仍被严格校验提前拒绝 |
| **旧请求重放修复前 SQL 红** | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py::test_v1_request_with_cooldown_deadline_replays_then_strictly_rejects_new_key tests/persistence/test_planning_inputs.py::test_v2_request_with_explicit_null_status_replays_and_conflicts -q --tb=short --basetemp=../.tmp/pytest/t03-req-red-sql3-20261110` | 1 | 2 failed；首轮 Draft 构造失败，第二轮显式 null 被误判 `request_conflict` |
| **旧请求重放修复后纯契约/规则聚焦** | `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py -q --basetemp=../.tmp/pytest/t03-req-green-pure2-20261110` | 0 | 23 passed；历史 Draft 可读、严格首次写入拒绝、新版三态与既有规则解析保持 |
| **旧请求重放修复后 SQL 聚焦** | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_planning_inputs.py -q --tb=short --basetemp=../.tmp/pytest/t03-req-green-sql2-20261110` | 0 | 16 passed；含首轮带截止时间重放、第二轮显式 null 重放、冲突、新键严格校验与并发重放 |
| **旧请求重放修复后阶段回归** | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/trade_planning tests/market/test_planning_rules.py tests/market/test_binance_usdm.py tests/market/test_public_boundary.py tests/persistence/test_planning_inputs.py tests/persistence/test_migrations.py tests/research/strategies tests/research/knowledge tests/persistence/test_strategy_catalog.py tests/persistence/test_knowledge_index.py tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t03-req-stage-20261110` | 0 | 183 passed；含 T01/T02、行情网关、迁移链和技术引擎回归 |
| **旧请求重放修复后后端 full** | 从隔离工作区根目录：`uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t03-request-compat-full-backend-tip.json` | 0 | `verification=passed`；后端 1128 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t03-request-compat-full-backend-tip.json` |
| 架构门禁 | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=38`，`findings=[]` |
| 静态检查 | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 0 | 全部通过；pyright 0 errors / 0 warnings |
| 迁移链 | `uv run --locked --no-sync alembic heads` | 0 | `0021_planning_inputs (head)` |

证据路径位于隔离工作区 `.tmp/`（不随 Git 传递，按上表命令可复现）：`.tmp/quality/manual-agent-t03-request-compat-full-backend-tip.json`；pytest 临时目录为 `.tmp/pytest/t03-*`。full 报告只保存安全计数与检查状态，不包含连接串、环境变量、原始异常或财务数据。

环境说明：验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV`、`GIT_CONFIG_COUNT`；未修改 `.env` 或业务配置。测试资金、费率、保证金和规则均为合成资料；未调用真实模型、未访问私有账户、未修改业务库、未发起真实交易。

## 8. 未验证项

- 未运行前端 lint/typecheck/Vitest/build、浏览器 e2e 或 http-e2e；本轮无前端改动，full 使用 `--component backend`。
- 未调用真实模型或付费服务；未验证真实模型质量、上下文/RAG 工具接入或模型财务值隔离投影（本轮尚无这些路径）。
- 未对真实 Binance 公开源执行 T18 的只读官方复验；规则测试使用固定合成 `exchangeInfo` 和 MockTransport。未证明规则字段在真实公网长期稳定、`MIN_NOTIONAL` 字段名未被上游调整或所有交易状态可解析。
- 未迁移业务库、未部署；`0021` 仅在临时测试 schema 验证，未应用到任何业务库。
- 未实现 T12/T13 的数量/成本/保证金/风险/可实施状态计算、采纳互斥、同池待实施计划唯一约束、未知占用保留/承接或用户声明释放。
- 未实现 T15/T16 的 HTTP API、错误码映射、前端表单/授权视图或财务投影。
- 未做多进程/高并发压力、长时间运行、规则缓存命中率或性能评估；本轮只做真实 PostgreSQL 双会话并发和受控临时实例验证。
- 未验证严格数据库提交时可得；快照时间是服务端决策/来源抓取时间，不是 PostgreSQL 提交时间。
- 未提供策略收益、产品已发布可用或实盘可实施声明。

## 9. 已知风险与重点审查位置

1. **历史快照与请求格式判定**：历史快照依据 `model_fields_set` 是否实际包含 `cooldown_status`，并以旧字段集合重算原始指纹；`versioned_payload()` 用 `exclude_unset` 保留历史序列化。Draft 现在允许读取首轮“未知状态 + 截止时间”的历史形态，但首次新写/新快照通过 `require_current_semantics()` 严格拒绝；仓储在重放命中后才跳过该严格检查。请求指纹同时匹配第二轮显式 `cooldown_status:null` 与首轮缺字段两种格式，新写入使用显式字段格式。请重点核对“重放优先、首次写入严格”的顺序、候选指纹是否可能接受不同参数、并发重放是否单次提交，以及是否应把历史格式信息显式持久化。
2. **规则刷新重放边界**：`replay_venue_rules` 在请求 advisory lock 下读取，但锁随预检查事务释放；两个并发同键请求仍可能都重新采集，随后由 `record_venue_rules` 重放为单次提交。请核对这一窗口是否可接受，以及是否应把公开读取纳入更长事务/锁。
3. **规则来源时间**：`fetched_at` 由网关在 HTTP 返回后采样；缓存命中沿用该值。请核对缓存 TTL、抓取时间与 60 分钟有效期的组合，以及是否需要在未来记录上游响应自身的观测时间。
4. **`MIN_NOTIONAL` 兼容性**：适配器优先读 `notional`，否则读 `minNotional`；未覆盖未来可能的 `NOTIONAL` 过滤器类型。`PRICE_FILTER`/`LOT_SIZE`/`MARKET_LOT_SIZE`/`MIN_NOTIONAL` 任一缺失即拒绝。T18 官方复验前不宣称产品规则已发布验收。
5. **数量单位与乘数**：首期对 Binance USDT-M 线性永续固定 `quantity_unit=base_asset`、`contract_multiplier=1`。请确认该假设在首期产品范围内正确，以及反向/币本位被 `ProductKey` 和规则适配器双重拒绝是否足够。
6. **generation 语义**：profile、policy 和 rules refresh 都递增池代次；profile/policy 使用 `expected_generation` CAS，rules refresh 不使用 expected generation。请核对规则刷新与并发 profile/policy 写入的锁顺序、是否会出现用户未预期地使旧检查失效，以及 T13 如何消费该代次。
7. **完整引用门槛**：`resolve_refs` 要求资料包含成本版本、完整保证金证据和显式冷却状态。这可能比 T12 允许的“草案 + 待补”更严格；请核对该服务应只作为“可规划引用”门槛，还是应返回带缺项的引用。
8. **规则刷新幂等指纹**：同一 request_id 的规则刷新只按产品复用首次快照，不比较新抓取内容；这是为避免重新抓取时间变化导致重试冲突。请核对是否满足“同键同参复用、需要新规则用新请求键”的契约，以及跨工作台/不同产品冲突处理。
9. **不支持模式的存储边界**：模型层直接拒绝 cross/hedge 和关闭止损/冷却/熔断的策略；如果未来需要存储“不支持模式”用于诊断，需要单独设计，当前选择是明确拒绝而非保存后由计算层阻断。
10. **已有占用判断**：产品支持要求六个占用字段全部显式；风险为零但名义额/保证金非零也会阻断。请核对是否与 T13 的占用承接、未知占用保留和同品种合并规则一致。
11. **版本不可变触发器**：`planning_pools` 允许 UPDATE、拒绝 DELETE；版本/请求表拒绝 UPDATE/DELETE。请核对触发器和请求幂等记录的组合是否会影响未来归档/清理，以及是否需要在 T13 增加池锁的更多约束。
12. **测试替身边界**：`test_planning_rules.py` 使用固定 `PublicExchangeSymbol` 替身和 MockTransport，证明解析、缓存时间和失败分支；不证明真实公网长期可用性或真实交易所规则。SQL 测试证明 PostgreSQL 行为，不证明生产并发吞吐。

## 10. 自测与正式审查状态

- 自测状态：`verified`。旧请求重放兼容修复、修复前红、修复后纯契约/规则 23 passed、SQL 16 passed、阶段回归 183 passed、后端 full 1128 passed / 0 failed / 0 skipped、静态检查、架构门禁和迁移 head 均已完成；上述未验证项不计入通过。
- 正式审查状态：`approved`。首轮正式审查对 `144e501` 判定 4 项 P2 不通过；第二轮对 `4f0e7ae` 判定 1 项历史快照 P2 不通过；第三轮对 `023e5a2` 判定 1 项旧请求重放 P2 不通过；用户于 2026-11-10 传回原审查助手对 `8d75a7a14471c36e4a168c166e3f94b659ceb9e7` 的正式通过结论，`reviewed_tip=8d75a7a`。T03 代码与复审文档以 fast-forward 合并到 `main`。
- 审查范围：首轮 `6fb08b5..144e501`（17 个文件，+4108/-15）；第二轮修复 `efae1dd..4f0e7ae`（9 个文件，+508/-51）；历史兼容修复 `127c247..023e5a2`（7 个文件，+235/-7）；旧请求重放修复 `6592f98..8d75a7a`（6 个文件，+301/-19）。重点为 Draft 历史形态读取与首次写入严格校验、双格式候选请求指纹、重放优先顺序、旧 fixture 与原 request sha、并发重放和冲突拒绝。本轮复审包文档提交只改进度/状态/契约标注和本文件，不夹带代码或其他任务改动；最终回复提供文档提交 hash。
- T03 已放行；T04 等待用户明确指定，不自动开始。
