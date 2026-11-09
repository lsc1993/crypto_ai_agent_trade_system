# T02 审查请求：可用的关键词 RAG

- 任务/审查单元：T02（D1；版本化关键词知识库、确定性分块/评分、GIN 检索与知识治理）
- 复审轮次：第 2 轮（首轮独立审查 P1/P2 不通过后的修复交审）
- 生成日期：2026-11-09
- 执行模型：DeepSeek Harness 驱动的 `deepseek-flash`（会话标注；上游精确构建版本未知）
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；质量验证以仓库当前 `docs/quality-verification.md` 为准。
- 首轮审查结论：不通过（P1 已发布版本仍可追加分块；P2 锁等待前采样发布时间）
- 自测状态：`verified`（修复、聚焦、阶段回归、静态检查和后端 full 已完成）
- 正式审查状态：`awaiting_review`（待原审查助手复审；开发自测不能替代正式结论，未预填通过）
- 下一审查单元：T03 未开始。只有用户传回原审查助手对当前版本的通过结论后，才可放行。

## 1. 固定点与工作区

| 项目 | 值 |
| --- | --- |
| 工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t02` |
| 分支 | `task/manual-agent-t02` |
| base | `fed38bd97835a1325fd399d5334d10c853cae9e1`（`main`，T01 合并后） |
| 首轮 implementation tip | `ed8e887cae1212f99808e0a381936decef66b6f7`（首轮正式审查不通过） |
| 首轮审查包文档 | `fd419e62e42fea134e381e9d09f43c1492146619` |
| 复审修复 tip | `8835a1deb5e4056a98a6e1a2a5f6e2f3e39e0bb9`（`fix: harden T02 knowledge chunk freezing and timestamps`） |
| tree | `daf6f394aa9125183af4a847f8bc96b34119f748` |
| 复审修复范围 | `fd419e6..8835a1d`，5 个文件，+744 / -33 |
| 原始实现范围 | `fed38bd..ed8e887`，13 个文件，+3067 / -0 |
| 代码 tip 处未提交文件 | 无；修复代码与测试均已提交 |
| 本轮审查包文档 | 本文件、开发进度和状态文档位于修复代码之后的 docs-only 提交；本文件不记录自身提交号，避免自引用。最终回复提供文档提交 hash。 |

代码 tip 处工作区干净，未夹带其他任务改动。`git diff --check` 通过。T02 未修改 `.env`、凭证、业务库、前端或既有 API/运行配置。

### 文件 SHA256（复审修复 tip `8835a1d`）

| 文件 | SHA256 |
| --- | --- |
| `backend/alembic/versions/0020_research_knowledge.py` | `c14289641670bd2edd08962e7676f1b8ac26bcbcc118bc80dcefce465c4b4875` |
| `backend/src/app/infrastructure/persistence/knowledge_index.py` | `59be03aaa3f840ab026f72787688da4bdce22b49d1b9d6e909d24bff12d3abf3` |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | `dab11adeca5a2c9d58efb9a8942167c7ec29792316af658cc4542e19241f1da6` |
| `backend/src/app/infrastructure/persistence/models/knowledge.py` | `5ae6fec0c0f2239770419d78b68b2e6b9187884ad815de8ab29a9f92d8757cbb` |
| `backend/src/app/research/knowledge/__init__.py` | `6a2fb24570fabed6de8c9e92d42f2bf6d4a5e9d7d408461e9d399cf26300b4dd` |
| `backend/src/app/research/knowledge/contracts.py` | `b75ebfc116b4fb45f72fae4b39c18c09f7363e41166439e91ba0dec7d55dd507` |
| `backend/src/app/research/knowledge/indexing.py` | `6a7d2959ddf7b6906c4bf78a62f1c92b3d0cfbb2102243f8cd6ac96957f2c3db` |
| `backend/src/app/research/knowledge/ports.py` | `4b531e3bf5aebce5e71a612b9818e3e70ac3350f4d88395922739abac0fb787f` |
| `backend/src/app/research/knowledge/service.py` | `af6ff1a78a3e7f2a3879c240daa7ac288ae2e534be8b914c36857da5827d2d2e` |
| `backend/tests/persistence/test_knowledge_index.py` | `7be40c0c0c04509d06a8b9f2d39b8ea23e1004d5211300c9048a9a0cccbd2155` |
| `backend/tests/research/knowledge/__init__.py` | `50d3f15ce0ce74aae9bc3172ed217e2401f0a1d19980d40c0db094bf38557a11` |
| `backend/tests/research/knowledge/test_indexing.py` | `4d77157d563a06786cfba9744a81ee1f89e041877696e3ccc4bc308dde67ad45` |
| `backend/tests/research/knowledge/test_search.py` | `d97f264418e21307bf8fc5e7ad46e328e6e3de3061a006c20eb732a15f9bf18c` |

## 2. 改动清单

### 2.1 原始实现（`ed8e887`，13 个文件）

| 文件 | 作用 |
| --- | --- |
| `backend/src/app/research/knowledge/contracts.py` | 不可变契约：导入、版本、查询、命中、状态/权限、内容哈希与稳定错误码 |
| `backend/src/app/research/knowledge/indexing.py` | NFKC 英文/中文双字词项、1000/100 分块、稳定块 ID、4:1 评分与 6 块上限 |
| `backend/src/app/research/knowledge/ports.py` | `KnowledgeIndex` 异步端口 |
| `backend/src/app/research/knowledge/service.py` | `KnowledgeService` 未来时点/未来声明拒绝与委托 |
| `backend/src/app/infrastructure/persistence/models/knowledge.py` | 文档、版本、分块和请求幂等 ORM 映射 |
| `backend/src/app/infrastructure/persistence/knowledge_index.py` | `SqlAlchemyKnowledgeIndex`：导入/发布/归档/分页/幂等/GIN 检索 |
| `backend/alembic/versions/0020_research_knowledge.py` | 4 张表、GIN 索引、检查约束和不可变触发器 |
| `backend/tests/research/knowledge/test_indexing.py`、`test_search.py` | 纯契约、分块、评分、服务边界 |
| `backend/tests/persistence/test_knowledge_index.py` | 真实 PostgreSQL 检索、历史、范围、并发、幂等和触发器 |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | 注册知识模型 |

### 2.2 复审修复（`8835a1d`，5 个文件）

| 文件 | 变化 |
| --- | --- |
| `backend/alembic/versions/0020_research_knowledge.py` | 新增分块 `BEFORE INSERT` 防护：父版本 `FOR KEY SHARE`、draft 状态、工作台、序号范围、版本正文切片、SHA-256；使用 `TG_TABLE_SCHEMA` 动态限定表名。 |
| `backend/src/app/infrastructure/persistence/knowledge_index.py` | `import/publish/archive` 改为锁后采样时间；publish 增加 `_verify_chunk_set`；search 增加版本正文切片、稳定块 ID、工作台、词项一致性校验。 |
| `backend/src/app/research/knowledge/indexing.py` | 新增 `chunk_at`、`chunk_id_for`；`chunk_text` 复用同一分块切片语义。 |
| `backend/tests/persistence/test_knowledge_index.py` | 新增 P1/P2 回归：发布后追加、强制发布后未占用范围内序号、触发器字段校验、触发器等锁发布、并发插入后缺失集合、伪造命中、锁等待时间。 |
| `backend/tests/research/knowledge/test_indexing.py` | 新增 `chunk_at` 与 `chunk_id_for` 确定性/边界测试。 |

## 3. 首轮审查问题与修复对照

| 审查问题 | 根因 | 修复 | 回归证据 |
| --- | --- | --- | --- |
| P1 已发布版本仍可追加分块 | `knowledge_chunks` 触发器只拦截 UPDATE/DELETE，没有限制 INSERT；publish 未核对分块集合；search 只校验分块自身哈希，未绑定版本正文和稳定块 ID | 新增 `trg_knowledge_chunks_insert_guard`：先对父版本 `FOR KEY SHARE`（与 publish 的版本行 `FOR UPDATE` 冲突并串行化），拒绝非 draft、跨工作台、越界序号、非版本正文切片和不匹配 SHA-256。publish 在版本行锁内执行 `_verify_chunk_set`，逐块核对数量、序号、稳定 ID、正文、指纹、词项、标题词项和工作台；search 的 `_row_to_hit` 重新核对版本正文切片、块 ID、工作台和词项。 | `test_published_version_rejects_appended_chunk`、`test_published_version_rejects_unoccupied_in_range_chunk`、`test_chunk_insert_guard_validates_text_index_workspace_and_hash`、`test_insert_waits_for_publish_lock_and_is_rejected`、`test_publish_rejects_incomplete_chunk_set_after_concurrent_insert`、`test_forged_chunk_cannot_become_legal_hit` |
| P2 锁等待之前采样发布时间 | import/publish/archive 在事务/业务行锁之前调用 `_now()`，等锁时间被保存为 `first_available_at`/`published_at`/`archived_at` | 时间采样移到请求锁、版本/文档行锁和分块集合校验之后、首次状态写入之前；import 的 `first_available_at`、publish 的 `published_at`、archive 的 `archived_at` 均使用锁后时间。 | `test_publish_time_is_sampled_after_lock_wait`、`test_import_time_is_sampled_after_document_lock_wait`、`test_archive_time_is_sampled_after_document_lock_wait` |

### 3.1 时间口径与剩余限制

- `first_available_at`、`published_at`、`archived_at` 是**服务端在获取必要锁之后的决策时间**，不是 PostgreSQL 提交时间。
- 历史检索仍使用 `published_at <= as_of` 和 `first_available_at <= as_of`；用户声明时间不参与放行。
- 采样到事务提交之间仍有极短窗口。普通时间戳无法在不使用数据库提交时间戳或二阶段发布的情况下严格证明“提交时可得”；本实现**不宣称严格提交时可得**，只保证不再把数分钟锁等待计入可得时间。若未来需要严格语义，应单独引入提交时间戳/二阶段可见性并复审。
- 相同 `request_id` 并发重放、未来时间拒绝和归档历史语义保持不变；本轮未扩大跨文档去重、角色权限或归档前历史搜索范围。

### 3.2 迁移兼容

`0020_research_knowledge` 仍在 T02 未合并分支，未应用到任何业务库；首轮审查方也未进行数据库实测。因此复审修复直接补齐 `0020` 的分块 INSERT 防护，不新增 `0021`、不改变迁移 head。若某个临时 schema 已执行旧版 `0020`，重建该临时 schema 即可；业务库没有需要前向修补的已应用迁移。

## 4. FR/AC/HN 映射

| 标识 | 本轮落地 | 证明边界 |
| --- | --- | --- |
| FR-04 RAG 与知识治理 | 显式导入、不可变版本、来源/范围/时间/权限、发布后检索、归档、无命中空结果、GIN 关键词检索；发布后分块集合冻结 | 未实现真实知识库质量评估、用户策略说明语料或跨会话长期记忆 |
| AC-04 有命中/无命中/旧版本/停用 | 命中返回文档/版本/块/来源/时间/指纹/整数分；无命中返回空元组；草稿不可检索；停用文档从新检索排除且历史清单可读；历史 `as_of` 排除后导入内容 | 未接 HTTP/前端，未展示“低覆盖”产品文案 |
| AC-05 上下文超限（支撑部分） | 单次检索最多 6 块、每块最多约 1000 字符，为后续上下文预算提供有界输入 | 上下文选择、压缩、摘要和预算在 T08/T09，本轮不宣称 AC-05 完整通过 |
| HN-09 知识/外部文本不扩权 | 检索按工作台/权限/状态/范围先过滤；正文只作为 `KnowledgeHit.text` 返回；注入样本不能改变过滤条件；伪造分块在数据库和检索层均被拒绝 | 工具守卫和每次调用的能力复核在 T09；本轮没有模型工具循环 |
| HN-10 来源/版本/时间 | 版本保留 document/version/block 标识、来源、范围、首次可得、声明发布、服务端发布和指纹；历史过滤只用服务端 `first_available_at`/`published_at`；锁后采样 | 真实外部来源的可得性证据在后续任务；未宣称严格数据库提交时可得 |

未实现/未宣称：FR-05/06 的完整上下文与预算、FR-01/02/03/07/08/09/14/15/16/17；T08/T09 工具循环、真实模型质量、真实知识库召回质量、产品规则/收益、API/前端。

## 5. 关键实现取舍

1. **分块集合冻结是数据库第一道边界**：分块 INSERT 触发器先锁定父版本并检查 draft 状态；publish 持有版本行 `FOR UPDATE`，因此“先检查 draft、后向 published 插入”的竞态被串行化。数据库触发器还核对工作台、序号范围、原文切片和 SHA-256，避免仅校验分块自身哈希。
2. **发布与检索两层复核**：publish 在锁内用 `prepare_chunks` 重建完整集合，逐块比较稳定 ID、正文、指纹、正文词项、标题词项和工作台；search 对每个命中重算版本正文切片和块 ID。即使触发器被绕过或历史行被直接改写，伪造分块也不能成为合法命中。
3. **时间采样的锁后语义**：publish 在请求锁、版本行锁、文档行锁和分块集合校验之后采样 `published_at`；import 在请求锁/文档行锁之后采样 `first_available_at`；archive 在文档行锁之后采样 `archived_at`。历史检索仍只使用服务端时间。
4. **内容哈希与时间分离**：`KnowledgeVersion.ref.sha256` 覆盖文档 ID、标题、来源、范围、权限、原文指纹和声明时间，不覆盖服务端首次可得/发布时间；服务端时间变化不改写历史正文指纹。
5. **固定评分与排序**：`4 * 标题匹配去重词数 + 正文匹配去重词数`，最多 6 块，同分按版本 UUID、块序号升序；SQL 计算分数，Python 逐行重算并拒绝不一致。
6. **过滤先于召回**：SQL 先限定工作台、published、未归档、权限、范围、历史截至时间，再用 `terms && :terms OR title_terms && :terms` 走 GIN 召回。
7. **请求幂等**：写方法在业务读取前获取 `pg_advisory_xact_lock(hashtextextended(request_id,0))`；相同 request_id 返回原结果，不同内容/操作/工作台冲突；真实 PostgreSQL 双会话测试覆盖并发。
8. **权限模型不虚构角色**：首期只有单工作台，`KnowledgeAccess.WORKSPACE` 是显式枚举，实际隔离由服务端注入的 `workspace_id` 完成；本轮不扩大角色/权限范围。
9. **迁移在原任务内修复**：`0020` 未合并、未应用到业务库，直接补齐 INSERT 防护；不在未发布任务上新增迁移号，T03 的计划编号保持 `0021`。

## 6. 接口、依赖与迁移影响

- 公共 Python 类型与协议：`KnowledgeImport`、`KnowledgeVersion`、`KnowledgeQuery`、`KnowledgeHit`、`KnowledgeStatus`、`KnowledgeAccess`；`KnowledgeIndex`、`KnowledgeService`；`tokenize`、`chunk_text`、`chunk_at`、`chunk_id_for`、`prepare_chunks`、`score_chunk`、`sha256_text`；`SqlAlchemyKnowledgeIndex`。
- HTTP/API、前端、Agent 工具循环、模型上下文、`WorkbenchApi`：本轮未改动；没有新增路由、DTO、能力开关或前端页面。
- 持久化：`knowledge_documents`、`knowledge_versions`、`knowledge_chunks`、`knowledge_index_requests`；新增 GIN 索引和分块 INSERT/UPDATE/DELETE 触发器；迁移 head 为 `0020_research_knowledge`。未迁移业务库，downgrade 明确拒绝删除历史引用。
- 依赖：无新增生产/开发依赖；未升级 LangGraph、Pydantic、SQLAlchemy 等锁定版本。
- 配置/安全：未修改 `.env`、凭证、业务库、运行配置或权限边界；未新增外部服务、MCP 工具、交易所或付费调用。

## 7. 测试执行与证据

执行目录除特别注明外为 `backend/`。数据库测试使用临时 PostgreSQL 17 容器（tmpfs、本机回环随机端口、仅容器内测试认证、受限角色 `crypto_research_test_runner`），先通过项目 `check_test_database` 只读身份/权限预检；未指向业务库，未修改业务库，容器与临时 schema 在验证后清理。验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV` 和缺失键的 `GIT_CONFIG_COUNT`，未修改 `.env`。

