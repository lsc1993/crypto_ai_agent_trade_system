# 技术交易计划书 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 独立技术研究提供有证据的入场、止损、目标及等待计划，并可靠交付两阶段模型结果与明确降级。

**Architecture:** 保留现有确定性行情分析和突破候选，新增引用驱动的 v2 决策与计划书。思考分析与非思考编排独立调用、校验与限额；持久化队列通过固定 worker 进入 Harness，前端查询任务状态。旧报告不变。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、httpx、SQLAlchemy/asyncpg、Alembic、PostgreSQL、React、TypeScript、Zod、TanStack Query、pytest、Vitest、Playwright。

**Spec:** [已确认设计](../specs/2026-10-09-technical-trading-plan-design.md)。执行前读取根/前后端 AGENTS、AI 维护指南和运行边界。

## Global Constraints

- 本期继续使用现有确定性突破候选规则，不降低盈亏比或数据质量门槛。
- 主计划最多一个；无候选输出等待，不虚构价格或新增逆势策略。
- 不新增生产依赖、外部 MCP、交易所、账户访问、TradeIntent 或执行能力；不修改 .env。
- 数值为 Decimal/十进制字符串，时间为带时区 UTC。
- 初始分析额度 32768、thinking enabled、reasoning_effort high；编排额度 8192、thinking disabled。
- 分析最多两次、编排最多两次；分析单次 180 秒、编排单次 90 秒、任务总执行截止 600 秒。
- 队列容量初始 20、执行并发初始 1；数据库领取与租约约束多实例，不依赖进程锁。
- 保存已校验摘要，不保存或转发 reasoning_content；所有日志为安全白名单元数据。
- 新增一条前向迁移；旧报告只读，v1/v2 按版本解码。
- 工作区现有其他任务差异保留。本次技术模型修复属于依赖基线，其相关差异需单独核对；不可整体 git add。
- 真实付费模型质量评估、推送及业务数据库迁移/部署不由测试通过自动授权。

## Review Focus

- 同数值出现在不同字段：只有字段及单位绑定引用有效，不能用全局数值白名单。
- 报告提交后任务更新失败：按 analysisId 恢复任务，不重新付费生成。
- 旧 worker 租约过期后恢复：旧 owner 不可更新任务或保存第二份报告。
- 用户切换币种且迟到请求返回：不可跳转到另一币种报告或丢失正在运行的任务。
- 所有任务轮询暂时失败：可恢复查询同一任务，不能自动新建生成请求。

---

### Task 1: v2 决策、引用与计划书契约

**Files:** Create `backend/src/app/reports/technical_plan.py`, `backend/src/app/agent/technical/references.py`, `backend/tests/agent/test_technical_references.py`, `backend/tests/reports/test_technical_plan.py`; modify `backend/src/app/reports/technical.py` and `backend/src/app/reports/technical_repository.py`.

**Interfaces:** `TechnicalReport` 继续代表旧 v1；新增 `TechnicalPlanReport`（v2），`TechnicalReportDocument = TechnicalReport | TechnicalPlanReport` 和 `parse_technical_report(payload: object) -> TechnicalReportDocument`。`TechnicalContext` 保存 analysis、summaryPrice、latestClosedPrices、dataCutoffAt。`build_reference_catalog(context: TechnicalContext) -> ReferenceCatalog`、`validate_decision(summary: TechnicalDecisionSummary, catalog: ReferenceCatalog) -> TechnicalDecisionSummary`、`render_plan_book(book: TechnicalPlanBook, catalog: ReferenceCatalog) -> RenderedPlanBook`。

