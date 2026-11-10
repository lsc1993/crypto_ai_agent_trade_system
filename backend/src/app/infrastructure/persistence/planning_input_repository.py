# 用 PostgreSQL 事务实现 C3 本地规划输入仓储：唯一资金池、代次递增、请求幂等和不可变版本。
# 写入顺序固定为请求锁 -> 资金池行锁 -> 时间采样 -> 版本构建 -> 请求结果；同一事务提交。
# 事务在持久化边界采样服务端时间；客户端时间、旧 ref 或旧 generation 不能推进业务。
# 该仓储不访问交易所、账户、模型或执行服务，只从本地资料和已冻结公开规则读取。
from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue, ValidationError
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.persistence.models.planning_inputs import (
    PlanningCostRecord,
    PlanningInputRequestRecord,
    PlanningPoolRecord,
    PlanningProfileRecord,
    PlanningRiskPolicyRecord,
    PlanningVenueRuleRecord,
)
from app.shared.agent_types import (
    JsonObject,
    ProductKey,
    VersionRef,
    require_utc,
    sha256_json,
)
from app.trade_planning.input_repository import (
    CurrentPlanningInputs,
    PlanningPool,
)
from app.trade_planning.inputs import (
    PROFILE_VALIDITY,
    CostAssumptions,
    CostAssumptionsDraft,
    MarginEvidence,
    MarginEvidenceDraft,
    PlanningGenerationConflictError,
    PlanningInputExpiredError,
    PlanningIntegrityError,
    PlanningProfileDraft,
    PlanningProfileSnapshot,
    PlanningRepositoryError,
    PlanningRequestConflictError,
    PlanningRiskPolicy,
    PlanningRiskPolicyDraft,
    VenueRuleSnapshot,
)

_ACTION_CREATE_PROFILE = "create_profile"
_ACTION_CREATE_POLICY = "create_policy"
_ACTION_REFRESH_RULES = "refresh_venue_rules"


# 请求重放快照只保留已提交 JSON 结果，不暴露 ORM 会话或异常。
class _RequestSnapshot:
    def __init__(self, result: dict[str, object] | None) -> None:
        self.result = result


