# T12 首轮修复复审

**结论为 changes_requested。** 已核对 base `c33613d`、修复范围 `e870d27..d0f5aee`、受审实现 `d0f5aee`、tree `e310be4d5cb34cf8d045a971f107de479fb718f6`。工作区 HEAD `d3e0964` 比受审实现仅多审查和进度文档。首轮八项报告中的原反例均得到修复。以下问题来自上下游契约和组合边界复核。

## 本轮发现与复验条件

1. **R1 · P1 · T12 拒绝 T03 正常产生的材料。** `backend/src/app/trade_planning/contracts.py:282` 要求当前池代次同时等于 profile、policy 的创建代次。T03 分别写入两份不可变快照，每次写入递增共享池代次，刷新规则也会递增。复现使用有效快照（profile=1，policy=2）和第 3 代池，通过注入仓储调用真实的 `PlanningInputService.resolve_refs`，成功返回第 3 代 refs。把同一组对象传给 `PlanningRequest` 即报“规划引用与资料的资金池代次不一致”。T12 夹具把三者都设为 1，掩盖了这个错误。此约束已存在于首轮实现。修复应保留精确版本、同池和拒绝未来代次的校验，由当前输入解析与采纳时的代次检查负责新鲜性。回归需把服务返回的 refs 原样送入 T12，覆盖先后写入和规则刷新。
2. **R2 · P2 · 强平检查仍消费未绑定的预览。** `backend/src/app/trade_planning/risk_checks.py:841` 单独取预览强平价比较。默认多单止损 95，把 applicable_direction 留空、参考价设为 96，得到 `margin_preview_matches=unknown` 和 `liquidation_distance_safe=fail`；把参考价改为 60 又会得到强平 pass。把产品改为 ETH 时，也可同时得到预览 fail 和强平 pass。缺绑定时该参考价无法证明本计划的强平方向，无论数值在哪一侧，相关检查均应 unknown。明确错配仍由预览检查 fail；只有已证明适用的证据才用于强平比较。
3. **R3 · P2 · 保守一格判断仍随 Decimal 精度改变。** `backend/src/app/trade_planning/order_rules.py:260` 的减法和绝对值位于显式计算上下文之外。tick 为 0.123456789012345678，入场、报价与最大不利价同为 99.999999099999999180，止损为 93.950616438395060957，目标为 111.111110111111110200。多头保守取整的真实止损调整量为 0.123456789012345677，低于一个 tick。相同 MARKET 请求在 precision 28/80 成功，在 6 下报 price_tolerance_exceeded。应覆盖完整价格解析路径的上下文独立性，包括恰在一格以内的调整。
4. **R4 · P2 · 缺少账户模式会掩盖已知占用冲突。** `backend/src/app/trade_planning/risk_checks.py:267` 在模式缺失时把产品和占用一起标成 unknown。默认支持品种上，设置 position_mode=None、existing_position_notional=10，得到 `existing_exposure_supported=unknown/profile_incomplete`。补填 one_way 后，已有仓位仍是明确阻断项。应当独立判断已知非零占用，保留对应 fail 原因；无法判断的模式继续 unknown。
5. **R5 · P3 · 冻结旧形状草稿时会物化四个绑定字段。** `backend/src/app/trade_planning/inputs.py:294` 向清理函数传入保证金正文，而该函数只查找 payload 下的 margin_evidence 子字典。省略四个绑定字段构造 MarginEvidenceDraft，再执行 MarginEvidence.build，四项均出现在结果的 model_fields_set，值均为 None，后续归档无法再区分这些缺省值和显式 null。此复现针对新冻结路径；直接读取原始历史归档与旧 request_id 的指纹兼容逻辑走其他分支。修复后应分别断言省略字段和显式 null 的归档载荷，并保留历史重放测试。

## 首轮各项处置

| 首轮项 | 已验证的修复 |
| --- | --- |
| F1 退出腿 | 分别要求 STOP_MARKET 和 TAKE_PROFIT_MARKET，按每腿核对市场数量步长、上下限、退出名义额与全量覆盖。默认数量 1.9 时单独设置市场最小量 2、最大量 1.8、最小名义额 185，均由对应检查阻断；名义额案例仅止损腿低于门槛。 |
| F2 材料绑定 | 成功和阻断结果均携带请求材料指纹。跨请求复用旧结果会产生 required 失败，清单拒绝跨材料组合。在 T12 可信纯函数边界，这足以检测旧结果误用。 |
| F3 集合与 required | 强制 34 项固定顺序。限价、市价分别测试缺项、同长度重复名和 required 降级均被拒绝。 |
| F4 最终比率 | 使用已结算的净收益除以已结算的损失。收益量化为零时返回稳定原因的 blocked。保留低比率数值草案并由 required 检查阻断符合当前分工。 |
| F5 缺项 | 单独缺失日损日期、保证金模式、持仓模式或市价最大不利价时保留 unknown。多项同时变化的状态语义见 R2、R4。 |
| F6 日界 | 23:59:55 的有效检查于下一 UTC 零点到期；在 00:00:00 和 00:00:01 重验均得到日损声明失效。T13 读取须使用必需检查的有效期。 |
| F7 预览绑定 | 产品、方向、入场价、数量、名义额和初始保证金参与适用性校验。四个新增绑定字段分别缺失均得到预览 unknown，错配得到 fail。后续强平检查及冻结路径见 R2、R5。 |
| F8 市价精度 | 首轮报价乘滑点上界的反例已修复，市价边界比较使用显式 80 位精度。同一请求后续保守取整仍有 R3。 |

## 验证

在仓库根目录执行 `uv run --project backend --locked --no-sync pytest backend/tests/trade_planning -q`，86 passed。`git diff --check e870d27 d0f5aee` 通过。在 backend 目录使用现有合成资料、公开函数及注入仓储执行上述探针。核对了请求所列 quick/full JSON 的 passed 状态；本次未独立重跑 PostgreSQL full、HTTP 或前端端到端测试。仅新增本复审记录。
