# 实盘手动计划 Agent：实施契约清单

- 版本：1.1；日期：2026-11-06；状态：开发计划的接口约定。执行状态（2026-11-09）：T00 已复审通过并合并；T01 已实现 C1/C2 的公共类型、策略目录与评估器适配，首轮正式审查不通过后完成并发幂等、嵌套快照重验和根 Schema 校验修复，经原审查助手复审通过（`reviewed_tip=159a43b`）并合并到 `main`；T02 已实现 C2 的 `KnowledgeIndex`/`KnowledgeService`、关键词分块/评分、GIN SQL 索引和 `0020_research_knowledge` 迁移，首轮独立审查判定 P1/P2 不通过，修复提交 `8835a1d` 补充分块 INSERT 防护、发布/检索一致性校验和锁后时间采样，聚焦 40、阶段回归 136、后端 full 1089 passed 全绿，经原审查助手复审通过（`reviewed_tip=8835a1d`）并合并到 `main`；T03 已实现 C3 本地资料/政策/成本/保证金/公开规则快照、单池 generation 与 `0021_planning_inputs` 迁移；首轮审查 4 项 P2 不通过后，修复提交 `4f0e7ae` 补齐冷却显式状态、规则刷新带锁重放、来源抓取时间和网关异常转换，聚焦 20 纯契约 + 12 SQL、阶段回归 176、后端 full 1121 passed，自测 `verified`，当前为 `awaiting_review`；其余接口尚未实现。
- 主计划：[实施任务与验证](2026-11-06-manual-trading-agent-implementation.md)。
- 依据：[需求 v2.0](../specs/2026-11-06-manual-trading-agent-requirements.md)、[架构 v2.0](../specs/2026-11-06-manual-trading-agent-design.md)。

本文固定跨任务命名、类型、存储和技术选择，避免实现者分别发明接口。本文中的新路径除 T00 已迁移的 `app/governance/` 外均为待创建路径；旧 `app/harness/` 包已移除。签名省略方法体，字段清单不是完整生产代码。

## C1. 公共类型与输入

`backend/src/app/shared/agent_types.py` 定义以下不可变 Pydantic 类型，统一 `extra="forbid"`；不依赖 Agent、SQLAlchemy 或交易执行。

| 类型 | 固定字段与约束 |
| --- | --- |
| `VersionRef` | `version_id: UUID`、`sha256: str`（64 位小写十六进制）；指向不可变版本 |
| `ArtifactRef` | `artifact_id: UUID`、`sha256: str`；只作引用，不内嵌完整财务载荷 |
| `ProductKey` | `venue: Literal["binance_usdm"]`、`symbol: ResearchSymbol`、`settlement: Literal["USDT"]`、`kind: Literal["linear_perpetual"]` |
| `UtcDateTime` | 复用当前 `market/contracts.py` 的 UTC 类型；请求中的未来观测时刻不得冒充真实观测 |
| `DecimalText` | API 十进制字符串；不接受 JSON number、NaN/Infinity、指数形式，最多 30 位整数和 18 位小数；超范围拒绝，不截断；内部用 Decimal |
| `PageQuery / VersionPage[ItemT]` | page/page_size（默认 1/20、page_size 最大 100）；items/page/page_size/total，HTTP 通过别名输出 pageSize，不改旧 API 的 page_size 线协议 |

`agent_runs/contracts.py` 的 `RunInput`：`request_id: UUID`、`thread_id: UUID | None`、`parent_run_id: UUID | None`、`product: ProductKey`、`timeframes: tuple[MarketTimeframe, ...]`、`goal: str`（1–2000 字符）、`strategy: VersionRef`、`parameters: dict[str, JsonValue]`（所选参数 Schema 校验）、`planning: PlanningRefs | None`、`analysis_mode: Literal["current","historical"]`、`as_of: UtcDateTime | None`、`budget_profile: Literal["standard"]`。MarketTimeframe 复用现有 market/contracts.py。工作台身份由服务端提供；历史模式没有可证明的历史来源时拒绝，永不标为当前可实施计划。

单用户默认工作台标识固定为 `uuid5(NAMESPACE_URL, "crypto-ai-agent/local-workspace/v1")`，由服务端装配注入，重启不重新随机生成。测试可注入不同工作台验证隔离，浏览器不能指定该值获权；此公开常量不是认证凭据。

`PlanningRefs` 定义于 `trade_planning/inputs.py`：`profile`、`policy`、`venue_rules`、`costs` 均为 `VersionRef`，另有 `pool_id: UUID`、`pool_generation: int`。可缺资料时整个字段为 None，先形成待补项；不能用零值替代。提交指纹包含原请求，首次解析后的有效输入另存；相同请求键重试先查原映射，不重新解析“最新版本”。

## C2. 策略与知识

| 类型及定义位置 | 字段 / 行为 |
| --- | --- |
| `StrategyVersion`，`research/strategies/contracts.py` | `ref: VersionRef`、稳定 `strategy_id`、名称/方法文本、`kind: single/composite`、组成版本/角色/参数、组合及冲突规则引用、参数 Schema、支持范围/周期/预热、`evaluator_id`、能力集合、发布时间与停用状态 |
| `PriceCandidate`，同上 | 候选稳定指纹、所选包/组成/参数/评估器版本、证据引用、方向、入场带/触发/止损/目标、有效期和适用条件；`price_rounding: strict/conservative_one_tick`；价格 Decimal，不能内含资金、数量或 TradeIntent |
| `StrategyEvaluation`，同上 | `strategy_ref: VersionRef`、参数/评估器及证据指纹、适用性、确定性事实、`candidates: tuple[PriceCandidate, ...]`、有限原因码；即使无候选也保留所选版本绑定，无评估器和无候选分开 |
| `KnowledgeVersion`，`research/knowledge/contracts.py` | 文档/版本/来源、原文指纹、适用范围、权限、首次导入/可证明可得时间、用户声明发布时间、状态；版本正文不可变 |
| `KnowledgeQuery / KnowledgeHit`，同上 | 查询文本、范围/截至/权限过滤；命中文档/版本/块、原文片段、来源/时间/指纹和整数分数 |

