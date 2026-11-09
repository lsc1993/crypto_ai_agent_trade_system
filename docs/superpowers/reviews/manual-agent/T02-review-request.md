# T02 审查请求：可用的关键词 RAG

- 任务/审查单元：T02（D1；版本化关键词知识库、确定性分块/评分、GIN 检索与知识治理）
- 审查轮次：第 1 轮（开发完成后的首次交审）
- 生成日期：2026-11-09
- 执行模型：DeepSeek Harness 驱动的 `deepseek-flash`（会话标注；上游精确构建版本未知）
- 文档版本：需求 v2.0、架构 v2.0、实施计划 v1.1、实施契约 v1.1、跨模型交接 v1.1、开发模型提示词 v1.0；质量验证以仓库当前 `docs/quality-verification.md` 为准。
- 自测状态：`verified`（实现、聚焦、阶段回归、静态检查和后端 full 已完成）
- 正式审查状态：`awaiting_review`（待原审查助手审查；开发自测不能替代正式结论，未预填通过）
- 下一审查单元：T03 未开始。只有用户传回原审查助手对当前版本的通过结论后，才可放行。

## 1. 固定点与工作区

| 项目 | 值 |
| --- | --- |
| 工作区 | `D:\project_git\crypto_ai_agent_trade_system\.worktrees\manual-agent-t02` |
| 分支 | `task/manual-agent-t02` |
| base | `fed38bd97835a1325fd399d5334d10c853cae9e1`（`main`，T01 合并后；T02 开始时工作区干净） |
| implementation tip | `ed8e887cae1212f99808e0a381936decef66b6f7`（`feat: add governed keyword knowledge retrieval`） |
| tree | `f6bd479930b9a1234d242457d16a4102576232a9` |
| 代码范围 | `fed38bd..ed8e887`，13 个文件，+3067 / -0 |
| 代码 tip 处未提交文件 | 无；代码、测试、迁移均已提交 |
| 审查包文档 | 本文件、开发进度和状态文档位于代码提交之后的 docs-only 提交；本文件不记录自身提交号，避免自引用。最终回复提供文档提交 hash。 |

代码 tip 处工作区干净，未夹带其他任务改动。`git diff --check` 通过。T02 未修改 `.env`、凭证、业务库、前端或既有 API/运行配置。

### 文件 SHA256（implementation tip `ed8e887`）

| 文件 | SHA256 |
| --- | --- |
| `backend/alembic/versions/0020_research_knowledge.py` | `fed6f11acc9a812a0413fca5b53ef561dd707c709a35f9dfb3860d3c61b1feab` |
| `backend/src/app/infrastructure/persistence/knowledge_index.py` | `1f84a27cefd3b9a700b2f19042f831d9fa4238beb351000d65933496cd2bbb6c` |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | `dab11adeca5a2c9d58efb9a8942167c7ec29792316af658cc4542e19241f1da6` |
| `backend/src/app/infrastructure/persistence/models/knowledge.py` | `5ae6fec0c0f2239770419d78b68b2e6b9187884ad815de8ab29a9f92d8757cbb` |
| `backend/src/app/research/knowledge/__init__.py` | `6a2fb24570fabed6de8c9e92d42f2bf6d4a5e9d7d408461e9d399cf26300b4dd` |
| `backend/src/app/research/knowledge/contracts.py` | `b75ebfc116b4fb45f72fae4b39c18c09f7363e41166439e91ba0dec7d55dd507` |
| `backend/src/app/research/knowledge/indexing.py` | `d2deff2d0c1df0028e38f6680ef1078d1d1dcdcaf13b4994d4dfa32a6ca2dc86` |
| `backend/src/app/research/knowledge/ports.py` | `4b531e3bf5aebce5e71a612b9818e3e70ac3350f4d88395922739abac0fb787f` |
| `backend/src/app/research/knowledge/service.py` | `af6ff1a78a3e7f2a3879c240daa7ac288ae2e534be8b914c36857da5827d2d2e` |
| `backend/tests/persistence/test_knowledge_index.py` | `fa4ccd260d2bf4a33ed8df873f803a163a094560023cda04e7f16ae1e7399bed` |
| `backend/tests/research/knowledge/__init__.py` | `50d3f15ce0ce74aae9bc3172ed217e2401f0a1d19980d40c0db094bf38557a11` |
| `backend/tests/research/knowledge/test_indexing.py` | `ce376ee9d26f67f3ff0b3549dfed4865deef09a63fdea41a72e43b71a2cee0f2` |
| `backend/tests/research/knowledge/test_search.py` | `d97f264418e21307bf8fc5e7ad46e328e6e3de3061a006c20eb732a15f9bf18c` |

