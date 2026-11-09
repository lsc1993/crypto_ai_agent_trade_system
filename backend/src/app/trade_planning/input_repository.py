# 声明手动规划输入仓储与公开规则读取端口；领域服务只依赖协议，不依赖 SQLAlchemy。
# 仓储事务负责单工作台唯一资金池、代次递增、请求幂等和不可变版本读写；
# 公开规则读取端口只返回已校验证的 VenueRuleSnapshot，不暴露私有账户或交易所凭证。
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import Field

from app.shared.agent_types import AgentModel, ProductKey, VersionRef
from app.trade_planning.inputs import (
    CostAssumptions,
    PlanningProfileDraft,
    PlanningProfileSnapshot,
    PlanningRiskPolicy,
    PlanningRiskPolicyDraft,
    VenueRuleSnapshot,
)


# 工作台唯一逻辑资金池；generation 是资料/政策/规则变化的共享失效代次。
class PlanningPool(AgentModel):
    pool_id: UUID
    workspace_id: UUID
    generation: int = Field(ge=0)


# 一次一致性读取得到的当前输入组合；任何一项缺失以 None 表示，由服务层判定待补。
@dataclass(frozen=True)
class CurrentPlanningInputs:
    pool: PlanningPool
    profile: PlanningProfileSnapshot
    policy: PlanningRiskPolicy | None
    venue_rules: VenueRuleSnapshot | None
    costs: CostAssumptions | None


# 公开规则读取端口：输入固定产品键，输出带来源、观测时刻和有效期的规则快照。
class PublicRuleReader(Protocol):
    async def load(self, product: ProductKey) -> VenueRuleSnapshot: ...


# 规划输入仓储端口；写方法负责事务、行锁和组织代次，调用方不直接操作会话。
class PlanningInputRepository(Protocol):
    async def get_pool(self, workspace_id: UUID) -> PlanningPool | None: ...

    async def create_profile(
        self,
        workspace_id: UUID,
        draft: PlanningProfileDraft,
        *,
        request_id: UUID,
        expected_generation: int,
    ) -> PlanningProfileSnapshot: ...

    async def create_policy(
        self,
        workspace_id: UUID,
        draft: PlanningRiskPolicyDraft,
        *,
        request_id: UUID,
        expected_generation: int,
    ) -> PlanningRiskPolicy: ...

    async def record_venue_rules(
        self,
        workspace_id: UUID,
        snapshot: VenueRuleSnapshot,
        *,
        request_id: UUID,
    ) -> VenueRuleSnapshot: ...

    async def replay_venue_rules(
        self,
        workspace_id: UUID,
        product: ProductKey,
        *,
        request_id: UUID,
    ) -> VenueRuleSnapshot | None: ...

    async def resolve_current(
        self,
        workspace_id: UUID,
    ) -> CurrentPlanningInputs | None: ...

    async def get_profile(
        self,
        workspace_id: UUID,
        ref: VersionRef,
    ) -> PlanningProfileSnapshot | None: ...

    async def get_policy(
        self,
        workspace_id: UUID,
        ref: VersionRef,
    ) -> PlanningRiskPolicy | None: ...

    async def get_venue_rules(
        self,
        workspace_id: UUID,
        ref: VersionRef,
    ) -> VenueRuleSnapshot | None: ...

    async def get_costs(
        self,
        workspace_id: UUID,
        ref: VersionRef | None,
    ) -> CostAssumptions | None: ...


__all__ = [
    "CurrentPlanningInputs",
    "PlanningInputRepository",
    "PlanningPool",
    "PublicRuleReader",
]
