# 可复现质量验证 Implementation Plan

> **For agentic workers:** 按 test-driven-development 与 verification-before-completion 逐项执行；独立任务可按 dispatching-parallel-agents 分工。本任务不自动提交或推送。

**Goal:** 让本地与 CI 复用可诊断、不会假绿的验证入口，并补齐测试库防护及离线评估。

**Architecture:** 标准库根脚本协调现有命令；后端测试支撑模块执行数据库预检；独立离线评估脚本复用现有模型验证链。

**Tech Stack:** Python 3.12、uv、pytest、npm、GitHub Actions、PostgreSQL 17。

**Spec:** [设计](../specs/2026-10-27-reproducible-quality-gates-design.md)。

## Global Constraints

- 不新增生产依赖，不修改 schema、业务数据库、`.env` 或真实模型配置。
- 不记录连接串、凭证、原始模型输出；模型评估不访问网络。
- 新增 Python 代码和测试维护详细中文职责、流程、失败边界注释。
- 失败或 blocked 不得报告为 passed；不提交、推送或部署。

## Review Focus

- 缺少命令、错误目录、超时或空任务列表不能得到成功结果。
- 数据库同目标比较不能因不同驱动、密码或主机别名而绕过。
- 数据库前提缺失时不能先建 schema 再检查；独立迁移用例同样防护。
- 评估不能导入测试私有 helper、只测 JSON 解析或把全部拒绝算通过。
- CI 与本地调用同一入口，退出码保留，产物不包含敏感信息。

## Task 1：统一入口、环境诊断和 CI

- [x] 新建 `backend/tests/tooling/test_verify.py`，行为测试覆盖命令失败、阻塞、超时和输出脱敏；先运行确认失败。
- [x] 新建 `scripts/verify.py`，提供 doctor/quick/full/eval/e2e，默认完整验证；构建结构化三态结果和安全摘要。
- [x] 新建 `.github/workflows/verify.yml`，安装锁定依赖，创建独立测试库及受限角色后调用同一完整入口。
- [x] 验证入口测试及全部静态检查；如需整理格式，仅执行 Ruff formatter，不手改历史迁移行为。

## Task 2：测试库预检

- [x] 新建测试支撑模块及行为测试，覆盖无配置、业务库同目标、非测试库、权限和脱敏；先确认失败。
- [x] 接入共享夹具和独立迁移测试，所有测试写入前检查。
- [x] 提供只读 doctor 检查入口，不自动创建库、角色或修改配置。
- [x] 运行聚焦测试，报告数据库验收是否实际执行。

## Task 3：离线模型评估

- [x] 编写版本化样本与评估器测试，覆盖预期不匹配、空集、无效样本；先确认失败。
- [x] 新建 `backend/scripts/evaluate_research.py` 及样本说明，复用实际校验与降级链，无真实 HTTP 请求。
- [x] 输出安全 JSON 统计与版本信息，预期不匹配时非零退出。
- [x] 运行评估器及聚焦测试，不能声称建立了真实模型质量基准。

## Task 4：集成、说明和最终验证

- [x] 更新 README、开发规范、AI 维护指南及项目状态，记录命令和未验收项。
- [x] 运行后端 Ruff/格式/Pyright/pytest、前端 lint/typecheck/Vitest/build，以及可用的统一入口。
- [x] 独立代码审查，修复重要问题并执行对应回归；检查 diff、文档链接和工作区范围。

## 执行记录

- 基线：`417cae7`，开始时工作区干净；初始沙箱中解释器与 Docker 不可用，提升执行权限后确认 Python 3.12.12、pytest 9.1.1 和 Docker 均可用，不是安装缺失。
- 新建分支 `chore/reproducible-quality-gates`，未提交、推送或部署。使用独立临时 PostgreSQL 17，无业务卷，固定受限角色通过只读身份检查。
- 统一入口测试由缺少模块的红灯到 15 项通过；评估器由缺少模块的红灯到 10 项通过；数据库防护包含 25 项离线回归及实际 PostgreSQL 全量验证。
- 独立评审发现外部 `PYTEST_ADDOPTS=--collect-only` 可能产生假绿，已补回归并清空该变量；回归真实运行故意失败的子测试，确认不会只收集。
- 统一入口全量验证发现 pytest 不会建立 `--basetemp` 的多层父目录；已以真实子 pytest 建立首次运行红灯，修复父目录初始化后 15 项入口测试通过。失败记录保留于执行过程，不把失败运行称为通过。
- Playwright 首次 4 项失败，对应两个桌面视口下的两条旧流程：交易腿使用非 UUID 标识。按当前契约修正测试输入后 16 项通过，未放宽应用校验。
- Ruff 整理 66 个存量文件；格式化前后比较 253 个后端文件 AST，除两处普通函数 docstring 缩进外全部一致，历史迁移 AST 均不变。
- 评估版本 `research-offline-v1`：8/8 匹配，接受 2、拒绝 4、适配器可降级错误 2。未调用真实模型，未建立真实研究质量基准；完整研究图的证据不足门控和降级持久化未新增到此适配器评估集。
- CI 工作流已做 YAML 解析检查，远端 GitHub Actions 与分支保护未启用或验收。CI 目前归档检查摘要，详细离线评估版本可用 `--output` 单独归档。