## 2. 改动清单

| 文件 | 作用 |
| --- | --- |
| `backend/src/app/research/knowledge/contracts.py` | 不可变契约：导入、版本、查询、命中、状态/权限、内容哈希与稳定错误码；校验 256 KiB、UTC、分块数和引用指纹 |
| `backend/src/app/research/knowledge/indexing.py` | 纯函数：NFKC 英文/中文双字词项、1000 字符分块/100 重叠、稳定块 ID、4:1 评分与 6 块上限常量 |
| `backend/src/app/research/knowledge/ports.py` | `KnowledgeIndex` 异步端口：导入、检索、发布、归档、分页 |
| `backend/src/app/research/knowledge/service.py` | `KnowledgeService`：拒绝未来截至时间/未来声明发布时间并委托索引；不实现算法或持久化 |
| `backend/src/app/infrastructure/persistence/models/knowledge.py` | 文档、不可变版本、分块词项数组和请求幂等 ORM 映射 |
| `backend/src/app/infrastructure/persistence/models/__init__.py` | 注册并导出知识模型 |
| `backend/src/app/infrastructure/persistence/knowledge_index.py` | `SqlAlchemyKnowledgeIndex`：导入/发布/归档/分页/幂等；GIN 召回、权重排序、历史过滤、并发重放 |
| `backend/alembic/versions/0020_research_knowledge.py` | 前向迁移：4 张表、GIN 索引、检查约束、版本/分块不可变触发器与文档禁删触发器 |
| `backend/tests/research/knowledge/test_indexing.py` | 纯契约：规范化、分块重叠、大小上限、内容哈希、查询边界、命中指纹、评分与恶意文本数据化 |
| `backend/tests/research/knowledge/test_search.py` | 服务边界：未来时点拒绝、空命中显式返回、文本不改写；使用内存替身仅证明服务契约，不冒充 SQL |
| `backend/tests/persistence/test_knowledge_index.py` | 真实 PostgreSQL：发布/检索、SQL 与纯函数分数一致、历史时点、范围/工作台、六块上限、去重、并发幂等和触发器 |

## 3. FR/AC/HN 映射

| 标识 | 本轮落地 | 证明边界 |
| --- | --- | --- |
| FR-04 RAG 与知识治理 | 显式导入、不可变版本、来源/范围/时间/权限、发布后检索、归档、无命中空结果、GIN 关键词检索 | 未实现真实知识库质量评估、用户策略说明语料或跨会话长期记忆 |
| AC-04 有命中/无命中/旧版本/停用 | 命中返回文档/版本/块/来源/时间/指纹/整数分；无命中返回空元组；草稿不可检索；停用文档从新检索排除且历史清单可读；历史 `as_of` 排除后导入内容 | 未接 HTTP/前端，未展示“低覆盖”产品文案 |
| AC-05 上下文超限（支撑部分） | 单次检索最多 6 块、每块最多约 1000 字符，为后续上下文预算提供有界输入 | 上下文选择、压缩、摘要和预算在 T08/T09，本轮不宣称 AC-05 完整通过 |
| HN-09 知识/外部文本不扩权 | 检索按工作台/权限/状态/范围先过滤；正文只作为 `KnowledgeHit.text` 返回；注入样本不能改变过滤条件；研究知识层不依赖 Agent/工具/交易 | 工具守卫和每次调用的能力复核在 T09；本轮没有模型工具循环 |
| HN-10 来源/版本/时间 | 版本保留 document/version/block 标识、来源、范围、首次可得、声明发布、服务端发布和指纹；历史过滤只用服务端 `first_available_at`/`published_at` | 真实外部来源的可得性证据在后续任务；本轮不把声明时间当历史可得证明 |

未实现/未宣称：FR-05/06 的完整上下文与预算、FR-01/02/03/07/08/09/14/15/16/17；T08/T09 工具循环、真实模型质量、真实知识库召回质量、产品规则/收益、API/前端。

## 4. 关键实现取舍

