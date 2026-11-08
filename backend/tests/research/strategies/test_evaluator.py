# 验证证据 epoch、技术突破评估器适配、策略服务绑定与无评估器降级。
# 固定合成行情复用现有技术引擎测试夹具；技术适配器只读取旧规则结果，不重写信号算法。
# 组合评估器仅在本测试注册，模拟未来用户组合的接入边界，不宣称生产策略已实现。
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue, ValidationError

from app.agent.interactive.adapters.technical_strategy import (
    TECHNICAL_BREAKOUT_PARAMETER_SCHEMA,
    TechnicalStrategyEvaluator,
)
from app.agent.technical.engine import calculate_technical_analysis
from app.market.contracts import MarketTimeframe
from app.reports.technical import wire_decimal_value
from app.research.evidence import (
    MARKET_EVIDENCE_KIND,
    EvidenceEpoch,
    EvidenceItem,
    EvidenceQuality,
    EvidenceUnavailableError,
)
from app.research.strategies.contracts import (
    PriceCandidate,
    PriceRounding,
    StrategyApplicability,
    StrategyCandidateState,
    StrategyCapability,
    StrategyComponent,
    StrategyDirection,
    StrategyDraft,
    StrategyEvaluation,
    StrategyEvaluationStatus,
    StrategyIntegrityError,
    StrategyKind,
    StrategyParameterError,
    StrategyVersion,
    parameter_sha256,
)
from app.research.strategies.ports import StrategyCatalog
from app.research.strategies.service import StrategyEvaluatorRegistry, StrategyService
from app.shared.agent_types import (
    JsonObject,
    PageQuery,
    VersionPage,
    VersionRef,
    sha256_json,
)
from tests.agent.test_technical_engine import NOW as MARKET_NOW
from tests.agent.test_technical_engine import make_technical_detail

NOW = MARKET_NOW
WORKSPACE_ID = uuid4()


# 构造带内容指纹的固定证据项；内容均为合成公开数据，不包含账户或凭证。
def _evidence_item(
    *,
    kind: str,
    content: JsonObject | None,
    quality: EvidenceQuality = EvidenceQuality.VALID,
    evidence_id: UUID | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id or uuid4(),
        kind=kind,
        source="synthetic-public-source",
        observed_at=NOW,
        available_at=NOW,
        fetched_at=NOW,
        payload_sha256=sha256_json(content) if content is not None else "0" * 64,
        quality=quality,
        content=content,
    )


# 将合成行情封存为单一分析截止口径；可选新闻项用于验证证据变化会改变候选指纹。
def _epoch(*, include_news: bool = False) -> EvidenceEpoch:
    detail = make_technical_detail()
    items = [
        _evidence_item(
            kind=MARKET_EVIDENCE_KIND,
            content=detail.model_dump(mode="json"),
        )
    ]
    if include_news:
        items.append(
            _evidence_item(
                kind="news",
                content={"headline": "synthetic public headline"},
            )
        )
    return EvidenceEpoch.seal(analysis_as_of=NOW, sealed_at=NOW, items=tuple(items))


# 生成技术规则版本；Schema 与评估器常量一致，防止服务静默接受未知参数。
def _technical_strategy(
    *,
    evaluator_id: str = "technical_breakout_v1",
    supported_symbols: tuple[str, ...] = ("BTCUSDT",),
) -> StrategyVersion:
    draft = StrategyDraft(
        draft_id=uuid4(),
        strategy_id=uuid4(),
        name="技术突破规则",
        method_text="仅使用已收盘 K 线的成交量突破与结构位方法。",
        kind=StrategyKind.SINGLE,
        components=(),
        composition_rules=None,
        parameter_schema=TECHNICAL_BREAKOUT_PARAMETER_SCHEMA,
        supported_symbols=supported_symbols,
        supported_timeframes=(
            MarketTimeframe.H1,
            MarketTimeframe.H4,
            MarketTimeframe.D1,
        ),
        warmup_candles=60,
        evaluator_id=evaluator_id,
        capabilities=(
            StrategyCapability.RESEARCH,
            StrategyCapability.PRICE_CANDIDATE,
            StrategyCapability.MANUAL_PLANNING,
        ),
        risk_notes="结构止损不保证成交价；成本门槛来自旧研究规则。",
        state_version=0,
    )
    return StrategyVersion.from_draft(draft, published_at=NOW, state_version=1)