# SQL 规划输入仓储；clock 可注入以稳定资料/规则时效和订单记录时间。
class SqlAlchemyPlanningInputRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    # 服务端时间必须带时区 UTC；所有时效与审计判断使用同一时钟。
    def _now(self) -> datetime:
        return require_utc(self._clock())

    # 读取当前资金池；不存在返回 None，由调用方以 expected_generation=0 创建。
    async def get_pool(self, workspace_id: UUID) -> PlanningPool | None:
        try:
            async with self._factory() as session:
                row = await session.scalar(
                    select(PlanningPoolRecord).where(
                        PlanningPoolRecord.workspace_id == workspace_id
                    )
                )
        except SQLAlchemyError:
            raise PlanningRepositoryError("规划资金池读取不可用") from None
        if row is None:
            return None
        return PlanningPool(
            pool_id=row.id,
            workspace_id=row.workspace_id,
            generation=row.generation,
        )

    # 创建不可变资料版本；同一 request_id 重放返回原结果，generation 不符拒绝。
    async def create_profile(
        self,
        workspace_id: UUID,
        draft: PlanningProfileDraft,
        *,
        request_id: UUID,
        expected_generation: int,
    ) -> PlanningProfileSnapshot:
        draft_payload = _draft_payload(draft)
        request_shas = _profile_request_shas(
            workspace_id,
            draft_payload,
            expected_generation,
        )
        request_sha = request_shas[0]
        try:
            async with self._factory() as session, session.begin():
                await _lock_request(session, request_id)
                replay = await _load_request(
                    session,
                    request_id,
                    workspace_id,
                    _ACTION_CREATE_PROFILE,
                    request_shas,
                )
                if replay is not None:
                    return _profile_result(replay)
                # 重放未命中才进入新版首次写入；这里执行严格冷却语义。
                draft.require_current_semantics()
                pool = await _ensure_pool(session, workspace_id, self._now())
                if pool.generation != expected_generation:
                    raise PlanningGenerationConflictError("规划资金池代次已变化，请重新读取")
                now = self._now()
                cost = _build_cost(draft.costs, now)
                margin = _build_margin(draft.margin_evidence, now)
                profile_generation = pool.generation + 1
                expires_at = _profile_expiry(now, cost, margin)
                profile = PlanningProfileSnapshot.build(
                    version_id=uuid4(),
                    pool_id=pool.id,
                    pool_generation=profile_generation,
                    draft=draft,
                    margin_evidence=margin,
                    costs_ref=None if cost is None else cost.ref,
                    declared_at=now,
                    expires_at=expires_at,
                )
                if cost is not None:
                    session.add(
                        _cost_row(
                            cost,
                            workspace_id=workspace_id,
                            pool_id=pool.id,
                            pool_generation=profile_generation,
                            now=now,
                        )
                    )
                session.add(
                    _profile_row(
                        profile,
                        workspace_id=workspace_id,
                        pool_id=pool.id,
                        now=now,
                    )
                )
                pool.generation = profile_generation
                pool.updated_at = now
                _store_request(
                    session,
                    request_id=request_id,
                    workspace_id=workspace_id,
                    action=_ACTION_CREATE_PROFILE,
                    request_sha256=request_sha,
                    result=_snapshot_payload(profile),
                    now=now,
                )
            return profile
        except IntegrityError:
            replayed = await self._replay_request(
                request_id,
                workspace_id,
                _ACTION_CREATE_PROFILE,
                request_shas,
            )
            if replayed is not None:
                return _profile_result(replayed)
            raise PlanningGenerationConflictError("规划资料写入冲突，请重新读取") from None
        except SQLAlchemyError:
            raise PlanningRepositoryError("规划资料写入不可用") from None

    # 创建风险政策版本；政策缺项允许保存，但不会通过 resolve_refs 的完整检查。
    async def create_policy(
        self,
        workspace_id: UUID,
        draft: PlanningRiskPolicyDraft,
        *,
        request_id: UUID,
        expected_generation: int,
    ) -> PlanningRiskPolicy:
        draft_payload = _draft_payload(draft)
        request_sha = _request_sha(
            _ACTION_CREATE_POLICY,
            workspace_id,
            {"draft": draft_payload, "expectedGeneration": expected_generation},
        )
        try:
            async with self._factory() as session, session.begin():
                await _lock_request(session, request_id)
                replay = await _load_request(
                    session,
                    request_id,
                    workspace_id,
                    _ACTION_CREATE_POLICY,
                    request_sha,
                )
                if replay is not None:
                    return _policy_result(replay)
                pool = await _ensure_pool(session, workspace_id, self._now())
                if pool.generation != expected_generation:
                    raise PlanningGenerationConflictError("规划资金池代次已变化，请重新读取")
                now = self._now()
                policy_generation = pool.generation + 1
                policy = PlanningRiskPolicy.build(
                    version_id=uuid4(),
                    pool_id=pool.id,
                    pool_generation=policy_generation,
                    draft=draft,
                    declared_at=now,
                )
                session.add(
                    _policy_row(
                        policy,
                        workspace_id=workspace_id,
                        pool_id=pool.id,
                        now=now,
                    )
                )
                pool.generation = policy_generation
                pool.updated_at = now
                _store_request(
                    session,
                    request_id=request_id,
                    workspace_id=workspace_id,
                    action=_ACTION_CREATE_POLICY,
                    request_sha256=request_sha,
                    result=_snapshot_payload(policy),
                    now=now,
                )
            return policy
        except IntegrityError:
            replayed = await self._replay_request(
                request_id,
                workspace_id,
                _ACTION_CREATE_POLICY,
                request_sha,
            )
            if replayed is not None:
                return _policy_result(replayed)
            raise PlanningGenerationConflictError("风险政策写入冲突，请重新读取") from None
        except SQLAlchemyError:
            raise PlanningRepositoryError("风险政策写入不可用") from None

    # 在重新读取公开源之前检查已提交请求；锁与请求冲突检查保持和首次写入一致。
    # 该方法不替代 record_venue_rules 的写入锁，只用于避免已提交请求依赖当前上游可用性。
    async def replay_venue_rules(
        self,
        workspace_id: UUID,
        product: ProductKey,
        *,
        request_id: UUID,
    ) -> VenueRuleSnapshot | None:
        request_sha = _rule_request_sha(workspace_id, product)
        try:
            async with self._factory() as session, session.begin():
                await _lock_request(session, request_id)
                replay = await _load_request(
                    session,
                    request_id,
                    workspace_id,
                    _ACTION_REFRESH_RULES,
                    request_sha,
                )
                if replay is None:
                    return None
                return _rule_result(replay)
        except SQLAlchemyError:
            raise PlanningRepositoryError("公开规则重放读取不可用") from None

    # 冻结公开规则快照；新规则推进共享代次，使旧核验在读取时立即过期。
    async def record_venue_rules(
        self,
        workspace_id: UUID,
        snapshot: VenueRuleSnapshot,
        *,
        request_id: UUID,
    ) -> VenueRuleSnapshot:
        snapshot_payload = _snapshot_payload(snapshot)
        request_sha = _rule_request_sha(workspace_id, snapshot.product)
        try:
            async with self._factory() as session, session.begin():
                await _lock_request(session, request_id)
                replay = await _load_request(
                    session,
                    request_id,
                    workspace_id,
                    _ACTION_REFRESH_RULES,
                    request_sha,
                )
                if replay is not None:
                    return _rule_result(replay)
                pool = await _ensure_pool(session, workspace_id, self._now())
                now = self._now()
                if snapshot.expires_at <= now:
                    raise PlanningInputExpiredError("公开规则快照在写入前已过期")
                rule_generation = pool.generation + 1
                session.add(
                    _rule_row(
                        snapshot,
                        workspace_id=workspace_id,
                        pool_generation=rule_generation,
                        now=now,
                    )
                )
                pool.generation = rule_generation
                pool.updated_at = now
                _store_request(
                    session,
                    request_id=request_id,
                    workspace_id=workspace_id,
                    action=_ACTION_REFRESH_RULES,
                    request_sha256=request_sha,
                    result=snapshot_payload,
                    now=now,
                )
            return snapshot
        except IntegrityError:
            replayed = await self._replay_request(
                request_id,
                workspace_id,
                _ACTION_REFRESH_RULES,
                request_sha,
            )
            if replayed is not None:
                return _rule_result(replayed)
            raise PlanningRepositoryError("公开规则写入冲突") from None
        except SQLAlchemyError:
            raise PlanningRepositoryError("公开规则写入不可用") from None

    # 一致性读取当前池、最新资料/政策/规则和资料关联成本；读取锁阻止代次在组合期间变化。
    async def resolve_current(self, workspace_id: UUID) -> CurrentPlanningInputs | None:
        try:
            async with self._factory() as session, session.begin():
                pool_row = await session.scalar(
                    select(PlanningPoolRecord)
                    .where(PlanningPoolRecord.workspace_id == workspace_id)
                    .with_for_update(read=True)
                )
                if pool_row is None:
                    return None
                profile_row = await session.scalar(
                    select(PlanningProfileRecord)
                    .where(PlanningProfileRecord.workspace_id == workspace_id)
                    .order_by(
                        PlanningProfileRecord.pool_generation.desc(),
                        PlanningProfileRecord.created_at.desc(),
                        PlanningProfileRecord.id.desc(),
                    )
                    .limit(1)
                )
                if profile_row is None:
                    return None
                profile = _profile_from_row(profile_row)
                policy_row = await session.scalar(
                    select(PlanningRiskPolicyRecord)
                    .where(PlanningRiskPolicyRecord.workspace_id == workspace_id)
                    .order_by(
                        PlanningRiskPolicyRecord.pool_generation.desc(),
                        PlanningRiskPolicyRecord.created_at.desc(),
                        PlanningRiskPolicyRecord.id.desc(),
                    )
                    .limit(1)
                )
                policy = None if policy_row is None else _policy_from_row(policy_row)
                rules_row = await session.scalar(
                    select(PlanningVenueRuleRecord)
                    .where(
                        PlanningVenueRuleRecord.workspace_id == workspace_id,
                        PlanningVenueRuleRecord.venue == profile.product.venue,
                        PlanningVenueRuleRecord.symbol == str(profile.product.symbol),
                    )
                    .order_by(
                        PlanningVenueRuleRecord.pool_generation.desc(),
                        PlanningVenueRuleRecord.created_at.desc(),
                        PlanningVenueRuleRecord.id.desc(),
                    )
                    .limit(1)
                )
                rules = None if rules_row is None else _rule_from_row(rules_row)
                costs = None
                if profile.costs_ref is not None:
                    cost_row = await session.get(PlanningCostRecord, profile.costs_ref.version_id)
                    if cost_row is None or cost_row.workspace_id != workspace_id:
                        raise PlanningIntegrityError("规划资料引用的成本版本不存在")
                    costs = _cost_from_row(cost_row)
                    if costs.ref != profile.costs_ref:
                        raise PlanningIntegrityError("成本版本指纹与资料引用不一致")
                return CurrentPlanningInputs(
                    pool=PlanningPool(
                        pool_id=pool_row.id,
                        workspace_id=pool_row.workspace_id,
                        generation=pool_row.generation,
                    ),
                    profile=profile,
                    policy=policy,
                    venue_rules=rules,
                    costs=costs,
                )
        except SQLAlchemyError:
            raise PlanningRepositoryError("规划资料读取不可用") from None

    # 按精确 ref 读取历史资料版本；工作台不匹配按不存在处理。
    async def get_profile(
        self, workspace_id: UUID, ref: VersionRef
    ) -> PlanningProfileSnapshot | None:
        try:
            async with self._factory() as session:
                row = await session.get(PlanningProfileRecord, ref.version_id)
        except SQLAlchemyError:
            raise PlanningRepositoryError("规划资料读取不可用") from None
        if row is None or row.workspace_id != workspace_id:
            return None
        profile = _profile_from_row(row)
        if profile.ref != ref:
            raise PlanningIntegrityError("规划资料引用与历史版本不一致")
        return profile

    async def get_policy(self, workspace_id: UUID, ref: VersionRef) -> PlanningRiskPolicy | None:
        try:
            async with self._factory() as session:
                row = await session.get(PlanningRiskPolicyRecord, ref.version_id)
        except SQLAlchemyError:
            raise PlanningRepositoryError("风险政策读取不可用") from None
        if row is None or row.workspace_id != workspace_id:
            return None
        policy = _policy_from_row(row)
        if policy.ref != ref:
            raise PlanningIntegrityError("风险政策引用与历史版本不一致")
        return policy

    async def get_venue_rules(
        self, workspace_id: UUID, ref: VersionRef
    ) -> VenueRuleSnapshot | None:
        try:
            async with self._factory() as session:
                row = await session.get(PlanningVenueRuleRecord, ref.version_id)
        except SQLAlchemyError:
            raise PlanningRepositoryError("公开规则读取不可用") from None
        if row is None or row.workspace_id != workspace_id:
            return None
        rules = _rule_from_row(row)
        if rules.ref != ref:
            raise PlanningIntegrityError("公开规则引用与历史版本不一致")
        return rules

    async def get_costs(self, workspace_id: UUID, ref: VersionRef | None) -> CostAssumptions | None:
        if ref is None:
            return None
        try:
            async with self._factory() as session:
                row = await session.get(PlanningCostRecord, ref.version_id)
        except SQLAlchemyError:
            raise PlanningRepositoryError("成本资料读取不可用") from None
        if row is None or row.workspace_id != workspace_id:
            return None
        costs = _cost_from_row(row)
        if costs.ref != ref:
            raise PlanningIntegrityError("成本资料引用与历史版本不一致")
        return costs

    # 并发相同请求在唯一约束上失败后重读已提交结果；内容不同按冲突处理。
    async def _replay_request(
        self,
        request_id: UUID,
        workspace_id: UUID,
        action: str,
        request_sha: str | tuple[str, ...],
    ) -> _RequestSnapshot | None:
        try:
            async with self._factory() as session:
                return await _load_request(session, request_id, workspace_id, action, request_sha)
        except SQLAlchemyError:
            return None


