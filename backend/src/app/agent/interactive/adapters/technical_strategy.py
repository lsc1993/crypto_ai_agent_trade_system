# 将既有确定性技术突破引擎适配为只读策略评估器。
# 适配器只调用 calculate_technical_analysis 并把其事实/候选映射为研究契约，
# 不修改旧信号算法、不生成数量/资金/订单，也不在缺少行情证据时回退其他策略。
from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

from pydantic import JsonValue

from app.agent.technical.engine import calculate_technical_analysis
from app.market.contracts import MarketTimeframe
from app.reports.technical import TechnicalDirection, TechnicalFacts
from app.research.evidence import EvidenceEpoch, EvidenceUnavailableError
from app.research.strategies.contracts import (
    PriceCandidate,
    PriceRounding,
    StrategyApplicability,
    StrategyCandidateState,
    StrategyDirection,
    StrategyEvaluation,
    StrategyEvaluationStatus,
    StrategyEvaluatorError,
    StrategyFact,
    StrategyKind,
    StrategyVersion,
    parameter_sha256,
    validate_parameter_schema,
    validate_parameters,
)
from app.shared.agent_types import JsonObject, parse_decimal_text

TECHNICAL_BREAKOUT_EVALUATOR_ID = "technical_breakout_v1"
TECHNICAL_BREAKOUT_EVALUATOR_VERSION = "1"
TECHNICAL_BREAKOUT_REQUIRED_TIMEFRAMES = (
    MarketTimeframe.H1,
    MarketTimeframe.H4,
    MarketTimeframe.D1,
)
TECHNICAL_BREAKOUT_MINIMUM_REWARD_RISK = Decimal("1.5")

# 适配器只接受这两个参数：最低盈亏比只能收紧旧规则，允许状态只过滤既有候选。
TECHNICAL_BREAKOUT_PARAMETER_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "minimum_reward_risk": {
            "type": "decimal",
            "minimum": "1.5",
            "maximum": "10",
            "description": "用户可收紧的最低净盈亏比，不能低于旧规则门槛。",
        },
        "allowed_states": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["triggered", "awaiting_confirmation"],
            },
            "minItems": 1,
            "maxItems": 2,
            "description": "仅过滤既有候选状态，不产生新的突破信号。",
        },
    },
    "required": ["minimum_reward_risk", "allowed_states"],
}

_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


