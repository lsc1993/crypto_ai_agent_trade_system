# 手动规划输入服务：校验支持范围、时效与完整引用，不执行数量/风险计算或交易。
# 写操作委托仓储处理事务、单池代次和请求幂等；服务只做产品范围、规则来源和待补判定。
# resolve_refs 只返回当时同池的当前合法版本引用，不返回完整财务载荷，也不刷新资料。
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from app.shared.agent_types import ProductKey, require_utc
from app.trade_planning.input_repository import (
    CurrentPlanningInputs,
    PlanningInputRepository,
    PlanningPool,
    PublicRuleReader,
)
from app.trade_planning.inputs import (
    PlanningInputError,
    PlanningIntegrityError,
    PlanningProfileDraft,
    PlanningProfileSnapshot,
    PlanningRefs,
    PlanningRiskPolicy,
    PlanningRiskPolicyDraft,
    PlanningRuleUnavailableError,
    VenueRuleSnapshot,
)
from app.trade_planning.product_support import PlanningProductCatalog


# 本地规划输入服务；clock 可注入以稳定测试资料时效和当日损益日期判断。
class PlanningInputService:
    def __init__(
        self,
        repository: PlanningInputRepository,
        *,
        rule_reader: PublicRuleReader | None = None,
        catalog: PlanningProductCatalog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._rule_reader = rule_reader
        self._catalog = catalog or PlanningProductCatalog()
        self._clock = clock or (lambda: datetime.now(UTC))

    # 服务端时钟必须返回 UTC；客户端时间不能用于证明资料/规则仍有效。
    def _now(self) -> datetime:
        return require_utc(self._clock())

    # 查询当前资金池代次；客户端提交修改前据此提供 expected_generation。
    async def get_pool(self, workspace_id: UUID) -> PlanningPool | None:
        return await self._repository.get_pool(workspace_id)

    # 创建不可变资料版本；成本与保证金在同一仓储事务中冻结，产品范围在此先行拒绝。
    async def create_profile(
        self,
        workspace_id: UUID,
        draft: PlanningProfileDraft,
        *,
        request_id: UUID,
        expected_generation: int,
    ) -> PlanningProfileSnapshot:
        self._catalog.require_supported(draft.product)
        return await self._repository.create_profile(
            workspace_id,
            draft,
            request_id=request_id,
            expected_generation=expected_generation,
        )

    # 创建风险政策版本；缺项政策可保存，但 resolve_refs 不会把它当作完整政策。
    async def create_policy(
        self,
        workspace_id: UUID,
        draft: PlanningRiskPolicyDraft,
        *,
        request_id: UUID,
        expected_generation: int,
    ) -> PlanningRiskPolicy:
        return await self._repository.create_policy(
            workspace_id,
            draft,
            request_id=request_id,
            expected_generation=expected_generation,
        )

    # 读取并冻结当前公开规则快照；规则读取失败不写入任何版本，也不回退旧规则冒充当前。
    async def refresh_venue_rules(
        self,
        workspace_id: UUID,
        product: ProductKey,
        *,
        request_id: UUID,
    ) -> VenueRuleSnapshot:
        self._catalog.require_supported(product)
        if self._rule_reader is None:
            raise PlanningRuleUnavailableError("公开规则读取端口未配置")
        snapshot = await self._rule_reader.load(product)
        if snapshot.product != product:
            raise PlanningRuleUnavailableError("公开规则快照与请求产品不一致")
        now = self._now()
        if snapshot.observed_at > now:
            raise PlanningRuleUnavailableError("公开规则观测时间不能晚于服务端当前时间")
        if snapshot.expires_at <= now:
            raise PlanningRuleUnavailableError("公开规则快照已过期")
        return await self._repository.record_venue_rules(
            workspace_id,
            snapshot,
            request_id=request_id,
        )

    # 组合当前合法引用；任何关键资料缺失、过期、跨日或模式不一致都返回 None。
    # 这里不回填零值、不选择旧版本，也不把“不完整”误报成可规划状态。
    async def resolve_refs(self, workspace_id: UUID) -> PlanningRefs | None:
        current = await self._repository.resolve_current(workspace_id)
        if current is None:
            return None
        if not _is_current(current, self._now(), self._catalog):
            return None
        profile = current.profile
        policy = current.policy
        rules = current.venue_rules
        costs = current.costs
        # 通过完整性检查后这些值必须存在；防御性校验避免未来分支绕过。
        if (
            profile.costs_ref is None
            or profile.margin_evidence is None
            or policy is None
            or rules is None
            or costs is None
        ):
            return None
        if profile.costs_ref != costs.ref:
            raise PlanningIntegrityError("规划资料成本引用与成本版本不一致")
        if policy.pool_id != profile.pool_id:
            raise PlanningIntegrityError("风险政策与规划资料不属于同一资金池")
        if rules.product != profile.product:
            raise PlanningIntegrityError("公开规则与规划产品不一致")
        if current.pool.pool_id != profile.pool_id:
            raise PlanningIntegrityError("规划资料与当前资金池不一致")
        if profile.pool_generation > current.pool.generation:
            raise PlanningIntegrityError("规划资料代次晚于当前资金池")
        return PlanningRefs(
            profile=profile.ref,
            policy=policy.ref,
            venue_rules=rules.ref,
            costs=costs.ref,
            pool_id=profile.pool_id,
            pool_generation=current.pool.generation,
        )


# 当前输入组合是否仍可组合：完整性、时效、UTC 当日声明和产品范围均须通过。
def _is_current(
    current: CurrentPlanningInputs,
    now: datetime,
    catalog: PlanningProductCatalog,
) -> bool:
    profile = current.profile
    if profile.is_expired(now):
        return False
    if not profile.is_complete:
        return False
    if profile.daily_risk_as_of != now.date():
        return False
    if profile.declared_at > now:
        return False
    policy = current.policy
    if policy is None or not policy.is_complete or policy.declared_at > now:
        return False
    rules = current.venue_rules
    if rules is None or rules.expires_at <= now or rules.observed_at > now:
        return False
    costs = current.costs
    if costs is None or costs.expires_at <= now:
        return False
    evidence = profile.margin_evidence
    if evidence is None or evidence.expires_at <= now or not evidence.is_complete:
        return False
    # 产品目录可能随版本变化；当前资料仍须属于当前支持范围。
    if not catalog.accepts(
        profile.product.symbol,
        mode=profile.margin_mode or "",
        position_mode=profile.position_mode or "",
    ):
        return False
    return True


# 服务层错误映射保持稳定入口；调用方只需捕获 PlanningInputError 及其子类。
PlanningServiceError = PlanningInputError


__all__ = ["PlanningInputService", "PlanningServiceError"]
