# 声明策略目录与只读评估器的异步端口；研究策略层不依赖 Agent、SQLAlchemy 或交易执行。
# 目录端口负责版本发布/停用，评估器端口只接收精确版本、参数和冻结证据并返回类型化结果。
# 具体仓储与适配器在基础设施/Agent 适配层实现，研究层不反向依赖它们。
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import JsonValue

from app.research.evidence import EvidenceEpoch
from app.research.strategies.contracts import (
    StrategyDraft,
    StrategyEvaluation,
    StrategyVersion,
)
from app.shared.agent_types import PageQuery, VersionPage, VersionRef


# 策略目录端口：所有写操作要求调用方提供幂等 request_id 和乐观并发版本。
class StrategyCatalog(Protocol):
    async def get_published(self, workspace_id: UUID, ref: VersionRef) -> StrategyVersion: ...

    async def publish(
        self,
        workspace_id: UUID,
        draft_id: UUID,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> StrategyVersion: ...

    async def create_draft(
        self,
        workspace_id: UUID,
        draft: StrategyDraft,
        *,
        request_id: UUID,
    ) -> StrategyDraft: ...

    async def update_draft(
        self,
        workspace_id: UUID,
        draft_id: UUID,
        draft: StrategyDraft,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> StrategyDraft: ...

    async def list_versions(
        self, workspace_id: UUID, query: PageQuery
    ) -> VersionPage[StrategyVersion]: ...

    async def archive(
        self,
        workspace_id: UUID,
        strategy_id: UUID,
        *,
        expected_version: int,
        request_id: UUID,
    ) -> None: ...


# 只读评估器端口：评估器 ID 与服务查询键必须完全一致，禁止回退到其他策略实现。
class StrategyEvaluator(Protocol):
    evaluator_id: str
    evaluator_version: str

    async def evaluate(
        self,
        strategy: StrategyVersion,
        parameters: dict[str, JsonValue],
        evidence: EvidenceEpoch,
    ) -> StrategyEvaluation: ...


__all__ = ["StrategyCatalog", "StrategyEvaluator"]
