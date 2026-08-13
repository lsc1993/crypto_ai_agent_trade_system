from __future__ import annotations

from typing import Any, Literal, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]

from app.agent.contracts import AgentRunState


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
    builder.add_node("collect_market", run.collect_market)
    builder.add_node("collect_news", run.collect_news)
    builder.add_node("compute_structure", run.compute_structure)
    builder.add_node("generate_model_report", run.generate_model_report)
    builder.add_node("persist_degraded_report", run.persist_degraded_report)
    builder.add_node("validate_and_persist_report", run.validate_and_persist_report)
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
