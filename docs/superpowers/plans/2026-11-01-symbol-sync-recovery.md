# 研究币种同步恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户安全重试失败同步，避免运行任务因超时或进程退出长期卡住。

**Architecture:** 复用目录行锁、不可变终态和租约。后端提供带失败任务 ID 的重试；worker 心跳与采集并行，取消时回收子任务；前端统一适配器和状态展示。

**Tech Stack:** Python 3.12、asyncio、FastAPI、SQLAlchemy/PostgreSQL、React、TanStack Query、Vitest。

**Spec:** [设计](../specs/2026-11-01-symbol-sync-recovery-design.md)

## Global Constraints

- 单 worker，默认整任务 120 秒、心跳 10 秒、租约 30 秒；无自动重试。
- 不新增依赖或 schema，不修改凭证、业务环境或交易能力。
- 保留已有未提交改动；本批不提交、推送或部署。

## Review Focus

- 同一失败请求并发到达只排一个任务；旧请求在新任务完成后不得再次排队。
- 归档与失租阻止旧 worker 改写任务；原始行情采集保持原有独立事务边界。
- 续租失败或异常停止采集；取消继续传播且不遗留心跳任务。
- API 错误与页面提示仅显示安全摘要；Mock/Hybrid 契约保持一致。
- 最新同步失败与既有研究资格分别展示；轮询在没有活跃任务后停止。

### Task 1: 仓储恢复和重试 API

Files: `symbols/contracts.py`、`symbols/repository.py`、`infrastructure/persistence/symbol_repository.py`、`api/routes/research_symbols.py`（均相对 backend/src/app）；`backend/tests/persistence/test_symbol_repository.py`、`backend/tests/symbols/`。

Interface: `retry(symbol: str, run_id: UUID, *, now: datetime) -> SyncRun`；POST 返回 202，body `{runId}`。

- [x] 先加 SQL/API 失败用例，确认并发、迟到、归档和过期边界失败。
- [x] 实现目录锁保护的 retry 和 claim 前过期回收，复用现有审计。
- [x] 运行聚焦 SQL/API 检查。

### Task 2: worker 有界生命周期

Files: `backend/src/app/symbols/sync.py`、`backend/tests/symbols/test_sync.py`。

Interface: 构造参数 `timeout_seconds=120`、`heartbeat_seconds=10`；保留 run_once/run_forever。

- [x] 先编写超时、正常心跳、失租、续租异常、取消回收的失败用例。
- [x] 实现并发心跳、整任务截止、子任务回收和安全失败映射。
- [x] 运行聚焦检查并覆盖真实仓储恢复。

### Task 3: 前端重试与状态

Files: `frontend/src/shared/api/`、`domain/research-symbol.ts`、`features/research-symbols/`、对应测试。

Interface: `retryResearchSymbolSync(symbol, runId)`；返回同步任务的 schema 校验结果。

- [x] 先加失败展示、重试提交/禁用、安全错误、终态刷新、HTTP/Hybrid 测试并确认失败。
- [x] 实现适配器、状态提示和仅活跃任务轮询。
- [x] 运行前端聚焦检查。

### Task 4: 综合验证与文档

- [x] 独立审查本批 diff，修复实际问题。
- [x] 根目录统一 full、e2e、http-e2e；检查链接、git diff --check。
- [x] 更新项目状态与运行说明，记录命令、结果和证明范围；回收临时测试实例。

## 验证记录

2026-11-01：首次统一 full 的 22 项检查通过；审查指出提交等待窗口的心跳异常可能被吞掉，事件协调测试先红后绿，work 扩展为包括终态提交。最终后端 full 的 15 项检查通过，813 passed、0 skipped；前端完整检查、HTTP 浏览器 3 条、Mock 浏览器 16 条通过。独立复核无剩余 P1/P2。补充暂时存储故障继续消费和已提交快照取消边界的测试。测试 schema 残留 0，独立实例已回收。

新增重试的浏览器全链未单独验收，当前由页面测试和真实 API/SQL 分层证明；本批浏览器用例是既有关键流程回归。没有真实公开源、模型质量或生产重启验收，无提交、推送或部署。