# 技术适配器的合法参数；不同最低盈亏比会被写入候选绑定指纹。
def _parameters(
    *,
    minimum_reward_risk: str = "1.5",
    allowed_states: tuple[str, ...] = ("triggered", "awaiting_confirmation"),
) -> JsonObject:
    return {
        "minimum_reward_risk": minimum_reward_risk,
        "allowed_states": list(allowed_states),
    }


# 仅实现 get_published 的目录替身；其他写操作在纯评估测试中不应被调用。
class _ReadOnlyCatalog:
    def __init__(self, version: StrategyVersion) -> None:
        self._version = version

    async def get_published(self, workspace_id: UUID, ref: VersionRef) -> StrategyVersion:
        assert workspace_id == WORKSPACE_ID
        assert ref == self._version.ref
        return self._version

    async def publish(self, *args: object, **kwargs: object) -> StrategyVersion:
        raise NotImplementedError

    async def create_draft(self, *args: object, **kwargs: object) -> StrategyDraft:
        raise NotImplementedError

    async def update_draft(self, *args: object, **kwargs: object) -> StrategyDraft:
        raise NotImplementedError

    async def list_versions(
        self, workspace_id: UUID, query: PageQuery
    ) -> VersionPage[StrategyVersion]:
        raise NotImplementedError

    async def archive(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError


# 记录调用次数并返回预设结果的评估器替身；用于证明绑定校验与参数门禁。
class _StubEvaluator:
    evaluator_id = "test_evaluator_v1"
    evaluator_version = "1"

    def __init__(self) -> None:
        self.calls = 0
        self.result: StrategyEvaluation | None = None

    async def evaluate(
        self,
        strategy: StrategyVersion,
        parameters: dict[str, JsonValue],
        evidence: EvidenceEpoch,
    ) -> StrategyEvaluation:
        self.calls += 1
        if self.result is not None:
            return self.result
        return StrategyEvaluation(
            strategy_ref=strategy.ref,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            parameters_sha256=parameter_sha256(parameters),
            evidence_sha256=evidence.sha256,
            status=StrategyEvaluationStatus.EVALUATED,
            applicability=StrategyApplicability.NOT_APPLICABLE,
            reason_codes=("stub_no_candidate",),
        )


# 组合评估器只在测试注册；它只引用冻结组成，不执行任意表达式。
class _CompositeTestEvaluator:
    evaluator_id = "test_composite_v1"
    evaluator_version = "1"

    async def evaluate(
        self,
        strategy: StrategyVersion,
        parameters: dict[str, JsonValue],
        evidence: EvidenceEpoch,
    ) -> StrategyEvaluation:
        frozen_refs = tuple(component.strategy_ref for component in strategy.components)
        candidate = PriceCandidate.build(
            strategy_ref=strategy.ref,
            component_refs=frozen_refs,
            parameters_sha256=parameter_sha256(parameters),
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            evidence_sha256=evidence.sha256,
            evidence_as_of=evidence.analysis_as_of,
            direction=StrategyDirection.LONG,
            entry_lower=Decimal("100"),
            trigger=Decimal("100.5"),
            entry_upper=Decimal("101"),
            stop_loss=Decimal("95"),
            target=Decimal("120"),
            valid_until=NOW + timedelta(hours=4),
            state=StrategyCandidateState.TRIGGERED,
            price_rounding=PriceRounding.STRICT,
            applicability_conditions=("synthetic_composite_only",),
        )
        return StrategyEvaluation(
            strategy_ref=strategy.ref,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            parameters_sha256=parameter_sha256(parameters),
            evidence_sha256=evidence.sha256,
            status=StrategyEvaluationStatus.EVALUATED,
            applicability=StrategyApplicability.APPLICABLE,
            candidates=(candidate,),
        )


# 适配器必须原样采用旧引擎的几何，只增加策略/参数/证据绑定，不改写信号。
@pytest.mark.asyncio
async def test_technical_evaluator_adapts_existing_rule_without_rewriting_geometry() -> None:
    strategy = _technical_strategy()
    evidence = _epoch()
    evaluation = await TechnicalStrategyEvaluator().evaluate(strategy, _parameters(), evidence)
    analysis = calculate_technical_analysis(make_technical_detail(), captured_at=NOW)
    plan = analysis.plans[0]

    assert evaluation.status is StrategyEvaluationStatus.EVALUATED
    assert evaluation.applicability is StrategyApplicability.APPLICABLE
    assert evaluation.strategy_ref == strategy.ref
    assert evaluation.parameters_sha256 == parameter_sha256(_parameters())
    assert evaluation.evidence_sha256 == evidence.sha256
    assert len(evaluation.candidates) == 1

    candidate = evaluation.candidates[0]
    assert candidate.strategy_ref == strategy.ref
    assert candidate.entry_lower == wire_decimal_value(plan.entry_lower)
    assert candidate.trigger == wire_decimal_value(plan.trigger_level)
    assert candidate.entry_upper == wire_decimal_value(plan.entry_upper)
    assert candidate.stop_loss == wire_decimal_value(plan.stop_loss)
    assert candidate.target == wire_decimal_value(plan.target)
    assert candidate.valid_until == plan.valid_until
    assert candidate.direction is StrategyDirection.LONG
    assert candidate.state is StrategyCandidateState.TRIGGERED
    assert candidate.price_rounding is PriceRounding.STRICT
    dumped = candidate.model_dump()
    assert "quantity" not in dumped
    assert "capital" not in dumped
    assert "trade_intent" not in dumped


# 参数与证据都会进入候选指纹；收紧最低盈亏比不能放宽旧规则，也不能保留旧候选 ID。
@pytest.mark.asyncio
async def test_candidate_fingerprint_changes_with_parameters_and_evidence() -> None:
    evaluator = TechnicalStrategyEvaluator()
    strategy = _technical_strategy()
    evidence = _epoch()
    first = await evaluator.evaluate(strategy, _parameters(), evidence)
    same = await evaluator.evaluate(strategy, _parameters(), evidence)
    tightened = await evaluator.evaluate(strategy, _parameters(minimum_reward_risk="1.6"), evidence)
    other_evidence = await evaluator.evaluate(strategy, _parameters(), _epoch(include_news=True))
    excluded = await evaluator.evaluate(strategy, _parameters(minimum_reward_risk="1.95"), evidence)

    assert first.candidates[0].candidate_id == same.candidates[0].candidate_id
    assert tightened.candidates[0].candidate_id != first.candidates[0].candidate_id
    assert tightened.candidates[0].entry_lower == first.candidates[0].entry_lower
    assert other_evidence.candidates[0].candidate_id != first.candidates[0].candidate_id
    assert other_evidence.candidates[0].entry_lower == first.candidates[0].entry_lower
    assert excluded.candidates == ()
    assert "parameters_exclude_candidates" in excluded.reason_codes


# 适配器只处理声明该评估器的单策略；币种不符或缺少行情证据时明确不可用。
@pytest.mark.asyncio
async def test_technical_evaluator_refuses_other_symbol_or_missing_market_evidence() -> None:
    evaluator = TechnicalStrategyEvaluator()
    unsupported_symbol = await evaluator.evaluate(
        _technical_strategy(supported_symbols=("ETHUSDT",)),
        _parameters(),
        _epoch(),
    )
    assert unsupported_symbol.status is StrategyEvaluationStatus.UNSUPPORTED
    assert unsupported_symbol.candidates == ()
    assert "unsupported_symbol" in unsupported_symbol.reason_codes

    news_only = EvidenceEpoch.seal(
        analysis_as_of=NOW,
        sealed_at=NOW,
        items=(
            _evidence_item(
                kind="news",
                content={"headline": "synthetic public headline"},
            ),
        ),
    )
    missing_market = await evaluator.evaluate(_technical_strategy(), _parameters(), news_only)
    assert missing_market.status is StrategyEvaluationStatus.UNSUPPORTED
    assert missing_market.candidates == ()
    assert "market_evidence_unavailable" in missing_market.reason_codes


# 没有已登记评估器时只返回方法研究状态，不能静默换用技术突破规则。
@pytest.mark.asyncio
async def test_missing_evaluator_keeps_candidate_empty_and_binds_selected_version() -> None:
    strategy = _technical_strategy(evaluator_id="missing_evaluator_v1")
    service = StrategyService(
        catalog=cast(StrategyCatalog, _ReadOnlyCatalog(strategy)),
        evaluators=StrategyEvaluatorRegistry(),
    )

    evaluation = await service.evaluate(WORKSPACE_ID, strategy.ref, _parameters(), _epoch())

    assert evaluation.strategy_ref == strategy.ref
    assert evaluation.evaluator_id == "missing_evaluator_v1"
    assert evaluation.status is StrategyEvaluationStatus.NO_EVALUATOR
    assert evaluation.candidates == ()
    assert "evaluator_unavailable" in evaluation.reason_codes


# 参数 Schema 不合格时服务直接返回原因，不调用已登记评估器，也不产生候选。
@pytest.mark.asyncio
async def test_invalid_parameters_are_reported_without_invoking_evaluator() -> None:
    strategy = _technical_strategy(evaluator_id="test_evaluator_v1")
    stub = _StubEvaluator()
    evaluators = StrategyEvaluatorRegistry()
    evaluators.register(stub)
    service = StrategyService(
        catalog=cast(StrategyCatalog, _ReadOnlyCatalog(strategy)),
        evaluators=evaluators,
    )

    evaluation = await service.evaluate(
        WORKSPACE_ID,
        strategy.ref,
        {"minimum_reward_risk": "1e3", "allowed_states": ["triggered"]},
        _epoch(),
    )

    assert evaluation.status is StrategyEvaluationStatus.INVALID_PARAMETERS
    assert evaluation.candidates == ()
    assert stub.calls == 0
    with pytest.raises(StrategyParameterError):
        # 公开校验函数也必须拒绝同一输入，避免只依赖服务层。
        from app.research.strategies.contracts import validate_parameters

        validate_parameters(
            strategy.parameter_schema,
            {"minimum_reward_risk": "1e3", "allowed_states": ["triggered"]},
        )


# 评估器返回的版本/参数/证据绑定不一致时，服务必须拒绝，不能把结果当成所选策略。
@pytest.mark.asyncio
async def test_adapter_binding_mismatch_is_rejected() -> None:
    strategy = _technical_strategy(evaluator_id="test_evaluator_v1")
    stub = _StubEvaluator()
    stub.result = StrategyEvaluation(
        strategy_ref=VersionRef(version_id=uuid4(), sha256="a" * 64),
        evaluator_id=stub.evaluator_id,
        evaluator_version=stub.evaluator_version,
        parameters_sha256=parameter_sha256(_parameters()),
        evidence_sha256=_epoch().sha256,
        status=StrategyEvaluationStatus.EVALUATED,
        applicability=StrategyApplicability.NOT_APPLICABLE,
        reason_codes=("stub_no_candidate",),
    )
    evaluators = StrategyEvaluatorRegistry()
    evaluators.register(stub)
    service = StrategyService(
        catalog=cast(StrategyCatalog, _ReadOnlyCatalog(strategy)),
        evaluators=evaluators,
    )

    with pytest.raises(StrategyIntegrityError):
        await service.evaluate(WORKSPACE_ID, strategy.ref, _parameters(), _epoch())


# 组合版本必须保留冻结组成引用；测试组合评估器通过正式服务边界完成一次评估。
@pytest.mark.asyncio
async def test_composite_evaluator_freezes_component_refs() -> None:
    component_refs = (
        VersionRef(version_id=uuid4(), sha256="b" * 64),
        VersionRef(version_id=uuid4(), sha256="c" * 64),
    )
    frozen_components = (
        StrategyComponent(role="trend", strategy_ref=component_refs[0], parameters={}),
        StrategyComponent(role="confirmation", strategy_ref=component_refs[1], parameters={}),
    )
    composite = StrategyVersion.from_draft(
        StrategyDraft(
            draft_id=uuid4(),
            strategy_id=uuid4(),
            name="测试组合",
            method_text="合成组合仅验证冻结引用与评估器边界。",
            kind=StrategyKind.COMPOSITE,
            components=frozen_components,
            composition_rules="仅由测试评估器解释，生产不登记该组合。",
            parameter_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
                "required": [],
            },
            supported_symbols=("BTCUSDT",),
            supported_timeframes=(
                MarketTimeframe.H1,
                MarketTimeframe.H4,
                MarketTimeframe.D1,
            ),
            warmup_candles=60,
            evaluator_id="test_composite_v1",
            capabilities=(StrategyCapability.RESEARCH,),
            risk_notes="仅为测试评估器，不生成生产计划。",
            state_version=0,
        ),
        published_at=NOW,
        state_version=1,
    )
    evaluators = StrategyEvaluatorRegistry()
    evaluators.register(_CompositeTestEvaluator())
    service = StrategyService(
        catalog=cast(StrategyCatalog, _ReadOnlyCatalog(composite)),
        evaluators=evaluators,
    )

    evaluation = await service.evaluate(WORKSPACE_ID, composite.ref, {}, _epoch())

    assert composite.components == frozen_components
    assert evaluation.strategy_ref == composite.ref
    assert evaluation.candidates[0].component_refs == component_refs
    assert evaluation.candidates[0].strategy_ref == composite.ref


