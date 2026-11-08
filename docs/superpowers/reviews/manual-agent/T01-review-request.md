# T01 审查请求：策略包版本与已有规则评估

- 任务/审查单元：T01（D1；策略包版本、参数白名单、只读评估器与既有规则适配）
- 复审轮次：第 2 轮（正式审查不通过后的修复交审）
- 生成日期：2026-11-08
- 执行模型：DeepSeek Harness 驱动的 `deepseek-flash`（会话标注；上游精确构建版本未知）
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；质量验证以仓库当前 `docs/quality-verification.md` 为准。
- 自测状态：`verified`（修复实现与自测完成）
- 正式审查状态：`approved`（用户于 2026-11-08 传回原审查助手正式通过结论；`reviewed_tip=159a43b`）
- 下一审查单元：T01 已放行；T02 等待用户明确指定，不自动开始。

## 1. 固定点与工作区

| 项目 | 值 |
| --- | --- |
| 工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t01` |
| 分支 | `task/manual-agent-t01` |
| base | `6f293fec8d47541ae001afdd3bb4295f298f0cdb`（`main`，T00 合并后） |
| 原 implementation tip | `8e73ace0cbdaa099190ed011d0eac7e9f7ac6d3b`（首轮正式审查不通过） |
| 修复 implementation tip | `159a43be3822e6f0fcbd314da67719187c06e610`（`fix: harden T01 concurrency and immutable inputs`） |
| tree | `6dc9d2f3bb0b1c8d7ab5f7e748a7fef7ff618ebd` |
| 首轮代码范围 | `6f293fe..8e73ace`，17 个文件，+3945 / -0 |
| 本轮修复范围 | `2521ec8..159a43b`（`2521ec8` 为修复前 docs tip），8 个文件，+571 / -61 |
| 未提交代码 | 无；修复 tip 处代码与测试已全部提交 |
| 审查包文档 | 本文件与进度/状态文档位于修复代码之后的 docs-only 提交；不在本文件内记录自身提交号，避免自引用。最终回复提供文档提交 hash。 |

修复 tip 处工作区干净。审查包文档提交只改文档，不夹带代码。

## 2. 改动清单

| 文件 | 作用 |
| --- | --- |
| `backend/src/app/shared/agent_types.py` | 新增不可变公共类型：`VersionRef`、`ArtifactRef`、`ProductKey`、`DecimalText`、`PageQuery`、`VersionPage`、JSON 规范化哈希 |
| `backend/src/app/research/evidence.py` | 新增 `EvidenceEpoch`/`EvidenceItem`：分析截止、封存、逐项来源/时间/质量/内容指纹与引用 |
| `backend/src/app/research/strategies/contracts.py` | 新增策略草稿/发布版本、参数 Schema 白名单、候选、评估结果和错误类型 |
| `backend/src/app/research/strategies/ports.py` | 新增 `StrategyCatalog`、`StrategyEvaluator` 异步端口 |
| `backend/src/app/research/strategies/service.py` | 新增评估器注册表与 `StrategyService`：参数门禁、精确查找、结果绑定校验 |
| `backend/src/app/agent/interactive/adapters/technical_strategy.py` | 新增 `technical_breakout_v1` 适配器；复用既有技术引擎，不修改旧算法 |
| `backend/src/app/infrastructure/persistence/models/research_strategies.py` | 新增策略定义、版本、目录请求幂等 ORM 映射 |
| `backend/src/app/infrastructure/persistence/strategy_catalog.py` | 新增 `SqlAlchemyStrategyCatalog`：发布/更新/归档/分页/幂等/组合校验 |
| `backend/alembic/versions/0019_strategy_catalog.py` | 新增前向迁移、约束、索引和发布不可变触发器 |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | 注册新 ORM 模型 |
| `backend/tests/research/strategies/test_catalog.py` | 参数 Schema、草稿/发布哈希、组合冻结、候选指纹、评估状态契约测试 |
| `backend/tests/research/strategies/test_evaluator.py` | 证据封存、技术适配器、服务无评估器/参数拒绝、绑定篡改、测试组合评估器 |
| `backend/tests/persistence/test_strategy_catalog.py` | SQL 发布不可变、请求幂等、归档历史、组合组成、分页测试 |

### 文件 SHA256（修复 tip `159a43b`）

| 文件 | SHA256 |
| --- | --- |
| `backend/alembic/versions/0019_strategy_catalog.py` | `4cf96ce4b7b401380cff97e1623f0bc5119192aa15f1eb8564b3bfc83ff240ca` |
| `backend/src/app/agent/interactive/__init__.py` | `b5c9611e7dfbf3f5f9a93de1552208f35c55e16d7cde792afdfeeb339528c9a4` |
| `backend/src/app/agent/interactive/adapters/__init__.py` | `ebd1c190103321ff27553035ae771de0037fee061f39e03bb5a4d62eac7f5d9e` |
| `backend/src/app/agent/interactive/adapters/technical_strategy.py` | `ebb13db75130ad8459e32d9cb7b4d2731188144f18b375cf10a8a5221e00b31e` |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | `e78560a897ba26912cd36d50a268f433823f1bc92d64fc5ddb80731d6f6f08f7` |
| `backend/src/app/infrastructure/persistence/models/research_strategies.py` | `747719df2f5aaab7c4095e1fa7bc625780f73363c7d5176734e49794e053e6f4` |
| `backend/src/app/infrastructure/persistence/strategy_catalog.py` | `5052727dc4b69361a8c12c1554961ca02c2a3087182c63c629f3feb1c06b80b4` |
| `backend/src/app/research/evidence.py` | `bd0e1a48b3f3ae0d297743ebd48de4487622babbb91c668b44a26230094ed2fc` |
| `backend/src/app/research/strategies/__init__.py` | `069f46fc8e6ed6c6a93cbe0aa9b49eef6224e58b3d494d4f904d982f14593760` |
| `backend/src/app/research/strategies/contracts.py` | `328fe6bc424dbdd0370c0f7da2ecdcf9992c2564331df94a77f856bf1eb2618e` |
| `backend/src/app/research/strategies/ports.py` | `9dc7bafc12bcf58074dcaf8bb11a441cd875a145bf75c0a7755b9737cf99cea4` |
| `backend/src/app/research/strategies/service.py` | `5ebf19832f20c8efde8318c4a49deb6c9f01de8147e8cfc7060e4761b93cb6ef` |
| `backend/src/app/shared/agent_types.py` | `4006b78f1ba72c68b0eead6148206ae49c503cd7e29dc22b7f22d74ed83f5fcd` |
| `backend/tests/persistence/test_strategy_catalog.py` | `4c25b4d454bf66c88853d43ab0e0cd7d0c1b5864f92752010a35dfad73237fa3` |
| `backend/tests/research/strategies/__init__.py` | `da348f4e9e3206fa32c1e81f1bc027b865673bdcf2a70b8d999241051aff742d` |
| `backend/tests/research/strategies/test_catalog.py` | `953f37e77a370a9fad0960c1b02a79128967a164ae38ce78a8f4cf453652907b` |
| `backend/tests/research/strategies/test_evaluator.py` | `76d01d2ac0f8474a014a9bcabf4f25f8d867bdccebd90335848781896e7e38b5` |

### 2.1 复审问题修复对照

| 审查问题 | 修复 | 回归证据 |
| --- | --- | --- |
| P1 并发相同 request_id 未返回原成功结果 | 在四个写方法的业务读取前获取 `pg_advisory_xact_lock(hashtextextended(request_id, 0))` 事务锁，同 request_id 串行化后再读幂等记录；请求结果和业务变更仍在同一事务提交。create_draft 也加入同一锁，保留 unique 冲突重放作为第二道保护。 | 真实 PostgreSQL 双会话、外部行锁同步点覆盖 publish/update_draft/archive/create_draft：同请求并发均返回原结果，业务变更和幂等记录各一次；同键不同内容/操作/工作台仍冲突。 |
| P1 封存证据/发布策略嵌套内容可变，旧指纹继续生效 | `EvidenceItem.content`、`EvidenceEpoch.items`、`StrategyComponent.parameters`、策略 `components`/`parameter_schema` 在模型边界深拷贝；`EvidenceEpoch.validated_snapshot()` 重验逐项内容指纹、epoch 哈希和标识；`StrategyVersion.validated_snapshot()` 重验发布正文哈希；`StrategyService` 和适配器在消费入口先取隔离快照；草稿发布前深拷贝并重校验。 | 修改 `market_evidence()` 返回内容、直接修改 epoch 内嵌内容、修改发布 Schema/组成参数均被拒绝；修改原始输入或草稿不影响已封存证据/已发布版本；合法输入保持通过。 |
| P2 参数 Schema 根节点可为 string/array 等非 object | `validate_parameter_schema()` 根入口强制 `type == "object"`，嵌套节点仍走原类型白名单。 | string/decimal/integer/boolean/array 根 Schema 直接拒绝，草稿契约也拒绝；合法 object 根及嵌套 string/array 继续通过。 |


## 3. FR/AC/HN 映射

| 标识 | 本轮落地 | 证明边界 |
| --- | --- | --- |
| FR-10 策略池 | 草稿编辑、发布不可变、归档、精确版本读取、参数 Schema、能力标记、组合组成冻结 | 不实现 MACD/三重过滤/用户策略算法；不代表生产策略效果 |
| FR-09（支撑） | 评估结果绑定所选策略版本、参数、评估器版本和证据指纹；无候选保留版本绑定 | 规划计算与计划产物在 T12+，本轮不生成数量/资金/计划 |
| AC-07 | 目录写操作 request_id 幂等；同键不同工作台/操作/内容拒绝；草稿/发布版本分离 | SQL 顺序重放与双会话并发重放已测；同键不同内容/操作/工作台拒绝 |
| AC-08 | 未登记评估器返回 `NO_EVALUATOR`，候选为空，不回退技术规则 | 方法研究入口尚未接 API/前端 |
| AC-09 | 技术适配器采用既有引擎几何；候选绑定所选版本/参数/证据；测试覆盖候选指纹变化 | 旧引擎无未来数据泄漏测试另行运行；本轮未新增策略算法 |
| AC-28 | 组合版本冻结组成 `VersionRef`；发布时校验已发布组成、指纹、归档状态与组成参数 Schema；测试组合评估器仅测试注册 | 生产不登记虚构组合；不等于未来用户组合已可产生实盘计划 |
| HN-09 | 评估器按 `evaluator_id` 精确查找；参数只接受有界白名单；适配器不匹配时失败而非换用其他策略 | 上下文裁剪/RAG 改写授权尚未实现（T08/T09） |
| HN-10 | 证据 epoch 保留来源、观测/可得/抓取时间、质量、内容指纹；时间顺序和未来内容被拒绝；候选绑定证据指纹 | 真实 RAG/知识时间语义在 T02/T08；本轮不声称外部来源质量 |

未实现/未宣称：FR-04、FR-14、FR-15、FR-16、FR-17；AC-21 至 AC-27、AC-29、AC-30；无 API、无前端、无真实模型质量、无产品规则验收。

## 4. 关键实现取舍

1. **参数 Schema 只实现安全子集**：根必须是 object，所有 object 必须显式 `additionalProperties: false`；支持 string/decimal/integer/boolean/array/enum/长度/边界；拒绝 `$ref`、正则、`format`、代码类型、未列入类型白名单的关键字、过深/过大结构。decimal 只接受普通十进制字符串，不接受 float/指数/NaN。未来策略需要新关键字时应改契约并复审，不能静默放宽。
2. **版本哈希只覆盖语义内容**：`StrategyVersion.ref.sha256` 覆盖策略身份、名称、方法文本、kind、组成、组合规则文本、参数 Schema、支持币种/周期、预热、evaluator_id、能力、风险说明；不覆盖 `published_at`、归档状态、草稿/定义版本号，避免归档或重新读取改变历史正文指纹。
3. **归档状态从定义行派生**：发布版本正文和 `sha256` 不变；`archived`/`archived_at` 由 `strategy_definitions` 派生。停用阻止新草稿/发布/执行，但历史列表仍可读取。数据库触发器只保护发布版本行，不阻止定义行归档。
4. **请求幂等表保存原始结果**：`strategy_catalog_requests` 以 request_id 为主键，保存操作、规范化请求指纹和原始返回 JSON；同键重放返回原结果，不同内容/工作台/操作返回冲突。四个写方法在业务读取前获取 request_id 事务级 advisory lock，让相同请求在第二个事务读状态前先重放已提交结果；请求结果与业务变更同事务提交。不同 request_id 仍由业务行锁和 expected_version 产生正常冲突。
5. **组合发布逐项核对**：每个组成必须是同工作台已发布版本、`VersionRef.sha256` 与内容一致、定义未归档、参数符合组成 Schema、不能引用自身 strategy_id；组合版本冻结组成引用，不执行任意表达式。
6. **技术适配器不改旧算法**：`TechnicalStrategyEvaluator` 只调用既有 `calculate_technical_analysis()`，把旧计划几何映射为 `PriceCandidate`；参数只允许 `minimum_reward_risk`（下限 1.5，只能收紧）和 `allowed_states`（只过滤既有候选）。不新增信号逻辑，不生成数量/资金/订单。价格按既有公开 18 位精度规则量化，取整后仍由候选几何校验；未声明 `conservative_one_tick`，使用 `strict`。
7. **证据 epoch 严格时间口径**：逐项要求 `observed <= available <= fetched`，且 `observed/available <= analysis_as_of`、`fetched <= sealed_at`；内容指纹与内容一致；epoch 标识和哈希由内容重算校验。内容最多 4 MiB；大型载荷可只保留 `ArtifactRef`。
8. **候选 ID 不写死 plans.0**：`PriceCandidate.candidate_id` 由版本、组成、参数哈希、评估器 ID/版本、证据哈希/截止时间、方向、价格、状态、tick 规则和适用条件共同哈希；测试证明参数/证据/几何变化会产生不同 ID。
9. **状态语义**：定义 `state_version` 从 0 开始；草稿 `state_version` 从 0 起编辑递增；发布版本 `state_version` 取发布时定义代次（首次发布为 1）；归档递增定义代次。草稿版本号和定义代次不是同一个计数器。
10. **迁移只新增**：`0019_strategy_catalog` 串接 `0018_technical_report_runs`，只新增三张表、索引、检查和发布不可变触发器；不修改旧表/旧报告/旧审计，不回填业务库，downgrade 明确拒绝。
11. **嵌套输入在模型边界深拷贝，在消费入口重验**：Pydantic `frozen=True` 只防字段重绑定，因此证据内容、epoch items、策略 Schema、组成参数和组合对象在构造时深拷贝；`EvidenceEpoch.validated_snapshot()` 和 `StrategyVersion.validated_snapshot()` 在评估前重建并校验哈希，服务和适配器都先取快照再读取。这样既隔离调用方后续修改，也拒绝“内容变了但旧指纹仍生效”。

## 5. 接口、依赖与迁移影响

- 公共 Python 类型：见上表；目前没有 HTTP/API 消费者，未修改现有接口、旧报告、模拟盘、风控或执行路径。
- 协议：`StrategyCatalog`（get_published/publish/create_draft/update_draft/list_versions/archive）与 `StrategyEvaluator`（evaluator_id/evaluator_version/evaluate）；仓储与适配器通过端口注入，`research/strategies` 不反向依赖 Agent/持久化。
- 持久化：三张新表 `strategy_definitions`、`strategy_versions`、`strategy_catalog_requests`；发布不可变触发器拒绝发布行 UPDATE/DELETE；迁移 head `0019_strategy_catalog`。
- 依赖：无新增生产依赖；未升级 LangGraph、Pydantic、SQLAlchemy 等锁定版本。
- 配置：未修改 `.env`、凭证、业务库或运行配置；未新增功能开关（T15/T16 再接入）。
- 前端：未改动；`AgentWorkbenchApi`/策略目录页面未接入。

## 6. 测试执行与证据

执行目录除特别注明外为 `backend/`。数据库测试使用临时 PostgreSQL 17 容器（tmpfs、回环随机端口、随机临时凭据），通过项目 `check_test_database` 预检；未指向业务库。验证进程移除了宿主 `APP_ENV`、`DATABASE_URL`、`DEEPSEEK_MODEL`、`NODE_ENV`、`CORS_ALLOWED_ORIGINS` 和缺失键的 `GIT_CONFIG_COUNT`，未修改 `.env`。

| 检查 | 命令 | 退出码 | 实际结果 |
| --- | --- | --- | --- |
| 首轮基线 | `uv run --locked --no-sync pytest tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t01-baseline-20261108` | 0 | 48 passed |
| 首轮预期红（缺模块） | `uv run --locked --no-sync pytest tests/research/strategies tests/persistence/test_strategy_catalog.py -q --basetemp=../.tmp/pytest/t01-red-20261108` | 1 | 3 collection errors：缺少新模块；符合预期 |
| 修复前纯回归红 | `uv run --locked --no-sync pytest tests/research/strategies/test_catalog.py tests/research/strategies/test_evaluator.py -q --basetemp=../.tmp/pytest/t01-fix-red-pure-20261108` | 1 | 6 failed / 15 passed：根 Schema、嵌套可变性和服务快照用例失败；符合预期 |
| 修复前 SQL 并发红 | 临时库 + `uv run --locked --no-sync pytest tests/persistence/test_strategy_catalog.py -q --basetemp=../.tmp/pytest/t01-fix-red-db-20261108` | 1 | 3 failed / 7 passed：publish/update/archive 的相同 request_id 并发用例失败；符合预期 |
| 修复后纯契约/评估器 + 既有引擎 | `uv run --locked --no-sync pytest tests/research/strategies tests/agent/test_technical_engine.py -q --basetemp=../.tmp/pytest/t01-fix-pure3-20261108` | 0 | 69 passed |
| 修复后 SQL + 迁移 | 临时库 + `uv run --locked --no-sync pytest tests/persistence/test_strategy_catalog.py tests/persistence/test_migrations.py -q --basetemp=../.tmp/pytest/t01-fix-db4-20261108` | 0 | 27 passed：含真实 PostgreSQL 双会话并发、内容指纹篡改、根 Schema 与发布不可变 |
| 后端 full（修复后最终代码） | 临时库 + `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t01-fix-full-backend-final.json` | 0 | `verification=passed`；后端 1049 passed / 0 failed / 0 skipped / 0 collection errors |
| 架构门禁 | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=38`，`findings=[]` |
| 静态检查 | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 0 | 全部通过 |
| 迁移链 | `uv run --locked --no-sync alembic heads` | 0 | `0019_strategy_catalog (head)` |