```python
# research/strategies/ports.py
class StrategyCatalog(Protocol):
    async def get_published(self, workspace_id: UUID, ref: VersionRef) -> StrategyVersion: ...
    async def publish(self, workspace_id: UUID, draft_id: UUID, *, expected_version: int,
                      request_id: UUID) -> StrategyVersion: ...

class StrategyEvaluator(Protocol):
    evaluator_id: str
    async def evaluate(self, strategy: StrategyVersion, parameters: dict[str, JsonValue],
                       evidence: EvidenceEpoch) -> StrategyEvaluation: ...

# research/knowledge/ports.py
class KnowledgeIndex(Protocol):
    async def import_text(self, workspace_id: UUID, draft: KnowledgeImport,
                          *, request_id: UUID) -> KnowledgeVersion: ...
    async def search(self, workspace_id: UUID, query: KnowledgeQuery) -> tuple[KnowledgeHit, ...]: ...
```

补齐管理端口：StrategyCatalog 另提供 async `create_draft(workspace_id: UUID, draft: StrategyDraft, *, request_id: UUID) -> StrategyDraft`、`update_draft(workspace_id: UUID, draft_id: UUID, draft: StrategyDraft, *, expected_version: int, request_id: UUID) -> StrategyDraft`、`list_versions(workspace_id: UUID, query: PageQuery) -> VersionPage[StrategyVersion]`、`archive(workspace_id: UUID, strategy_id: UUID, *, expected_version: int, request_id: UUID) -> None`。StrategyDraft 按 StrategyVersion 的可编辑字段及 draft_id/state_version 定义，不允许客户端赋 evaluator 实现或 published 状态。KnowledgeIndex 另提供 async `list_versions(workspace_id: UUID, query: PageQuery) -> VersionPage[KnowledgeVersion]`、`publish(workspace_id: UUID, ref: VersionRef, *, expected_version: int, request_id: UUID) -> KnowledgeVersion`、`archive(workspace_id: UUID, document_id: UUID, *, expected_version: int, request_id: UUID) -> None`。import_text 先创建不可变 draft 版本，发布后检索可见；KnowledgeImport 可携 document_id 导入新版本，不回写旧文。

`KnowledgeImport` 在同目录 contracts 中定义：标题、UTF-8 文本、来源说明、适用范围和可选声明发布时间；不接收 URL 抓取目标或本地文件路径。最大 256 KiB。原文按 1000 Unicode 字符分块、重叠 100；NFKC、小写英文词及中文双字词用于索引，不改原文。查询最多 64 个去重词项；SQL 先过滤范围/状态/时间/权限，用 GIN `text[]` 交集召回。评分固定为 `4 * 标题匹配词数 + 正文匹配词数`；同分按版本 UUID、块序号排序，最多返回 6 块；分数不称概率。用户声明的早期发布时间不能覆盖服务端首次可得记录。

已有规则适配器使用 `calculate_technical_analysis()` 的合法候选几何与状态，候选标识按内容/策略/证据哈希生成。该规则已有固定研究成本门槛，保留为此评估器的已知限制；实盘规划重新计算成本，不把旧费率当用户费率，也不假装该适配器等价于未来策略。合成组合评估器只在测试注册，生产不自动发布虚构组合。

已有规则适配器可明确声明 conservative_one_tick：结构保护向外、目标向内的幅度不超过一个产品 tick，且取整后几何/策略门槛仍成立；超出即拒绝。其他新策略默认 strict，只有用户规则及对应评估器明确支持才允许该容差，不借容差移动结构来弥补风险不合格。

## C3. 本地财务输入与产品规则

`trade_planning/inputs.py` 定义：

| 类型 | 必需内容 |
| --- | --- |
| `PlanningProfileSnapshot` | 资料 ref、pool/generation、USDT 规划资金/可用保证金/剩余单日与组合风险、已有仓位/挂单风险及资金占用、当日损益资料日期、冷却状态/截止时间、熔断状态、杠杆/保证金及持仓模式、`costs_ref: VersionRef \| None`、`margin_evidence: MarginEvidence \| None`、声明时间/有效期；未知显式为 None。冷却状态必须显式：未知不完整，`none` 不得携带截止时间，`active` 必须有晚于声明时间的截止时间 |
| `PlanningRiskPolicy` | 用户确认的单笔风险额、最大名义额/数量/杠杆、最小净盈亏比、日损与组合约束、止损强制要求、冷却/熔断规则，全部版本化；无默认金额、比例或杠杆，不读取模拟盘 RiskConfig |
| `VenueRuleSnapshot` | ProductKey、合约乘数/数量单位、PRICE_FILTER/LOT_SIZE/MARKET_LOT_SIZE/MIN_NOTIONAL 等适用过滤器、交易状态、订单/触发/有效期支持、规则时刻/来源/有效期；缺项不可用，不能只看 pricePrecision/quantityPrecision |
| `CostAssumptions` | 入场/止损/目标退出费率、滑点/价差与持有成本情景及上界、来源/声明/有效期；同一项不得在成交价和附加费重复计入 |
| `MarginEvidence` | 逐仓模式、声明杠杆、适用名义额/维持保证金档位或交易所界面预览、保证金需求/强平参考/触发价基准、来源和有效期；用户资料标 user_declared，不能伪装公共 API 已核实 |