| 检查 | 命令 | 退出码 | 实际结果 |
| --- | --- | --- | --- |
| 首轮预期红（缺模块） | `uv run --locked --no-sync pytest tests/research/knowledge tests/persistence/test_knowledge_index.py -q --basetemp=../../.tmp/pytest/t02-red-20261109` | 1 | 3 collection errors：缺少新模块；符合测试先行预期 |
| 首轮纯契约断言修正 | `uv run --locked --no-sync pytest tests/research/knowledge -q --basetemp=../../.tmp/pytest/t02-pure1-20261109` | 1 | 12 passed / 3 failed；失败为测试对中文双字词数量、分块长度和 4:1 评分的期望写错，修正测试断言后复跑通过 |
| 首轮聚焦绿 | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/research/knowledge tests/persistence/test_knowledge_index.py -q --basetemp=../../.tmp/pytest/t02-fourth-green-20261109` | 0 | 30 passed |
| P1/P2 预期红 | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/persistence/test_knowledge_index.py -q --tb=short --basetemp=../../.tmp/pytest/t02-fix-red-20261109` | 1 | 7 failed / 15 passed；发布后追加、锁等待时间、伪造命中、插入/发布并发和缺失分块集合用例失败，符合预期 |
| 修复后聚焦绿 | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/research/knowledge tests/persistence/test_knowledge_index.py -q --basetemp=../../.tmp/pytest/t02-fix-green5-20261109` | 0 | 40 passed；含追加拒绝、强制发布后未占用范围内序号拒绝、触发器字段校验、插入等待发布锁、并发插入后缺失集合、伪造命中拒绝和锁后时间采样 |
| 修复后阶段回归 | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/research/knowledge tests/research/strategies tests/persistence/test_knowledge_index.py tests/persistence/test_migrations.py tests/persistence/test_strategy_catalog.py tests/agent/test_technical_engine.py -q --basetemp=../../.tmp/pytest/t02-fix-stage2-20261109` | 0 | 136 passed；含 T01 策略目录、迁移链和既有技术引擎回归 |
| 修复后后端 full | 仓库根目录 + 临时 PostgreSQL 17 + `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t02-fix2-full-backend.json` | 0 | `verification=passed`；后端 1089 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t02-fix2-full-backend.json` |
| 架构门禁 | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=38`，`findings=[]` |
| 静态检查 | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 0 | 全部通过；pyright 0 errors / 0 warnings |
| 迁移链 | `uv run --locked --no-sync alembic heads` | 0 | `0020_research_knowledge (head)` |

