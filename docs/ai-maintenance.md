# AI 研究与 Harness 维护指南

本指南描述当前项目实现，配合[根目录规则](../AGENTS.md)、[后端约定](../backend/AGENTS.md)与[运行边界](operational-boundaries.md)使用。能力进展和未完成项见[项目状态](project-status.md)。

## 执行路径与修改入口

当前技术页面使用 [v2 交易计划书](technical-trading-plan.md)及专用后台 worker。`plan_model.py` 分开思考分析与非思考编排，`references.py` 校验引用，数字由程序按字段渲染。原始 reasoning_content 不保存或转发。下段定性投影描述保留的 v1 同步路径，综合研究不变。迁移为 0018，迁移与部署需按运行环境核验；个别真实模型成功样本不构成长期质量基准。

本节及后续重试、压缩说明描述原有综合研究。独立技术研究位于 `agent/technical/`，路径为公开行情采集 → 确定性事实与条件计划 → 受限定性模型解释 → 不可变保存，通过单独的 Harness 策略运行。它不使用综合报告的新闻图或正文压缩；技术模型显式关闭思考模式，仅接收冻结分析的定性投影与已审查方法，完整数值分析仍由确定性代码计算、保存及展示。格式校验失败最多尝试三次，纠正仅使用相同投影和白名单字段路径/错误类别，超时与上游错误直接降级。2026-10-09 经用户确认，正常定性中文不因包含中文数字字符被直接拒绝，但具体数值、数量、交易语言及引用继续校验；不替换原文。安全诊断日志为 `technical_model_response_rejected`，不记录模型原文；接口、方法指纹、迁移及测试入口见 [Skill 技术研究报告](technical-reports.md)。

研究请求经 API 与 Harness 准入后进入固定 LangGraph：采集市场 → 采集新闻 → 计算确定性市场结构 → 证据门 → 模型生成并校验保存，或保存降级报告。模型无权选择工具或改变图路径；该链路不调用策略、风控放行或模拟/真实下单。

| 关注点 | 入口 |
| --- | --- |
| 服务装配、资源和 checkpoint 生命周期 | [main.py](../backend/src/app/main.py) |
| Harness 策略、运行和审计契约 | [policy.py](../backend/src/app/harness/policy.py)、[runtime.py](../backend/src/app/harness/runtime.py)、[audit.py](../backend/src/app/harness/audit.py) |
| 图节点、研究编排与冻结证据 | [graph.py](../backend/src/app/agent/graph.py)、[service.py](../backend/src/app/agent/service.py)、[evidence.py](../backend/src/app/agent/evidence.py) |
| Prompt、模型请求、校验、重试与压缩 | [prompt.py](../backend/src/app/agent/prompt.py)、[model.py](../backend/src/app/agent/model.py) |
| 市场结构与专题事实 | [market_structure.py](../backend/src/app/agent/market_structure.py)、[factor_collection.py](../backend/src/app/agent/factor_collection.py)、[factors.py](../backend/src/app/agent/factors.py) |
| 持久化与 HTTP 诊断映射 | [report_repository.py](../backend/src/app/infrastructure/persistence/report_repository.py)、[analysis_reports.py](../backend/src/app/api/routes/analysis_reports.py) |
| 客户端契约与报告展示 | [report.ts](../frontend/src/domain/report.ts)、[报告页面](../frontend/src/features/reports/) |

## 必须保持的约束

- 模型只接收本次冻结的公开证据；引用 UUID 必须属于当前报告，专题解释必须引用对应专题证据。支撑/阻力与市场结构由确定性代码计算，模型不能改写。
- RSS 标题、摘要和其他外部文本均为不可信数据。保留新闻内容边界与转义，不能把其中的指令升级为系统指令。
- 缺失、失败、未披露、零值、历史快照是不同含义。来源故障不得用旧值冒充本次输入；ETF 日期、暂定值与回填限制见[专题说明](report-factors.md)。
- 研究目录准入不授权交易。新增币种不得扩大静态交易契约；新增来源也不得增加模型工具或私有账户权限。
- 报告、证据及 Harness 审计保持可关联与不可变。持久化变更需说明迁移、旧报告读取及失败处理，不修改已保存的模型结果来伪造成功。

## 模型修改与诊断

当前使用受限 DeepSeek JSON 格式化器。允许的模型配置在 `AppSettings` 中；密钥缺失时不发模型请求，产生可审计的降级结果。配置值与凭证不得打印。

当前格式校验最多尝试三次（包含首次请求），仅 `model_invalid_response` 进入格式纠正；超时或上游错误直接交给降级路径。纠正提示使用有界的字段路径、错误类别和长度信息，不拼接原始错误响应。

正文长度校验与 Prompt 的目标长度有不同用途；当前校验区间为 1100–2500 字符。超长候选先尝试按完整句子压缩，再通过同一验证链。修改此逻辑时不能截断价格、数字或句子，也不能跳过证据和交易语言校验。实际限制以 `model.py` 为准，修改常量时同步更新本段与测试。

排障先看报告的 `validationFailure`（尝试次数、问题数、字段路径、错误类别），再按运行标识关联安全日志。相关事件包括 `agent_research_started/completed/failed`、`agent_model_response_rejected`、`agent_model_format_retry_started/completed` 和 `agent_model_narrative_compacted`。只记录白名单元数据，不输出完整 Prompt、模型原文、新闻全文、证据载荷或密钥。

改动报告字段时同时核对 Prompt 示例、Pydantic 模型、最终验证、持久化映射、API 响应、前端 schema 与展示。不能只改 Prompt 就认定新契约已经生效。

## 回归清单

现有测试与样本是起点，无需为日常验证调用真实付费模型。以下命令在 `backend/` 执行，不包含依赖 PostgreSQL 的持久化验收：

```powershell
uv run pytest tests/agent tests/harness tests/security
```

| 场景 | 当前主要验证入口 |
| --- | --- |
| 合法中文双周期 JSON、枚举与无工具请求 | `tests/agent/test_model.py` |
| 缺失密钥、无效 JSON、超时、有限重试与安全日志 | `tests/agent/test_model.py`、`tests/agent/test_service.py` |
| 伪造证据 ID、错误专题引用、新闻边界和交易操作语言 | `tests/agent/test_model.py`、`tests/agent/test_factors.py`、`tests/security/` |
| 超长/不足正文、压缩不截断数值 | `tests/agent/test_model.py` |
| 准入拒绝、Harness 生命周期及审计关联 | `tests/harness/`，数据库部分另见 `tests/persistence/test_harness_audit_repository.py` |
| 报告保存、旧报告兼容和诊断展示 | `tests/persistence/test_agent_research_repository.py`、`tests/api/test_agent_analysis_reports.py`，以及前端报告测试 |

修改数据源或专题时还需运行相应 `tests/market/`、`tests/news/`、`tests/symbols/`。新增 schema 或报告字段需要专用测试数据库与前后端联验；聚焦测试不替代这些检查。

后续若建立固定样本评估集，应复用 `tests/fixtures/agent/` 中可审查的样本，记录 Prompt/模型/契约版本及证据覆盖、格式通过、降级和引用正确性。该评估集与真实模型质量基准目前属于待补充工作，不能把替身单元测试通过等同于模型质量已获验证。