- [ ] 写失败测试：`test_v1_round_trip_unchanged`；`test_no_candidate_requires_wait`；`test_rejects_foreign_evidence_and_method`；`test_same_value_wrong_field_or_unit_rejected`；`test_rejects_unbound_numeric_literals`；`test_conditional_entry_terms_allowed_but_orders_and_promises_rejected`；`test_rendered_prices_equal_wire_decimals`。
- [ ] 在 backend 执行 `uv run pytest tests/agent/test_technical_references.py tests/reports/test_technical_plan.py -q`，确认因缺少接口失败。
- [ ] 实现冻结引用表和 Pydantic 契约。决策包含 stance（long/short/wait）、selectedPlanRef、marketStructure、supportingEvidence、counterEvidence、methodApplications、entryConditions、stopRationale、targetRationale、invalidation、alternative、waitingConditions、risks；每条绑定 evidenceId 和限定 factRefs/methodRefs。引用值保留字段标签/单位，正文插值语法 `{{factRef}}` 仅生成带标签值，未知占位符拒绝。
- [ ] 段落限制：每条 20–1200 字符，列表 1–6 条，总正文上限 16000；方法应用 1–4 个且限定本次选中方法。引用模板中的数值只通过程序渲染；旧 v1 验证不放宽。
- [ ] v2 保留 analysis、身份与时间字段，新增 decision（可空）、planBook、generation（model/rules、阶段结果、版本、诊断）。completed 仅用于两阶段模型成功；其他交付标 degraded，行情失败仍可表达缺失信息。运行相关失败码保持枚举。
- [ ] 重跑上述测试并运行 `uv run pytest tests/agent/test_technical_engine.py tests/agent/test_technical_model.py -q`；只提交本任务文件，提交说明 `feat: add evidence-bound technical plan contracts`。

### Task 2: 两阶段模型、额度与安全诊断

**Files:** Create `backend/src/app/agent/technical/plan_model.py`, `backend/src/app/agent/technical/plan_prompt.py`, `backend/tests/agent/test_technical_plan_model.py`; modify `backend/src/app/shared/config.py`; add config tests to `backend/tests/agent/test_technical_plan_model.py`。

**Interfaces:** `TechnicalPlanLanguageModel.analyze(context: TechnicalContext) -> TechnicalDecisionResult`；`compose(context: TechnicalContext, decision: TechnicalDecisionSummary) -> TechnicalCompositionResult`。结果包含已校验正文/摘要与 `TechnicalStageDiagnostic`；`TechnicalPlanModelError` 包含安全 code、stage、diagnostics。`DeepSeekTechnicalPlanLanguageModel` 接收 client、key、model、独立设置。沿用旧 formatter 供 v1 接口。

- [ ] 写失败测试：`test_analysis_thinks_composition_does_not` 断言 32768/8192、high/enabled 与 disabled；`test_length_retries_with_low_thinking_once`；`test_empty_content_is_distinct`；`test_invalid_reference_correction_has_no_raw_response`；`test_tools_rejected`；`test_reasoning_never_forwarded_or_logged`；`test_auth_failure_not_retried`；`test_retry_after_bounded`；`test_timeout_respects_stage_budget`。
- [ ] 在 backend 执行 `uv run pytest tests/agent/test_technical_plan_model.py -q`，确认失败。
- [ ] 实现专用设置 `technical_analysis_max_tokens=32768`、`technical_composition_max_tokens=8192`、`technical_analysis_timeout_seconds=180`、`technical_composition_timeout_seconds=90`、`technical_run_timeout_seconds=600`；范围分别 4096–65536、2048–16384、30–180、15–90、120–600，另校验阶段超时不超过总截止。综合报告配置不改。
- [ ] 每阶段最多两次，仅瞬时上游、空正文、length、合约问题重试；认证/参数错误终止。length/空正文的分析第二次使用 low，thinking 仍 enabled。Retry-After 最多 5 秒，剩余预算不足不重试。
- [ ] HTTP 完整响应上限 2MiB，content 独立上限 32000 字符；工具、未知 finish_reason、非字符串 content 拒绝。仅采集 stop/length、token 非负整数、耗时、尝试数和已知字段错误；不记录原始异常或 reasoning。
- [ ] 使用 MockTransport 跑上述测试和旧模型测试；Ruff/Pyright 聚焦检查；提交 `feat: generate technical analysis and plan in separate stages`。

### Task 3: v2 固定服务、冻结保存与降级

**Files:** Create `backend/src/app/agent/technical/plan_service.py`, `backend/src/app/agent/technical/plan_fallback.py`, `backend/tests/agent/test_technical_plan_service.py`; modify `backend/src/app/infrastructure/persistence/technical_report_repository.py`, `backend/src/app/reports/technical_repository.py`; extend `backend/tests/persistence/test_technical_report_repository.py`。