# 创建或锁定工作台资金池；INSERT ... ON CONFLICT 处理并发首建，随后行锁串行化代次。
async def _ensure_pool(
    session: AsyncSession,
    workspace_id: UUID,
    now: datetime,
) -> PlanningPoolRecord:
    await session.execute(
        pg_insert(PlanningPoolRecord)
        .values(
            id=uuid4(),
            workspace_id=workspace_id,
            generation=0,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["workspace_id"])
    )
    row = await session.scalar(
        select(PlanningPoolRecord)
        .where(PlanningPoolRecord.workspace_id == workspace_id)
        .with_for_update()
    )
    if row is None:
        raise PlanningRepositoryError("规划资金池创建后不可读取")
    return row


# 冻结成本版本；用户声明有效期与本地 15 分钟取较早者。
def _build_cost(draft: CostAssumptionsDraft | None, now: datetime) -> CostAssumptions | None:
    if draft is None:
        return None
    if draft.valid_until <= now:
        raise PlanningInputExpiredError("成本资料已过期")
    expires_at = min(now + PROFILE_VALIDITY, draft.valid_until)
    return CostAssumptions.build(
        version_id=uuid4(),
        draft=draft,
        declared_at=now,
        expires_at=expires_at,
    )


# 冻结保证金证据；用户声明有效期与本地 15 分钟取较早者。
def _build_margin(
    draft: MarginEvidenceDraft | None,
    now: datetime,
) -> MarginEvidence | None:
    if draft is None:
        return None
    if draft.valid_until <= now:
        raise PlanningInputExpiredError("保证金证据已过期")
    expires_at = min(now + PROFILE_VALIDITY, draft.valid_until)
    return MarginEvidence.build(
        draft=draft,
        declared_at=now,
        expires_at=expires_at,
    )


