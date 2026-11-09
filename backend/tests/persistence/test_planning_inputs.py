# 验证 C3 规划资料的 PostgreSQL 实现：单池代次、请求幂等、并发写入、时效与不可变版本。
# 测试使用专用测试库的随机 schema，只写入合成资金/费率/保证金资料。
# 并发用例通过两个独立服务实例竞争同一工作台池，证明数据库锁与唯一约束而非 UI 防重。
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.planning_inputs import (
    PlanningCostRecord,
    PlanningInputRequestRecord,
    PlanningProfileRecord,
    PlanningRiskPolicyRecord,
    PlanningVenueRuleRecord,
)
from app.infrastructure.persistence.planning_input_repository import (
    SqlAlchemyPlanningInputRepository,
)
from app.shared.agent_types import ProductKey
from app.trade_planning.input_service import PlanningInputService
from app.trade_planning.inputs import (
    CostAssumptionsDraft,
    MarginEvidenceDraft,
    PlanningGenerationConflictError,
    PlanningProfileDraft,
    PlanningProfileSnapshot,
    PlanningRequestConflictError,
    PlanningRiskPolicy,
    PlanningRiskPolicyDraft,
    VenueRuleSnapshot,
)

NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)


class Database(Protocol):
    session_factory: async_sessionmaker[AsyncSession]


# 可推进 UTC 时钟；资料过期与当日损益日期必须按服务端时钟判断。
@dataclass
class MutableClock:
    value: datetime = NOW

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


# 构造首期支持产品；动态研究币种不会自动进入规划目录。
def _product(symbol: str = "BTCUSDT") -> ProductKey:
    return ProductKey(
        venue="binance_usdm",
        symbol=symbol,
        settlement="USDT",
        kind="linear_perpetual",
    )


# 构造完整合成费率草稿；调用方可覆盖费率以证明新 profile 使用新成本版本。
def _cost_draft(
    clock: MutableClock,
    *,
    entry_fee_rate: str = "0.0004",
) -> CostAssumptionsDraft:
    return CostAssumptionsDraft.model_validate(
        {
            "entry_fee_rate": entry_fee_rate,
            "stop_exit_fee_rate": "0.0004",
            "target_exit_fee_rate": "0.0004",
            "slippage_rate": "0.0005",
            "spread_rate": "0.0001",
            "holding_cost_rate": "0.0001",
            "slippage_upper_bound": "0.001",
            "spread_upper_bound": "0.0002",
            "holding_cost_upper_bound": "0.0002",
            "source": "合成费率资料",
            "valid_until": clock.value + timedelta(minutes=30),
        }
    )


# 构造完整合成保证金证据草稿；始终标记为用户声明而非 API 核实。
def _margin_draft(clock: MutableClock) -> MarginEvidenceDraft:
    return MarginEvidenceDraft.model_validate(
        {
            "margin_mode": "isolated",
            "leverage": "2",
            "applicable_notional": "5000",
            "maintenance_margin_rate": "0.005",
            "required_margin": "250",
            "liquidation_price_reference": "40000",
            "trigger_price_basis": "mark_price",
            "source": "合成交易所界面预览",
            "valid_until": clock.value + timedelta(minutes=30),
        }
    )


