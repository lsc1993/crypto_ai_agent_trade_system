"""Public lifecycle of manually requested technical research."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import field_validator, model_validator

from app.market.symbols import ResearchSymbol
from app.reports.technical import TechnicalBase, require_utc

TechnicalRunPhase = Literal[
    "queued", "collecting", "analyzing", "validating", "composing", "saving", "finished"
]
TechnicalRunStatus = Literal["queued", "running", "completed", "degraded", "failed"]
PHASES = ("queued", "collecting", "analyzing", "validating", "composing", "saving", "finished")


@dataclass(frozen=True)
class TechnicalRunLease:
    run_id: UUID
    owner: UUID


class TechnicalRun(TechnicalBase):
    id: UUID
    analysis_id: UUID
    symbol: ResearchSymbol
    status: TechnicalRunStatus
    phase: TechnicalRunPhase
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report_id: UUID | None = None
    error_code: (
        Literal[
            "interrupted",
            "symbol_not_admitted",
            "run_timeout",
            "storage_unavailable",
            "research_failed",
        ]
        | None
    ) = None

    @field_validator("created_at", "updated_at", "started_at", "finished_at")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_utc(value)

    @model_validator(mode="after")
    def lifecycle(self) -> "TechnicalRun":
        terminal = self.status in {"completed", "degraded", "failed"}
        if terminal != (self.phase == "finished") or terminal != (self.finished_at is not None):
            raise ValueError("run_terminal")
        if (self.status in {"completed", "degraded"}) != (self.report_id is not None):
            raise ValueError("run_report")
        if (self.status == "failed") != (self.error_code is not None):
            raise ValueError("run_error")
        return self


class TechnicalRunError(RuntimeError):
    def __init__(
        self, code: Literal["request_conflict", "queue_full", "storage_unavailable"]
    ) -> None:
        super().__init__(code)
        self.code = code