**Interfaces:** `TechnicalPlanResearchService.generate(symbol: ResearchSymbol, *, analysis_id: UUID, progress: Callable[[TechnicalRunPhase], Awaitable[None]], before_save: Callable[[], Awaitable[None]]) -> TechnicalPlanReport`。仓储所有读写支持 `TechnicalReportDocument`，新增 `get_by_analysis_id(analysis_id: UUID) -> TechnicalReportDocument | None`。

- [ ] 写失败测试：`test_v2_freezes_once_across_retries`；`test_composition_failure_preserves_valid_decision`；`test_analysis_failure_rules_waiting_not_fabricated_ai`；`test_invalid_market_skips_both_calls`；`test_total_deadline_leaves_time_for_degraded_save`；`test_lost_ownership_prevents_save`；`test_v1_v2_mixed_history_round_trip`。
- [ ] 在 backend 执行 `uv run pytest tests/agent/test_technical_plan_service.py -q`，确认失败。
- [ ] 复用 engine，冻结摘要/已收盘价格及方法指纹；将 Task 1–2 串成固定调用，不新增工具循环。保存前重新校验全文、立场、引用和所有价格。模型调用总截止预留最后 15 秒用于降级保存，存储失败传播明确错误。
- [ ] 第一阶段失败调用 `build_rules_plan_book(context)`；第二阶段失败调用 `build_decision_plan_book(context, decision)`。两者标识 rules，保留本次拒绝理由；没有候选主卡为空，仅展示等待观察点。副情景不擅自生成方向/新价格。
- [ ] get/list/persist 根据 version 解析；使用 analysisId 唯一索引恢复报告。冻结 evidence 保存 context、选定方法、已校验 decision 与安全诊断；不存 reasoning。
- [ ] 跑上述服务测试及原服务/仓储测试（仓储仅专用测试 PostgreSQL）；提交 `feat: persist v2 technical plans with honest fallback`。

### Task 4: 持久化队列、租约与幂等迁移

**Files:** Create `backend/src/app/reports/technical_runs.py`, `backend/src/app/reports/technical_run_repository.py`, `backend/src/app/infrastructure/persistence/models/technical_runs.py`, `backend/src/app/infrastructure/persistence/technical_run_repository.py`, `backend/alembic/versions/0018_create_technical_report_runs.py`, `backend/tests/persistence/test_technical_run_repository.py`; modify models `__init__.py` 与 `backend/tests/persistence/test_migrations.py`。

**Interfaces:** `enqueue(symbol, *, request_id: UUID, now: datetime) -> TechnicalRun`；`get(run_id: UUID) -> TechnicalRun | None`；`claim(*, owner: UUID, now: datetime) -> TechnicalRun | None`；`heartbeat(run_id, *, owner, now) -> bool`；`advance(run_id, *, owner, phase, now) -> bool`；`finish(run_id, *, owner, status, report_id, error_code, now) -> bool`；`recover_expired(*, now) -> int`。协议中每个参数使用明确 ResearchSymbol/UUID/UTC datetime/枚举类型。

- [ ] 写失败数据库测试：`test_request_id_replay_and_symbol_conflict`；`test_active_symbol_reuse_retains_each_request_key`；`test_concurrent_queue_capacity_twenty`；`test_only_one_global_run_claimed`；`test_expired_owner_cannot_advance_or_finish`；`test_report_commit_recovery_does_not_reenqueue`；`test_forward_migration_keeps_v1_reports`。
- [ ] 专用 PostgreSQL 中执行 `uv run pytest tests/persistence/test_technical_run_repository.py -q`，确认失败。
- [ ] 新 revision `0018_technical_report_runs`，down_revision `0017_technical_reports`。增加任务表、请求键关联表、单行队列协调表；事务锁协调行串行化 enqueue/claim/恢复，容量为 queued+running ≤20。同标识不同币种返回安全冲突，活跃币种复用仍保存新 requestId 别名。
- [ ] 使用合法状态/阶段/终态 CHECK、唯一活跃 symbol 部分索引、requestId 唯一索引、报告关联 FK；analysisId 在入队生成，可在 Harness 开始前存在，不能提前强制 harness FK。
- [ ] claim 设置 owner 和 30 秒租约，heartbeat 每 10 秒。所有更新检查 owner、running 和未过期租约。过期任务优先按 analysisId 找报告并恢复终态，否则 interrupted/failed；不重新执行旧模型请求。任意任务查询不触发生成。
- [ ] migration downgrade 拒绝删除历史。确认 `uv run alembic heads` 单 head，并通过专用库迁移/并发测试；提交 `feat: queue durable technical research runs`。

