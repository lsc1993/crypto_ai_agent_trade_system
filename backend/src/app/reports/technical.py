# 独立技术 v1 报告及 v2 复用的事实、方法和候选契约，公开财务值序列化为十进制字符串。
# 计划是条件研究结构；数值几何同时检查内部精度和公开舍入，冻结状态不能解释成实时执行许可。
"""Public, bounded contracts for the independent technical research report."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    field_validator,
    model_validator,
)

from app.market.symbols import ResearchSymbol


def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(word.capitalize() for word in tail)


# 拒绝浮点和布尔值，只允许有限十进制或其字符串，避免精度损失进入金融计算。
def _decimal_only(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, str)):
        raise ValueError("金融数值必须是 Decimal 或十进制字符串")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("金融数值必须是有效十进制数") from error
    if not parsed.is_finite():
        raise ValueError("金融数值必须有限")
    return parsed


def _decimal_text(value: Decimal) -> str:
    """Round public strings to 18 places, leaving internal Decimal math untouched."""
    if not value.is_finite() or value.adjusted() > 37:
        raise ValueError("金融数值超出公开十进制精度")
    with localcontext() as context:
        context.prec = max(56, len(value.as_tuple().digits) + 18)
        rounded = value.quantize(Decimal("1e-18"), rounding=ROUND_HALF_EVEN)
    rendered = format(rounded, "f").rstrip("0").rstrip(".")
    result = rendered if rendered and rendered != "-0" else "0"
    unsigned = result.removeprefix("-")
    integer, _, fraction = unsigned.partition(".")
    if len(integer) + len(fraction) > 38:
        raise ValueError("金融数值超出公开十进制精度")
    return result


def wire_decimal_value(value: Decimal) -> Decimal | None:
    """Return the exact value the public Decimal string would convey, if supported."""
    try:
        return Decimal(_decimal_text(value))
    except ValueError:
        return None


DecimalText = Annotated[
    Decimal,
    BeforeValidator(_decimal_only),
    PlainSerializer(_decimal_text, return_type=str, when_used="json"),
]


class _TechnicalModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        frozen=True,
        extra="forbid",
    )


# 研究候选方向与无突破状态，枚举本身不授权订单或账户访问。
class TechnicalDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    NONE = "none"


def wire_plan_prices_valid(
    direction: TechnicalDirection,
    *,
    stop: Decimal,
    lower: Decimal,
    trigger: Decimal,
    upper: Decimal,
    target: Decimal,
) -> bool:
    """Check that rounded public price strings preserve strict plan geometry."""
    values = tuple(wire_decimal_value(value) for value in (stop, lower, trigger, upper, target))
    if any(value is None for value in values):
        return False
    wire_stop, wire_lower, wire_trigger, wire_upper, wire_target = values
    if (
        wire_stop is None
        or wire_lower is None
        or wire_trigger is None
        or wire_upper is None
        or wire_target is None
    ):
        return False
    if min(wire_stop, wire_lower, wire_trigger, wire_upper, wire_target) <= 0:
        return False
    if not wire_lower <= wire_trigger <= wire_upper:
        return False
    if direction is TechnicalDirection.LONG:
        return wire_stop < wire_lower <= wire_upper < wire_target
    if direction is TechnicalDirection.SHORT:
        return wire_target < wire_lower <= wire_upper < wire_stop
    return False


# 保留各周期样本数量、最新收盘时间及明确质量原因，便于复核拒绝依据。
class TechnicalQuality(_TechnicalModel):
    status: str
    reasons: tuple[str, ...]
    candle_counts: dict[str, int]
    latest_closed_at: dict[str, datetime]

    @field_validator("latest_closed_at")
    @classmethod
    def latest_times_utc(cls, value: dict[str, datetime]) -> dict[str, datetime]:
        for timestamp in value.values():
            _require_utc(timestamp)
        return value


# 冻结审查方法的来源、版本与改写指纹，方法说明不是行情证据。
class TechnicalMethod(_TechnicalModel):
    id: str
    version: str
    source_skill_id: str
    source_sha256: str
    adapted_sha256: str
    adaptation_note: str


# 所有指标和形态由程序从冻结行情计算；模型只能解释，不能重写财务值。
class TechnicalFacts(_TechnicalModel):
    trend_alignment: dict[str, str]
    sma20: dict[str, DecimalText]
    sma50: dict[str, DecimalText]
    atr14: DecimalText
    range_high: DecimalText
    range_low: DecimalText
    volume_ratio: DecimalText
    volume_signal: str
    small_body: bool
    long_upper_wick: bool
    long_lower_wick: bool
    breakout: TechnicalDirection
    support_levels: tuple[DecimalText, ...]
    resistance_levels: tuple[DecimalText, ...]


# 假设空仓的有限条件候选，包含有效期和每侧成本假设，不包含金额、仓位或订单。
class TechnicalPlan(_TechnicalModel):
    direction: TechnicalDirection
    state: str
    trigger_level: DecimalText
    entry_lower: DecimalText
    entry_upper: DecimalText
    stop_loss: DecimalText
    target: DecimalText
    reward_risk: DecimalText
    fee_rate_per_side: DecimalText
    slippage_rate_per_side: DecimalText
    valid_until: datetime
    rationale: str

    @field_validator("valid_until")
    @classmethod
    def expiration_utc(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def validate_geometry(self) -> TechnicalPlan:
        if self.direction not in {TechnicalDirection.LONG, TechnicalDirection.SHORT}:
            raise ValueError("计划方向无效")
        if self.state not in {"triggered", "awaiting_confirmation"}:
            raise ValueError("计划状态无效")
        if any(
            price <= 0
            for price in (
                self.trigger_level,
                self.entry_lower,
                self.entry_upper,
                self.stop_loss,
                self.target,
            )
        ):
            raise ValueError("价格必须为正")
        if (
            self.reward_risk < 0
            or not (0 <= self.fee_rate_per_side < 1)
            or not (0 <= self.slippage_rate_per_side < 1)
        ):
            raise ValueError("收益风险比与成本假设无效")
        if not self.entry_lower <= self.trigger_level <= self.entry_upper:
            raise ValueError("触发价必须位于入场区间")
        if self.direction is TechnicalDirection.LONG and not (
            self.stop_loss < self.entry_lower <= self.entry_upper < self.target
        ):
            raise ValueError("多头结构价格顺序无效")
        if self.direction is TechnicalDirection.SHORT and not (
            self.target < self.entry_lower <= self.entry_upper < self.stop_loss
        ):
            raise ValueError("空头结构价格顺序无效")
        if not wire_plan_prices_valid(
            self.direction,
            stop=self.stop_loss,
            lower=self.entry_lower,
            trigger=self.trigger_level,
            upper=self.entry_upper,
            target=self.target,
        ):
            raise ValueError("计划价格不能安全序列化")
        if any(
            wire_decimal_value(value) is None
            for value in (self.reward_risk, self.fee_rate_per_side, self.slippage_rate_per_side)
        ):
            raise ValueError("计划财务数值超出公开十进制精度")
        expected_rationale = (
            "closed_volume_breakout_with_structural_target"
            if self.state == "triggered"
            else "awaiting_closed_volume_breakout_with_structural_target"
        )
        if self.rationale != expected_rationale:
            raise ValueError("计划理由与状态不一致")
        return self


# 组合质量、可选事实、有限候选及无计划原因，统一挂到本次证据标识。
class TechnicalAnalysis(_TechnicalModel):
    quality: TechnicalQuality
    facts: TechnicalFacts | None
    plans: tuple[TechnicalPlan, ...]
    no_plan_reasons: tuple[str, ...]
    methods: tuple[TechnicalMethod, ...]
    evidence_id: UUID


_HAN_NUMERALS = "零〇一二三四五六七八九十百千万亿两壹贰叁肆伍陆柒捌玖拾佰仟萬億貳參参陸"
_HAN_NUMBER = rf"[{_HAN_NUMERALS}]+"
_QUANTITY_UNITS = (
    r"(?:美元|美金|元|币|个|根|次|倍|成|手|份|张|笔|天|日|周|月|年|小时|分钟|秒|个百分点|角钱|分钱|"
    r"条|种|项|组|套|档|段|轮|层|级|只|枚|支|串|片|股|单|幅|口|节|座|页|块)"
)
_QUANTITATIVE_CHINESE = re.compile(
    rf"{_HAN_NUMBER}(?:点{_HAN_NUMBER})?{_QUANTITY_UNITS}"
    rf"|百分(?:之)?{_HAN_NUMBER}|{_HAN_NUMBER}点{_HAN_NUMBER}"
    rf"|第{_HAN_NUMBER}|{_HAN_NUMBER}比{_HAN_NUMBER}|{_HAN_NUMBER}分之{_HAN_NUMBER}"
    rf"|一半|半数|半{_QUANTITY_UNITS}"
)
_FINANCIAL_CHINESE = re.compile(
    r"(?:价格|价位|金额|数量|手续费|滑点|成本|盈亏比|量比|波幅|幅度|点位|涨幅|跌幅|比例|比率|利率|费用|"
    r"支撑|阻力|目标|止损|止盈|入场|区间|均线|周期|成交量|波动率|资金费率|市价|现价|开盘价|收盘价|最高价|最低价|概率)"
    r"(?:为|设为|定为|采用|取|是|在|到|约|达|位|位于|接近|靠近|落在|维持|升至|跌至|等于|至少|超过|高于|低于|不超过|大于|小于|附近|：|:|\s)*"
    + _HAN_NUMBER
    + r"(?=$|[\s，。；：！？、]|美元|美金|元|币|分|角|倍|成|点|至|到|作为)"
)


# 区分正常含数字字形的词语与具体数量，不修改或删除原始叙事字符。
def _contains_quantitative_number(text: str) -> bool:
    # Chinese numeral characters also occur in ordinary words such as 一致 and 一旦.
    # Recognize quantities without deleting or rewriting the original narrative.
    if any(character.isnumeric() and character not in _HAN_NUMERALS for character in text):
        return True
    if _QUANTITATIVE_CHINESE.search(text) or _FINANCIAL_CHINESE.search(text):
        return True
    return any(
        len(match.group()) > 1 and match.group() != "万一"
        for match in re.finditer(_HAN_NUMBER, text)
    )


# 技术 v1 的纯定性中文论断；数值、操作指令与收益承诺由确定性校验拒绝。
class TechnicalClaim(_TechnicalModel):
    text: str
    evidence_ids: tuple[UUID, ...]

    @field_validator("text")
    @classmethod
    def qualitative_only(cls, value: str) -> str:
        text = value.strip()
        if not text or len(text) > 500 or _contains_quantitative_number(text):
            raise ValueError("技术叙事必须是有界且不含数值的定性中文")
        if re.search(r"[\u4e00-\u9fff]", text) is None:
            raise ValueError("技术叙事必须包含中文")
        prohibited = (
            "买入",
            "卖出",
            "做多",
            "做空",
            "开仓",
            "下单",
            "杠杆",
            "仓位",
            "胜率",
            "保证",
            "收益",
        )
        if any(term in text for term in prohibited):
            raise ValueError("技术叙事不能包含交易指令或收益承诺")
        return text


# 模型主判断、反向情景及风险，每条由适配器核对当前冻结证据。
class TechnicalNarrative(_TechnicalModel):
    thesis: TechnicalClaim
    alternative: TechnicalClaim
    risks: tuple[TechnicalClaim, ...]


# v1 完成状态必须有模型叙事且无错误码，降级必须明确错误并移除叙事。
class TechnicalReport(_TechnicalModel):
    version: Literal["technical-v1"] = "technical-v1"
    id: UUID
    analysis_id: UUID
    symbol: ResearchSymbol
    status: str
    created_at: datetime
    data_cutoff_at: datetime
    analysis: TechnicalAnalysis
    narrative: TechnicalNarrative | None
    error_code: str | None

    @field_validator("created_at", "data_cutoff_at")
    @classmethod
    def utc_only(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def validate_status(self) -> TechnicalReport:
        if self.status not in {"completed", "degraded"}:
            raise ValueError("报告状态无效")
        if self.error_code not in {
            None,
            "market_unavailable",
            "data_quality_insufficient",
            "model_not_configured",
            "model_timeout",
            "model_upstream_error",
            "model_invalid_response",
        }:
            raise ValueError("报告错误码无效")
        if self.status == "completed" and self.narrative is None:
            raise ValueError("完成的报告需要模型叙事")
        if self.status == "completed" and self.error_code is not None:
            raise ValueError("完成的报告不能包含错误码")
        if self.status == "degraded" and (self.narrative is not None or self.error_code is None):
            raise ValueError("降级报告需要错误码且不能包含叙事")
        if self.data_cutoff_at > self.created_at:
            raise ValueError("报告截止时间不能晚于创建时间")
        return self


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("时间必须是 UTC")
    return value.astimezone(UTC)


# Shared public helpers for versioned technical contracts.
TechnicalBase = _TechnicalModel
contains_quantitative_number = _contains_quantitative_number
require_utc = _require_utc
