# 后端开发约定

本文件补充[根目录规则](../AGENTS.md)，不放宽其中的安全边界。命令均在 `backend/` 执行。

## 实现入口

- Python 3.12，依赖由 `pyproject.toml` 与 `uv.lock` 管理；使用 `uv sync --locked` 安装已锁定依赖。
- `src/app/main.py` 负责服务装配与 lifespan，`api/routes/` 负责 HTTP 映射，领域服务经协议和仓储访问外部资源。
- 公共输入输出使用 Pydantic 模型或明确数据类；API 字段映射以现有路由响应模型为准，避免把内部 snake_case 直接当作前端契约。
- 金额、数量、价格、费用用 `Decimal`，持久化时间用带时区 UTC；API 错误只返回安全的 `{ code, message, details }`，不暴露上游响应、连接串或原始异常。
- 数据模型位于 `src/app/infrastructure/persistence/models/`，迁移位于 `alembic/versions/`。变更 schema 前说明影响；只新增前向迁移，不改写已应用历史、不回写冻结报告。

## 代码注释与 AI Agent 生成原则

AI Agent 新增、生成或修改后端代码时，必须把详细中文注释作为交付的一部分，审查时同时核对注释与代码的一致性。

- 每个 Python 文件（包括包入口、脚本、测试及迁移）在模块层说明职责、主要数据流和依赖边界。空包入口说明包的职责；仅导出的入口说明导出用途，不虚构执行逻辑。
- 关键类、公共函数及方法说明输入输出、前置条件、业务限制、异常或副作用。复杂私有函数同样解释关键步骤；重点说明为什么这样实现，避免把代码逐句翻译成中文。
- 金额精度、UTC 时间、冻结证据、公开源准入、模型输出校验、风险拒绝、模拟成交、事务、幂等及租约/取消等流程，应在对应代码附近解释约束和失败路径。研究结论、条件计划、交易意图和模拟执行的边界必须准确。
- 测试说明被验证的场景、替身/固定样本的作用与关键断言意图；迁移说明历史目的、兼容旧记录的方式和实际回退限制。为历史迁移补充注释不得改变修订链、SQL 或 schema 行为。
- 可添加注释的构建配置使用其原生注释语法；锁文件、严格 JSON 样本、版本标记和冻结方法文本不强行插入注释。不得为增加注释破坏格式、改变样本或方法指纹，也不得修改环境配置或凭证。
- 注释编码必须兼容实际读取器：Python 源码使用 UTF-8；当前 Windows 下 Alembic 以本地编码读取 `alembic.ini`，该文件使用 ASCII 注释，其中文解释放在本规范及 `alembic/env.py` 中。
- 优先使用 `#` 注释表达实现说明。保留现有 docstring 契约；新增或修改 docstring 时核对 FastAPI、Pydantic 等框架是否将其用于 API 文档或 schema，不能把这类变化当作无行为变化的注释调整。不要在模型 Prompt 或 SQL 字符串中加入所谓注释。
- 修改代码时同步更新过时注释；以当前实现和测试证据为准，不照抄历史设计、不描述尚未实现的保证、不包含凭证、真实账户信息或个人工具路径。
- 仅补充注释时核对可执行 token 和必要的配置值未变，并运行影响范围的检查；不能用静态注释覆盖检查替代业务回归。

## AI 与领域隔离

- 先读 [AI 维护指南](../docs/ai-maintenance.md)。研究 `agent/` 与策略 `strategy/` 是不同边界：前者生成证据化报告，后者生成 `TradeIntent`。
- `harness/` 保持受限协调层，通过注入的协议执行固定研究工作流；禁止引入模型工具循环、私有账户、模拟盘或执行服务调用。
- 模型输出必须经过确定性契约、证据引用和文本校验。不要为消除降级而直接放宽验证、伪造证据或复用旧数据冒充新采集。
- 动态 `ResearchSymbol` 需经目录准入；交易、回测、模拟盘继续遵循各自静态契约，不能全局替换 `ContractSymbol`。
- 研究币种同步 worker 在 API lifespan 中消费已排队任务，不能据此增加定时交易、自动报告生成或任意后台采集。

## 测试与验证

功能或修复先写失败的 pytest 测试。按变更范围运行聚焦测试，再完成后端质量检查：

```powershell
uv run ruff check .
uv run pyright
uv run pytest
```

`tests/conftest.py` 的 `migrated_database` 使用 `TEST_DATABASE_URL`，创建唯一临时 schema、运行迁移并清理该测试 schema。运行此类测试必须确认指向专用测试 PostgreSQL，不能指向开发业务库或生产库；不要打印配置值，也不要自行修改 `.env`。测试夹具对其临时 schema 的生命周期不授权人工清理业务数据。

缺少测试数据库时，可以运行不使用数据库的聚焦测试，但必须注明全量持久化测试未运行。迁移检查还应核对 `uv run alembic heads`，不能把静态检查通过当作迁移验证通过。

| 修改范围 | 重点回归入口（相对本目录） |
| --- | --- |
| Prompt、模型契约、重试或压缩 | `tests/agent/test_model.py`、`tests/agent/test_service.py`、`tests/security/` |
| Harness 策略、生命周期或审计 | `tests/harness/`、`tests/persistence/test_harness_audit_repository.py`、`tests/security/` |
| 研究币种、公开源与专题 | `tests/symbols/`、`tests/market/`、`tests/agent/test_factors.py`、相关 API 与持久化测试 |
| 报告字段与迁移 | 报告/API/仓储/迁移测试，以及对应前端解码与展示测试 |
| 策略、回测、风控、模拟成交 | `tests/strategy/`、`tests/research/backtests/`、`tests/risk/`、`tests/execution/`、`tests/paper_trading/` |

模型与外部 HTTP 回归优先使用固定样本和替身，测试不能依赖真实模型密钥或发起真实交易。策略相关改动另遵循根目录关于未来数据、手续费、滑点、部分成交、幂等、风控与模拟盘差异的验证要求。