首批支持目录只发布 BTCUSDT、ETHUSDT 的 Binance USDT 线性永续、逐仓、新入场；这只是实施起点，不更改研究目录或模拟盘契约。反向、全仓、多资产、同品种已有仓位/挂单合并以及不支持订单模式明确阻断。新增规划产品需规则与回归证据，不能从研究准入自动加入。

初始资料有效期 15 分钟、公开规则快照 60 分钟、费用/保证金资料取用户声明有效期与 15 分钟的较早者；均不得超过各自来源有效期。用于采纳/重验的报价最多 60 秒，已收盘序列覆盖最新所需周期。上述时效是本计划的保守初值，不代表市场长期稳定。UTC 跨日后单日剩余额度必须重新声明；不按新的一天自动恢复资金或释放未知占用。

公开规则适配器放在 `infrastructure/market_rules/binance_usdm.py`，复用受控公开 HTTP 边界。当前 `market/binance_usdm.py:get_exchange_info()` 仅返回六个准入字段，不能直接作实盘过滤器来源。新增有类型的规则读取端口与固定 `/fapi/v1/exchangeInfo` 解析，旧方法行为兼容；不使用签名或私有档位接口。公开网关缓存命中必须沿用首次 HTTP 抓取时刻，规则快照的 60 分钟有效期按来源时间计算；网关类型化异常在规则适配器边界转换为 `planning_rule_unavailable`。字段与模式支持必须在发布前只读复核现行官方说明。

`PlanningInputService.create_profile(workspace_id: UUID, draft: PlanningProfileDraft, *, request_id: UUID, expected_generation: int) -> PlanningProfileSnapshot` 与 `create_policy(workspace_id: UUID, draft: PlanningRiskPolicyDraft, *, request_id: UUID, expected_generation: int) -> PlanningRiskPolicy` 为 async；两个 Draft 位于 inputs.py，字段按上表，缺失资料明确保留。补录与某候选/数量/模式绑定的 MarginEvidence 也创建新 profile 版本，重验生成待审新材料；不把旧预览套用到变化数量。资料、政策、规则和成本齐备后由服务端 `resolve_refs(workspace_id: UUID) -> PlanningRefs | None` 组合引用，不要求创建一份不完整 profile 就返回完整 PlanningRefs。

PlanningProfileDraft 可带 `costs: CostAssumptionsDraft | None`，草稿按 CostAssumptions 字段填写；服务在同一事务创建不可变成本版本并关联 profile.costs_ref，不另造外部费率接口。所选 profile 中的成本可更新为新 profile/成本版本，绝不回写已审计划。resolve_refs 只组合当时同池的当前合法版本，并保留其 generation。

## C4. 任务、租约与单次提交

`agent_runs/contracts.py` 定义 `RunStatus`：queued/running/waiting_input/waiting_approval/completed/degraded/failed/cancelled/expired。终态不可重开。`RunSnapshot` 包含身份、不可变修订输入、状态号、received/applied 消息水位、当前待办、结果引用及质量；完整财务值不内嵌。

`agent_runs/segments.py` 定义：

| 类型 | 字段 |
| --- | --- |
| `RunFence` | workspace_id、run_id、revision、segment_id、owner、lease_epoch |
| `ExecutionContext` | fence、策略/工具/政策版本、授权和预算引用、证据 epoch；只能服务端构造 |
| `SegmentOutcome` | `kind: wait_input/wait_approval/completed/degraded/failed/cancelled`、产物引用、preparing 待办引用、安全原因、applied_message_seq、可选计划采纳提案 |
| `CompletionDecision` | committed/conflict/lease_lost/messages_pending、已提交状态号及安全原因；不接受模型自报成功 |

以上纯类型在 T05 建立。计划采纳提案类型 `PlanAdoptionProposal` 同样位于 segments.py，只含 plan_ref、interaction_id、material_hash、pool_id/generation，不导入尚未实现的规划服务；T13 才由 coordinator 核对并应用。T04 首先建立业务行的 owner/lease_epoch/lease_expires_at 字段及状态一致约束，T07 再实现实际领取与片段存储，避免预算任务依赖尚不存在的租约字段。

```python
# agent_runs/ports.py
class AgentRunRepository(Protocol):
    async def enqueue(self, workspace_id: UUID, data: RunInput) -> RunSnapshot: ...
    async def get(self, workspace_id: UUID, run_id: UUID) -> RunSnapshot | None: ...
    async def claim(self, owner: UUID) -> ExecutionContext | None: ...
    async def heartbeat(self, fence: RunFence) -> bool: ...
    async def recover_expired(self) -> int: ...

class SegmentRepository(Protocol):
    async def commit(self, fence: RunFence, outcome: SegmentOutcome) -> CompletionDecision: ...

# agent/interactive/ports.py
class SegmentRunner(Protocol):
    async def run(self, context: ExecutionContext) -> SegmentOutcome: ...
```

租约 30 秒、10 秒心跳；领取/续租/写入在行锁后读数据库 `clock_timestamp()`，不以客户端 now 或事务开始时钟证明合法。队列可运行上限 20，工作台等待上限 100；容量在专用队列锁内检查；唯一 `(workspace_id, request_id)`，不按 symbol 合并。

