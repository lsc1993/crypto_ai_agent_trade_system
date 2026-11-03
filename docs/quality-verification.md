# 可复现质量验证

## 初始化与统一入口

需要 uv、Python 3.12，以及满足 `frontend/package.json` 的 Node.js/npm。首次在仓库根目录执行：

```powershell
uv sync --project backend --locked
npm ci --prefix frontend
```

初始化只安装锁定依赖，不创建或修改 `.env`，不启动业务服务。已有虚拟环境无法运行时，先检查解释器和客户端沙箱权限；不要直接认定项目依赖损坏。

此后在仓库根目录运行统一入口；它使用当前 Python，因此推荐通过后端 uv 环境启动：

```powershell
uv run --project backend --locked --no-sync python scripts/verify.py doctor
uv run --project backend --locked --no-sync python scripts/verify.py quick
uv run --project backend --locked --no-sync python scripts/verify.py full --report .tmp/quality/full.json
```

| 档位 | 范围与前置条件 |
| --- | --- |
| `doctor` | 只读诊断 Python、锁定后端环境、Node/npm、前端依赖、Docker Compose、测试库和 Chromium；不运行业务测试或修复环境 |
| `quick` | 后端格式/lint/类型、非数据库且非 Compose 的 pytest、迁移链头、离线评估；前端 lint/类型/Vitest；不含数据库验收、构建和浏览器 |
| `full`（默认） | 后端格式/lint/类型、全部 pytest、迁移链头和离线评估；前端 lint/类型/Vitest/build；需要专用测试库及 Docker Compose |
| `eval` | 只运行后端离线契约评估及其依赖诊断，不发起真实模型调用 |
| `e2e` | 单独运行 Chromium 下的 Mock 界面验收，强制 Mock 模式且不复用既有 4173 服务；不代表 HTTP/数据库联验 |
| `http-e2e` | 浏览器通过真实 HTTP 保存日志、提交技术研究及重试失败的币种同步，验证终态、刷新和新会话读取；专用测试库与随机 schema，不装配完整业务 lifespan |

可加 `--component backend` 或 `--component frontend` 缩小范围；不兼容的档位与范围组合会拒绝。`--timeout` 为每条检查的秒数上限，默认 900。检查超时会终止进程树。pytest 临时目录在 `.tmp/pytest/` 下按运行隔离。统一入口清空继承的 `PYTEST_ADDOPTS`，防止外部 `--collect-only`、`-k` 或 `-m` 将完整验收悄悄缩小；手动聚焦 pytest 不受此限制。

编辑中先运行受影响测试；一批工作完成后运行 `quick`；交付前运行 `full`，关键界面另运行 `e2e`。子 Agent 只运行其聚焦测试，由主会话运行完整入口。快速检查通过不能替代完整验收。

## 状态、证据与排障

`http-e2e` 需要默认 `--component all`，同时预检后端与前端。默认端口为 8174/4174，不复用已有服务；可用 `HTTP_E2E_BACKEND_PORT`、`HTTP_E2E_FRONTEND_PORT` 调整。它复用生产交易日志路由、服务、仓储和迁移，浏览器不拦截 HTTP。正常退出与随机 token 认证的测试回收端点共同清理本次 schema；整个进程树被强杀时仍须依靠独立临时数据库实例生命周期清理，不能指向业务实例。

`quick` 与 `full` 均新增 `architecture` 检查，保留原字符串安全测试并增加 AST 依赖门禁。`eval`、`quick` 与 `full` 同时运行适配器评估和研究服务流程评估。

每项输出 `passed`、`failed` 或 `blocked`。最终退出码 0 表示所选范围通过，1 表示检查失败，2 表示只有前置条件阻塞；失败优先。依赖项没有通过时，后续测试标记 blocked，不会连接数据库；无关检查继续执行。空计划和零测试不能被当作通过。

`--report PATH` 保存版本化 JSON 安全摘要，其中包含档位、范围、各项状态、固定原因码和工具退出码。报告不包含环境变量、连接串、原始异常或模型输出；子进程原始输出默认不回显、不归档。失败时按下表在对应目录复现，查看当地诊断，不要把敏感输出复制到共享报告。

