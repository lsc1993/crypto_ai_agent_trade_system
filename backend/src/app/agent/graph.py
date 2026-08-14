from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, Literal, Protocol, cast

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]

from app.agent.contracts import AgentErrorCode, AgentNodeName, AgentRunState

logger = structlog.get_logger(__name__)
AgentGraphNode = Callable[[AgentRunState], Awaitable[dict[str, object]]]


class AgentGraphRun(Protocol):
    """Request-scoped node implementation; payloads never become graph state."""

    async def collect_market(self, state: AgentRunState) -> dict[str, object]: ...

    async def collect_news(self, state: AgentRunState) -> dict[str, object]: ...

    async def compute_structure(self, state: AgentRunState) -> dict[str, object]: ...

    def evidence_gate(self, state: AgentRunState) -> Literal["model", "degraded"]: ...

    async def generate_model_report(self, state: AgentRunState) -> dict[str, object]: ...

    async def persist_degraded_report(self, state: AgentRunState) -> dict[str, object]: ...

    async def validate_and_persist_report(
        self,
        state: AgentRunState,
    ) -> dict[str, object]: ...


def build_agent_graph(
    run: AgentGraphRun,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None,
) -> Any:
    """Compile the only permitted market-research control flow."""

    builder: Any = StateGraph(AgentRunState)
    builder.add_node("collect_market", _logged_node("collect_market", run.collect_market))
    builder.add_node("collect_news", _logged_node("collect_news", run.collect_news))
    builder.add_node("compute_structure", _logged_node("compute_structure", run.compute_structure))
    builder.add_node(
        "generate_model_report",
        _logged_node("generate_model_report", run.generate_model_report),
    )
    builder.add_node(
        "persist_degraded_report",
        _logged_node("persist_degraded_report", run.persist_degraded_report),
    )
    builder.add_node(
        "validate_and_persist_report",
        _logged_node("validate_and_persist_report", run.validate_and_persist_report),
    )
    builder.add_edge(START, "collect_market")
    builder.add_edge("collect_market", "collect_news")
    builder.add_edge("collect_news", "compute_structure")
    builder.add_conditional_edges(
        "compute_structure",
        run.evidence_gate,
        {
            "model": "generate_model_report",
            "degraded": "persist_degraded_report",
        },
    )
    builder.add_edge("generate_model_report", "validate_and_persist_report")
    builder.add_edge("persist_degraded_report", END)
    builder.add_edge("validate_and_persist_report", END)
    return builder.compile(checkpointer=checkpointer)


def _logged_node(node_name: AgentNodeName, node: AgentGraphNode) -> AgentGraphNode:
    async def invoke(state: AgentRunState) -> dict[str, object]:
        started_at = perf_counter()
        logger.info(
            "agent_research_node_started",
            analysis_id=str(state.analysis_id),
            symbol=state.symbol.value,
            node_name=node_name,
        )
        try:
            update = await node(state)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.info(
                "agent_research_node_failed",
                analysis_id=str(state.analysis_id),
                symbol=state.symbol.value,
                node_name=node_name,
            )
            logger.debug(
                "agent_research_node_details",
                analysis_id=str(state.analysis_id),
                node_name=node_name,
                phase="failed",
                error_type=type(error).__name__,
                duration_ms=_duration_ms(started_at),
            )
            raise
        error_code = _new_error_code(state, update)
        logger.info(
            "agent_research_node_completed",
            analysis_id=str(state.analysis_id),
            symbol=state.symbol.value,
            node_name=node_name,
            error_code=error_code,
        )
        logger.debug(
            "agent_research_node_details",
            analysis_id=str(state.analysis_id),
            node_name=node_name,
            phase="completed",
            error_code=error_code,
            duration_ms=_duration_ms(started_at),
            evidence_count=_evidence_count(update),
            news_source_count=_bounded_count(update, "news_source_count"),
            news_success_count=_bounded_count(update, "news_success_count"),
            news_failure_count=_bounded_count(update, "news_failure_count"),
        )
        return update

    return invoke


def _new_error_code(state: AgentRunState, update: dict[str, object]) -> str | None:
    error_codes = update.get("error_codes")
    if not isinstance(error_codes, (list, tuple)):
        return None
    values = cast(list[object] | tuple[object, ...], error_codes)
    for value in values:
        try:
            code = AgentErrorCode(value)
        except (TypeError, ValueError):
            continue
        if code not in state.error_codes:
            return code.value
    return None


def _evidence_count(update: dict[str, object]) -> int | None:
    evidence_ids = update.get("evidence_ids")
    if not isinstance(evidence_ids, (list, tuple)):
        return None
    values = cast(list[object] | tuple[object, ...], evidence_ids)
    return len(values) if len(values) <= 30 else None


def _bounded_count(update: dict[str, object], field: str) -> int | None:
    value = update.get(field)
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 30:
        return value
    return None


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1_000))