# 证据封存拒绝未来内容、错误哈希和重复行情来源；市场证据缺失有稳定错误码。
def test_evidence_epoch_rejects_future_or_tampered_content() -> None:
    detail = make_technical_detail()
    content = detail.model_dump(mode="json")
    item = _evidence_item(kind=MARKET_EVIDENCE_KIND, content=content)

    with pytest.raises(ValidationError):
        EvidenceEpoch.seal(
            analysis_as_of=NOW - timedelta(minutes=1),
            sealed_at=NOW,
            items=(item,),
        )

    with pytest.raises(ValidationError):
        EvidenceItem.model_validate(
            {
                **item.model_dump(mode="python", by_alias=False),
                "payload_sha256": "0" * 64,
            }
        )

    duplicate = EvidenceEpoch.seal(
        analysis_as_of=NOW,
        sealed_at=NOW,
        items=(
            item,
            item.model_copy(update={"evidence_id": uuid4()}),
        ),
    )
    with pytest.raises(EvidenceUnavailableError):
        duplicate.market_detail()


# 封存必须隔离输入对象；已封存 epoch 的嵌套内容被改动时，消费入口应明确拒绝。
@pytest.mark.asyncio
async def test_sealed_evidence_isolates_input_and_rejects_nested_mutation() -> None:
    detail = make_technical_detail()
    content = cast(JsonObject, detail.model_dump(mode="json"))
    item = _evidence_item(kind=MARKET_EVIDENCE_KIND, content=content)
    epoch = EvidenceEpoch.seal(
        analysis_as_of=NOW,
        sealed_at=NOW,
        items=(item,),
    )
    original_sha = epoch.sha256

    # 修改构造输入不得改变已封存 epoch。
    summary = cast(dict[str, Any], content["summary"])
    summary["price"] = "1"
    snapshot = epoch.validated_snapshot()
    assert snapshot.sha256 == original_sha
    assert snapshot.items[0].content is not None
    assert cast(dict[str, Any], snapshot.items[0].content["summary"])["price"] != "1"

    # 直接修改 epoch 内嵌内容后，评估入口必须拒绝旧指纹继续生效。
    assert epoch.items[0].content is not None
    actual_summary = cast(dict[str, Any], epoch.items[0].content["summary"])
    actual_summary["price"] = "1"
    with pytest.raises(EvidenceUnavailableError):
        epoch.validated_snapshot()
    with pytest.raises(EvidenceUnavailableError):
        await TechnicalStrategyEvaluator().evaluate(_technical_strategy(), _parameters(), epoch)


