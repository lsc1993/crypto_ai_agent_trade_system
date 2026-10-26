# 专用 worker 消费用户手动提交的技术 v2 队列，以租约所有权约束阶段推进和保存。
# 心跳失败时取消研究；停机与异常采用有界清理，恢复优先识别已提交报告，避免覆盖成功结果。
# 队列不定时生成报告，不持续追踪触发状态，也不执行交易。
"""Dedicated manual research queue worker, with ownership and bounded shutdown."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

import structlog

from app.harness.contracts import HarnessPolicyViolation
from app.market.symbols import ResearchSymbol
from app.reports.contracts import ReportStorageUnavailableError
from app.reports.technical_plan import TechnicalPlanReport
from app.reports.technical_run_repository import TechnicalRunRepository
from app.reports.technical_runs import TechnicalRunError, TechnicalRunLease, TechnicalRunPhase


# 受控研究执行端口；注入进度回调和保存前租约复核，不允许任意后台任务。
class TechnicalPlanRunExecutor(Protocol):
    async def generate(
        self,
        symbol: ResearchSymbol,
        *,
        analysis_id: UUID,
        progress: Callable[[TechnicalRunPhase], Awaitable[None]],
        before_save: Callable[[], Awaitable[TechnicalRunLease | None]],
    ) -> TechnicalPlanReport: ...


# 负责领取、续租、终态更新和恢复；研究内容由固定执行器生成。
class TechnicalResearchWorker:
    def __init__(
        self,
        *,
        repository: TechnicalRunRepository,
        executor: TechnicalPlanRunExecutor,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository, self._executor, self._clock = repository, executor, clock

    # 先恢复过期运行再领取一项；研究与续租同时运行，任何所有权丢失都终止当前工作。
    async def run_once(self) -> bool:
        await self._repository.recover_expired(now=self._clock())
        owner = uuid4()
        run = await self._repository.claim(owner=owner, now=self._clock())
        if run is None:
            return False

        # 阶段推进失败表示所有权已失效，必须中断研究而不是只忽略进度写入失败。
        async def progress(phase: TechnicalRunPhase) -> None:
            if not await self._repository.advance(
                run.id, owner=owner, phase=phase, now=self._clock()
            ):
                raise RuntimeError("lease_lost")

        async def before_save() -> TechnicalRunLease:
            if not await self._repository.heartbeat(run.id, owner=owner, now=self._clock()):
                raise RuntimeError("lease_lost")
            return TechnicalRunLease(run.id, owner)

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(10)
                if not await self._repository.heartbeat(run.id, owner=owner, now=self._clock()):
                    raise RuntimeError("lease_lost")

        work = asyncio.create_task(
            self._executor.generate(
                run.symbol, analysis_id=run.analysis_id, progress=progress, before_save=before_save
            )
        )
        pulse = asyncio.create_task(heartbeat())
        try:
            done, _ = await asyncio.wait((work, pulse), return_when=asyncio.FIRST_COMPLETED)
            # 续租任务先结束意味着租约不可靠；先传播其异常，不能继续等待模型完成后提交。
            if pulse in done:
                await pulse
                raise RuntimeError("heartbeat_ended")
            report = await work
            await self._repository.finish(
                run.id,
                owner=owner,
                status=report.status,
                report_id=report.id,
                error_code=None,
                now=self._clock(),
            )
        except asyncio.CancelledError:
            # Report recovery takes precedence if cancellation happens after commit.
            work.cancel()
            pulse.cancel()
            await self._fail_if_owned(run.id, owner, "interrupted")
            raise
        except Exception as error:
            work.cancel()
            pulse.cancel()
            code = (
                "symbol_not_admitted"
                if isinstance(error, HarnessPolicyViolation)
                else (
                    "storage_unavailable"
                    if isinstance(error, (TechnicalRunError, ReportStorageUnavailableError))
                    else "research_failed"
                )
            )
            await self._fail_if_owned(run.id, owner, code)
            structlog.get_logger(__name__).info(
                "technical_run_failed", run_id=str(run.id), error_code=code
            )
        finally:
            for task in (work, pulse):
                if not task.done() and not task.cancelling():
                    task.cancel()
            try:
                async with asyncio.timeout(2):
                    await asyncio.gather(work, pulse, return_exceptions=True)
            except TimeoutError:
                pass
        # 返回值只表示本次领取过任务，失败终态也算已处理；并非研究成功标志。
        return True

    # 仅尝试写入仍归当前租约的失败；存储会优先推导已保存报告，失败写入也限制等待时间。
    async def _fail_if_owned(self, run_id: UUID, owner: UUID, code: str) -> None:
        # Expire/recover later rather than overwriting a report already committed.
        # The repository derives a saved report before accepting a failure terminal.
        try:
            async with asyncio.timeout(2):
                await self._repository.finish(
                    run_id,
                    owner=owner,
                    status="failed",
                    report_id=None,
                    error_code=code,
                    now=self._clock(),
                )
        except (TechnicalRunError, TimeoutError):
            pass

    # 空队列时短暂等待停止事件，有工作则继续消费，不自行创建研究请求。
    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                worked = await self.run_once()
                if worked:
                    continue
            except TechnicalRunError:
                structlog.get_logger(__name__).info("technical_queue_unavailable")
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