| 检查名称 | 复现或修复入口 |
| --- | --- |
| `python-3.12` / `backend-dependencies` | 检查 Python 3.12；根目录 `uv sync --project backend --locked` |
| `backend-format` / `backend-lint` | `backend/`：`uv run ruff format --check .` / `uv run ruff check .` |
| `tooling-format` / `tooling-lint` | `backend/`：`uv run ruff format --check --config pyproject.toml ../scripts` / `uv run ruff check --config pyproject.toml ../scripts` |
| `backend-types` | `backend/`：`uv run pyright` |
| `test-database` | `backend/`：`uv run python -m scripts.check_test_database`，按下一节满足前提 |
| `backend-tests` | `backend/`：`uv run python -m pytest -q -ra`；快速模式另加 `-m "not database and not compose"` |
| `migration-heads` | `backend/`：`uv run alembic heads`，这不等于业务数据库已迁移 |
| `offline-evaluation` | `backend/`：`uv run python -m scripts.evaluate_research` |
| `research-flows` | `backend/`：`uv run python -m scripts.evaluate_research_flows` |
| `architecture` | `backend/`：`uv run python -m scripts.check_architecture` |
| `http-database-e2e` | 根目录：`uv run --project backend --locked --no-sync python scripts/verify.py http-e2e` |
| `node` / `npm` / `frontend-dependencies` | 核对 Node 范围，根目录 `npm ci --prefix frontend` |
| `frontend-*` | `frontend/`：现有 lint、typecheck、test -- --run、build 命令 |
| `chromium` / `mock-e2e` | `frontend/`：`npx playwright install chromium`；随后根目录统一入口 `e2e` |

系统临时目录有权限问题时，为手动 pytest 命令加 `--basetemp`，指向 `.tmp/` 内一个新的、专属于本次运行的目录；pytest 会清理该指定目录，不要使用已有工作目录或共享目录。

## 专用测试库的防护契约

测试连接必须由当前进程显式提供 `TEST_DATABASE_URL`，不再从 `.env` 自动取得测试授权。不要在终端输出、文档或提交中记录实际连接串；可用既有受信任的环境注入机制配置它。

- 驱动固定 `postgresql+asyncpg`，库名 `crypto_research_test`，登录角色 `crypto_research_test_runner`，允许显式端口；禁止 URL query 覆盖连接目标。
- 该角色需要本测试库的 CONNECT/CREATE 权限，以创建随机临时 schema 和运行迁移；不得拥有超级用户、建库、建角色、复制、绕过 RLS 权限或其他角色成员资格。建议独立临时实例，由受限角色拥有测试库。
- 先进行配置检查，再以只读连接核对服务端数据库、角色和权限，预检不会创建库、角色或 schema。
- 进程及根目录/后端 `.env` 的业务 `DATABASE_URL` 只作为拒绝依据。业务库与测试库同名即保守拒绝，忽略驱动、密码、主机别名及端口；因此不同集群的同名业务库也会被拒绝。
- 所有数据库测试均依赖共享预检夹具，包括独立迁移测试；按 fixture 依赖闭包自动标记 `database`，不依赖目录名猜测。直接运行 pytest 也不能绕过预检。

此约束是防误配置措施，不是抵御恶意数据库管理员的安全隔离。预检和后续写连接之间仍有时间差；专用实例、独立身份、最小权限及网络隔离仍由运行环境负责。迁移不要求测试角色拥有业务库权限。

## 研究报告 HTTP 与任务恢复验收

`http-e2e` 包含五条浏览器流程：日志保存、BTC 技术报告完成、ETH 技术报告缺模型配置降级，以及下述两条币种同步重试。研究路径经生产 202 入队、真实 worker/Harness/两阶段适配器与 SQL 仓储；只有行情和模型传输为固定合成输入，浏览器不拦截请求。用例核对报告与 run 的分析身份、完成或降级分类、刷新/历史列表及全新浏览器上下文读取。该装配不访问真实外部源，不是完整生产 lifespan 或真实模型质量验收。