# 构造完整规划资料草稿；默认全部关键项显式，缺项测试单独覆盖。
def _profile_draft(
    clock: MutableClock,
    *,
    cost_entry_fee_rate: str = "0.0004",
    daily_risk_as_of: date | None = None,
    include_costs: bool = True,
    include_margin: bool = True,
) -> PlanningProfileDraft:
    return PlanningProfileDraft.model_validate(
        {
            "product": _product().model_dump(mode="json"),
            "planning_capital": "10000",
            "available_margin": "5000",
            "remaining_single_trade_risk": "100",
            "remaining_daily_loss": "300",
            "remaining_portfolio_risk": "500",
            "existing_position_notional": "0",
            "existing_position_margin": "0",
            "existing_position_risk": "0",
            "open_order_notional": "0",
            "open_order_margin": "0",
            "open_order_risk": "0",
            "daily_risk_as_of": (
                clock.value.date() if daily_risk_as_of is None else daily_risk_as_of
            ),
            "cooldown_until": None,
            "circuit_breaker_active": False,
            "leverage": "2",
            "margin_mode": "isolated",
            "position_mode": "one_way",
            "margin_evidence": (
                _margin_draft(clock).model_dump(mode="json") if include_margin else None
            ),
            "costs": (
                _cost_draft(clock, entry_fee_rate=cost_entry_fee_rate).model_dump(mode="json")
                if include_costs
                else None
            ),
        }
    )


# 构造完整风险政策草稿；所有金额、比例和杠杆显式给出。
def _policy_draft() -> PlanningRiskPolicyDraft:
    return PlanningRiskPolicyDraft.model_validate(
        {
            "max_risk_per_trade": "100",
            "max_notional": "5000",
            "max_quantity": "2",
            "max_leverage": "3",
            "min_reward_risk_ratio": "1.5",
            "max_daily_loss": "300",
            "max_portfolio_risk": "500",
            "stop_loss_required": True,
            "enforce_cooldown": True,
            "enforce_circuit_breaker": True,
        }
    )


# 构造公开规则快照；tick 可覆盖以验证 resolve_refs 使用最新规则版本。
def _rule_snapshot(
    clock: MutableClock,
    *,
    price_tick: str = "0.10",
    product: ProductKey | None = None,
) -> VenueRuleSnapshot:
    observed_at = clock.value
    return VenueRuleSnapshot.build(
        version_id=uuid4(),
        product=product or _product(),
        contract_multiplier="1",
        quantity_unit="base_asset",
        price_tick=price_tick,
        min_price="556.80",
        max_price="4529764",
        quantity_step="0.001",
        min_quantity="0.001",
        max_quantity="1000",
        market_min_quantity="0.001",
        market_max_quantity="120",
        market_quantity_step="0.001",
        min_notional="100",
        trading_status="TRADING",
        order_types=("LIMIT", "MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET"),
        time_in_force=("GTC", "IOC", "FOK"),
        observed_at=observed_at,
        expires_at=observed_at + timedelta(minutes=60),
        source="binance_usdm_public_exchange_info",
    )


# 按顺序返回预置规则快照的替身读取器；不联网，也不模拟未声明私有接口。
@dataclass
class QueueRuleReader:
    clock: MutableClock
    ticks: list[str] = field(default_factory=lambda: ["0.10"])
    calls: int = 0

    async def load(self, product: ProductKey) -> VenueRuleSnapshot:
        index = min(self.calls, len(self.ticks) - 1)
        self.calls += 1
        return _rule_snapshot(self.clock, price_tick=self.ticks[index], product=product)


# 组装使用同一时钟的仓储与领域服务；规则读取器只用于 refresh 入口。
def _service(
    database: Database,
    clock: MutableClock,
    *,
    reader: QueueRuleReader | None = None,
) -> tuple[PlanningInputService, SqlAlchemyPlanningInputRepository]:
    repository = SqlAlchemyPlanningInputRepository(database.session_factory, clock=clock)
    service = PlanningInputService(
        repository,
        rule_reader=reader or QueueRuleReader(clock),
        clock=clock,
    )
    return service, repository