# 资料整体有效期取本地 15 分钟、成本与保证金证据的较早者。
def _profile_expiry(
    now: datetime,
    cost: CostAssumptions | None,
    margin: MarginEvidence | None,
) -> datetime:
    candidates = [now + PROFILE_VALIDITY]
    if cost is not None:
        candidates.append(cost.expires_at)
    if margin is not None:
        candidates.append(margin.expires_at)
    return min(candidates)


# 资料行构造；document 保存完整快照，sha256/时间列用于索引和触发器一致性。
def _profile_row(
    profile: PlanningProfileSnapshot,
    *,
    workspace_id: UUID,
    pool_id: UUID,
    now: datetime,
) -> PlanningProfileRecord:
    return PlanningProfileRecord(
        id=profile.ref.version_id,
        workspace_id=workspace_id,
        pool_id=pool_id,
        pool_generation=profile.pool_generation,
        document=_snapshot_payload(profile),
        sha256=profile.ref.sha256,
        declared_at=profile.declared_at,
        expires_at=profile.expires_at,
        created_at=now,
    )


def _policy_row(
    policy: PlanningRiskPolicy,
    *,
    workspace_id: UUID,
    pool_id: UUID,
    now: datetime,
) -> PlanningRiskPolicyRecord:
    return PlanningRiskPolicyRecord(
        id=policy.ref.version_id,
        workspace_id=workspace_id,
        pool_id=pool_id,
        pool_generation=policy.pool_generation,
        document=_snapshot_payload(policy),
        sha256=policy.ref.sha256,
        declared_at=policy.declared_at,
        created_at=now,
    )


