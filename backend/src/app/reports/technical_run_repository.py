# 技术研究队列仓储协议规定入队、领取、续租、阶段推进、终态与过期恢复操作。
# 所有修改携带显式 UTC 时刻，领取后的操作带所有者标识，防止失去租约继续写入。
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.market.symbols import ResearchSymbol
from app.reports.technical_runs import TechnicalRun, TechnicalRunPhase, TechnicalRunStatus


# 通过协议封装队列原子操作，执行器不直接处理底层并发与事务。
class TechnicalRunRepository(Protocol):
    # 使用请求标识处理手动提交的幂等与冲突，返回可查询的公开运行状态。
    async def enqueue(
        self, symbol: ResearchSymbol, *, request_id: UUID, now: datetime
    ) -> TechnicalRun: ...
    async def get(self, run_id: UUID) -> TechnicalRun | None: ...
    # 尝试原子领取待运行任务，无可领取项返回空值；所有者随后用于续租和保存复核。
    async def claim(self, *, owner: UUID, now: datetime) -> TechnicalRun | None: ...
    # 仅为匹配所有者的运行续租，布尔结果告诉 worker 是否仍拥有执行权。
    async def heartbeat(self, run_id: UUID, *, owner: UUID, now: datetime) -> bool: ...
    # 带所有者推进固定阶段，失败不能被解释成继续执行许可。
    async def advance(
        self, run_id: UUID, *, owner: UUID, phase: TechnicalRunPhase, now: datetime
    ) -> bool: ...
    # 带所有者写入完成、降级或失败终态，并关联报告或安全错误码。
    async def finish(
        self,
        run_id: UUID,
        *,
        owner: UUID,
        status: TechnicalRunStatus,
        report_id: UUID | None,
        error_code: str | None,
        now: datetime,
    ) -> bool: ...
    # 恢复过期租约时优先识别已提交报告，避免把提交成功后的中断误判成研究失败。
    async def recover_expired(self, *, now: datetime) -> int: ...
