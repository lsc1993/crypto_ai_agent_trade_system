# 项目状态与文档索引

核对日期：2026-11-01。本次质量基础设施变更基线：`417cae7`；此前功能核对及验证记录保留如下。下列“已实现”表示存在对应代码和测试入口；运行部署、公开源连通和真实模型质量需要独立证据，不能从历史计划或单元测试推断。

## 当前能力

当前交付形态为本地研究工作台：FastAPI、React、PostgreSQL 和 Docker Compose。综合研究、独立技术研究、确定性回测及手动模拟盘是不同路径；研究模型不能生成或执行 `TradeIntent`。

| 能力 | 当前实现与范围 | 代码/测试入口 |
| --- | --- | --- |
| 公开行情与存储 | Binance USDⓈ-M 公开行情、K 线及衍生品指标；实时查询与已存储研究数据分别有接口 | [market](../backend/src/app/market/)、[市场测试](../backend/tests/market/) |
| 研究币种管理 | 合约准入检查、目录登记、初始同步、失败重试、超时/租约恢复及归档；动态研究范围不扩大交易范围 | [symbols](../backend/src/app/symbols/)、[管理页](../frontend/src/features/research-symbols/ResearchSymbolManagementPage.tsx)、[测试](../backend/tests/symbols/) |
| 按需 AI 研究 | 固定 LangGraph、冻结证据、中文双周期叙事、模型校验与降级；无模型工具调用 | [agent](../backend/src/app/agent/)、[测试](../backend/tests/agent/) |
| 报告专题 | 美国政策、近七天资金费率、BTC/ETH 美国现货 ETF 资金流；各专题独立处理缺失和失败 | [专题说明](report-factors.md)、[因子测试](../backend/tests/agent/test_factors.py) |
| 独立技术研究 | v2 两阶段模型、程序验证的条件候选、引用校验、规则降级与持久化后台任务；保留 v1 同步接口和历史读取 | [交易计划书](technical-trading-plan.md)、[technical](../backend/src/app/agent/technical/)、[模型测试](../backend/tests/agent/test_technical_plan_model.py)、[worker 测试](../backend/tests/agent/test_technical_worker.py) |
| 技术报告展示 | 字段路径、状态与方法中文展示；多周期结构对照、条件计划与分析依据，原始引用可追溯 | [中文映射](../frontend/src/features/technical-reports/technical-presentation.ts)、[市场结构](../frontend/src/features/technical-reports/TechnicalMarketStructure.tsx)、[计划书](../frontend/src/features/technical-reports/TechnicalPlanBook.tsx) |
| 受控 Harness | Phase 1 协调层与 Phase 2 审计：策略准入、固定生命周期、审计仓储 | [harness](../backend/src/app/harness/)、[测试](../backend/tests/harness/)、[架构决策](superpowers/specs/2026-08-31-controlled-agent-harness-architecture-design.md) |
| 模型失败可观测性 | 综合研究提供安全摘要、有限格式重试及超长正文压缩；技术 v2 提供白名单规则反馈、保留合法段落的有限纠错及安全拒绝日志 | [维护指南](ai-maintenance.md)、[综合模型](../backend/src/app/agent/model.py)、[技术模型](../backend/src/app/agent/technical/plan_model.py) |
| 确定性回测 | 当前 BTCUSDT SMA 回测、风控、模拟成交与审计；收盘决策、下一根开盘成交 | [回测](../backend/src/app/research/backtests/)、[测试](../backend/tests/research/backtests/) |
| 手动模拟盘 | 当前 BTCUSDT 本地账户、手动意图或单次策略评估、快照模拟成交、绩效与审计 | [模拟盘](../backend/src/app/paper_trading/)、[测试](../backend/tests/paper_trading/) |
| 交易日志与复盘 | 本地持久化交易记录、统计和看板；不接入真实交易账户 | [trades](../backend/src/app/trades/)、[dashboard](../backend/src/app/dashboard/) |
| 本地部署 | Compose 的 PostgreSQL/API/前端，以及 API 内币种同步与技术研究任务 | [部署说明](local-deployment.md)、[配置](../compose.yaml) |
| 可复现质量检查 | 本地/CI 共用 doctor、quick、full、eval、Mock e2e；三态摘要、退出码、超时终止及 pytest 参数隔离 | [质量验证](quality-verification.md)、[入口](../scripts/verify.py)、[CI 配置](../.github/workflows/verify.yml) |
| 测试库防误配置 | 显式测试授权、固定专用库/受限角色、只读身份权限预检；共享夹具及独立迁移用例均受保护 | [预检](../backend/scripts/check_test_database.py)、[测试](../backend/tests/tooling/test_test_database_guard.py) |
| 固定离线契约评估 | 8 个合成案例通过真实综合研究适配器校验，分别统计接受/拒绝/可降级错误并保留版本指纹；不代表真实模型质量 | [样本说明](../backend/evaluation/README.md)、[评估入口](../backend/scripts/evaluate_research.py) |
| 研究服务流程评估 | 9 个合成案例验证综合研究与技术 v2 的成功、拒绝、降级和证据不足门控；另有真实仓储降级历史及审计回归 | [流程集](../backend/evaluation/flows/README.md)、[真实仓储回归](../backend/tests/persistence/test_research_flow_evaluation_history.py) |
| 架构机器门禁 | AST 检查研究/交易、Harness/IO及持久化、Risk/LLM 直接依赖；故意违规、漏扫及坏语法均有回归，保留原字符串安全检查 | [检查器](../backend/scripts/check_architecture.py)、[故障样例测试](../backend/tests/security/test_architecture_gate.py) |
| HTTP 与数据库浏览器验收 | 交易日志在 api 模式经真实 HTTP 和生产仓储保存后，刷新及新上下文重读；随机测试 schema，不是整站生产装配验收 | [浏览器用例](../frontend/e2e-http/trade-persistence.spec.ts)、[隔离服务](../backend/scripts/http_e2e_server.py) |
| 技术研究 HTTP 与任务恢复验收 | 生产队列/worker/Harness/适配器/SQL 的完成与降级闭环；worker 重建、子进程终止、取消、提交后恢复、去重与迟到租约拒绝 | [研究浏览器用例](../frontend/e2e-http/research-persistence.spec.ts)、[恢复测试](../backend/tests/persistence/test_technical_worker_recovery.py) |
| 币种同步重试 HTTP 验收 | 浏览器手动重试、运行中禁用/轮询、重复任务复用、部分恢复或再次失败及新会话重读；生产 worker/SQL/快照仓储，固定合成来源 | [同步浏览器用例](../frontend/e2e-http/symbol-sync-retry.spec.ts)、[隔离装配](../backend/scripts/http_e2e_symbols.py) |
| 完整 Compose 运行与恢复验收 | 生产镜像、入口迁移、完整应用 lifespan 与 Nginx；合成日志在 API 重启、保卷重建及独立空库备份恢复后保持一致 | [本地运行验收记录](superpowers/plans/2026-11-01-isolated-compose-acceptance.md)、[部署说明](local-deployment.md) |