# 技术突破评估器：精确匹配 evaluator_id，复用旧规则并只增加参数与绑定。
class TechnicalStrategyEvaluator:
    evaluator_id = TECHNICAL_BREAKOUT_EVALUATOR_ID
    evaluator_version = TECHNICAL_BREAKOUT_EVALUATOR_VERSION

    async def evaluate(
        self,
        strategy: StrategyVersion,
        parameters: dict[str, JsonValue],
        evidence: EvidenceEpoch,
    ) -> StrategyEvaluation:
        # 直接调用适配器时也先隔离并重验输入，避免嵌套修改沿用旧版本/证据指纹。
        strategy = strategy.validated_snapshot()
        evidence = evidence.validated_snapshot()
        if strategy.archived or strategy.archived_at is not None:
            raise StrategyEvaluatorError("策略已停用", code="strategy_archived")
        if strategy.evaluator_id != self.evaluator_id:
            raise StrategyEvaluatorError(
                "策略没有绑定技术突破评估器", code="evaluator_contract_mismatch"
            )
        if strategy.kind is not StrategyKind.SINGLE:
            raise StrategyEvaluatorError(
                "技术突破评估器只处理单策略", code="evaluator_contract_mismatch"
            )
        _validate_adapter_schema(strategy)
        normalized = validate_parameters(strategy.parameter_schema, parameters)
        parameter_sha = parameter_sha256(normalized)

        try:
            market_item = evidence.market_evidence()
            detail = evidence.market_detail()
        except EvidenceUnavailableError:
            return _unsupported(
                strategy,
                evidence,
                parameter_sha,
                "market_evidence_unavailable",
            )
        if detail.summary.symbol not in strategy.supported_symbols:
            return _unsupported(strategy, evidence, parameter_sha, "unsupported_symbol")
        if not set(TECHNICAL_BREAKOUT_REQUIRED_TIMEFRAMES) <= set(strategy.supported_timeframes):
            return _unsupported(strategy, evidence, parameter_sha, "unsupported_timeframe")

        minimum_reward_risk = parse_decimal_text(normalized["minimum_reward_risk"])
        if minimum_reward_risk < TECHNICAL_BREAKOUT_MINIMUM_REWARD_RISK:
            return _invalid(
                strategy,
                evidence,
                parameter_sha,
                "minimum_reward_risk_below_rule",
            )
        allowed_states = _allowed_states(normalized["allowed_states"])

        analysis = calculate_technical_analysis(detail, captured_at=evidence.analysis_as_of)
        if analysis.quality.status != "valid" or analysis.facts is None:
            return _unsupported(
                strategy,
                evidence,
                parameter_sha,
                "invalid_market_evidence",
            )

        facts = _facts(analysis.facts, market_item.evidence_id)
        candidates: list[PriceCandidate] = []
        for plan in analysis.plans:
            if plan.state not in allowed_states:
                continue
            if plan.reward_risk < minimum_reward_risk:
                continue
            if plan.direction not in {TechnicalDirection.LONG, TechnicalDirection.SHORT}:
                continue
            candidates.append(
                PriceCandidate.build(
                    strategy_ref=strategy.ref,
                    component_refs=(),
                    parameters_sha256=parameter_sha,
                    evaluator_id=self.evaluator_id,
                    evaluator_version=self.evaluator_version,
                    evidence_sha256=evidence.sha256,
                    evidence_as_of=evidence.analysis_as_of,
                    direction=(
                        StrategyDirection.LONG
                        if plan.direction is TechnicalDirection.LONG
                        else StrategyDirection.SHORT
                    ),
                    entry_lower=_public_decimal(plan.entry_lower),
                    trigger=_public_decimal(plan.trigger_level),
                    entry_upper=_public_decimal(plan.entry_upper),
                    stop_loss=_public_decimal(plan.stop_loss),
                    target=_public_decimal(plan.target),
                    valid_until=plan.valid_until,
                    state=StrategyCandidateState(plan.state),
                    price_rounding=PriceRounding.STRICT,
                    applicability_conditions=(
                        "closed_candles_only",
                        "technical_breakout_v1",
                    ),
                )
            )

        if candidates:
            return StrategyEvaluation(
                strategy_ref=strategy.ref,
                evaluator_id=self.evaluator_id,
                evaluator_version=self.evaluator_version,
                parameters_sha256=parameter_sha,
                evidence_sha256=evidence.sha256,
                status=StrategyEvaluationStatus.EVALUATED,
                applicability=StrategyApplicability.APPLICABLE,
                facts=facts,
                candidates=tuple(candidates),
            )
        reasons = (
            ("parameters_exclude_candidates",)
            if analysis.plans
            else _reason_codes(analysis.no_plan_reasons)
        )
        return StrategyEvaluation(
            strategy_ref=strategy.ref,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            parameters_sha256=parameter_sha,
            evidence_sha256=evidence.sha256,
            status=StrategyEvaluationStatus.EVALUATED,
            applicability=StrategyApplicability.NOT_APPLICABLE,
            facts=facts,
            reason_codes=reasons,
        )


# 只接受评估器自己的参数键和必填项；其他 Schema 可能描述未实现算法，不能静默忽略。
def _validate_adapter_schema(strategy: StrategyVersion) -> None:
    validate_parameter_schema(strategy.parameter_schema)
    properties = strategy.parameter_schema.get("properties")
    required = strategy.parameter_schema.get("required")
    if (
        not isinstance(properties, dict)
        or set(properties) != {"minimum_reward_risk", "allowed_states"}
        or not isinstance(required, list)
        or not {"minimum_reward_risk", "allowed_states"} <= set(required)
    ):
        raise StrategyEvaluatorError(
            "技术突破评估器的参数 Schema 不匹配", code="evaluator_contract_mismatch"
        )