### Task 5: 固定 worker、Harness 与 HTTP 接口

**Files:** Create `backend/src/app/agent/technical/worker.py`, `backend/tests/agent/test_technical_worker.py`; modify `backend/src/app/harness/technical_research.py`, `backend/src/app/api/routes/technical_reports.py`, `backend/src/app/main.py`; extend `backend/tests/api/test_technical_reports.py` 和 `backend/tests/harness/` 对应技术运行测试。

**Interfaces:** `TechnicalPlanRunExecutor.generate(symbol, *, analysis_id, progress, before_save) -> TechnicalPlanReport` 经现有 HarnessRuntime 执行；`TechnicalResearchWorker.run_once() -> bool`、`run_forever(stop: asyncio.Event) -> None`。API 通过注入 `TechnicalRunRepository` 提交/查询；原同步生成接口使用原服务和契约。

- [ ] 写失败测试：`test_runs_route_is_not_report_uuid`；`test_enqueue_returns_202_without_model_call`；`test_execution_rechecks_admission`；`test_worker_uses_same_analysis_id_in_harness_and_report`；`test_shutdown_cancels_bounded_work`；`test_heartbeat_loss_cancels_generation`；`test_saved_report_recovers_after_finish_failure`；`test_legacy_sync_endpoint_still_201`。
- [ ] 在 backend 执行 `uv run pytest tests/agent/test_technical_worker.py tests/api/test_technical_reports.py -q`，确认新场景失败。
- [ ] 新 POST `/api/v1/technical-reports/runs` 请求 `{symbol,requestId}`；新 GET `/runs/{run_id}` 返回 TechnicalRun。注册顺序在 `/{report_id}` 之前；不存在 404、幂等冲突 409、容量不足 429、存储不可用 503，返回安全错误结构。
- [ ] 入队/执行均检查目录准入。worker 从队列取固定研究任务、进入现有策略白名单，在每阶段更新进度；模型没有队列或工具权限。终态审计继续由保存触发器维护，服务异常经 Harness 写失败审计。
- [ ] lifespan 增加专用 worker 和独立 httpx client，heartbeat 失效立即取消运行；停止领取后最多等待 5 秒再取消，调用和客户端释放不泄漏任务。保存之前检查 owner，报告唯一 analysisId 防止重复提交。恢复流程永不重放模型。
- [ ] 测试通过后跑 Harness/security 和 Compose 配置回归；提交 `feat: expose background technical report generation`。

### Task 6: 前端契约、适配器和任务交互

**Files:** Modify `frontend/src/domain/technical-report.ts`, `frontend/src/domain/technical-report.test.ts`, `frontend/src/shared/api/workbench-api.ts`, `http-workbench-api.ts`, `mock-workbench-api.ts`, `hybrid-workbench-api.ts` 与对应测试；modify `frontend/src/features/technical-reports/TechnicalReportListPage.tsx`, `TechnicalReportDetailPage.tsx`, `technical-copy.ts`, `technical-reports.css`, `TechnicalReportPages.test.tsx`；create `TechnicalPlanBook.tsx` 与 `TechnicalRunProgress.tsx`。

**Interfaces:** Zod discriminatedUnion 解码 v1/v2。`WorkbenchApi.startTechnicalReportRun(input: {symbol: Symbol; requestId: string}): Promise<TechnicalRun>`、`getTechnicalReportRun(runId: string): Promise<TechnicalRun>`；保留原三个报告方法。展示只读服务端渲染结果，不自行金融计算。