1. **版本正文不可变，内容哈希与时间分离**：`KnowledgeVersion.ref.sha256` 覆盖文档 ID、标题、来源、范围、权限、原文指纹和用户声明发布时间，不覆盖服务端 `first_available_at`/`published_at`；服务端时间变化不会改写历史正文指纹。正文另有 UTF-8 SHA-256，命中片段也校验指纹。
2. **分块与索引完全确定性**：按 Unicode 字符 1000/100 分块，保留原文；NFKC 只用于词项；英文小写连续字母数字、中文连续表意文字取相邻双字词并去重；块 ID 由版本 ID、块序号和块指纹派生。无 Embedding、向量库、分词依赖或外部 IO。
3. **评分固定且双算**：`4 * 标题匹配去重词数 + 正文匹配去重词数`，最多 6 块，同分按版本 UUID、块序号升序。SQL 计算分数，Python 对每行重算并拒绝不一致；排序在 SQL 与 Python 两处使用同一规则。
4. **过滤先于召回**：SQL 先限定工作台、published、文档未归档、权限、范围、历史截至时间，再用 `terms && :terms OR title_terms && :terms` 走 GIN 召回。标题词项复制到每块以支持标题权重，不额外连接标题表。
5. **历史可得性只认服务端时间**：检索 `as_of` 需同时满足 `published_at <= as_of` 和 `first_available_at <= as_of`；用户声明时间不参与放行。测试覆盖“声明早于导入、但导入后不可见”和“后导入文档不出现在早期历史结果”。
6. **请求幂等与并发**：写方法在业务读取前获取 `pg_advisory_xact_lock(hashtextextended(request_id,0))`，再检查 `knowledge_index_requests`；版本/分块/文档元数据/请求结果同事务提交。相同 request_id 返回原结果，不同内容/操作/工作台冲突；真实 PostgreSQL 双会话测试覆盖 import/publish/archive 并发。
7. **内容去重范围有限**：同一文档内规范化内容哈希相同则返回既有版本，不新增行；未显式提供 `document_id` 时创建新文档，跨文档相同正文不去重。这是有意保留“同名文档/不同来源”边界，已知限制见第 8 节。
8. **归档为文档级状态**：归档阻止新导入、发布和新检索；已发布历史仍由 `list_versions` 读取完整版本正文，不删除版本或分块。草稿不进入公开历史清单。
9. **数据库第二道不可变保护**：版本触发器只允许草稿一次性迁移到 published，published 行、正文列、分块和文档删除均拒绝；检查约束锁定状态/代次/发布时间/UTF-8 字节上限。仓储正常路径仍以事务和版本哈希为主。
10. **权限模型不虚构角色**：首期只有单工作台，`KnowledgeAccess.WORKSPACE` 是显式枚举，实际隔离由服务端注入的 `workspace_id` 完成；没有新增用户角色、RBAC 或跨工作台授权。
11. **服务层与仓储双重时点检查**：`KnowledgeService` 拒绝未来声明/截至时间，SQL 仓储也拒绝未来 `as_of`，防止绕过服务层直接调用；生产服务端时钟为 UTC。

## 5. 接口、依赖与迁移影响

- 公共 Python 类型与协议：`KnowledgeImport`、`KnowledgeVersion`、`KnowledgeQuery`、`KnowledgeHit`、`KnowledgeStatus`、`KnowledgeAccess`；`KnowledgeIndex`、`KnowledgeService`；`tokenize`、`chunk_text`、`prepare_chunks`、`score_chunk`、`sha256_text`；`SqlAlchemyKnowledgeIndex`。
- HTTP/API、前端、Agent 工具循环、模型上下文、`WorkbenchApi`：本轮未改动；没有新增路由、DTO、能力开关或前端页面。
- 持久化：新增 `knowledge_documents`、`knowledge_versions`、`knowledge_chunks`、`knowledge_index_requests`；新增 `ix_knowledge_chunks_terms`、`ix_knowledge_chunks_title_terms` 两个 GIN 索引和文档/版本索引；迁移 head 为 `0020_research_knowledge`。未迁移业务库，downgrade 明确拒绝删除历史引用。
- 依赖：无新增生产/开发依赖；未升级 LangGraph、Pydantic、SQLAlchemy 等锁定版本。
- 配置/安全：未修改 `.env`、凭证、业务库、运行配置或权限边界；未新增外部服务、MCP 工具、交易所或付费调用。