证据路径位于工作区 `.tmp/`（不随 Git 传递，按上表命令可复现）：`.tmp/quality/manual-agent-t02-fix2-full-backend.json`；pytest 临时目录为 `.tmp/pytest/t02-*`。并发测试不是顺序重放：发布/插入由独立 blocker 事务和 `pg_stat_activity` 锁等待检测同步，断言锁后时间、请求幂等记录和业务变更各一次。full 报告只保存安全计数与检查状态，不包含连接串、环境变量、原始异常或知识正文。

## 8. 未验证项

- 未运行前端 lint/typecheck/Vitest/build；本轮无前端改动，full 使用 `--component backend`。
- 未运行浏览器 e2e、http-e2e；知识库尚未接入 HTTP API/前端（T15/T16 或后续任务）。
- 未调用真实模型，未验证真实模型质量、真实知识库召回质量、真实用户策略说明或中文/英文语义别名效果。
- 未实现/验证 T08/T09 的上下文选择、工具守卫、动态 RAG 调用和模型工具循环；本轮只有检索基础。
- 未实现 T03/T18 的规划资料、产品规则、市场规则或真实公开源复核。
- 未迁移业务库、未部署；迁移只在临时测试库验证。`0020` 未应用到业务库，故在原任务内补齐；若临时环境已应用旧版 `0020`，需重建该临时 schema。
- 未做多进程/高并发压力测试；本轮是真实 PostgreSQL 双会话加可控行锁的并发回归，不证明生产级吞吐、哈希碰撞或大规模知识库性能。
- 未验证严格数据库提交时可得；`published_at` 是锁后发布决策时间，采样到提交的极短窗口见 3.1。
- 未扩大跨文档相同正文去重、用户/角色权限或归档前历史搜索范围；这些是当前明确边界。
- 未提供收益、策略效果或可实施计划声明。