- [ ] 写失败测试：`decodesMixedVersionHistory`；`httpRunApiUses202AndValidatedSchema`；`hybridDelegatesRuns`；`mockRunsRemainDisclosed`；`resumesRunAfterRefresh`；`queryFailureDoesNotCreateNewRun`；`lateResponseCannotNavigateAfterSymbolChange`；`terminalStopsPolling`；`waitingHasNoInventedEntryCard`。
- [ ] 在 frontend 执行 `npm run test -- --run src/domain/technical-report.test.ts src/shared/api/technical-report-api.test.ts src/features/technical-reports/TechnicalReportPages.test.tsx`，确认新场景失败。
- [ ] HTTP/Mock/Hybrid 对齐新契约，补齐测试替身的 WorkbenchApi 方法。Mock v2 报告带显式演示标识，任务状态可查询；不伪装真实调用。
- [ ] 提交生成请求前创建 UUID requestId，重试同一提交使用同 ID。返回 runId 写入 URL 查询参数；查询每 2 秒直到终态。切换币种与组件卸载停止本地轮询/跳转，服务端任务继续；迟到成功仍保留可恢复的任务引用。查询失败显示重试查询按钮，不新建任务。
- [ ] v2 首屏当前立场与等待条件；主计划卡显示确认、结构止损、目标、成本后盈亏比、失效与有效期；无候选突出拒绝理由。备选/方法/风险其后，指纹/审计末尾。v1 继续旧展示。规则编排与模型失败明确区分。
- [ ] 运行新测试和适配器全部测试，lint/typecheck；提交 `feat: show technical trading plans and generation progress`。

### Task 7: 端到端验证、文档及交付

**Files:** Extend `frontend/e2e/technical-reports.spec.ts`, `backend/tests/security/test_agent_dependency_boundary.py` 与文档安全测试入口；modify `docs/technical-reports.md`, `docs/ai-maintenance.md`, `docs/operational-boundaries.md`, `docs/local-deployment.md`, `docs/project-status.md`, `frontend/README.md`。

- [ ] 写 E2E：手动提交 → 阶段进度 → 刷新恢复 → v2 主计划/等待 → 降级提示；断言不显示订单/账户执行入口。用 fixtures 验证旧 v1 仍可读取。
- [ ] 更新边界测试证明新 worker/模型仅依赖研究模块，不访问 strategy/risk/execution/paper_trading；检查日志不含正文/思考/凭证。文档清楚说明两阶段预算、队列中断、迁移、旧报告兼容和本期候选限制。
- [ ] 专用测试 PostgreSQL 跑 backend `uv run ruff check .`、`uv run pyright`、`uv run pytest`，确认实际通过数；绝不用业务数据库。无专用库则明确未验证，不认定完成持久化验收。
- [ ] frontend 跑 `npm run lint`、`npm run typecheck`、`npm run test -- --run`、`npm run build`；正确 Mock 服务与 Chromium 上执行 `npm run test:e2e -- technical-reports.spec.ts`。
- [ ] 更新项目状态仅写代码/验证支持的事实。真实模型评估与业务迁移/部署未执行必须注明，不将替身测试等同模型质量改善。
- [ ] 使用 requesting-code-review 技能进行一次独立全量差异审查，修复有证据问题并回归；仅提交本任务差异，提交 `test: verify two-stage technical research delivery`。
- [ ] 使用 verification-before-completion 技能核对证据，给出提交、验证目录/结果、迁移待应用及未验证项。使用 finishing-a-development-branch 处理集成，不默认覆盖工作区或推送。

## 执行方式建议与自审

建议 Native：本人按任务顺序实现，最后进行独立审查。各任务紧密依赖同一契约，顺序实施减少接口冲突；无需并行派发全部实现任务。用户也可选择 Subagent-driven，逐任务实现并逐任务审查。

自审：设计的契约、双阶段、降级、持久化、幂等、租约、API、三适配器、展示、兼容和验证均映射至上述任务。五项 Review Focus 分别由 Task 1、4、4–5、6、6 的测试覆盖。具体实现若发现需要扩大候选算法或权限，停止该扩展并说明，不自行偏离已确认设计。
