# T05 正式模块审查

- 日期：2026-11-11。
- base：`4d1af68fc704f50b21b9f9b0619b446f315f66d6`。
- reviewed implementation tip：`249a8adc3769c9576015c7ff4a4edaa3e1798a6b`；范围 14 文件，+3686/-6。
- `9c4c105` 仅作为审查材料；已核对相对 implementation tip 只有文档变化。
- 结论：**需要修改，未通过**。以下 4 项均为 P2（应在后续批次前修复的正确性问题），没有发现需列为 P0/P1 的证据。开发端应先复现，再修复并补回归；本报告不代表修复验收。

## F1：实际用量超限后，已有 prepared 仍取得发送许可

位置：`backend/src/app/infrastructure/persistence/agent_attempt_repository.py:150-155`。

`mark_sent()` 读取最新累计预算后仅调用 `validate_activity_start()`，未检查 Token 是否已超过当前上限。结算允许真实 usage 高于预留，`BudgetStatus` 也明确允许如实记录超限，因此另一尝试的结算能使预算超限；此前创建的 prepared 仍可被置为 in_flight，返回新的发送许可。该行为与预算模块“真实用量超限后阻塞新调用”的说明不符。

复现路径（真实 SQL 回归建议）：

1. 使用现有 `_running_run` 和默认初始预算，在同一 run 预留动作 1..6，每次输入 16000、输出 512；预留动作 7，输入 1024、输出 512。输入累计占用 97024，全部可成功。
2. 对动作 1..4 依次 `mark_sent` 并成功结算，每次真实输入 usage=16384、输出 usage=1，并给合成结果引用。输入累计变为 98560，超过上限 98304；每次 usage 仍在单次 16384 上限内。
3. 对动作 7 调用 `mark_sent`。当前实现仍成功；预期应拒绝新发送，保持 prepared，直到取得足够追加授权。

修复时应检查已有预留的发送准入，避免再次累加该尝试的次数/Token。不能直接复用会额外加一份预留的 `validate_reservation_fits()`。

## F2：修订推进后，旧 unknown 无法用有效回执结算

位置：`backend/src/app/infrastructure/persistence/agent_attempt_repository.py:591`；关联 `_lock_fenced_run()` 的当前修订检查。

租约检查要求 fence.revision 等于 run 当前修订，随后 `_load_attempt()` 又要求 attempt.revision 等于当前修订。修订推进后，旧 fence 被拒绝，新 fence 也无法载入旧 attempt，导致供应商可验证回执授权分支永远不可达。旧 unknown 的最坏预留会永久占用 run 总预算，无法按回执结算为实际量。

复现路径：revision=1 下 reserve → mark_sent → settle(unknown)，然后按现有测试辅助函数推进到 revision=2。使用 revision=2 当前有效 fence，对旧 attempt 调用 settle(succeeded/failed，非空 provider_receipt，receipt_verified=True，已知 usage)：得到 `attempt_not_found`；改用 revision=1 fence 则得到 `lease_lost`。

需要区分“当前执行权限围栏”与“被对账尝试所属修订”。仅允许当前有效 owner 对同 run/workspace 的历史已发送尝试进行受验证回执约束的对账，不应放开旧 prepared 的发送或旧 worker 写权限。T07 必须有跨修订恢复回归。

## F3：公开状态机允许 prepared→failed，实际结算及存储无法表示

位置：`backend/src/app/agent_runs/attempts.py:61`、`:219`；`backend/src/app/infrastructure/persistence/agent_attempt_repository.py:597-615`；`backend/alembic/versions/0023_agent_attempts.py:119-123`。

纯状态机将 prepared→failed 声明为合法，并有测试断言；但结算权限函数只处理 in_flight/unknown。reserve 后发生发送前校验失败时，settle(failed) 返回 `invalid_attempt_transition`，预留无法终止。同键恢复仍得到 prepared。若强行先 mark_sent，则会把未发送调用记录为已发送；快照与 SQL 生命周期约束同样强制所有 failed 必须有 sent_at。

