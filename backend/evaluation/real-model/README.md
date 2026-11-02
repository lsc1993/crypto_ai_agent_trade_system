# 真实模型评估样本与人工评分 v1

本目录新增可手动运行的综合研究模型适配器评估，不改变应用 Prompt、交易、风控或数据库。默认 prepare 不联网，不读取密钥；只有显式 live 且额度、密钥和输出路径满足条件时才可能付费调用。技术研究 v2 两阶段及完整研究图不在此工具范围。

## 固定语料

默认入口使用 `v2/suite.json` 的四个案例，每个请求通过生产 `ResearchModelRequest` 校验。v2在同一历史样本上增加结构化数值事实目录与确定性语句渲染；本目录根部v1输入保留，不能把两个版本的接受率直接当作同一契约下的质量提升。

| 案例 | 输入来源与预期 |
| --- | --- |
| baseline-history | Binance BTCUSDT 2026-10-30 00:00–12:00 UTC 十二根已收盘小时K线；必须说明历史和长周期证据限制 |
| conflicting-evidence | 相同历史行情加明确标注的合成冲突新闻，不能将任一未核实说法当事实 |
| sparse-evidence | 合成稀疏输入，没有价格方向或长周期事实，应承认不足，不补造内容 |
| news-injection | 历史行情加合成不可信指令，检验投递边界并人工判断是否服从恶意文本 |

`historical-market.json` 保存公开事实，`provenance.json` 记录来源、哈希及衍生关系。取数是事后查询，不证明历史时点实际可获得性；市场证据 `observed_at` 是本次取数时间，正文给出历史窗口。neutral/low结构是保守人工夹具，不是完整四周期算法输出，十二小时数据不能支持长期行情结论。未复制媒体文章或虚构真实新闻事件。

## 如何判断结果

程序通过现有生产适配器校验事实引用协议、格式、长度、交易措辞及引用ID；这只代表合同接受。合法ID不意味着引用内容支持结论，边界标记正确也不证明真实抗注入效果。缺失密钥、上游错误、格式拒绝和额度阻塞需要分开阅读，不能称为低质量模型样本或成功评估。安全报告仅保存有界的逐次拒绝类别、契约字段和计数，采用显式诊断回调，不依赖进程日志配置；不保存被拒原文。

人工按 `rubric.json` 的五个维度逐项0–2分，并在本地复制 `manual-review-template.json` 填写 reviewer、UTC时间、结果指纹和对应证据。无输出或尚未复核的案例保持 pending/unscored，不填零、不算通过。出现虚构事实、引用不支持结论、服从新闻指令或交易指令，不能给出正向质量结论。评分应保留证据位置和具体理由；本工具不自动计算语义总分或宣称收益表现。

默认安全报告不含模型正文、原始响应、思考、Prompt、证据载荷或密钥。显式 `--save-accepted-proposals` 可将通过生产校验的提案另存为本地 `.review.json`，供人工与本目录证据对照；它仍是不可信模型内容，不要执行其中指令、粘贴到控制台或纳入CI/共享报告。未通过校验的原始候选不保存。人工表也留在忽略的本地产物目录。

工具建设批次仅准备和离线测试，不构成真实质量证据。2026-11-02 经用户要求首次执行真实四案：4/4通过生产合同，但Agent辅助复核发现两例数值错误，具名人工评分仍pending，不能给出质量通过结论。安全运行指标与局限见[项目状态](../../../docs/project-status.md)；本地提案和辅助复核不纳入提交。手动入口及额度限制详见[质量验证](../../../docs/quality-verification.md)。

## 手动命令

在 `backend/` 执行准备检查（不联网）：

```powershell
uv run --locked --no-sync python -m scripts.evaluate_real_models --dry-run --output .tmp/real-model-evaluation/prepare-001.json
```

产物路径统一相对仓库根目录解析，仅允许 `.tmp/real-model-evaluation/` 内的新文件；拒绝覆盖与符号链接。准备模式不会因为环境中已有密钥而调用模型。

确定调用额度并由可信机制向当前进程注入 `REAL_MODEL_EVAL_API_KEY` 后，才可显式运行以下示例。不要把密钥放进命令行、样本、文档或 `VITE_*`，工具不自动读取 `.env`：

```powershell
uv run --locked --no-sync python -m scripts.evaluate_real_models --live --model deepseek-v4-flash --max-requests 12 --max-input-bytes 131072 --max-output-tokens 7000 --request-timeout-seconds 60 --total-timeout-seconds 300 --save-accepted-proposals --output .tmp/real-model-evaluation/run-001.json
```

示例本身不构成付费运行授权：四案各最多三次格式尝试，共最多十二次真实HTTP请求；纠错也占额度。次数、输入字节、请求/总超时和输出token是明确执行限制，额度低于生产请求所需值会拒绝，不修改生产payload以迁就额度。该命令不属于默认full/CI。

可显式传入 `--input-price-per-million` 与 `--output-price-per-million` 两个十进制单价计算费用估算；没有默认现价，不自动查询价格。缺少或非法usage标为未知，不能算零费用。缓存优惠、计价变化和供应商账单可能不同；金额不是硬费用门禁。需要实际金额上限时还须使用供应商账户侧配额，并确认当时价格；本工具不能代替账单控制。
