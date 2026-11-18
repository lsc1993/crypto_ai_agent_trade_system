# T12 复审结论（9a55aad）

**正式结论为 approved，reviewed_tip 为 `9a55aad`。** R1–R5 全部关闭。本轮修复范围为 `d3e0964..9a55aad`，项目基线为 `c33613d`，实现 tree 为 `ddb94ce43404bdf9338c4fdacce2e2d7a4c4ba8a`。复审时工作区 HEAD 为 `8a46890`，其相对受审实现的改动仅涉及审查与进度文档。

| 项目 | 复核结果 |
| --- | --- |
| R1 当前池代次 | 在独立 PostgreSQL 17 实例中运行真实仓储与服务回归。第 1 代资料、第 2 代政策经规则刷新后，T03 返回第 3 代 refs，T12 原样接受。分别将资料或政策创建代次置于 refs 之后，均遭拒绝。请求仍校验同池与精确版本；采纳时的当前代次重验归 T13。 |
| R2 强平检查 | 缺少预览方向时，参考价 60、96 分处止损 95 两侧，两例的强平检查均为 unknown。产品错配时预览为 fail，强平检查为 unknown。只有预览匹配后才比较当前方向与强平参考价的位置。 |
| R3 保守取整 | 上轮反例的多头止损取整为 93.827159649382715280。补测空头反向取整，多空完整价格解析结果在调用方 Decimal 精度 6、28、80 下分别一致。 |
| R4 已知占用 | 分别缺少保证金模式或持仓模式，逐一设置仓位或挂单的名义额、保证金、风险为非零，共 12 种组合。模式检查保持 unknown，已知占用均为 fail。 |
| R5 冻结语义 | 对产品、方向、入场价、数量四个绑定字段穷举 16 种省略与显式 null 的组合。冻结及归档均保留相应键集合，重新加载归档后版本引用一致。 |

## 验证记录

- 仓库根目录运行 `uv run --project backend --locked --no-sync pytest backend/tests/trade_planning -q`，92 passed。
- `backend/` 下以独立 PostgreSQL 17 和受限测试身份运行 `uv run --locked --no-sync pytest -q tests/persistence/test_planning_inputs.py tests/trade_planning`，109 passed，无跳过，包含上述 92 项及 R1 SQL 集成回归。临时实例已停止并移除。
- `backend/` 下另运行 R1、R3、R4、R5 的组合探针。仓库根目录的 `git diff --check d3e0964 9a55aad` 通过。
- 已查看开发方归档的后端 quick/full JSON，二者均记录 passed。本次未独立重跑后端 full、HTTP 或前端端到端测试。

批准范围为该实现提交的 T12 确定性规划模块。T13 的 readiness、采纳及资金池占用仍待实现和验收。