`SqlAlchemyAgentCommitCoordinator` 是 `SegmentRepository` 的实现，也是新片段审计端口的事务所有者：业务状态、pending 待办、片段、合法 Harness 终态、事件、owner 释放及适用的计划采纳/资金池占用在同一事务提交。带池操作按 pool → run → interaction/plan 取锁；非池事务不能持 run 锁后再取池锁。不可变草案可先保存，但保存本身不产生业务完成。

治理内核的新类别为 interactive_planning，旧序列化值及 harness_* 存储保留。每片段独立治理 run；正常等待只表示片段结束。异常审计序号 3 也通过带 fence 的 coordinator，不使用旧无租约追加路径。回收器只对已有 started 前缀追加合法失败序号 3；缺前缀者保留中断事实，不伪造 requested/authorized/started。

LangGraph 每片段 namespace 为 `ir:<run_id>:<revision>:<segment_id>`。人工待办先 preparing，图 END 并完成 saver 写入后才原子发布 pending、释放 owner。反馈后新片段从业务日志恢复，不保留模型协程、不重读失租片段作为权威；业务服务不另造模型循环。

## C5. 用量、尝试、反馈与上下文

| 类型 / 所在文件 | 固定字段与接口 |
| --- | --- |
| `AttemptRequest / StepAttempt`，`agent_runs/attempts.py` | 逻辑 step_id、attempt_id、动作序号、输入指纹、类别 model/tool/transport、最大预留、prepared/in_flight/succeeded/failed/unknown、已校验结果引用和用量 |
| `BudgetLedger`，`agent_runs/budget.py` | `async reserve(fence: RunFence, request: AttemptRequest) -> StepAttempt`；`async mark_sent(fence, attempt_id) -> None`；`async settle(fence, attempt_id, result: AttemptResult) -> None`。`AttemptResult` 同目录包含状态、结果引用、已知 usage 或 unknown、供应商回执与固定原因 |
| `HumanInteraction / InteractionResponse`，`agent_runs/interactions.py` | interaction_id、run/revision、动作/差异、material_hash、state_version、expires_at、preparing/pending/answered/applied/expired；响应 request_id、expected_state_version、reviewed_payload_hash、approve/reject/request_changes/provide_input 及类型化修改 |
| `InteractionService`，同上 | `async respond(workspace_id: UUID, run_id: UUID, response: InteractionResponse) -> FeedbackReceipt`；receipt 明确 recorded/applied，不提前宣称计划已采纳 |
| `MessageService`，`agent_runs/messages.py` | `async record(workspace_id: UUID, run_id: UUID, message: UserMessage) -> MessageReceipt`；消息有 request_id、文本/类型化资料引用、单调 seq，received 与 applied 分开 |
| `EvidenceEpoch`，`research/evidence.py` | 截至/封存时间、逐项来源/observed/available/fetched 时间、版本/指纹/质量、内容引用；纯研究契约；`agent_runs/evidence.py` 负责冻结服务，刷新当前资料不能冒充旧历史时点 |
| `ContextManifest / ModelContext`，`agent/interactive/context.py` | 精确策略/资料引用、事实及知识/观察引用、已应用消息水位、Prompt/Schema/工具版本、各块长度、省略理由；模型投影无原始财务值 |

`ContextBuilder.build(context: ExecutionContext, evidence: EvidenceEpoch, *, applied_seq: int) -> ModelContext` 为 async 方法。返回字段固定为 `messages`（校验后的供应商中立消息序列）、`tools`（已授权 Schema）、`manifest`、`input_reservation`。调用前再检查当前任务/取消/目录及资料代次；重建历史保留完整 assistant tool-call 与 tool result 配对，不能插入未发生过的工具调用。

预算初始值逐字落实设计：模型 8 次，工具 12 次（预留 2 次供终态前核验），并发 1，单输入 16384，单输出 4096，累计输入/输出 98304/32768，模型超时 60 秒，活动时间 600 秒，外部传输 64 次，安全收尾至少 15 秒。每个逻辑调用最多 2 次已知可重试尝试；格式纠错也计模型总额，SDK 隐藏重试关闭或逐次记账。追加授权硬上限为模型 32、工具 48、输入/输出各初始四倍、活动 1800 秒、传输 256，绝不增加交易资金。

没有可靠计数器时，按最终 UTF-8 JSON 请求字节数加 4096 包络作为保守输入预留，显式标为估算，协议/工具 Schema 也计入；回执 usage 另记真实 Token。无法证明额外推理计费上界的模式不启用。unknown 保留最坏预留，不把重试、修订或恢复当预算清零；恢复不自动重放未知付费请求。初版模型适配显式关闭供应商 thinking 模式，仍提供可审计行动摘要；不保存原始隐藏推理。

## C6. 工具、模型及 MCP

`agent/interactive/tools/contracts.py` 定义 `RegisteredTool`（id/version、输入输出 Schema 指纹、能力/范围、超时/大小）、`ToolRequest`（name/arguments/供应商 call_id）、`ToolObservation`（工具/step/attempt、结果引用、安全摘要、质量/原因）；`GuardDecision`（allow/clarify/approve/reject）由 T06 在 agent_runs/decisions.py 定义并导入复用，不重复建第二种裁决类型。

`ToolGateway.call(context: ExecutionContext, request: ToolRequest) -> ToolObservation` 为 async；顺序是权限/版本 → Schema/范围/时间 → 原子预算预留与步骤落盘 → 实际发送 → 结果 Schema/来源/大小/时效 → 观察及结算 → 安全投影。治理内核不路由工具。七个固定工具名沿用设计 §8.1；build_manual_trade_plan 只接受候选和资料引用，不接受模型指定的最终数量或金额。