研究验收工厂在清理 schema 前先取消并回收 worker，再关闭模型 HTTP 客户端和 SQL 引擎；不把测试回收端点加入生产应用。历史迁移预置的 BTC/ETH 目录在隔离 schema 内追加合成 ready 记录，用于走实际目录授权，而非模拟真实初始同步已经成功。

在 `backend/` 可聚焦执行：

```powershell
uv run pytest tests/persistence/test_technical_worker_recovery.py tests/tooling/test_http_e2e_research.py tests/tooling/test_http_e2e_server.py
```

需要满足专用数据库预检，测试同样自动标记 `database`。覆盖 worker 重建、实际子进程被终止后的过期恢复、保存后 finish 故障、模型调用中取消、报告已提交后的取消、并发重复提交及旧租约迟到保存。恢复规则是“无报告则 interrupted、有已保存报告则恢复 completed/degraded”，不是自动重试。取消指 worker/协程退出，当前没有用户取消 HTTP 接口。

实际子进程测试使用阻塞执行器证明 worker/SQL 崩溃恢复；完整模型适配器/Harness 链由其他用例证明。新浏览器上下文只能证明没有客户端缓存依赖，不证明后端操作系统重启。取消时运行状态为 interrupted，已有不可变 Harness 终态可能先记录 workflow_exception/CancelledError，worker 不覆盖它。

## 完整 Compose 运行与恢复

独立 HTTP 工厂不是完整生产装配。2026-11-01 另行使用生产 Dockerfile、入口迁移、完整 API lifespan、Nginx 和独立 PostgreSQL 完成合成交易日志验收，包含 API 重启、保卷整套重建及备份恢复到独立空库；记录见[隔离 Compose 验收](superpowers/plans/2026-11-01-isolated-compose-acceptance.md)。没有新增统一入口档位，不能将 `http-e2e` 的通过结果直接解释为这组运行验收通过。

该次验收使用临时编排与测试资源，API/数据库内部隔离、模型密钥为空。恢复实例有独立前端来源，且在原实例停止后通过新浏览器读取。证明范围限于所验合成日志和迁移链，不覆盖全业务数据、断电恢复、PITR、真实公开源或付费模型。

## 研究币种同步恢复回归

在 `backend/` 运行 `uv run pytest tests/symbols/test_sync.py tests/persistence/test_symbol_repository.py tests/persistence/test_symbol_sync_recovery.py tests/api/test_symbol_sync_retry.py`。SQL 用例要求显式专用测试库授权，覆盖并发重试、迟到失败 ID、归档/版本、租约截止与新消费者回收；worker 联验使用固定合成行情与真实快照仓储，验证续租后超过原租约仍可保存、归档取消、超时和协程中断的持久化结果。另验证终态提交等待中的心跳异常会取消提交、队列存储暂时故障后继续消费，以及快照独立提交后取消时保留行情但不关联任务或授予准入。该组不连接公开源，不证明生产进程重启或公网质量。

前端回归为 `src/features/research-symbols/ResearchSymbolManagementPage.test.tsx`、`src/shared/api/research-symbol-sync.test.ts` 和已有目录旅程，覆盖状态、请求契约、重试禁用、安全错误与活跃任务轮询。Mock 不执行同步，HTTP/Hybrid 写入失败不回退离线结果。

`http-e2e` 另使用 [同步装配](../backend/scripts/http_e2e_symbols.py)及[浏览器用例](../frontend/e2e-http/symbol-sync-retry.spec.ts)验证 SOL 首次失败后重试为部分覆盖、XRP 再次失败。目录元数据为固定夹具，不代表公网准入检查；初次失败与重试终态均由生产 worker、SQL 租约/审计和快照仓储写入。资金费率未注入，恢复结果明确为部分覆盖而非就绪。

