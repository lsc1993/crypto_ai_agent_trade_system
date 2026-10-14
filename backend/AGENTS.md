# 后端开发约定

本文件补充[根目录规则](../AGENTS.md)，不放宽其中的安全边界。命令均在 `backend/` 执行。

## 实现入口

- Python 3.12，依赖由 `pyproject.toml` 与 `uv.lock` 管理；使用 `uv sync --locked` 安装已锁定依赖。
- `src/app/main.py` 负责服务装配与 lifespan，`api/routes/` 负责 HTTP 映射，领域服务经协议和仓储访问外部资源。
- 公共输入输出使用 Pydantic 模型或明确数据类；API 字段映射以现有路由响应模型为准，避免把内部 snake_case 直接当作前端契约。
- 金额、数量、价格、费用用 `Decimal`，持久化时间用带时区 UTC；API 错误只返回安全的 `{ code, message, details }`，不暴露上游响应、连接串或原始异常。
- 数据模型位于 `src/app/infrastructure/persistence/models/`，迁移位于 `alembic/versions/`。变更 schema 前说明影响；只新增前向迁移，不改写已应用历史、不回写冻结报告。

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