证据路径：`.tmp/quality/manual-agent-t01-fix-full-backend-final.json`（工作区内，不随 Git 传递；按上表命令可复现）。并发测试不是顺序重放：每条用例在真实 PostgreSQL 中由独立 blocker 事务持有业务行锁，两个独立会话同时提交同一 request_id，释放后断言两个结果一致、幂等记录和业务变更各一次。首轮 full 因宿主 `CORS_ALLOWED_ORIGINS` 覆盖默认开发来源而失败 1 项；清理该环境变量后重跑全绿，代码未因该环境覆盖修改。

## 7. 未验证项

- 未运行前端 lint/typecheck/Vitest/build；本轮无前端改动，full 使用 `--component backend`。
- 未运行浏览器 e2e、http-e2e；策略目录尚未接入 HTTP API/前端（T15/T16）。
- 未调用真实模型，未验证真实模型质量、真实知识/RAG、真实公开源质量。
- 未实现/验证 T12+ 确定性规划、资金/风险/市场规则、计划采纳、执行反馈和单池占用。
- 未迁移业务库，未部署；迁移只在临时测试库验证。
- 未实现用户未来组合算法、MACD、三重过滤；测试组合评估器只在测试注册。
- 未做多进程/高并发压力测试；本轮是真实 PostgreSQL 双会话加可控行锁的并发回归，不证明生产级吞吐或哈希碰撞下的行为。
- 未验证真实策略收益或产品可实施性；不提供收益声明。