`agent/interactive/model_port.py` 定义 `ModelDecision = ToolBatch | ControlProposal | FinalAnalysis`，模型端口 `async decide(context: ModelContext) -> ModelDecision`。ToolBatch 包含 `calls: tuple[ToolRequest, ...]`、安全摘要，最多 4 项，逐一串行守卫，不因此增加并发；未执行项返回明确 not_executed 观察。ControlProposal 从 agent_runs/decisions.py 导入，字段为类型化动作类别、差异、材料引用和安全原因。FinalAnalysis 包含 `market_blocks: tuple[ClaimBlock, ...]`、`decision_blocks`、`selected_candidate_id: str | None`、`plan_ref: ArtifactRef | None`、`no_plan_reasons: tuple[str, ...]`、限制与安全摘要；ClaimBlock 在同文件定义为定性 text、evidence_ids、fact_refs（目标角色+事实 id），价格/数值只引用程序事实。控制提案与最终分析均不直接批准权限或提交业务。模型配置记录 requested/returned model、Prompt/Schema/工具指纹，不暗中切换供应商。

T11 在同一 model_port.py 定义 `AnalysisArtifactStager(Protocol)`：`async validate_and_stage(context: ExecutionContext, analysis: FinalAnalysis) -> tuple[ArtifactRef, ...]`。GraphDependencies 只消费此协议，T14 的 ArtifactService 才提供生产实现；T11 测试不导入尚不存在的 reports/interactive.py 或实际规划服务。替身用于证明图路由与提交边界，不代表生产产物校验已交付。

预计新增顶层生产依赖为 `mcp==2.3.0`（不加 cli/rich extras）与适配器直接使用的 `httpx2>=2.10.0,<3`，锁定完整传递依赖；2026-11-06 官方元数据列出 Python >=3.10、httpx2、mcp-types 等。本地已有 Python 3.12、Pydantic 2.13.4，静态版本范围可相容，实际锁定/类型/运行兼容必须在 T10 验证；本轮未安装或做依赖求解，不宣称依赖已验收。httpx2 只限 MCP 适配器，现有 httpx 0.28.1 继续服务公开源和模型；不升级 LangGraph 1.2.10、checkpoint-postgres 3.1.2 或 langchain-core 1.5.3。

核心装配提供同进程的只读 MCPServer，挂载 `/internal/agent-mcp/mcp`，只公开 read_strategy_definition。它由固定 loopback HTTP 客户端访问，使用进程启动时产生的内部凭据；浏览器不获该值。生产仍是同一 API 进程，无新增 Compose 服务；测试必须真实 TCP 调用，内存 transport 只能作单元测试。外部服务不默认登记，不支持 stdio、自选 URL/命令、sampling、roots、动态 elicitation 或远端自扩权。

`infrastructure/mcp/client.py:McpToolClient.call(context, request) -> ToolObservation` 使用官方 `Client` 和 Streamable HTTP，登记端点/协议/Schema 指纹固定。选择本地服务支持的 2026-07-28 协议，协商或版本检查失败明确不可用。自有 httpx2 transport 在 SDK 前拦截所有 3xx、未登记目标、超额传输及超过 64 KiB 的 JSON/SSE 消息；模型摘要最多 8 KiB。SDK 自身可能处理同源重定向，不能仅靠 follow_redirects=False。每个实际 HTTP 请求仍记账，关闭自动重连/重试或由 transport 次次限制；未通过此测试不登记工具。

`infrastructure/mcp/server.py` 使用 `MCPServer.streamable_http_app()`，宿主 lifespan 显式管理 session_manager。启动不主动调用尚未监听的本机 HTTP；消费者在服务可接收请求后再连接，有界失败后报告不可用。关闭顺序为停止/等待 worker → 关闭客户端与 MCP manager → 数据库/模型资源；无凭据日志、默认遥测导出或后台发现。

## C7. 确定性规划、产物与占用

`trade_planning/contracts.py` 定义 `PlanningRequest`：合法 PriceCandidate、精确策略 ref、PlanningRefs，以及解析并核对指纹后的 `profile: PlanningProfileSnapshot`、`policy: PlanningRiskPolicy`、`rules: VenueRuleSnapshot`、`costs: CostAssumptions`、当前公开报价引用/时刻、订单操作选择；MarginEvidence 从 profile 中读取。纯函数接收完整已解析数据，不通过引用自行查库。`SizingResult`：Decimal 数量/名义额/保证金/止损路径风险/目标情景净收益/净盈亏比与计算版本；`ValidationCheck`：name/required/pass-fail-unknown/basis/source/time/material_hash/expires_at/reason_code。

```python
# trade_planning/sizing.py：纯函数，无网络/LLM
def calculate_size(request: PlanningRequest) -> SizingResult: ...

# trade_planning/service.py
class ManualPlanningService:
    async def build(self, context: ExecutionContext, candidate_id: str,
                    refs: PlanningRefs) -> PlanningResult: ...
    async def revalidate(self, context: ExecutionContext,
                         plan_ref: ArtifactRef) -> PlanningResult: ...
```

`PlanningResult` 在同目录 contracts 定义，含不可变 `ManualTradePlan`、checks、建议 readiness、`ModelPlanProjection`；不直接生效采纳。计划包括品种/策略/来源/输入版本、订单/触发/有效期、方向/价格/数量单位、资金/保证金/成本/风险/退出分配、失效/部分成交/未成交/跳价分支与人工清单。模型投影仅含引用、公开候选、检查状态/原因，不含原始财务值；完整 `ManualPlanView` 仅所属工作台受限读取。