async def _prepare_complete_refs(
    database: Database,
    clock: MutableClock,
    *,
    reader: QueueRuleReader | None = None,
) -> tuple[
    PlanningInputService,
    SqlAlchemyPlanningInputRepository,
    UUID,
    PlanningProfileSnapshot,
    PlanningRiskPolicy,
    VenueRuleSnapshot,
]:
    service, repository = _service(database, clock, reader=reader)
    workspace_id = uuid4()
    profile = await service.create_profile(
        workspace_id,
        _profile_draft(clock),
        request_id=uuid4(),
        expected_generation=0,
    )
    policy = await service.create_policy(
        workspace_id,
        _policy_draft(),
        request_id=uuid4(),
        expected_generation=1,
    )
    rules = await service.refresh_venue_rules(
        workspace_id,
        _product(),
        request_id=uuid4(),
    )
    return service, repository, workspace_id, profile, policy, rules


@pytest.mark.asyncio
async def test_profile_and_policy_versions_are_idempotent_and_advance_generation(
    migrated_database: Database,
) -> None:
    clock = MutableClock()
    service, repository = _service(migrated_database, clock)
    workspace_id = uuid4()
    draft = _profile_draft(clock)
    request_id = uuid4()

    profile = await service.create_profile(
        workspace_id,
        draft,
        request_id=request_id,
        expected_generation=0,
    )
    assert profile.pool_generation == 1
    assert profile.is_complete is True

    replay = await service.create_profile(
        workspace_id,
        draft,
        request_id=request_id,
        expected_generation=0,
    )
    assert replay.ref == profile.ref
    pool = await repository.get_pool(workspace_id)
    assert pool is not None and pool.generation == 1

    policy_request = uuid4()
    policy = await service.create_policy(
        workspace_id,
        _policy_draft(),
        request_id=policy_request,
        expected_generation=1,
    )
    assert policy.pool_generation == 2
    policy_replay = await service.create_policy(
        workspace_id,
        _policy_draft(),
        request_id=policy_request,
        expected_generation=1,
    )
    assert policy_replay.ref == policy.ref
    pool = await repository.get_pool(workspace_id)
    assert pool is not None and pool.generation == 2


@pytest.mark.asyncio
async def test_stale_generation_and_reused_request_id_are_rejected(
    migrated_database: Database,
) -> None:
    clock = MutableClock()
    service, repository = _service(migrated_database, clock)
    workspace_id = uuid4()
    first_request = uuid4()
    await service.create_profile(
        workspace_id,
        _profile_draft(clock),
        request_id=first_request,
        expected_generation=0,
    )

    with pytest.raises(PlanningGenerationConflictError):
        await service.create_profile(
            workspace_id,
            _profile_draft(clock),
            request_id=uuid4(),
            expected_generation=0,
        )

    # 同一请求键不能换成另一份资料；即使代次正确也拒绝。
    with pytest.raises(PlanningRequestConflictError):
        await service.create_profile(
            workspace_id,
            _profile_draft(clock, cost_entry_fee_rate="0.0005"),
            request_id=first_request,
            expected_generation=1,
        )

    pool = await repository.get_pool(workspace_id)
    assert pool is not None and pool.generation == 1


@pytest.mark.asyncio
async def test_resolve_refs_requires_complete_current_versions(
    migrated_database: Database,
) -> None:
    clock = MutableClock()
    service, repository = _service(migrated_database, clock)
    workspace_id = uuid4()

    incomplete = await service.create_profile(
        workspace_id,
        _profile_draft(clock, include_costs=False, include_margin=False),
        request_id=uuid4(),
        expected_generation=0,
    )
    assert incomplete.is_complete is False
    policy = await service.create_policy(
        workspace_id,
        _policy_draft(),
        request_id=uuid4(),
        expected_generation=1,
    )
    rules = await service.refresh_venue_rules(
        workspace_id,
        _product(),
        request_id=uuid4(),
    )
    assert await service.resolve_refs(workspace_id) is None

    # 完整资料产生新 profile 和成本版本，四个引用齐备后才可组合 PlanningRefs。
    complete = await service.create_profile(
        workspace_id,
        _profile_draft(clock),
        request_id=uuid4(),
        expected_generation=3,
    )
    assert complete.is_complete is True
    refs = await service.resolve_refs(workspace_id)
    assert refs is not None
    assert refs.profile == complete.ref
    assert refs.policy == policy.ref
    assert refs.venue_rules == rules.ref
    assert refs.costs == complete.costs_ref
    assert refs.pool_generation == 4
    pool = await repository.get_pool(workspace_id)
    assert pool is not None and pool.generation == 4


