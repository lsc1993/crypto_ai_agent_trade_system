# T07 正式代码审查

## 最新结论：R1/P1 复审通过

- 复审日期：2026-11-12；实现 tip：`ec3e8e541aad7e36b0f247f5ac2c4c3c8e0c8885`。
- 正式结论：**R1/P1 已关闭，T07 本轮代码复审通过，未发现新增阻断问题**。下文首轮不通过结论作为历史保留，由本节取代。
- 复审范围：`f5091f5..ec3e8e5` 中两个后端文件（+70/-5）。该 Git 范围合计六个文件，另外四个是文档。复审时分支为 `t07-agent-segments`，HEAD 为 `7b5a55c`，工作区干净；实现 tip 到 HEAD 无 backend 差异。
- 清理路径现在无条件取消执行器与心跳，并通过 `gather(..., return_exceptions=True)` 等待两者退出。外层原有 `CancelledError` 在 finally 完成后继续传播，run_once/run_forever 均重新抛出；清理本身不调用 commit。正常结果、心跳失租、异常路径仍经过共同清理。

独立验证（目录 `D:\t07\backend`）：

| 项目 | 命令/方法 | 本轮实际结果 |
| --- | --- | --- |
| 原取消复现 | 使用下文原复现替身，并补充显式捕获 CancelledError 及 commit 计数断言 | `executor_cancelled=True pending_tasks=0 CancelledError_propagated=True commits=0` |
| 新回归反向验证 | 将 `git show f5091f5:backend/src/app/agent/interactive/worker.py` 编译到进程内独立命名空间，仅在内存替换 `_run_with_heartbeat`；执行两条 `cancelling_run_once / cancelling_run_forever` 测试 | 预期 **2 failed / 8 deselected**，均检出遗留执行器任务；未改写工作区代码 |
| 当前 worker 回归 | `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py -q` | **10 passed**，退出 0 |
| 相关回归 | `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py tests/agent_runs/test_segments.py tests/agent_runs/test_contracts.py tests/governance/test_interactive_planning.py -q` | **29 passed**，退出 0 |
| 静态检查 | `uv run --locked --no-sync ruff check src/app/agent/interactive/worker.py tests/agent_runs/test_worker.py` | 通过，退出 0 |
| 格式检查 | `uv run --locked --no-sync ruff format --check src/app/agent/interactive/worker.py tests/agent_runs/test_worker.py` | 2 files already formatted，退出 0 |

验证边界：当前进程未设置 `TEST_DATABASE_URL`，本轮未独立重跑数据库、迁移、D2 阶段或 full；开发端提供的 44 / 419 / 1245 passed 仍是开发验证记录。本次通过依据为修复差异审查、独立原复现及新回归红绿验证，不将开发自测作为正式通过结论的替代。本轮未修改实现、未开始 T08，也未进行合并、部署或业务库迁移。

## 首轮审查记录（历史）

- 日期：2026-11-12。
- 范围：`231d938454834b7f3ecd54180d433c499bcf76ce..f5091f5805121353f67fa16eb0651ba3e05b6a80`。
- 工作区/分支：`D:\t07` / `t07-agent-segments`；审查开始时工作区干净，HEAD 为 `08294b7`，实现 tip 到 HEAD 没有 backend 差异。
- 结论：**不通过，需修复后重新审查；不得进入 T08**。开发自测 `verified` 不等于正式通过。

## 阻断发现

### R1 / P1：worker 自身取消没有停止执行器，留下无心跳的孤立执行任务

位置：`backend/src/app/agent/interactive/worker.py:172–174`，`_run_with_heartbeat` 的 `finally`。

`runner_task` 由 `asyncio.create_task` 创建。当上层取消 `run_once` / `run_forever` 时，取消会中断 `asyncio.wait`，但不会自动传播给等待集合内的任务。当前 finally 仅 cancel/gather `heartbeat_task`，没有清理 `runner_task`，随后上层重新抛出 CancelledError。因此 worker 已退出、心跳已停止，执行器却仍能继续运行。如果进程的事件循环仍存活（例如仅重启 worker），旧片段会与租约过期后领取的新片段重叠执行。提交 fencing 能拦截迟到提交，但不能停止旧执行器继续计算或调用外部服务。这也与 worker 的停止语义及取消注释不符。

独立复现（在 `backend/`，PowerShell；使用现有测试替身，无数据库或模型调用）：

```powershell
@'
import asyncio, runpy
m = runpy.run_path('tests/agent_runs/test_worker.py')
async def main():
    c = m['_context']()
    e = m['FakeExecutor'](block=True)
    w = m['_worker'](
        runs=m['FakeRuns'](m['_snapshot'](c)),
        segments=m['FakeSegments'](contexts=[c]), executor=e)
    t = asyncio.create_task(w.run_once())
    await e.started.wait()
    t.cancel()
    await asyncio.gather(t, return_exceptions=True)
    pending = [x for x in asyncio.all_tasks()
               if x is not asyncio.current_task() and not x.done()]
    print('executor_cancelled=', e.cancelled, 'pending_tasks=', len(pending))
    for x in pending:
        x.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
asyncio.run(main())
'@ | uv run --locked --no-sync python -
```

实际输出：`executor_cancelled= False pending_tasks= 1`。

期望：外层取消继续传播前，取消并等待执行器和心跳任务退出；不伪造业务失败或成功。增加回归：执行器启动后取消 worker，断言执行器收到 CancelledError、没有遗留执行任务、没有业务 commit；还应覆盖 run_forever 任务取消的路径。

## 重点核对结果及验证边界

- 静态核对 claim/heartbeat/commit 的 owner、revision、lease_epoch、segment/namespace 与数据库租约校验；recover_expired 在取得任务/片段锁后重采样 `clock_timestamp()` 并检查两处租约。
- 静态核对 seq0 requested、seq1 authorized、seq2 started 的协调器路径，以及成功/等待要求 started、失败/恢复仅在 started 存在时追加 seq3 的路径。
- 静态核对等待/终态、片段结果、审计、事件和 owner 释放位于同一 session.begin；等待分支先锁队列。取消覆盖正常完成/降级/等待，消息是否已应用取数据库水位，runner 自报值不推进水位。
- 静态核对 0027 与 ORM CHECK/index，以及身份不可变、终态不可更新、结束释放租约、禁止删除的触发器。以上静态核对不代表数据库并发或迁移执行已独立验收。
- 本轮在 `D:\t07\backend` 执行 `uv run --locked --no-sync pytest tests/agent_runs/test_worker.py tests/agent_runs/test_segments.py tests/governance/test_interactive_planning.py -q`：**21 passed**。上述 R1 独立复现成功；原有测试没有覆盖该取消窗口。
- 当前进程未设置 `TEST_DATABASE_URL`；未读取 .env 或使用业务库。未独立重跑 PostgreSQL 持久化/恢复/迁移测试和 full，不将开发端报告的 1243 passed 视作本轮独立验证。

本轮仅记录审查意见，未修改实现、未修改原审查请求的 awaiting_review 字段、未推进 T08。修复提交应附新的 implementation tip 和回归证据后重新送审。