## 8. 已知风险与重点审查位置

1. **参数 Schema 的安全子集**：请重点核对 `contracts.py` 是否仍有可绕过类型白名单的嵌套关键字；当前根必须 object，object 必须显式 `additionalProperties: false`，未来扩展不能静默放宽。
2. **发布不可变性**：仓储和数据库触发器双重保护发布行；请核对是否有直接 SQL 路径可改写发布正文/指纹、或通过定义行归档改变历史清单语义。
3. **请求并发重放**：四个写方法在业务读取前获取 `pg_advisory_xact_lock(hashtextextended(request_id, 0))`；请核对锁的获取顺序、与业务行锁的无死锁性、不同 request_id 的冲突行为，以及 64 位哈希碰撞只会导致额外串行化的假设。
4. **组合组成校验**：请核对组成版本是否必须同工作台、已发布、未归档、指纹一致、参数符合组成 Schema、不能自引用；是否存在绕过路径。
5. **技术适配器边界**：请核对是否真正复用旧引擎、没有新增信号/数量/资金/订单；最低盈亏比只能收紧；价格量化后几何仍成立；`allowed_states` 只过滤既有候选。
6. **证据时间口径**：请核对 `observed/available/fetched/analysis_as_of/sealed_at` 的约束是否会对 T08 冻结服务造成不合理限制，是否仍有未来数据进入候选的路径。
7. **候选绑定**：候选绑定 `evidence_sha256`（epoch 内容哈希）而非独立 epoch UUID；epoch UUID 由哈希派生，可重算。请确认这满足"证据引用"审计要求，或要求在 T08 增加显式 `evidence_epoch_id`。
8. **嵌套快照语义**：模型边界深拷贝配合 `validated_snapshot()` 重验逐项内容/epoch/策略正文哈希；请核对是否存在未经过快照入口的消费路径，以及快照重验的成本是否可接受。模型字段仍非深层不可变对象；服务/适配器以快照为信任边界，直接 SQL 或权威仓储仍是最终来源。
9. **定义归档行未被触发器保护**：归档通过仓储事务和目录代次控制；直接 SQL 修改 `strategy_definitions.archived_at` 可能改变可用性。当前测试覆盖仓储路径，未测试恶意 SQL 对定义行的修改。
10. **首次发布 state_version=1**：定义代次从 0 开始，草稿版本号独立；请确认 API 消费者对 `expectedVersion` 的理解一致。

## 9. 自测与正式审查状态

- 自测状态：`verified`。修复代码、回归测试、迁移、静态检查和后端 full 已完成；上述未验证项不计入通过。
- 正式审查状态：`approved`。用户于 2026-11-08 传回原审查助手正式通过结论，`reviewed_tip` 为 `159a43be3822e6f0fcbd314da67719187c06e610`；T01 代码与复审文档以 fast-forward 从 `e12de3a` 合并到 `main`。
- 审查范围：修复提交 `2521ec8..159a43b`（8 个文件，+571 / -61；`2521ec8` 为修复前 docs tip）+ 首轮已审查范围 `6f293fe..8e73ace`；本审查包文档提交仅改文档，不包含其他任务改动。
- T01 已放行。T02 及后续审查单元仍须等待用户明确指定，不因本次合并自动推进。