复现路径：reserve 后直接 settle(AttemptResult(status=FAILED, reason_code="cancelled_before_send"))。预期状态机、快照、仓储与数据库对发送前失败具有一致定义，并明确对应次数与 Token 的记账规则；不得用伪造发送来满足约束。

## F4：数据库允许未结算 Token 提前写 actual，静默释放预留

位置：`backend/alembic/versions/0023_agent_attempts.py:430-445`；对应 ORM `backend/src/app/infrastructure/persistence/models/agent_attempts.py:205-218`。

此项是数据库防护缺口，当前正常仓储不会主动这样写。触发器允许 reserved→reserved，但仅对 unknown/settled 约束 actual 的空值语义。对正常 prepared 模型尝试执行以下 SQL 可绕过最坏预留占用：

```sql
UPDATE budget_reservations
SET actual_amount = 0
WHERE attempt_id = :attempt_id
  AND meter IN ('input_tokens', 'output_tokens');
```

状态仍为 reserved，触发器不会拒绝；后续 status 按 COALESCE(actual,reserved) 把 Token 计为零，次数一致性检查也无法发现。mark_sent 仅为次数 meter 写 actual，错误 Token 零值继续保留。另外形状规则仅位于 UPDATE 触发器，INSERT unknown+actual=0 也未被 CHECK 拦截。

应按 meter/state 明确定义 actual 的合法形状，并同时覆盖 INSERT/UPDATE；补充直接 SQL 拒绝测试及被拒绝后预算占用不变的断言。不能简单要求所有 charged.actual=NULL，因为已发送次数 meter 合法使用 actual=1。

## 已核对的约束与后续依赖

- 公共预留路径在同一 run 行锁下完成预算加载、准入与写入，避免两个并发预留分别读取旧余量。fence 使用锁后的数据库 clock_timestamp 校验租约；未发现该路径直接突破并发额度的证据。
- AP-05 公共方法逐维度不减、至少一项增加、部署硬上限、授权引用与额度幂等校验成立。批准用户身份/审核原子应用属于 T06，不能因存在追加原语就宣称审批链已实现。
- unknown 无 usage 时保留预留、同键不重放的基础路径成立。receipt_verified 是受信调用方提供的断言，并非本模块实际验证供应商回执；后续适配必须绑定回执与具体 attempt/请求并验证真实性，不能把模型或客户端布尔值直接传入。
- succeeded 必须带 ArtifactRef，现有成功步骤复用引用且不重复占预算。T05 不验证真实产物存在、归属及指纹，材料已明确这一边界；T11/T14 必须先持久化已校验结果再成功结算，覆盖崩溃窗口和恢复后的引用解析，不将不透明 UUID 当成真实结果验证。
- T07 的 claim/heartbeat、活动时间最终记录、恢复枚举及终态协调仍未实现，本报告未将其缺失直接列为 T05 缺陷。

## 验证与证据限制

- 执行目录 `D:\t05\backend`：`uv run --locked --no-sync python -m pytest tests/agent_runs/test_attempts.py tests/agent_runs/test_budget.py tests/agent_runs/test_segments.py -q`，**14 passed**。
- 在同目录用 Python 直接调用当前结算守卫：状态机 prepared→failed 返回 True，但守卫返回 invalid_attempt_transition；用返回历史 attempt 的最小会话替身调用 `_load_attempt`，返回 attempt_not_found。后者只证明应用判断，不代表真实 SQL 验收。
- F1/F4 为代码与约束静态路径核对，尚未独立运行上述真实 SQL 复现；F2/F3 的完整数据库链路同样待开发端复现。
- 当前进程未设置显式 TEST_DATABASE_URL，未读取 `.env` 获取测试授权，因此本轮未独立执行 PostgreSQL、迁移或完整后端回归。审查材料中的 1175 passed 是开发端既有证据，不作为本轮重新执行的结果。
- 本轮无真实模型、网络发送或交易；未修改实现、迁移、配置或状态进度文件。