线性产品计算固定为：合约乘数 m；方向允许入场范围中最不利价 e；止损 s；目标 t；分别计算含适用费用/滑点/持有成本的单单位止损路径损失 L 和目标路径净收益 W。风险额度 R 取用户政策与资料允许的单笔/日损剩余/组合剩余最小值；初步数量上限同时考虑 R/L、名义额、数量、可用保证金及产品档位。对步长向下取整后重新算 L*q、W*q、净盈亏比、保证金/强平核对及所有过滤器；不可把最小订单冲突修成向上加量。未知关键资料、非正 L/W、不满足用户最小净盈亏比则阻断。

价格离散化采用允许区间内的 tick 格点：下界 ceil、上界 floor；止损和目标只有所选评估器声明允许的价位容差才可向保守风险方向取整（多单止损向下/目标向下，空单止损向上/目标向上），取整后重新验证策略几何及全部风险。无合法格点/容差则阻断，不偷偷移动结构。市场入场只在有明确最大不利成交价及滑点界时支持；否则提示改为受限价条件，不能生成无价格边界的可实施清单。

首期退出分配默认单一全量目标和全量保护止损；若用户策略包提供分批方案，只有各批 step/最小额/总量和保护覆盖全部通过才可用。不是所有订单组合都自动支持；所需交易所界面/触发方式不在规则档案时阻断。保证金或强平资料不足不能用简式替代，user_declared 只能表示用户资料已校验一致，不表示系统核实账户。

Readiness 固定为 draft/needs_inputs/blocked/ready_for_review/ready_for_manual_execution/needs_revalidation/expired。必需检查全部 pass 且有效、当前资料代次合法、用户采纳和单池占用同时成立才可实施；报告质量、任务完成与其独立。读取时按服务器时刻和当前池代次派生状态，不靠一个永久 true 字段。

`trade_planning/ports.py:ManualPlanRepository` 提供 async `stage(fence: RunFence, plan: ManualTradePlan, checks: tuple[ValidationCheck, ...]) -> ArtifactRef` 与 `read(workspace_id: UUID, plan_id: UUID) -> ManualPlanView | None`；草案写入也检查 fence，采纳/池占用仍只由 coordinator 原子应用。ManualPlanView 带 serverNow、checkedAt/expiresAt 与来源；浏览器用服务端参考时间和接收后的经过时间判断过期，后台页重新可见时重新读取，不让设备时钟偏差维持旧可实施标记。清单导出选 UTF-8 Markdown，使用固定模板和 UUID/版本文件名，保留有效期/依据/人工分支，不输出交易所可提交请求。

`PlanCommitment` 状态为 active/unresolved/resolved_to_declaration/released_unexecuted，前两者占用唯一槽。计划有稳定 plan_id 与不可变 artifact 版本；同一计划的合法重验复用占用槽，只更新核验关联，不误判为第二计划；新版本替代已采纳入场参数前须确认旧入场未实施/无挂单或按新资料承接处理。每工作台固定一逻辑池；未知执行/到期不释放。新资料、政策、用户报告推进 generation，旧核验失效；完整资料承接已有仓位/挂单或用户声明未执行且无挂单后才可处理占用，追加依据不覆盖历史。已报告实施的旧计划不再作为新入场清单。

`ExecutionFeedback` 定义于 `trade_planning/feedback.py`：计划 ref、request_id、expected_version、user_reported、是否实施、成交/退出数量/价/费/时间与已知/未知标签、偏差；不含账户身份或凭证。`FeedbackService.record(workspace_id, feedback) -> FeedbackReceipt` 为 async；缺退出/费用时净收益为 None，不把未知当零；只对完整闭合样本计算成本后表现，部分成交保留剩余风险，手工反馈不自动发给模型或进入 RAG。

## C8. API 与本地访问

新 API 统一 `/api/v1`、camelCase、分页 `{items,page,pageSize,total}`、安全错误 `{code,message,details}`。所有新资源读取均校验本地会话/工作台，写入再验证 Origin 和 CSRF。浏览器 session 为随机 HttpOnly、SameSite=Strict cookie（HTTPS 才 Secure）；CSRF 为绑定会话的随机值，通过同源 bootstrap 获取，仅内存使用；有效期 8 小时、进程重启重新建立本地会话但工作台/持久任务不丢失。首期 API 单进程、一个任务消费者，不部署多进程负载均衡。这里没有用户密码登录或多用户隔离。bootstrap 也验证精确来源/Host，跨站无 Origin 写入默认拒绝；内部 MCP 用独立服务凭据，不能复用浏览器会话。

当前全局 CORS 的 allow_credentials=False 保持不变。新 Agent 浏览器请求固定走同源 `/api/v1`，不复用旧配置中的跨源报告 URL；开发/preview 由受控 Vite `/api` proxy 转发（默认后端 8000，HTTP 验收只注入本次专属端口），部署沿用 Nginx 同源入口。新客户端使用 credentials=same-origin，旧 API/分页解析器不改；新 Zod page Schema 解 camelCase pageSize，不误用旧 createWirePageSchema。SSE 响应带 `X-Accel-Buffering: no`，由真实代理旅程验证无缓冲等待；不为此全局开放 credential CORS。