def _cost_row(
    costs: CostAssumptions,
    *,
    workspace_id: UUID,
    pool_id: UUID,
    pool_generation: int,
    now: datetime,
) -> PlanningCostRecord:
    return PlanningCostRecord(
        id=costs.ref.version_id,
        workspace_id=workspace_id,
        pool_id=pool_id,
        pool_generation=pool_generation,
        document=_snapshot_payload(costs),
        sha256=costs.ref.sha256,
        declared_at=costs.declared_at,
        expires_at=costs.expires_at,
        created_at=now,
    )


def _rule_row(
    rules: VenueRuleSnapshot,
    *,
    workspace_id: UUID,
    pool_generation: int,
    now: datetime,
) -> PlanningVenueRuleRecord:
    return PlanningVenueRuleRecord(
        id=rules.ref.version_id,
        workspace_id=workspace_id,
        venue=rules.product.venue,
        symbol=str(rules.product.symbol),
        pool_generation=pool_generation,
        document=_snapshot_payload(rules),
        sha256=rules.ref.sha256,
        observed_at=rules.observed_at,
        expires_at=rules.expires_at,
        created_at=now,
    )


# 从行解析并核对标识/指纹/代次，防止正文列与索引列被分别改写。
def _profile_from_row(row: PlanningProfileRecord) -> PlanningProfileSnapshot:
    profile = _parse_profile(row.document)
    if (
        profile.ref.version_id != row.id
        or profile.ref.sha256 != row.sha256
        or profile.pool_id != row.pool_id
        or profile.pool_generation != row.pool_generation
        or profile.declared_at != row.declared_at
        or profile.expires_at != row.expires_at
    ):
        raise PlanningIntegrityError("规划资料行与内容不一致")
    return profile