@pytest.mark.asyncio
async def test_resolve_rejects_expired_profile_and_stale_daily_declaration(
    migrated_database: Database,
) -> None:
    clock = MutableClock()
    service, _, workspace_id, _, _, _ = await _prepare_complete_refs(migrated_database, clock)
    assert await service.resolve_refs(workspace_id) is not None

    clock.advance(timedelta(minutes=16))
    assert await service.resolve_refs(workspace_id) is None

    # 新资料即使未过期，昨日亏损声明也不能用于今日规划。
    stale = await service.create_profile(
        workspace_id,
        _profile_draft(
            clock,
            daily_risk_as_of=clock.value.date() - timedelta(days=1),
        ),
        request_id=uuid4(),
        expected_generation=await _generation(service, workspace_id),
    )
    assert stale.is_expired(clock.value) is False
    assert await service.resolve_refs(workspace_id) is None


@pytest.mark.asyncio
async def test_new_policy_invalidates_generation_and_latest_versions_are_used(
    migrated_database: Database,
) -> None:
    clock = MutableClock()
    service, repository, workspace_id, profile, first_policy, rules = await _prepare_complete_refs(
        migrated_database, clock
    )
    first_refs = await service.resolve_refs(workspace_id)
    assert first_refs is not None

    new_policy = await service.create_policy(
        workspace_id,
        _policy_draft(),
        request_id=uuid4(),
        expected_generation=3,
    )
    assert new_policy.ref != first_policy.ref
    refs = await service.resolve_refs(workspace_id)
    assert refs is not None
    assert refs.policy == new_policy.ref
    assert refs.profile == profile.ref
    assert refs.pool_generation == 4

    # 旧版本仍按引用读取，不被新政策覆盖；新 profile 关联新的成本版本。
    old_cost = await repository.get_costs(workspace_id, profile.costs_ref)
    assert old_cost is not None
    new_profile = await service.create_profile(
        workspace_id,
        _profile_draft(clock, cost_entry_fee_rate="0.0005"),
        request_id=uuid4(),
        expected_generation=4,
    )
    new_refs = await service.resolve_refs(workspace_id)
    assert new_refs is not None
    assert new_refs.profile == new_profile.ref
    assert new_refs.costs == new_profile.costs_ref
    assert new_refs.costs != profile.costs_ref
    new_cost = await repository.get_costs(workspace_id, new_profile.costs_ref)
    assert new_cost is not None
    assert new_cost.entry_fee_rate == Decimal("0.0005")
    assert old_cost.entry_fee_rate == Decimal("0.0004")
    assert rules.ref == first_refs.venue_rules


@pytest.mark.asyncio
async def test_venue_rule_versions_are_immutable_and_latest_is_used(
    migrated_database: Database,
) -> None:
    clock = MutableClock()
    reader = QueueRuleReader(clock, ticks=["0.10", "0.20", "0.50"])
    service, repository = _service(migrated_database, clock, reader=reader)
    workspace_id = uuid4()
    await service.create_profile(
        workspace_id,
        _profile_draft(clock),
        request_id=uuid4(),
        expected_generation=0,
    )
    await service.create_policy(
        workspace_id,
        _policy_draft(),
        request_id=uuid4(),
        expected_generation=1,
    )
    first = await service.refresh_venue_rules(
        workspace_id,
        _product(),
        request_id=uuid4(),
    )
    second = await service.refresh_venue_rules(
        workspace_id,
        _product(),
        request_id=uuid4(),
    )
    assert first.ref != second.ref
    assert first.price_tick == Decimal("0.10")
    assert second.price_tick == Decimal("0.20")

    refs = await service.resolve_refs(workspace_id)
    assert refs is not None
    assert refs.venue_rules == second.ref
    assert refs.pool_generation == 4
    stored_first = await repository.get_venue_rules(workspace_id, first.ref)
    assert stored_first is not None and stored_first.price_tick == Decimal("0.10")

    # 直接 UPDATE 规则版本必须被数据库触发器拒绝。
    async with migrated_database.session_factory() as session:
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                update(PlanningVenueRuleRecord).values(document=PlanningVenueRuleRecord.document)
            )


