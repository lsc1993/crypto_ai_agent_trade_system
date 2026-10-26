# 综合研究只允许预定义的固定节点与条件边，模型不参与节点选择或工具路由。
# 所有大载荷留在请求内运行对象；图状态和节点日志仅记录可关联的安全元数据。
"""受控 Agent 研究图编排模块。

数据流：采集冻结行情与新闻 → 计算确定性市场结构 → 证据门控 → 模型提案验证或
降级报告持久化。图状态只保存 ID、计数和错误码，原始载荷保留在请求运行对象中。
"""

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


# 注入一次研究运行的节点端口；节点返回轻量状态更新，实际证据由运行对象持有。
class AgentGraphRun(Protocol):
    """单次请求的节点实现接口；大载荷始终保留在运行对象中，不写入图状态。"""

    # 冻结行情并关联快照，失败只更新受控错误，供后续统一选择降级路径。
    async def collect_market(self, state: AgentRunState) -> dict[str, object]: ...

    # 收集固定窗口的新闻和独立专题，返回来源计数与本次证据标识。
    async def collect_news(self, state: AgentRunState) -> dict[str, object]: ...

    # 质量门通过才计算趋势与区间；模型配置缺失也在此设置降级原因。
    async def compute_structure(self, state: AgentRunState) -> dict[str, object]: ...

    # 门控由运行对象的确定性错误状态决定，不接受模型选择的节点名称。
    def evidence_gate(self, state: AgentRunState) -> Literal["model", "degraded"]: ...

    # 只发送本次冻结研究上下文，候选失败在最终保存节点转成降级结果。
    async def generate_model_report(self, state: AgentRunState) -> dict[str, object]: ...

    # 证据不足分支直接保存已有事实载荷及限制，不伪造模型结论。
    async def persist_degraded_report(self, state: AgentRunState) -> dict[str, object]: ...

    # 综合候选和降级状态确定终态，关联报告与证据后才允许图结束。
    async def validate_and_persist_report(
        self,
        state: AgentRunState,
    ) -> dict[str, object]: ...


# 证据门只在模型生成与降级保存间分支，任一路径都以不可变报告保存结束。
def build_agent_graph(
    run: AgentGraphRun,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None,
) -> Any:
    """编译唯一允许的市场研究控制流。

        收集节点按固定顺序运行；只有 evidence_gate 放行才调用模型，否则直接持久化
        降级报告。checkpointer 仅保存轻量状态，以便审计或恢复而不复制不可信正文。
    """

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
    # 行情、新闻和结构顺序固定；新闻内容不能让图跳过质量门或插入新节点。
    builder.add_edge(START, "collect_market")
    builder.add_edge("collect_market", "collect_news")
    builder.add_edge("collect_news", "compute_structure")
    builder.add_conditional_edges(
        "compute_structure",
        # 只有冻结证据和确定性结构分析均有效时才允许调用模型；否则直接生成降级报告。
        run.evidence_gate,
        {
            "model": "generate_model_report",
            "degraded": "persist_degraded_report",
        },
    )
    # 模型生成失败仍经过最终保存节点，所以生成提案不等于报告完成。
    builder.add_edge("generate_model_report", "validate_and_persist_report")
    builder.add_edge("persist_degraded_report", END)
    builder.add_edge("validate_and_persist_report", END)
    return builder.compile(checkpointer=checkpointer)


def _logged_node(node_name: AgentNodeName, node: AgentGraphNode) -> AgentGraphNode:
    """为节点包裹受控生命周期日志，并保留取消和原始异常的传播语义。"""
    async def invoke(state: AgentRunState) -> dict[str, object]:
        started_at = perf_counter()
        logger.info(
            "agent_research_node_started",
            analysis_id=str(state.analysis_id),
            symbol=state.symbol,
            node_name=node_name,
        )
        try:
            update = await node(state)
        # 请求取消由调用方处理，不转换为节点成功或普通错误结果。
        except asyncio.CancelledError:
            raise
        # 异常只记录类型和耗时，不能把异常正文中的上游载荷写入安全日志。
        except Exception as error:
            logger.info(
                "agent_research_node_failed",
                analysis_id=str(state.analysis_id),
                symbol=state.symbol,
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
        # 运行日志只记录受控的统计字段和错误码，不记录模型、新闻或行情正文。
        error_code = _new_error_code(state, update)
        logger.info(
            "agent_research_node_completed",
            analysis_id=str(state.analysis_id),
            symbol=state.symbol,
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
        # 包装器只补充日志，原节点更新原样交回图状态校验，不能吞掉字段。
        return update

    return invoke


def _new_error_code(state: AgentRunState, update: dict[str, object]) -> str | None:
    """找出本节点新增的受控错误码，供日志记录而不解析或回显原始异常。"""
    error_codes = update.get("error_codes")
    if not isinstance(error_codes, (list, tuple)):
        return None
    values = cast(list[object] | tuple[object, ...], error_codes)
    # 只取新出现的有限错误；非法值跳过，不能作为任意字符串写入节点诊断。
    for value in values:
        try:
            code = AgentErrorCode(value)
        except (TypeError, ValueError):
            continue
        if code not in state.error_codes:
            return code.value
    return None


# 计数上限与状态证据上限一致；异常容器不用于诊断，也不输出证据本体。
def _evidence_count(update: dict[str, object]) -> int | None:
    evidence_ids = update.get("evidence_ids")
    if not isinstance(evidence_ids, (list, tuple)):
        return None
    values = cast(list[object] | tuple[object, ...], evidence_ids)
    return len(values) if len(values) <= 30 else None


# 诊断计数限定范围并排除布尔值，避免利用宽松整数类型把异常字段写入日志。
def _bounded_count(update: dict[str, object], field: str) -> int | None:
    value = update.get(field)
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 30:
        return value
    return None


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1_000))