def _policy_from_row(row: PlanningRiskPolicyRecord) -> PlanningRiskPolicy:
    policy = _parse_policy(row.document)
    if (
        policy.ref.version_id != row.id
        or policy.ref.sha256 != row.sha256
        or policy.pool_id != row.pool_id
        or policy.pool_generation != row.pool_generation
        or policy.declared_at != row.declared_at
    ):
        raise PlanningIntegrityError("风险政策行与内容不一致")
    return policy


def _cost_from_row(row: PlanningCostRecord) -> CostAssumptions:
    costs = _parse_costs(row.document)
    if (
        costs.ref.version_id != row.id
        or costs.ref.sha256 != row.sha256
        or costs.declared_at != row.declared_at
        or costs.expires_at != row.expires_at
    ):
        raise PlanningIntegrityError("成本资料行与内容不一致")
    return costs


def _rule_from_row(row: PlanningVenueRuleRecord) -> VenueRuleSnapshot:
    rules = _parse_rules(row.document)
    if (
        rules.ref.version_id != row.id
        or rules.ref.sha256 != row.sha256
        or rules.product.venue != row.venue
        or str(rules.product.symbol) != row.symbol
        or rules.observed_at != row.observed_at
        or rules.expires_at != row.expires_at
    ):
        raise PlanningIntegrityError("公开规则行与内容不一致")
    return rules


def _parse_profile(document: dict[str, object]) -> PlanningProfileSnapshot:
    try:
        return PlanningProfileSnapshot.model_validate(document)
    except ValidationError as error:
        raise PlanningIntegrityError("规划资料内容校验失败") from error


def _parse_policy(document: dict[str, object]) -> PlanningRiskPolicy:
    try:
        return PlanningRiskPolicy.model_validate(document)
    except ValidationError as error:
        raise PlanningIntegrityError("风险政策内容校验失败") from error


def _parse_costs(document: dict[str, object]) -> CostAssumptions:
    try:
        return CostAssumptions.model_validate(document)
    except ValidationError as error:
        raise PlanningIntegrityError("成本资料内容校验失败") from error


def _parse_rules(document: dict[str, object]) -> VenueRuleSnapshot:
    try:
        return VenueRuleSnapshot.model_validate(document)
    except ValidationError as error:
        raise PlanningIntegrityError("公开规则内容校验失败") from error


# 解析请求重放结果；损坏的历史结果不能被当作成功响应。
def _profile_result(snapshot: _RequestSnapshot) -> PlanningProfileSnapshot:
    if snapshot.result is None:
        raise PlanningIntegrityError("规划资料请求缺少已保存结果")
    return _parse_profile(snapshot.result)


def _policy_result(snapshot: _RequestSnapshot) -> PlanningRiskPolicy:
    if snapshot.result is None:
        raise PlanningIntegrityError("风险政策请求缺少已保存结果")
    return _parse_policy(snapshot.result)


def _rule_result(snapshot: _RequestSnapshot) -> VenueRuleSnapshot:
    if snapshot.result is None:
        raise PlanningIntegrityError("公开规则请求缺少已保存结果")
    return _parse_rules(snapshot.result)