@pytest.mark.asyncio
async def test_duplicate_rule_refresh_request_replays_first_snapshot(
    migrated_database: Database,
) -> None:
    clock = MutableClock()
    reader = QueueRuleReader(clock, ticks=["0.10", "0.20"])
    service, repository = _service(migrated_database, clock, reader=reader)
    workspace_id = uuid4()
    await service.create_profile(
        workspace_id,
        _profile_draft(clock),
        request_id=uuid4(),
        expected_generation=0,
    )
    await service.create_policy(
        workspace_id,
        _policy_draft(),
        request_id=uuid4(),
        expected_generation=1,
    )
    request_id = uuid4()
    first = await service.refresh_venue_rules(
        workspace_id,
        _product(),
        request_id=request_id,
    )
    replay = await service.refresh_venue_rules(
        workspace_id,
        _product(),
        request_id=request_id,
    )
    assert replay.ref == first.ref
    assert replay.price_tick == Decimal("0.10")
    pool = await repository.get_pool(workspace_id)
    assert pool is not None and pool.generation == 3


@pytest.mark.asyncio
async def test_concurrent_profile_creation_allows_one_generation_writer(
    migrated_database: Database,
) -> None:
    clock = MutableClock()
    service, repository = _service(migrated_database, clock)
    workspace_id = uuid4()
    draft = _profile_draft(clock)

    results = await asyncio.gather(
        service.create_profile(
            workspace_id,
            draft,
            request_id=uuid4(),
            expected_generation=0,
        ),
        service.create_profile(
            workspace_id,
            draft,
            request_id=uuid4(),
            expected_generation=0,
        ),
        return_exceptions=True,
    )
    successes = [item for item in results if isinstance(item, PlanningProfileSnapshot)]
    conflicts = [item for item in results if isinstance(item, PlanningGenerationConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1

    pool = await repository.get_pool(workspace_id)
    assert pool is not None and pool.generation == 1
    async with migrated_database.session_factory() as session:
        profile_count = await session.scalar(
            select(func.count()).select_from(PlanningProfileRecord)
        )
        request_count = await session.scalar(
            select(func.count()).select_from(PlanningInputRequestRecord)
        )
    assert profile_count == 1
    assert request_count == 1


@pytest.mark.asyncio
async def test_planning_version_tables_reject_update_and_delete(
    migrated_database: Database,
) -> None:
    clock = MutableClock()
    service, _, workspace_id, _, _, _ = await _prepare_complete_refs(migrated_database, clock)
    assert await service.resolve_refs(workspace_id) is not None

    statements = (
        update(PlanningProfileRecord).values(document=PlanningProfileRecord.document),
        delete(PlanningProfileRecord),
        update(PlanningCostRecord).values(document=PlanningCostRecord.document),
        delete(PlanningRiskPolicyRecord),
        update(PlanningInputRequestRecord).values(result=PlanningInputRequestRecord.result),
    )
    for statement in statements:
        async with migrated_database.session_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(statement)


# 读取当前池代次作为下一次乐观并发写入的期望值；仅测试辅助，不替代生产 API。
async def _generation(service: PlanningInputService, workspace_id: UUID) -> int:
    pool = await service.get_pool(workspace_id)
    assert pool is not None
    return pool.generation