| 路径 | 请求 / 响应 |
| --- | --- |
| `GET /agent-capabilities` | 开关/模型/MCP/规划支持与不可用原因；monitoring=false；不回显配置值 |
| `POST /agent-session` | 同源空请求 → 会话 cookie、csrfToken、expiresAt；不授予订单权限 |
| `POST /agent-runs` | RunInput → 202 RunSnapshot；同键冲突 409 |
| `GET /agent-runs`、`/{id}`、`/{id}/artifacts` | 分页/单任务/安全报告与计划引用，不内嵌原始财务输入 |
| `GET/POST /agent-runs/{id}/messages`、`POST /{id}/interactions/{itemId}/responses`、`POST /{id}/cancel` | messages GET 分页重读用户上下文/处理水位，POST 类型化输入 → received/recorded、当前状态号；取消不能取消交易所订单 |
| `GET /agent-runs/{id}/interactions`、`/{id}/events?after={seq}` | 待办与事件分页；Accept:text/event-stream 时 SSE，id=seq；先补拉后订阅 |
| `/research-strategies`、`/research-knowledge` | GET 列表/详情，POST 草稿/导入；`/{id}/versions` 发布、`/{id}/archive` 停用、`/search` 检索预览；写操作 requestId + expectedVersion |
| `/planning-profiles`、`/planning-risk-policies` | GET 本地受限视图，POST 新不可变版本；风险政策修改显示前后差异；不改变模拟盘配置 |
| `GET /manual-plans/{id}`、`/{id}/checklist` | 授权完整视图和人工清单；导出保留时间/到期/来源；不得返回可提交的交易所请求 |
| `POST /manual-plans/{id}/revalidations` | requestId + expectedVersion → 202 关联新任务，不重开旧运行 |
| `/manual-plans/{id}/execution-feedback`、`/{id}/commitment-resolutions` | GET 历史，POST 用户报告/占用处理 → receipt；无私有账户请求或自动撤改 |

审核默认 AP-01 至 AP-07 全部沿用，监控未交付时 AP-07 不可启用。pending 最多一项，普通工具不逐次询问。审核默认 24 小时，计划审核取与计划到期较早者，任务最长等待 7 天。新资金/参数/范围/重大计划变化按材料重新审核；用户明确同一选择不重复确认。

### C8.1 前端 WorkbenchApi 精确扩展

下列接口定义于 `shared/api/agent-workbench-contract.ts`。AgentRun/StartAgentRun/AgentEvent/HumanInteraction/InteractionResponse/MessageReceipt/FeedbackReceipt 对应 C1/C4/C5 的 camelCase 安全 DTO；Catalog、Profile、Policy、Plan、ExecutionFeedback 类型对应 C2/C3/C7；所有输入/结果由各 domain 文件的同名 Schema 推导。CommandMeta 固定 requestId 与 expectedVersion；Page 使用现有前端 Page<T>。不在这层加入金融计算。

`domain/agent-common.ts` 单独持有 VersionRef/ArtifactRef/ProductKey/CommandMeta/PageQuery 及新 page Schema，其他新领域单向引用它；不让 agent-run.ts 与 manual-plan.ts 互相导入运行时 Zod Schema。已有 DecimalString/decimal.js 规则继续复用。StrategyVersion/KnowledgeVersion/PlanningProfileSnapshot 等按各自 domain 文件导出，AgentCapabilities/AgentSession/安全 InteractiveArtifact 放 agent-run.ts。

```ts
interface AgentCatalogApi {
  getAgentCapabilities(): Promise<AgentCapabilities>;
  createAgentSession(): Promise<AgentSession>;
  listStrategies(query: PageQuery): Promise<Page<StrategyVersion>>;
  createStrategyDraft(input: StrategyDraftInput): Promise<StrategyDraft>;
  updateStrategyDraft(id: string, input: StrategyDraftInput & CommandMeta): Promise<StrategyDraft>;
  publishStrategy(id: string, meta: CommandMeta): Promise<StrategyVersion>;
  archiveStrategy(id: string, meta: CommandMeta): Promise<void>;
  listKnowledge(query: PageQuery): Promise<Page<KnowledgeVersion>>;
  importKnowledge(input: KnowledgeImportInput): Promise<KnowledgeVersion>;
  publishKnowledge(ref: VersionRef, meta: CommandMeta): Promise<KnowledgeVersion>;
  archiveKnowledge(id: string, meta: CommandMeta): Promise<void>;
  searchKnowledge(input: KnowledgeQuery): Promise<KnowledgeHit[]>;
  getPlanningProfile(): Promise<PlanningProfileSnapshot | null>;
  getPlanningRiskPolicy(): Promise<PlanningRiskPolicy | null>;
  createPlanningProfile(input: PlanningProfileInput & CommandMeta): Promise<PlanningProfileSnapshot>;
  createPlanningRiskPolicy(input: PlanningRiskPolicyInput & CommandMeta): Promise<PlanningRiskPolicy>;
}

interface AgentRunApi {
  startAgentRun(input: StartAgentRun): Promise<AgentRun>;
  getAgentRun(id: string): Promise<AgentRun>;
  listAgentRuns(query: PageQuery): Promise<Page<AgentRun>>;
  getAgentMessages(id: string, query: PageQuery): Promise<Page<RecordedUserMessage>>;
  getAgentInteractions(id: string): Promise<HumanInteraction[]>;
  sendAgentMessage(id: string, input: UserMessage): Promise<MessageReceipt>;
  respondAgentInteraction(id: string, itemId: string, input: InteractionResponse): Promise<FeedbackReceipt>;
  cancelAgentRun(id: string, meta: CommandMeta): Promise<AgentRun>;
  subscribeAgentEvents(id: string, afterSeq: number, onEvent: (event: AgentEvent) => void): () => void;
  getAgentArtifacts(id: string): Promise<InteractiveArtifact[]>;
  getManualPlan(id: string): Promise<ManualPlanView>;
  revalidateManualPlan(id: string, meta: CommandMeta): Promise<AgentRun>;
  getManualChecklist(id: string): Promise<ManualChecklist>;
  recordExecutionFeedback(id: string, input: ExecutionFeedbackInput & CommandMeta): Promise<PlanningFeedbackReceipt>;
  listExecutionFeedback(id: string, query: PageQuery): Promise<Page<ExecutionFeedback>>;
  resolvePlanCommitment(id: string, input: CommitmentResolution & CommandMeta): Promise<PlanningFeedbackReceipt>;
}

interface AgentWorkbenchApi extends AgentCatalogApi, AgentRunApi {}
```