# 请求级事务锁：同一 request_id 并发调用串行化，重放读取已提交结果。
async def _lock_request(session: AsyncSession, request_id: UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:request_key, 0))"),
        {"request_key": str(request_id)},
    )


# 读取并校验请求幂等记录；同一 request_id 不能对应不同工作台、操作或内容。
async def _load_request(
    session: AsyncSession,
    request_id: UUID,
    workspace_id: UUID,
    action: str,
    request_sha: str | tuple[str, ...],
) -> _RequestSnapshot | None:
    record = await session.get(PlanningInputRequestRecord, request_id)
    if record is None:
        return None
    candidates = (request_sha,) if isinstance(request_sha, str) else request_sha
    if (
        record.workspace_id != workspace_id
        or record.action != action
        or record.request_sha256 not in candidates
    ):
        raise PlanningRequestConflictError("请求键已用于不同操作或内容")
    return _RequestSnapshot(record.result)


# 写入请求结果；result 为 None 表示成功但没有返回体。
def _store_request(
    session: AsyncSession,
    *,
    request_id: UUID,
    workspace_id: UUID,
    action: str,
    request_sha256: str,
    result: JsonObject,
    now: datetime,
) -> None:
    session.add(
        PlanningInputRequestRecord(
            request_id=request_id,
            workspace_id=workspace_id,
            action=action,
            request_sha256=request_sha256,
            result=cast(dict[str, object], result),
            created_at=now,
        )
    )


# 规范化请求指纹覆盖操作、工作台和业务参数，不把 request_id 自身计入内容。
def _request_sha(action: str, workspace_id: UUID, payload: JsonObject) -> str:
    body: JsonObject = {
        "action": action,
        "workspaceId": str(workspace_id),
        "payload": payload,
    }
    return sha256_json(cast(JsonValue, body))


# 规则刷新请求指纹只覆盖产品；重新抓取得到的 version_id/observed_at 不参与幂等键。
def _rule_request_sha(workspace_id: UUID, product: ProductKey) -> str:
    return _request_sha(
        _ACTION_REFRESH_RULES,
        workspace_id,
        {"product": product.model_dump(mode="json", by_alias=False)},
    )


# 快照持久化载荷；资料快照使用 versioned_payload 保持历史字段集合。
def _snapshot_payload(
    value: PlanningProfileSnapshot | PlanningRiskPolicy | CostAssumptions | VenueRuleSnapshot,
) -> JsonObject:
    if isinstance(value, PlanningProfileSnapshot):
        return copy.deepcopy(value.versioned_payload())
    dumped = value.model_dump(mode="json", by_alias=False)
    return cast(JsonObject, copy.deepcopy(dumped))


# 草稿持久化载荷；与快照相同，使用内部字段名并保留 None。
def _draft_payload(value: PlanningProfileDraft | PlanningRiskPolicyDraft) -> JsonObject:
    dumped = value.model_dump(mode="json", by_alias=False)
    return cast(JsonObject, copy.deepcopy(dumped))


# 资料请求指纹兼容两代历史格式：
# - 第二轮请求显式包含 cooldown_status（未知时为 null）；
# - 首轮请求没有该字段。
# 当前新写入使用显式字段格式；重放同时接受旧格式，其他内容变化仍由 SHA 拒绝。
def _profile_request_shas(
    workspace_id: UUID,
    draft_payload: JsonObject,
    expected_generation: int,
) -> tuple[str, ...]:
    candidates: list[JsonObject] = [draft_payload]
    if draft_payload.get("cooldown_status") is None:
        candidates.append(
            {key: value for key, value in draft_payload.items() if key != "cooldown_status"}
        )
    hashes: list[str] = []
    for candidate in candidates:
        digest = _request_sha(
            _ACTION_CREATE_PROFILE,
            workspace_id,
            {"draft": candidate, "expectedGeneration": expected_generation},
        )
        if digest not in hashes:
            hashes.append(digest)
    return tuple(hashes)


__all__ = ["SqlAlchemyPlanningInputRepository"]