浏览器检查失败任务 ID、202 排队、运行中按钮禁用、目录轮询、重复请求复用同一任务、迟到旧请求 409、刷新及新上下文重读同一终态。仅在隔离验收服务注册的 token 认证事件门控制采集完成，避免固定等待造成偶然通过；主 runner 生成随机 token，Playwright worker 重载配置时继承它，token 不进入 `VITE_*`。回收先取消并等待同步和研究消费者，再删除随机 schema；不证明真实公开源可用或整个生产同步进程重启。

## 手动验证真实公开源

新闻逐条隔离回归位于 `tests/news/test_rss.py`、`tests/news/test_collection_diagnostics.py` 及相关研究服务测试：保留合格条目、拒绝安全计数、请求局部诊断、取消及整源安全边界，并验证覆盖说明通过现有报告字段保存。前端 `ReportPages.test.tsx` 验证完整/降级报告及旧记录的限制说明展示。生产适配器继续使用原有白名单和文本规则；公开源检查遇到被过滤条目会保留部分覆盖，而不是将剩余合法条目视为全源完整。

在 `backend/` 显式运行以下命令；该检查会联网，不属于统一 `full`、离线评估或 CI 的默认步骤：

```powershell
New-Item -ItemType Directory -Force ../.tmp/quality | Out-Null
uv run --locked --no-sync python -m scripts.check_public_sources --report ../.tmp/quality/public-sources.json
```

[诊断脚本](../backend/scripts/check_public_sources.py)默认只经生产适配器读取固定 BTCUSDT/ETHUSDT 的合约元数据、行情摘要、四周期已收盘 K 线、衍生品和七日资金费率，以及已登记的六个 RSS 源，共 22 个分项。两个分项并发，每项最多 20 秒，不叠加生产适配器之外的重试；K 线分项复用生产行情详情读取，仍依赖摘要可用，不能解释为独立 K 线端点探针。不读取应用配置、`.env`、数据库、账户或模型，不注册币种，不保存价格、新闻正文或原始响应，也不提供任意 URL 参数。真实模型和完整研究报告不在该命令范围。

可显式加 `--include-context`，增加 Alternative.me 恐惧贪婪历史和 BTC/ETH Farside ETF，共25项。情绪阈值48小时，并核对返回八条日度历史的连续性；ETF按纽约当地日历七天及披露完整性判断，单列 `latest_trading_date`，`observed_at` 为空，不冒用抓取时刻。未来日期已由生产ETF适配器过滤，诊断只覆盖返回字段；部分披露不能记为完整通过。此选项仍只在手动运行时联网，不加入默认full或离线测试。

综合研究完整采集到SQL闭环的固定回归见 `tests/persistence/test_comprehensive_research_capture_history.py`：外层行情/新闻为合成输入，其余使用生产采集、新闻仓储、研究图、缺配置模型、报告仓储与Harness。另有一次真实公开源、空模型配置的隔离运行记录，见[收尾清单](optimization-closeout.md)。两者分别证明确定性回归与单次实时采集，不互相冒充，也不证明真实模型质量。

诊断阈值只用于本命令：摘要五分钟、K 线周期加五分钟、衍生品两小时；BTC/ETH 费率最近一笔十二小时内，七日历史至少二十条、首条距窗口起点不超过十二小时且相邻间隔不超过十二小时，才标为覆盖完整。这些阈值不改变生产准入或风控。RSS 分别报告解析可用性与最近七日内容条数；低频源没有近期内容表示覆盖不足，不等于连接故障。未来时间、空数据、陈旧和来源失败分别记录，时间检查仅限适配器公开的字段：摘要与衍生品只提供三个上游分量中最早的聚合观测时刻，不能据此证明每个分量均无未来值。检查通过不等于研究币种准入、完整数据质量或研究报告已就绪。

安全 JSON 包含契约版本、固定检查标识、UTC 检查/观测/完成时间、条数、阈值、可用性及固定原因码；RSS 另列拒绝数与预算截取数，`recent_news_count` 只统计本次保留样本，不推断被截去条目的时效。存在过滤或截取时为部分覆盖；可取得时附 HTTP 状态码，生产领域错误未保留该状态时为 null。原始异常、环境值、代理地址和返回正文不进入报告。全部通过退出 0，部分通过或来源失败退出 1，报告写入失败退出 2。只比较统计和时间，不归档原始采集内容；落盘前需创建输出目录。