## 9. 已知风险与重点审查位置

1. **分块 INSERT 触发器**：请重点核对 `FOR KEY SHARE` 与 publish 的版本行 `FOR UPDATE` 的锁顺序/死锁性、`TG_TABLE_SCHEMA` 动态表名、`FOUND` 不可靠而改用 state 非空哨兵、正文切片常量 900/1000 与 Python 分块的一致性，以及 `sha256(convert_to(...))` 对 PostgreSQL 17 的依赖。
2. **发布与检索双层校验**：publish 的 `_verify_chunk_set` 和 search 的 `_row_to_hit` 都重建预期分块；请核对是否覆盖数量、序号、工作台、稳定 ID、正文、指纹、正文词项和标题词项，以及是否存在绕过路径。
3. **锁后时间采样与提交窗口**：请核对 import/publish/archive 的采样位置是否在必要锁之后、是否仍有未来时间/历史可得性漏洞；`published_at` 不宣称等于提交时间，剩余窗口见 3.1。
4. **迁移在原任务内修复**：`0020` 未合并、未应用业务库，因此直接补齐触发器；请确认该兼容策略可接受，以及若审查方已有旧版 `0020` 临时 schema，是否应重建。
5. **并发回归的同步方式**：测试通过 `pg_stat_activity` 等待锁、真实 blocker 事务和独立会话验证；请核对是否存在测试自身依赖时序或权限的脆弱性。
6. **性能**：每个分块 INSERT 执行一次动态父版本查询并取 `FOR KEY SHARE`；最大 256 KiB 文档约 292 块，导入开销随块数线性增长；search 额外携带版本正文切片做校验。未做规模压测，请评估是否需要缓存或批量校验。
7. **既有语义保持**：相同 `request_id` 并发重放、未来时间拒绝、内容去重范围、归档历史读取和单工作台权限未扩大；请核对本次修复没有改变这些契约。
8. **测试替身边界**：`test_search.py` 的内存索引只证明 `KnowledgeService` 的未来时点拒绝和委托契约，不证明 SQL；真实排序、过滤、并发、触发器和伪造命中全部在 `test_knowledge_index.py`。

## 10. 自测与正式审查状态

- 自测状态：`verified`。修复、聚焦 40 passed、阶段回归 136 passed、真实 PostgreSQL 锁等待/并发/触发器回归、静态检查、架构门禁、迁移链和后端 full 1089 passed 均完成；上述未验证项不计入通过。
- 正式审查状态：`awaiting_review`。首轮独立审查判定 P1/P2 不通过；本轮为修复交审，尚未取得原审查助手对当前版本的正式结论。不自行标记 approved，不开始 T03。
- 审查范围：复审修复 tip `8835a1d`，修复范围 `fd419e6..8835a1d`（5 个文件，+744/-33）；原始实现范围 `fed38bd..ed8e887`（13 个文件，+3067/-0）。本轮审查包文档提交只改进度/状态/契约标注和本文件，不夹带代码或其他任务改动；最终回复提供文档提交 hash。
- 收到审查意见后，先核对/复现，再逐条修复并补回归；有异议以代码和测试说明，不盲改或自行豁免。修复后记录新 tip、变更与验证，再次交审。
