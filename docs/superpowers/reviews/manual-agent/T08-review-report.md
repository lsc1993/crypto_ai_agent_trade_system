# T08 正式审查报告

- 日期：2026-11-16
- 范围：`f331e09..96b8270`；当前 HEAD `0bb1331` 相对 tip 仅有说明文档变化。
- 结论：**changes_requested**。开发自测不替代本次审查；以下四项需修复后复审。
- 审查未修改实现、凭证、配置或数据库。

## 发现

### R1 / P1：公开行情实际传输次数超过预算预留

位置：`backend/src/app/agent/interactive/adapters/research_evidence.py:41–42`。

`planned_transport_calls` 将摘要视为一次请求，返回 `1 + len(timeframes)`，但实际 Binance 公开网关的冷缓存摘要会读取 ticker/24hr、premiumIndex、openInterest 三个端点，再读取各周期 klines。网关还允许重试。因此这里既非逐次计数，也非保守上界；预算仅够计划数时仍可发出额外传输。

离线复现使用真实公开网关、现有合成行情样本和 `httpx.MockTransport`：单 M15 周期 `planned=2`、`actual=4`，未触发重试即低计一倍。请求路径为上述三个摘要端点与 klines。既有测试替身没有覆盖该扇出。

建议在每次真实传输（含重试）前扣预算，或为 T08 提供能够证明覆盖扇出和重试的保守预留方案，并同步调整最多八次的边界。补真实网关冷缓存与重试测试，证明余额不足时不会超额发送。

### R2 / P2：必需证据投影被静默按字符截断

位置：`backend/src/app/agent/interactive/context.py:966–967`。

`projected[:_MAX_PROJECTED_FACT_CHARS]` 在必需块预算校验前截断事实文本，可能切断价格、时间、单位或限制说明；manifest 仍将其记录为完整包含且不报告省略。这违反本批次必需证据不可裁剪及整块处理的约束。

离线复现：投影返回 3994 个 ASCII 字符后接 `price=12345.67`，正常 build 的证据消息尾部只剩 `price=`，`omitted=()`，限制中也没有投影截断说明。截断位置稍变即可保留一个错误的部分数值。

建议由投影器按完整事实生成有界内容，构建器对超限必需块明确失败；不要对事实文本做字符切片。补阈值落在数字和时间字段中间的回归。

### R3 / P2：manifest 归属未与保存围栏绑定

位置：`backend/src/app/infrastructure/persistence/agent_run_repository.py:549–570`。

保存只验证传入 fence 的活性，没有比对 manifest 的 workspace_id、run_id、revision、segment_id。行归属取自 fence，document 却直接取自独立 manifest；读取时只校验摘要和模型形状，也不核对二者归属。因此合法围栏 A 可以保存任务 B 的清单并在 A 下读回，破坏审计关联和工作台隔离保证。摘要一致不能证明归属一致。

使用真实 repository 和合法 manifest、会话替身隔离数据库锁检查的复现结果：保存成功，行 workspace 属于 A、文档 workspace 属于 B，行 revision=1、文档 revision=2；从 A 读取仍返回 B 清单。此复现证明仓储逻辑缺口，不声称真实 PostgreSQL 验证。

建议写入前比对四项归属，并验证证据引用属于同一运行修订；读取时也拒绝行与文档归属不一致。补真实数据库的跨工作台、跨运行、跨修订和跨片段拒绝测试。

### R4 / P2：携带已冻结 epoch 时显式刷新被忽略

位置：`backend/src/app/agent_runs/evidence.py:261–275`。

`context.evidence_epoch` 非空时，验证最新存储记录后立即返回，未考虑 `refresh=True`。调用方在已冻结上下文上要求刷新时不会读取公开源、推进动作序号或生成新 epoch，可能继续使用已过期证据。

离线复现：先保存 epoch，再用携带该 epoch 的 ExecutionContext 调用 `freeze(..., refresh=True)`，返回同一 epoch，新增公开读取数为零。现有刷新测试使用未携带 epoch 的上下文，未覆盖该分支。

建议将这条复用路径限定在 `not refresh`；显式刷新应进入当前运行检查和新预算区段。补已绑定 epoch 的刷新回归。

## 其他重点结论与验证边界

- `_lock_live_fence` 与 T07 使用相同的任务→片段锁序；在任务锁后读取数据库时钟，并检查 owner、lease epoch、revision、namespace、取消标记。此次未发现确定的新增锁序缺陷，未执行真实数据库并发验证。
- manifest 字段总体为引用、指纹、水位、长度与原因；未发现直接复制财务值或原始证据正文的字段。内部 `context_manifest` 当前没有公开业务产物投影消费；T14 仍须兑现显式过滤约定。
- `calculation_version` 仅在非空时进入 epoch 哈希载荷，缺失历史字段保留原哈希形状；本次未发现确定的历史 epoch 兼容缺陷。
- 读前 requested_at / 读后 sealed_at 分离符合正常抓取时序；该结论不消除 R1 和 R4。
- 主审在 `backend/` 独立执行 `uv run --locked --no-sync pytest tests/agent/interactive -q`：**37 passed**。证据专项另跑 15 passed，是上述集合子集，不相加。
- 上述预算、文本截断、manifest 错绑和刷新均做了离线复现，无真实网络、模型或交易调用。
- 本次未重跑 PostgreSQL 持久化测试、阶段回归或后端 full；当前进程没有显式 TEST_DATABASE_URL。开发端 46 / 413 / 1291 的结果仅作为其申报记录，不作为本审查的独立通过结果。