T15 只将 AgentCatalogApi 并入 WorkbenchApi；T16 三个适配器补齐 AgentRunApi 后再并入 AgentWorkbenchApi。不得为了让 T15 编译而返回假任务、空计划或“尚未实现但成功”的占位结果。

AgentCapabilities 只含 enabled、modelAvailable、mcpAvailable、planningProducts、monitoring=false、有限不可用原因；AgentSession 只含 csrfToken/expiresAt。RecordedUserMessage 在 agent-run.ts 定义为 UserMessage 加 seq/createdAt/recorded-applied 状态，受限重读不把原文塞入 SSE；结构化财务表单仍不写聊天。StrategyDraftInput 与 KnowledgeImportInput 自带 requestId；其余 CommandMeta 的 expectedVersion 对应 draft/task/plan 的 stateVersion，规划写入对应当前 pool generation。PlanningFeedbackReceipt 特意区别于人机交互 FeedbackReceipt，防止把“已报告成交”混同“审核反馈已应用”。InteractiveArtifact 仅市场报告/决策安全内容或 plan_ref，绝不携完整财务计划。缺少会话时 Http 实现先同源创建会话；写请求由统一新客户端注入 CSRF，重放 POST 复用原 requestId，不用会话刷新重发未知副作用请求。

## C9. 前向迁移与配置契约

| 任务 | 新迁移文件（`backend/alembic/versions/`） | 主表及约束 |
| --- | --- | --- |
| T01 | `0019_strategy_catalog.py` | strategy_definitions/strategy_versions；发布不可变，历史引用不删除 |
| T02 | `0020_research_knowledge.py` | knowledge_documents/versions/chunks，词项 GIN、不可变正文 |
| T03 | `0021_planning_inputs.py` | planning_pools、profiles/policies/venue_rules/costs 版本；workspace 唯一池、generation |
| T04 | `0022_agent_tasks.py` | agent_threads/runs/revisions/requests/events/evidence_epochs/artifacts、queue；幂等/seq/版本、owner/epoch/lease 与状态约束 |
| T05 | `0023_agent_attempts.py` | agent_steps/attempts、budget_authorizations/reservations；真实发送独立 attempt |
| T06 | `0024_agent_interactions.py` | agent_interactions/feedback/messages；单 pending、请求键及消息水位 |
| T07 | `0025_agent_segments.py` | agent_segments、owner/epoch/checkpoint namespace；扩展现有 audit run_kind 检查为 interactive_planning |
| T13 | `0026_manual_plans.py` | manual_plans/checks/adoptions/commitments/execution_feedback/resolutions；active/unresolved 同池部分唯一索引 |

每个文件用短于 Alembic 版本列上限的 revision 字符串，串行接前一 head；执行时若其他任务已加迁移，先按真实 head 调整本计划编号，绝不改写旧迁移或另建分叉。迁移只扩表/约束，不搬走旧审计/报告、不修改真实资金；业务库迁移与部署需另行按正式发布流程操作。

新设置由 `shared/config.py` 定义：`interactive_agent_enabled=False`、`manual_planning_enabled=False`，后者要求前者；本机 MCP 端口由部署侧 `agent_internal_api_port=8000` 指定（测试可注入本次专属端口，host/path 固定，不接受客户端 URL）；模型档案从已授权供应商配置读取 requested model，但不改现有值；工具/MCP 目录来自代码登记。新增功能关闭时消费者及内部 MCP 不启动，能力接口明确关闭；现有旧页面、API 和报告契约保留。

## C10. 官方资料与本轮核对范围

- [MCP 2.3.0 官方包元数据](https://pypi.org/pypi/mcp/2.3.0/json)：版本、Python 与传递依赖输入；本轮只读核对，未安装。
- [官方 Python SDK v2.3.0 源码](https://github.com/modelcontextprotocol/python-sdk/tree/v2.3.0)：实际适配以该标签为准，不复制浮动 main 示例。
- [MCP Client transports](https://py.sdk.modelcontextprotocol.io/client/transports/)：使用受控 HTTP 客户端、单独限制 JSON/SSE 与重定向；SDK 的传输默认不能替代项目守卫。
- [MCP ASGI 嵌入](https://py.sdk.modelcontextprotocol.io/run/asgi/)：宿主需管理挂载服务的 lifespan。
- [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)：原生工具消息格式及能力；当前配置模型仍需专项能力测试，不能仅凭示例模型名自动替换配置。
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：checkpoint 与业务状态分别治理，不假定图持久化保证外部调用恰好一次。

这些是计划制定时的技术依据，锁定环境、MCP 网络、模型质量、市场规则与产品支持均须按主计划分别验证。
