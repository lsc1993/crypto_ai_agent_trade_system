# Agent 任务领域包入口：导出 T04 公共契约与服务，不在此装配数据库或启动后台消费者。
# 任务仓储的 SQL 实现位于 infrastructure/persistence，避免领域契约依赖具体存储。
"""Persistent agent task contracts, events and application service."""

from app.agent_runs.contracts import (
    RUNNABLE_CAPACITY,
    WAITING_CAPACITY_PER_WORKSPACE,
    AgentRunError,
    RunInput,
    RunQuality,
    RunSnapshot,
    RunStatus,
    canonical_run_input_json,
    legacy_run_input_sha256,
    run_input_sha256,
)
from app.agent_runs.events import RunEvent, RunEventPage, RunEventType
from app.agent_runs.ports import AgentRunRepository
from app.agent_runs.service import AgentRunService

__all__ = [
    "RUNNABLE_CAPACITY",
    "WAITING_CAPACITY_PER_WORKSPACE",
    "AgentRunError",
    "AgentRunRepository",
    "AgentRunService",
    "RunEvent",
    "RunEventPage",
    "RunEventType",
    "RunInput",
    "RunQuality",
    "RunSnapshot",
    "RunStatus",
    "canonical_run_input_json",
    "legacy_run_input_sha256",
    "run_input_sha256",
]
