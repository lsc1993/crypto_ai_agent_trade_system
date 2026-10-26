# 综合研究报告仓储协议，将领域结果保存与分页读取从生成流程中隔离。
# Agent 扩展另设保存方法，普通确定性报告替身无需承担模型研究字段。
from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app.reports.contracts import (
    AgentReportCreation,
    AnalysisReportCreation,
    AnalysisReportStatus,
    PersistedAnalysisReport,
    ReportPage,
)


# 保存报告与冻结证据并提供标识、运行标识和分页查询；具体事务由实现负责。
class AnalysisReportRepository(Protocol):
    # 保存一个报告创建对象并返回持久化详情，不允许生成服务自行更新历史报告。
    async def persist(
        self,
        creation: AnalysisReportCreation,
    ) -> PersistedAnalysisReport: ...

    async def get_by_id(self, report_id: UUID) -> PersistedAnalysisReport | None: ...

    async def get_by_analysis_id(
        self,
        analysis_id: UUID,
    ) -> PersistedAnalysisReport | None: ...

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        symbol: Any | None,
        status: AnalysisReportStatus | None,
    ) -> ReportPage: ...


# 扩展保存研究运行和结构化分析，仍沿用普通报告的读取协议。
class AgentAnalysisReportRepository(AnalysisReportRepository, Protocol):
    """Agent-capable extension that keeps deterministic repository fakes compatible."""

    # 将研究时段、模型结果和同一证据关联作为完整创建对象交给仓储。
    async def persist_agent(
        self,
        creation: AgentReportCreation,
    ) -> PersistedAnalysisReport: ...