## 本次整理的行为

2026-11-01 研究币种同步恢复：新增携带失败任务 ID 的手动重试 API 与管理页操作，目录行锁合并并发请求，迟到的旧失败请求不再排队。单 worker 默认整任务 120 秒、心跳 10 秒、租约 30 秒；领取前回收过期运行，失租取消采集，不自动重放失败任务。页面区分研究资格与最新同步状态，只在有活跃任务时轮询。复用现有表和依赖；设计及验证范围见[同步恢复设计](superpowers/specs/2026-11-01-symbol-sync-recovery-design.md)。

研究运行验收批次：扩展独立 HTTP 工厂，以合成行情和固定模型传输运行真实技术 v2 队列，BTC 完成、ETH 缺配置降级；新增报告刷新、历史列表和新会话读取。回收测试 schema 前先停止 worker/模型客户端。新增真实数据库故障恢复测试，不修改生产 worker、仓储规则或 schema；取消指协程/worker 生命周期，当前不增加用户取消 API，也不自动重放失败任务。

2026-10-31：统一入口新增 `http-e2e`、AST 架构门禁及研究服务流程评估；pytest 安全插件保留失败代码标识，移除参数化值，零执行、缺失或损坏产物不可通过。CI 增加分支 push 触发、真实 HTTP 流程及两套评估/测试摘要归档。该工作不修改生产 schema、依赖锁文件或模型权限，远端 CI 与合并门禁仍需独立验收。