客户端沿用 httpx 的进程环境网络方式，不读取或更改代理配置。主机进程结果不代表 Docker 容器网络、长期可用性或实时服务承诺；单次失败也不能据此推断整个公开源失效。离线回归入口为 `uv run pytest tests/tooling/test_public_sources.py`，使用固定响应，不联网。

## 评估产物与 CI 证明范围

真实模型评估工具为独立显式入口 `python -m scripts.evaluate_real_models`，默认仅准备固定历史/合成扰动样本，不联网、不读密钥。只有 `--live`、专用进程密钥、明确调用/输入/输出/时间额度及新产物路径同时提供时才允许付费请求；不挂接默认full/CI。适配器接受率与引用ID合法性不等于语义质量，人工评分始终单列pending。命令、语料来源、费用估算限制与本地人工提案注意事项见[真实模型评估说明](../backend/evaluation/real-model/README.md)。

默认语料现为独立v2：固定K线衍生64条结构化事实，模型选择事实标识，生产适配器渲染带字段/单位/UTC范围的完整语句。原v1不回写；safe report另含数值渲染模块SHA，比较时同时核对语料、Prompt、适配器及渲染指纹。语法通过不证明自然语言上下文的语义支持，不能用机器接受率代替具名人工复核。

小批诊断可加 `--case baseline-history`，只允许固定suite已有ID，报告另有选择范围；完整语料指纹不变，单案不能代替四案。可见目录最多十六条，冻结64条事实保留，live报告分开记录冻结/提供条数；Prompt与渲染同一白名单。缩小输入或通过代码测试不等于真实接受率提高，需按实际拒绝类别和用量记录结论。

统一摘要现为 schema_version 2，后端测试通过显式 pytest 插件生成安全计数和失败代码标识，去掉所有参数化后缀，不保存异常、捕获输出或跳过原因。只收集、零执行、摘要缺失/格式损坏或写入失败不能通过。失败时可直接查看报告的 `diagnostics.failures`，再按代码标识运行聚焦回归，无需再次全量测试才能定位。每次运行使用独立产物名防止旧报告冒充新结果。

CI 归档目录包含 `pytest-*`、`architecture-*`、`research-adapter-*`、`research-flows-*` 安全 JSON，保留测试计数与评估版本指纹；不会上传 pytest 原始日志、浏览器 trace 或模型原文。

AST 检查覆盖研究到交易模块、Harness 到交易/外部 IO/持久化实现、Risk 到 Agent/LLM 的直接依赖，支持相对/父包/别名及明确动态导入。空扫描、缺关键模块、解析/读取失败均非零；不保证任意反射、间接包装、重导出和传递依赖安全。规则与故意违规样例见 [架构门禁](../backend/scripts/check_architecture.py)和[测试](../backend/tests/security/test_architecture_gate.py)。

[固定评估集](../backend/evaluation/README.md)通过真实综合研究适配器和无网络传输替身验证接受、拒绝与可降级错误，记录样本、Prompt 和契约指纹；不是付费模型质量或交易表现基准。真实模型研究质量、真实抗注入能力、完整研究图的证据不足门控及降级持久化没有由这个适配器评估集验收。

[研究服务流程集](../backend/evaluation/flows/README.md)补充技术 v2 两阶段、综合研究证据门控及保存/读取合同；离线内存读取与真实数据库回归分别给出证据，不能互相替代，详见该集的限制说明。

[GitHub Actions](../.github/workflows/verify.yml)配置保留为参考，声明安装锁定依赖、创建独立 PostgreSQL 17 与受限测试身份，并调用同一 `full`、`e2e` 与 `http-e2e` 入口。当前交付只要求本地验收，不执行远端 CI 或设置分支合并门禁；仓库中的配置不代表远端已验证或已启用门禁。
