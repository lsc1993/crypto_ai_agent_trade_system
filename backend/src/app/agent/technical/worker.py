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


class TechnicalPlanRunExecutor(Protocol):
    async def generate(
        self,
        symbol: ResearchSymbol,
        *,
        analysis_id: UUID,
        progress: Callable[[TechnicalRunPhase], Awaitable[None]],
        before_save: Callable[[], Awaitable[TechnicalRunLease | None]],
    ) -> TechnicalPlanReport: ...


class TechnicalResearchWorker:
    def __init__(
        self,
        *,
        repository: TechnicalRunRepository,
        executor: TechnicalPlanRunExecutor,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository, self._executor, self._clock = repository, executor, clock

    async def run_once(self) -> bool:
        await self._repository.recover_expired(now=self._clock())
        owner = uuid4()
        run = await self._repository.claim(owner=owner, now=self._clock())
        if run is None:
            return False

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
        return True

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
