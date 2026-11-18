# T12 首轮正式审查

**结论为 changes_requested。** 受审范围为 `c33613d..ef198f8`，implementation tree 为 `136c688be9bcb811acffb9b933b13573c9fcfef2`。工作区 HEAD 为 `e870d27`，与受审 tip 的差异仅有进度文档和审查请求。以下反例均针对纯函数接口，使用合成资料。

## 需要修复的发现

| 编号 | 位置 | 反例、影响与复审条件 |
| --- | --- | --- |
| F1 · P1 | `backend/src/app/trade_planning/order_rules.py:32`、`risk_checks.py:475` | 只检查入场订单类型和入场数量过滤器，求解成功就把全量保护止损和目标退出标为通过。默认限价入场数量 1.9，只声明 LIMIT 时全部 required 检查仍通过。单独把 market_quantity_step 改为 1 也得到相同结果。应明确定义每条退出腿的类型和触发方式，逐腿检查所需能力、步长、上下限和适用的名义额规则，再证明全量保护成立。 |
| F2 · P1 | `backend/src/app/trade_planning/risk_checks.py:469`、`checklist.py:94` | SizingResult 没有请求指纹。先用默认政策算出 1.9，再传入 max_quantity=0.1、max_risk_per_trade=0.1 的新请求和旧结果，全部 required 检查通过，还盖上新材料指纹。风险检查和清单两个入口均须验证数量结果绑定本次材料，或在入口内从同一请求求解。 |
| F3 · P2 | `backend/src/app/trade_planning/contracts.py:473` | 校验器只在调用方给出的检查子集中计算阻断项。把最低盈亏比改为 100，只传原检查元组的第一项，build_manual_checklist 仍返回 blocking_checks=()。应校验当前操作预期的完整检查名、唯一性和必需性，或在构建清单时统一生成检查。复审需覆盖缺项、重复及 required 降级。 |
| F4 · P2 | `backend/src/app/trade_planning/sizing.py:222` | 比率按未结算的单位值计算。合法数量 1e-18、零费率、多单入场 100、止损 98.9、目标 101.9 时，输出损失 2e-18、收益 1e-18，净比率却是 1.727272…，最低比率 1.5 仍全项通过。应从保守结算后的金额重算比率。同例目标改为 100.1，收益向下量化为零，构造 SizingResult 抛出 ValidationError。此类边界应返回带稳定原因的 blocked。 |
| F5 · P2 | `backend/src/app/trade_planning/risk_checks.py:168`、`:273`、`:421` | 缺 daily_risk_as_of 被标为 fail/stale；缺 margin_mode 或 position_mode 被标为产品及占用 fail/unsupported；市价缺最大不利价时，价格、上界和数量都报 fail。按审查请求“缺项 unknown、确定冲突 fail”的承诺，应区分未声明与已知过期、不支持或越界，并避免把一项缺失传播为无关硬冲突。 |
| F6 · P2 | `backend/src/app/trade_planning/risk_checks.py:173` | 当日损益检查的有效期直接沿用 profile.expires_at。UTC 23:59:55 所有项通过，daily_risk_current 标为次日 00:07:55 到期，全部 required 中最早到期也在次日 00:00:45。T13 在午夜按检查有效期派生状态，会继续使用昨天的日损声明。应将该检查有效期截短至下一 UTC 零点，并覆盖跨日读取。 |
| F7 · P2 | `backend/src/app/trade_planning/margin.py:64` | 名义额和初始保证金精确相等，仍不能证明同一强平参考适用于不同入场价和数量。例如 50 × 3.8 和 100 × 1.9 都是名义额 190、两倍杠杆保证金 95，同一参考价 30 能让两份多头计划都通过，但这是两种不同的开仓预览。应绑定预览的产品、方向、入场价、数量和杠杆等实际条件；绑定不足时适用性为 unknown。多单 stop > liquidation、空单 stop < liquidation 的方向判断本身正确。 |
| F8 · P2 | `backend/src/app/trade_planning/order_rules.py:162` | 市价边界的加乘依赖环境 Decimal 精度。报价 100000000000.123456789012345678，加 1% 的精确上界为 101000000000.12469135690246913478；tick 为 1e-18，申报价 101000000000.124691356902469134 合法。默认精度 28 判不一致，精度 80 通过。应在统一计算上下文内比较，并测边界内外各一个 tick。 |

## C7 取舍和 T13 接口

- R 同时取政策单笔、日损、组合硬上限及对应三个剩余额度的最小值，符合当前 C7。正常多空场景的 L/W 按不利退出价计算毛损益、对应路径费用和一次持有成本。持有成本这一解释要求输入代表整个持有情景的总费率。
- 入场带下界 ceil、上界 floor，以及止损和目标的保守舍入方向与 C7 一致。触发价目前只检查位于区间，tick=0.5、trigger=99.9 可以全项通过。若它是人工观察阈值，此行为可以成立；如清单把它交给用户作为交易所触发单参数，则须验证格点。当前测试注释称触发价需要对齐，应与操作语义统一。
- 市价边界同时采用申报的最大不利价与成本上界。允许申报值比报价加减成本上界更紧，只在该更紧边界有独立依据时才足以支持数量计算。普通 MARKET 指令本身不会执行用户填写的保护价；后续清单需明确超出情景时的人工分支。
- 最低净盈亏比由 required 检查阻断、保留数值草案的分工可接受，前提是 F2–F4 修复。材料哈希排除 evaluated_at 也可接受，前提是读取时按当前时刻检查有效期，包含 F6 的日界。是否采纳、资金池代次与占用、最终 readiness 继续由 T13 负责。

## 验证范围

在工作区根目录运行 `uv run --project backend --locked --no-sync pytest backend/tests/trade_planning -q`，68 passed。在 backend 目录通过现有 planning_fixtures 和纯函数入口运行上述边界反例。此次未重跑 PostgreSQL full、HTTP 或前端端到端验证。审查未修改实现。