# 从已校验参数中读取允许状态；Schema 枚举保证值合法，这里仍做防御性校验。
def _allowed_states(value: JsonValue) -> frozenset[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise StrategyEvaluatorError("技术突破允许状态参数无效", code="evaluator_contract_mismatch")
    states = frozenset(item for item in value if isinstance(item, str))
    if not states <= {
        StrategyCandidateState.TRIGGERED.value,
        StrategyCandidateState.AWAITING_CONFIRMATION.value,
    }:
        raise StrategyEvaluatorError(
            "技术突破允许状态超出候选范围", code="evaluator_contract_mismatch"
        )
    return states


# 将旧引擎事实映射为只读事实；数值和证据标识原样保留，模型不能重算。
def _facts(facts: TechnicalFacts, evidence_id: UUID) -> tuple[StrategyFact, ...]:
    trend_text = ", ".join(
        f"{timeframe}:{direction}" for timeframe, direction in sorted(facts.trend_alignment.items())
    )
    return (
        StrategyFact(
            fact_id="atr14",
            label="14 周期平均真实波幅",
            value=_public_decimal(facts.atr14),
            unit="quote",
            evidence_ids=(evidence_id,),
        ),
        StrategyFact(
            fact_id="range_high",
            label="前二十根已收盘高点",
            value=_public_decimal(facts.range_high),
            unit="quote",
            evidence_ids=(evidence_id,),
        ),
        StrategyFact(
            fact_id="range_low",
            label="前二十根已收盘低点",
            value=_public_decimal(facts.range_low),
            unit="quote",
            evidence_ids=(evidence_id,),
        ),
        StrategyFact(
            fact_id="volume_ratio",
            label="信号成交量相对二十根均值",
            value=_public_decimal(facts.volume_ratio),
            unit="ratio",
            evidence_ids=(evidence_id,),
        ),
        StrategyFact(
            fact_id="trend_alignment",
            label="多周期趋势排列",
            text=trend_text,
            evidence_ids=(evidence_id,),
        ),
        StrategyFact(
            fact_id="breakout",
            label="已收盘突破状态",
            text=facts.breakout.value,
            evidence_ids=(evidence_id,),
        ),
    )


# 公开事实按契约最多保留 18 位小数；内部引擎精度不因展示舍入被回写。
def _public_decimal(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1e-18"), rounding=ROUND_HALF_EVEN)


# 无评估能力时仍保留所选版本和参数/证据绑定，方便界面区分“无评估器”与“无候选”。
def _unsupported(
    strategy: StrategyVersion,
    evidence: EvidenceEpoch,
    parameter_sha: str,
    reason: str,
) -> StrategyEvaluation:
    return StrategyEvaluation(
        strategy_ref=strategy.ref,
        evaluator_id=TECHNICAL_BREAKOUT_EVALUATOR_ID,
        evaluator_version=TECHNICAL_BREAKOUT_EVALUATOR_VERSION,
        parameters_sha256=parameter_sha,
        evidence_sha256=evidence.sha256,
        status=StrategyEvaluationStatus.UNSUPPORTED,
        applicability=StrategyApplicability.UNKNOWN,
        reason_codes=(reason,),
    )


# 参数不合规时拒绝，不调用旧引擎生成任何候选。
def _invalid(
    strategy: StrategyVersion,
    evidence: EvidenceEpoch,
    parameter_sha: str,
    reason: str,
) -> StrategyEvaluation:
    return StrategyEvaluation(
        strategy_ref=strategy.ref,
        evaluator_id=TECHNICAL_BREAKOUT_EVALUATOR_ID,
        evaluator_version=TECHNICAL_BREAKOUT_EVALUATOR_VERSION,
        parameters_sha256=parameter_sha,
        evidence_sha256=evidence.sha256,
        status=StrategyEvaluationStatus.INVALID_PARAMETERS,
        applicability=StrategyApplicability.UNKNOWN,
        reason_codes=(reason,),
    )


# 将旧引擎原因码映射为契约允许的小写标识；数字开头的周期原因加 rule_ 前缀。
def _reason_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    mapped: list[str] = []
    for value in values:
        code = value if _REASON_CODE.fullmatch(value) else f"rule_{value}"
        code = code.replace("-", "_")[:64]
        if _REASON_CODE.fullmatch(code) is None:
            code = "technical_rule_no_candidate"
        if code not in mapped:
            mapped.append(code)
    return tuple(mapped) or ("technical_rule_no_candidate",)


__all__ = [
    "TECHNICAL_BREAKOUT_EVALUATOR_ID",
    "TECHNICAL_BREAKOUT_EVALUATOR_VERSION",
    "TECHNICAL_BREAKOUT_MINIMUM_REWARD_RISK",
    "TECHNICAL_BREAKOUT_PARAMETER_SCHEMA",
    "TECHNICAL_BREAKOUT_REQUIRED_TIMEFRAMES",
    "TechnicalStrategyEvaluator",
]
