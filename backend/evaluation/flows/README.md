# 研究服务离线流程评估

在 `backend/` 运行 `uv run python -m scripts.evaluate_research_flows --output ../.tmp/research-flows.json`。
不需要真实模型密钥、网络或数据库；程序不读取环境配置，HTTP 只能经过固定 `MockTransport`。

`suite.json` 固定案例身份、流程、故障模式、分类、质量、错误码和精确模型调用阶段。
`market.json` 是 `synthetic-breakout-v1` 合成行情配方：展开八十根十五分钟、小时、中周期与日线的已收盘 K 线，指定短周期平台、历史转折和末根量能。全部价格使用 Decimal，时间固定为 UTC。该配方不代表真实行情。

技术 v2 使用真实 `DeepSeekTechnicalPlanLanguageModel` 和 `TechnicalPlanResearchService`，覆盖两阶段成功、分析格式拒绝、编排超时降级、数据不足门控及未配置模型。综合研究使用真实 `DeepSeekResearchLanguageModel` 和固定研究图，覆盖成功、格式拒绝、超时和缺少日线门控。响应中的 `__EVIDENCE_ID__` 只替换为本次服务冻结证据的身份，研究正文与事实引用路径均固定。技术分析启用思考、编排关闭思考；两阶段上下文一致，模型原始思考不进入后续请求或评估产物。

每例通过真实服务保存后重新解析内存 JSON 再读取；内存仓储只验证服务保存与读取契约，不能证明数据库事务或不可变触发器。专用测试库的真实仓储回归位于 `tests/persistence/test_research_flow_evaluation_history.py`，通过 `migrated_database` 的随机 schema、真实 Harness 和 SQL 仓储验证分析拒绝、编排降级与证据不足的历史读取及降级审计。测试语料在测试文件内独立构造，只有显式烟雾检查读取本开发集。

结果分别统计 `accepted`、`rejected`、`degraded`、`insufficient`，每项都要求保存与读取成功。格式拒绝的服务报告仍会保存为降级，统计分类用于区分拒绝原因。产物保留样本版本及语料、展开行情、Prompt、完整方法包与模型/报告契约指纹；技术 Prompt 指纹也包含构造函数，覆盖编排阶段追加规则。仅全部案例符合预期才退出零，空集、坏配置、损坏响应外壳、调用次数或结果不匹配均退出非零。

产物只包含受校验的案例标识、阶段、质量、固定错误码与统计，不包含模型正文、思考、证据载荷、Prompt 或原始异常。固定响应只验证生产合同与降级路径，不代表真实模型质量、事实准确性、抗注入能力或投资表现。