2026-10-27：新增统一质量入口、GitHub Actions 配置、测试库预检和离线契约评估，运行契约见[质量验证](quality-verification.md)。数据库测试仅接受进程显式 `TEST_DATABASE_URL`，不再从 `.env` 自动授权；未修改业务配置、schema 或依赖锁文件。为使格式门禁可用，对 66 个存量文件执行 Ruff 机械格式整理：历史迁移 AST 不变，两处普通函数文档字符串缩进调整，其他格式文件 AST 不变。首次浏览器回归发现两条旧用例填写非 UUID 交易腿 ID，已改为合成 UUID，保持应用契约不变。

研究币种准入失败返回结构化、安全的检查详情，管理页展示后端消息并去重检查提示。公开行情超限、限流和超时使用固定摘要，不透出上游异常原文。Binance 公开 JSON 响应上限调整为 1,500,000 字节，允许原上限以上的正常合约目录，仍拒绝超过新上限的响应。相关回归见[错误接口测试](../backend/tests/api/test_errors.py)、[行情适配器测试](../backend/tests/market/test_binance_usdm.py)、[资金费率测试](../backend/tests/market/test_funding_history.py)、[准入服务测试](../backend/tests/symbols/test_service.py)及[页面测试](../frontend/src/test/research-symbols.test.tsx)。

共享文档按当前代码整理开发入口、数据模式、来源与验证要求。工具会话、诊断文件、测试临时目录及本地备份不属于项目交付文件。