## 6. 测试执行与证据

执行目录除特别注明外为 `backend/`。数据库测试使用临时 PostgreSQL 17 容器（tmpfs、本机回环随机端口、仅容器内测试认证、受限角色 `crypto_research_test_runner`），先通过项目 `check_test_database` 只读身份/权限预检；未指向业务库，未修改业务库，容器与临时 schema 在验证后清理。验证进程内移除宿主 `APP_ENV`、`CORS_ALLOWED_ORIGINS`、`DEEPSEEK_MODEL`、`DATABASE_URL`、`NODE_ENV` 和缺失键的 `GIT_CONFIG_COUNT`，未修改 `.env`。

| 检查 | 命令 | 退出码 | 实际结果 |
| --- | --- | --- | --- |
| 首轮预期红（缺模块） | `uv run --locked --no-sync pytest tests/research/knowledge tests/persistence/test_knowledge_index.py -q --basetemp=../../.tmp/pytest/t02-red-20261109` | 1 | 3 collection errors：缺少 `app.research.knowledge` 与 `knowledge_index`；符合测试先行预期 |
| 纯契约首轮（测试断言修正） | `uv run --locked --no-sync pytest tests/research/knowledge -q --basetemp=../../.tmp/pytest/t02-pure1-20261109` | 1 | 12 passed / 3 failed；失败为测试对中文双字词数量、分块长度和 4:1 评分的期望写错，修正测试断言后复跑通过，非实现缺陷 |
| 纯契约复跑 | `uv run --locked --no-sync pytest tests/research/knowledge -q --basetemp=../../.tmp/pytest/t02-pure2-20261109` | 0 | 15 passed |
| 聚焦绿（含真实 SQL） | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/research/knowledge tests/persistence/test_knowledge_index.py -q --basetemp=../../.tmp/pytest/t02-fourth-green-20261109` | 0 | 30 passed；含同 request_id 并发重放、同键不同内容冲突、历史时点、范围/工作台、六块上限、内容去重和不可变触发器 |
| 阶段回归 | 临时 PostgreSQL 17 + `uv run --locked --no-sync pytest tests/research/knowledge tests/research/strategies tests/persistence/test_knowledge_index.py tests/persistence/test_migrations.py tests/persistence/test_strategy_catalog.py tests/agent/test_technical_engine.py -q --basetemp=../../.tmp/pytest/t02-stage-20261109` | 0 | 126 passed；含 T01 策略目录、迁移链和既有技术引擎回归 |
| 后端 full | 仓库根目录 + 临时 PostgreSQL 17 + `uv run --project backend --locked --no-sync python scripts/verify.py full --component backend --report .tmp/quality/manual-agent-t02-full-backend.json` | 0 | `verification=passed`；后端 1079 passed / 0 failed / 0 skipped / 0 collection errors；证据 `.tmp/quality/manual-agent-t02-full-backend.json` |
| 架构门禁 | `uv run --locked --no-sync python -m scripts.check_architecture` | 0 | `status=passed`，`files_scanned=38`，`findings=[]` |
| 静态检查 | `uv run --locked --no-sync ruff check .`；`ruff format --check .`；`pyright` | 0 | 全部通过；pyright 0 errors / 0 warnings |
| 迁移链 | `uv run --locked --no-sync alembic heads` | 0 | `0020_research_knowledge (head)` |

证据路径位于工作区 `.tmp/`（不随 Git 传递，按上表命令可复现）：`.tmp/quality/manual-agent-t02-full-backend.json`；pytest 临时目录为 `.tmp/pytest/t02-*`。并发测试不是顺序重放：每条用例由独立 blocker 事务持有业务行锁，两个独立会话同时提交同一 request_id，释放后断言结果一致、幂等记录和业务变更各一次。full 报告只保存安全计数与检查状态，不包含连接串、环境变量、原始异常或知识正文。

## 7. 未验证项

- 未运行前端 lint/typecheck/Vitest/build；本轮无前端改动，full 使用 `--component backend`。
- 未运行浏览器 e2e、http-e2e；知识库尚未接入 HTTP API/前端（T15/T16 或后续任务）。
- 未调用真实模型，未验证真实模型质量、真实知识库召回质量、真实用户策略说明或中文/英文语义别名效果。
- 未实现/验证 T08/T09 的上下文选择、工具守卫、动态 RAG 调用和模型工具循环；本轮只有检索基础。
- 未实现 T03/T18 的规划资料、产品规则、市场规则或真实公开源复核。
- 未迁移业务库、未部署；迁移只在临时测试库验证。
- 未做多进程/高并发压力测试；本轮是真实 PostgreSQL 双会话加可控行锁的并发回归，不证明生产级吞吐、哈希碰撞或大规模知识库性能。
- 未验证跨文档相同正文去重、用户/角色级权限或历史 `as_of` 归档语义；这些是当前明确边界。
- 未提供收益、策略效果或可实施计划声明。

## 8. 已知风险与重点审查位置

1. **历史可得性语义**：检索同时要求 `published_at <= as_of` 与 `first_available_at <= as_of`，用户声明时间只展示不参与放行；归档文档始终从新检索排除。请核对是否符合 FR-04/HN-10 对“当时可得”和“停用后历史引用”的预期，以及是否需要支持“归档前时点”的历史搜索。
2. **权限模型**：`KnowledgeAccess` 目前只有 `workspace` 单值，实际隔离依赖服务端 `workspace_id`；请核对是否满足首期单工作台安全边界，以及未来引入角色时是否需要改契约而不是静默扩权。
3. **去重范围**：同一 `document_id` 内相同内容返回既有版本；未提供 `document_id` 时创建新文档，不跨文档去重。请确认这是否符合“导入去重”的产品口径，或应改为工作台级内容去重。
4. **版本不可变触发器**：草稿只允许一次性迁移到 published，published 行禁止任何更新/删除；请核对是否存在直接 SQL 路径可改写正文、回退状态或绕过 `knowledge_chunks` 触发器。
5. **SQL 与纯函数评分一致性**：SQL 用 `unnest(...) AS alias(term)` 相关子查询计算交集，Python 每行重算并拒绝不一致；请重点核对 SQL 语法、GIN 实际使用、空词项和同分排序，以及 `render_derived` 对 PostgreSQL 版本的兼容性。
6. **历史/时间字段**：`first_available_at` 在草稿导入时记录，`published_at` 在发布时记录；声明时间不得晚于首次可得。请核对时间比较、UTC 归一化和数据库 check 约束是否有绕过路径。
7. **请求并发重放**：三个写方法在业务读取前获取 request_id 事务锁；请核对锁顺序、与文档/版本行锁的无死锁性，以及同键不同工作台/内容/操作的冲突行为。
8. **单字中文与分词边界**：中文只索引连续双字词，单个孤立汉字不产生词项，纯单字查询会被查询契约拒绝；请确认这是否可接受，或需要补充单字 fallback、停用词或别名策略。
9. **性能与正文暴露**：`KnowledgeVersion` 在读取时重算全文 SHA-256、分块数和内容哈希，`list_versions` 每页最多 100 个 256 KiB 文档；未做规模压测。`KnowledgeHit` 返回完整 1000 字符块，上下文预算由后续任务处理。请评估是否需要缓存或摘要字段。
10. **归档后请求重放**：导入/发布请求的幂等结果保存的是当时版本 JSON；文档之后归档时，重放仍可能返回 `archived=false` 的历史响应。请确认这是可接受的幂等语义，还是应在重放时刷新归档状态。
11. **测试替身边界**：`test_search.py` 的内存索引只证明 `KnowledgeService` 的未来时点拒绝和委托契约，不证明 SQL；真实排序、过滤和并发全部在 `test_knowledge_index.py`。请勿把替身结果当作生产检索质量证明。

## 9. 自测与正式审查状态

- 自测状态：`verified`。实现、聚焦测试、真实 SQL 并发/历史/触发器回归、阶段回归、静态检查、架构门禁、迁移链和后端 full 均完成；上述未验证项不计入通过。
- 正式审查状态：`awaiting_review`。尚未取得原审查助手对当前版本的正式结论；不自行标记 approved，不开始 T03。
- 审查范围：implementation tip `ed8e887`，diff `fed38bd..ed8e887`，13 个文件，+3067 / -0；本审查包文档提交只改进度/状态/契约标注和本文件，不夹带代码或其他任务改动。
- 收到审查意见后，先核对/复现，再逐条修复并补回归；有异议以代码和测试说明，不盲改或自行豁免。修复后记录新 tip、变更与验证，再次交审。
