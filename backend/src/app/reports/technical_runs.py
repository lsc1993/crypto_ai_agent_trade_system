# 手动技术研究队列的公共生命周期契约，阶段推进与报告终态通过运行标识关联。
# 运行所有权与结果分开：租约只证明当前领取者，不改变冻结研究或授权执行。
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


# 保存前用于核对运行标识和领取者，防止过期 worker 提交另一个所有者的结果。
@dataclass(frozen=True)
class TechnicalRunLease:
    run_id: UUID
    owner: UUID


# 完成和降级必须关联报告，失败必须关联错误，所有终态同时带结束阶段与时间。
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


# 排队冲突、容量或存储故障使用有限错误码，不向调用方泄漏存储异常。
class TechnicalRunError(RuntimeError):
    def __init__(
        self, code: Literal["request_conflict", "queue_full", "storage_unavailable"]
    ) -> None:
        super().__init__(code)
        self.code = code