后端全部 248 个 Python 文件（源码、脚本、测试和历史迁移）补充中文注释，说明职责、关键流程、契约、失败路径与设计原因；可添加注释的构建配置同步补充说明。根目录与后端 `AGENTS.md`、[AI 维护指南](ai-maintenance.md)明确 AI Agent 生成代码必须维护详细注释，具体要求见[后端规范](../backend/AGENTS.md#代码注释与-ai-agent-生成原则)。锁文件、严格 JSON/XML 样本、版本标记与冻结技术方法保留原内容；Windows Alembic 配置采用 ASCII 注释以兼容本地编码读取。

## 最近验证

2026-11-02 币种同步 HTTP 验收：新增 SOL 首次失败后手动重试为部分覆盖、XRP 再次失败两条浏览器旅程，经真实重试路由、生产同步 worker、SQL 租约/审计及快照仓储，验证 202 入队、运行中禁用与轮询、重复请求复用、旧失败请求 409、刷新及新上下文读取。初次失败同样由 worker 写入，目录与行情来自固定合成夹具；未注入资金费率，未将部分覆盖宣称为就绪。修复 Playwright worker 重载配置时重新生成 token 导致控制请求 403 的验收配置问题；测试控制入口只在独立验收服务注册，生产应用未增加接口。

根目录统一 `full` 的 22 项检查全部通过，后端 817 collected/passed、零失败/跳过/收集错误，前端 lint/typecheck/Vitest/build 通过；统一 `http-e2e` 的五条浏览器旅程通过，后端目录安全文档回归 55 项通过。独立只读审查未发现 P1/P2；四份说明相对链接与 `git diff --check` 通过。测试使用本次独立 tmpfs PostgreSQL 和受限身份，结束时临时 schema 为 0，核对标签后移除测试容器。未新增生产依赖、迁移或业务接口，未操作远端 CI、推送、业务配置或真实公开源。

2026-11-01 隔离 Compose 验收，代码基线 `bf35bb0`：使用现有生产 Dockerfile 构建当前 API、前端及恢复实例的独立前端镜像，经实际入口迁移启动 PostgreSQL/API/Nginx。API 与数据库仅连接独立 internal 网络，空模型密钥且未设置非空代理环境变量；前端额外使用独立入口桥接网，仅发布回环端口。本机 Docker Desktop 的纯 internal 网络未发布宿主机端口，临时拓扑调整后重新启动验证通过，没有修改业务 Compose。

真实生产页面保存合成交易日志，刷新和新 context 重读通过。随后 API 重启的 `StartedAt` 改变，保留原卷的 down/up 使三个容器 ID 均改变；再将 `pg_dump` 自定义格式备份恢复到不同卷、不同数据库集群的空库。四个阶段的同一交易 ID、完整响应 SHA256 与迁移链头 `0018_technical_report_runs` 一致。共四次浏览器验收通过；最终停止原栈，恢复实例的新浏览器只请求自己的入口，仍能读取原记录。两个研究币种在隔离网络下的初始同步均为失败，未冒充公开源同步成功。

本批证明范围是合成交易日志及迁移链在正常重启、保卷重建和逻辑备份恢复后可用；不覆盖全部业务数据、断电恢复、PITR、真实公开源或模型质量。没有修改生产代码、Dockerfile、业务 Compose、依赖或 schema；没有执行远端 CI、推送、合并或部署到业务环境。详细步骤与资源回收结果见[验收记录](superpowers/plans/2026-11-01-isolated-compose-acceptance.md)。

本地版本收尾：2026-11-01 在开发分支按纯格式整理、质量与研究验收、同步恢复形成三组本地提交。提交前重新执行统一 `full`，22 项检查全部通过，后端 813 项测试通过且零跳过，前端 lint/typecheck/Vitest/build 通过。收尾审查修正了运行边界文档中仍否认失败重试端点的旧说明。没有推送、合并、运行远端 CI、设置合并门禁或部署；此前各批次的“未提交”等记录保留其当时的验证状态。

2026-11-01 同步恢复批次：根目录 `uv run --project backend --locked --no-sync python scripts/verify.py full --report .tmp/quality/symbol-sync-full.json` 的 22 项检查通过，包含前端 lint/typecheck/Vitest/build。独立审查发现并修复终态提交等待期间未持续监控心跳的竞态，新增用例先失败后通过；随后执行 `full --component backend --report .tmp/quality/symbol-sync-backend-final.json`，最终 15 项后端检查通过，813 collected/passed，failed/skipped/collection_errors 均为 0，包含 Ruff/格式/Pyright/AST/迁移链头及两套离线评估。

同批统一 `http-e2e`（3 条）与 Mock `e2e`（16 条）通过。新增重试交互由 Vitest 验证、真实 HTTP 路由及 SQL 由 pytest 验证；已有浏览器流程只作为回归，不宣称新增同步重试已做浏览器全链验收。真实 SQL 另覆盖心跳延寿、归档取消、超时/取消可重读、快照提交后取消；队列短暂故障后的消费恢复也有回归。审查复核无剩余 P1/P2 阻断项。临时 schema 残留 0，独立 PostgreSQL 17 测试容器已回收。

本批无新增依赖或迁移，不连接真实公开源或模型，不修改业务数据库、生产配置或交易能力；未提交、推送、运行远端 CI 或部署。完整 Compose 启停/生产进程重启仍待独立验收。

研究运行验收批次：根目录统一 `full` 最终通过，安全摘要记录 790 collected/passed，failed/skipped/collection_errors 均为 0。后端 Ruff/格式/Pyright/AST/迁移链头/两套评估及前端 lint/typecheck/Vitest/build 均通过；统一 `http-e2e` 的日志、研究完成、研究降级共 3 条用例通过，统一 Mock `e2e` 的 16 条通过。

专用 PostgreSQL 17 使用受限角色与随机 schema；实际终止 worker 子进程后验证租约恢复，另外验证保存后收尾故障、模型执行中取消、提交报告后取消、并发去重与旧所有者拒绝。独立只读审查无 P1/P2 阻断项；审查后补充的提交后取消窗口纳入最终全量回归。临时 schema 残留 0，测试容器已回收。没有修改生产 worker/仓储规则、业务数据库、迁移链或模型权限，未提交、推送、部署或运行远端 CI。

证明范围：实际被终止的子进程使用阻塞执行器，完整 Harness/适配器链由其他测试覆盖；浏览器新 context 不等于后端 OS 重启。只验证 worker/协程取消，未新增用户取消接口。固定响应及合成行情不代表真实模型质量或公开源连通性。

2026-10-31，根目录统一 `full` 最终通过，安全 pytest 摘要记录 collected/passed 均为 780，failed/skipped/collection_errors 均为 0：

- 后端 Ruff、格式、严格 Pyright、AST 架构门禁、完整 pytest、迁移链头及两套离线评估通过；AST 扫描 32 个受保护源码文件，0 findings。适配器评估 8/8、服务流程评估 9/9 匹配，后者接受 2、拒绝 2、降级 3、证据不足 2。
- 前端 lint、typecheck、完整 Vitest、build 通过；统一 `e2e` 的 16 个 Mock 浏览器用例通过，统一 `http-e2e` 的 1 个真实 HTTP/PostgreSQL 浏览器闭环通过。HTTP 测试库使用独立临时 PostgreSQL 17、受限角色及随机 schema，没有访问业务库。
- 新增真实 SQL 回归覆盖三类技术 v2 降级历史重读及 Harness 审计；独立代码审查未发现需阻断的 P1/P2 问题。共享链接、workflow YAML 解析与 `git diff --check` 通过。
- 本地验证不替代远端 CI；本轮尚未提交、推送、运行 GitHub Actions 或设置分支保护。未部署、迁移业务库、调用真实模型或验证真实公开源。

2026-10-27，本次质量基础设施变更后，在仓库根目录执行 `uv run --project backend --locked --no-sync python scripts/verify.py full --report .tmp/quality/full-final.json`，最终退出 0，各检查均为 passed：

- 后端 Ruff lint、格式检查、Pyright、完整 pytest 706 项通过；测试使用新建独立 PostgreSQL 17 与受限测试角色，迁移链头仍为 `0018_technical_report_runs`。临时测试容器已停止并自动清理，未迁移业务库。
- 前端 lint、typecheck、完整 Vitest 和 build 通过。单独执行统一入口 `e2e`，两个桌面视口下共 16 个 Mock 界面用例通过；首次运行中的过期非 UUID 测试输入已修复。
- 适配器离线评估 8/8 预期匹配：接受 2、拒绝 4、可降级错误 2；未调用真实模型。详细样本、版本与证明范围见[评估说明](../backend/evaluation/README.md)。
- 独立代码审查发现并修复 `PYTEST_ADDOPTS` 污染风险；首次运行临时目录缺失也已补红绿回归。共享文档链接、workflow YAML 解析及 `git diff --check` 通过。
- 未推送、执行远端 GitHub Actions、设置分支保护、重新部署、迁移业务库或验证真实公开源及付费模型。HTTP/数据库端到端验收与真实模型质量基准仍未完成。

2026-10-14，在本次整理的工作区执行：

- `backend/`：`uv run ruff check .`、`uv run pyright` 通过；完整 pytest 656 项通过，数据库测试使用独立、无持久化卷的 PostgreSQL 测试实例。`uv run alembic heads` 返回 `0018_technical_report_runs`。
- `frontend/`：lint、typecheck、完整 Vitest 299 项和 build 通过；构建保留单包超过 500 kB 的体积提示。
- 共享文档的相对链接与 `git diff --check` 通过；运行边界安全文档测试包含在后端全量测试内。
- 未运行 Playwright、真实公开源连通或付费模型验证，未重新部署或迁移业务数据库；上述测试不替代运行环境与模型质量验收。

2026-10-14，后端注释整理后再次验证：`backend/` 的 Ruff、Pyright 和完整 pytest 656 项通过，使用独立无持久化卷的 PostgreSQL 测试实例及专属 pytest 临时目录；迁移链头仍为 `0018_technical_report_runs`。全部 248 个 Python 文件的可执行 token、AST 和原始代码行与整理前一致，新增行仅为 `#` 注释；构建配置的有效值和非注释行保持一致，容器入口仍使用 LF。相对链接与 `git diff --check` 通过。本次仅验证后端及相关文档，未重新运行前端、公开源或真实模型验收。

## 已知差异与待验收项

- 研究币种管理保持单 worker；2026-11-01 补齐 120 秒整任务上限、10 秒心跳和手动失败重试。历史 [2026-09-07 计划](superpowers/plans/2026-09-07-research-symbol-management.md)中的双 worker 未实施，不能将该计划全部勾为完成。原始行情保存与同步任务终态仍是独立事务，失租前已提交的行情不会回滚；旧任务不能再改写同步状态、来源或快照关联。
- 初始同步采集行情/K 线/衍生品和资金费率。资讯、情绪留待报告运行时按需采集；管理侧 ETF 能力当前标为不支持。报告侧另有 BTC/ETH ETF 适配器，两个状态不能混为一谈。
- 技术研究的数值与价格由确定性程序计算或按冻结字段渲染，模型不能改写数值、扩大交易范围或自动执行条件计划。历史触发状态冻结，到期不自动重算。
- 当前迁移链头为 `0018_technical_report_runs`，v2 部署需前后端与该迁移配套。测试库迁移通过不代表业务库已升级；业务环境须按[部署说明](local-deployment.md)另行验收。
- 真实模型曾出现数值、引用和交易措辞校验降级；有限纠错与合法段落保留已有实现。已有适配器及综合/技术 v2 服务离线评估和真实仓储回归，固定响应仍不代表真实模型质量、抗注入能力或交易表现，真实模型质量基准待补充。
- 当前交付使用本地验收，远端 CI 与合并门禁不纳入本轮交付要求；已有 workflow 配置保留但未运行。HTTP 浏览器验收覆盖日志及技术 v2 的局部装配；另有完整生产 Compose 的日志、进程重启和备份恢复验收，两类证据不能扩展为整站功能或真实模型质量。AST 门禁只覆盖可解析直接依赖，不是任意动态代码执行安全证明。
- 当前不提供真实执行、模型任意工具、长期用户记忆或自动策略交易。Harness 后续阶段保留为规划，不能因历史设计列出就视为启用。

## 阅读顺序

1. [根目录 AGENTS.md](../AGENTS.md)：全局安全与协作规则。
2. [后端约定](../backend/AGENTS.md) / [前端约定](../frontend/AGENTS.md)：按任务范围阅读。
3. [运行边界](operational-boundaries.md)、[AI 维护指南](ai-maintenance.md)：数据源、模型、Harness 与回归入口。
4. [部署说明](local-deployment.md)、[前端 README](../frontend/README.md)、[专题口径](report-factors.md)：运行与产品行为。
5. `docs/superpowers/specs/` 与 `docs/superpowers/plans/`：查阅相关功能的历史设计和实施记录。

[早期 MVP 执行索引](superpowers/plans/2026-07-23-mvp-execution-index.md)中的独立 market-worker、CCXT、固定研究币种以及部分契约是当时的设计，不能直接作为当前运行说明。历史 checkbox 不是自动维护的验收状态；保留历史文件，通过本索引标记现状和差异。

## 维护方式

功能变更时更新相应能力、限制、核对日期和证据链接。区分“代码实现”“测试验证”“运行验收”三个结论；未执行的检查明确列出，不从提交标题或计划推断通过。稳定规则放 AGENTS.md，变化较快的进展留在本文，详细设计仍放原设计文档。