# 审查复现：通过 market_evidence() 取得内容后修改，不能让评估沿用旧证据指纹。
@pytest.mark.asyncio
async def test_market_evidence_nested_mutation_cannot_reuse_old_fingerprint() -> None:
    epoch = _epoch()
    item = epoch.market_evidence()
    assert item.content is not None
    summary = cast(dict[str, Any], item.content["summary"])
    summary["price"] = "1"

    with pytest.raises(EvidenceUnavailableError):
        await TechnicalStrategyEvaluator().evaluate(_technical_strategy(), _parameters(), epoch)


# 服务必须在调用评估器前验证发布版本身份；嵌套 Schema 改动不能沿用旧版本引用。
@pytest.mark.asyncio
async def test_service_rejects_mutated_published_strategy_body() -> None:
    strategy = _technical_strategy()
    properties = cast(dict[str, Any], strategy.parameter_schema["properties"])
    risk = cast(dict[str, Any], properties["minimum_reward_risk"])
    risk["maximum"] = "99"
    service = StrategyService(
        catalog=cast(StrategyCatalog, _ReadOnlyCatalog(strategy)),
        evaluators=StrategyEvaluatorRegistry(),
    )

    with pytest.raises(StrategyIntegrityError):
        await service.evaluate(WORKSPACE_ID, strategy.ref, _parameters(), _epoch())


# 参数哈希函数只接受 JSON 安全值，且对字典顺序稳定。
def test_parameter_hash_is_order_stable() -> None:
    assert parameter_sha256({"a": "1", "b": [1, True]}) == parameter_sha256(
        {"b": [1, True], "a": "1"}
    )
    with pytest.raises(TypeError):
        sha256_json(cast(JsonValue, {"unsafe": object()}))
