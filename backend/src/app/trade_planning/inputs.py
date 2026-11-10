# 定义本地手动交易规划的 C3 输入契约：资料、风险政策、成本、保证金证据和公开规则快照。
# 这些类型只进入受限本地规划域，不包含账户身份、交易凭证或可提交的真实订单。
# 所有金额、数量、价格、费率和保证金均使用 DecimalText；时间为 UTC；未知值显式保留为 None，
# 不得用零或默认金额补齐。版本指纹覆盖全部内容，避免旧 ref 被新资料复用。
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import Field, JsonValue, field_validator, model_validator

from app.shared.agent_types import (
    AgentContractError,
    AgentModel,
    DecimalText,
    JsonObject,
    ProductKey,
    UtcDateTime,
    VersionRef,
    parse_decimal_text,
    require_utc,
    serialize_decimal_text,
    sha256_json,
)

# 初始资料有效期 15 分钟；公开规则快照 60 分钟。两者都是保守初值，不是市场稳定性承诺。
PROFILE_VALIDITY = timedelta(minutes=15)
VENUE_RULE_VALIDITY = timedelta(minutes=60)


# 首期支持逐仓、单向、新入场；其他模式在类型或服务边界明确拒绝。
class MarginMode(StrEnum):
    ISOLATED = "isolated"
    CROSS = "cross"


class PositionMode(StrEnum):
    ONE_WAY = "one_way"
    HEDGE = "hedge"


class QuantityUnit(StrEnum):
    BASE_ASSET = "base_asset"
    CONTRACT = "contract"


# 冷却状态必须显式声明；None 表示未知，不能由 cooldown_until=None 推断为“无冷却”。
class CooldownStatus(StrEnum):
    NONE = "none"
    ACTIVE = "active"


# C3 领域错误携带稳定原因码；API/调用方据此返回安全提示，不回显财务正文或上游细节。
class PlanningInputError(AgentContractError):
    def __init__(self, message: str, *, code: str = "planning_input_invalid") -> None:
        super().__init__(message, code=code)


class PlanningRequestConflictError(PlanningInputError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="planning_request_conflict")


class PlanningGenerationConflictError(PlanningInputError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="planning_generation_conflict")


class PlanningInputExpiredError(PlanningInputError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="planning_input_expired")


class PlanningIntegrityError(PlanningInputError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="planning_integrity_violation")


class PlanningRepositoryError(PlanningInputError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="planning_input_unavailable")


class PlanningRuleUnavailableError(PlanningInputError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="planning_rule_unavailable")


class PlanningProductUnsupportedError(PlanningInputError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="planning_product_unsupported")


# 校验 UTC 时间；本地时区或 naive 时间会使时效判断不可复现。
def _require_utc(value: datetime) -> datetime:
    return require_utc(value)


# 与 Pydantic JSON 序列化保持一致的 UTC 表示；版本指纹必须跨构建路径稳定。
def _utc_json(value: datetime) -> str:
    return _require_utc(value).astimezone(UTC).isoformat().replace("+00:00", "Z")


# 校验可选 UTC 时间，None 保持未知/未声明语义。
def _optional_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _require_utc(value)


# 把构建参数规范化为 JSON 十进制文本；调用方可能传字符串或 Decimal，二者都受 C1 边界约束。
def _decimal_json(value: Decimal | str) -> str:
    return serialize_decimal_text(parse_decimal_text(value))


# 检查非负金融值；None 表示未知，不做隐式补零。
def _require_non_negative(value: Decimal | None, *, field: str) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{field} 不能为负")


# 检查必须为正的金融值；None 仍表示未知，由 missing_fields 处理。
def _require_positive(value: Decimal | None, *, field: str) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{field} 必须大于零")


# 校验官方过滤器上下界；最大值为无穷的交易所字段仍需显式数值，避免猜测。
def _validate_min_max(
    minimum: Decimal,
    maximum: Decimal,
    *,
    field: str,
) -> None:
    if minimum <= 0 or maximum < minimum:
        raise ValueError(f"{field} 上下界无效")


# 版本化快照公共基类：ref 指纹覆盖除 ref 本身外的全部 JSON 内容。
class VersionedPlanningSnapshot(AgentModel):
    ref: VersionRef

    # 重新序列化当前快照并计算内容指纹；子类新增字段会自动纳入。
    def content_sha256(self) -> str:
        payload = self.model_dump(mode="json", by_alias=False)
        payload.pop("ref", None)
        return sha256_json(cast(JsonValue, payload))

    # 校验 ref 与当前内容一致；数据库篡改、嵌套对象篡改或手工构造旧 ref 都会失败。
    @model_validator(mode="after")
    def validate_ref(self) -> Self:
        if self.ref.sha256 != self.content_sha256():
            raise ValueError("规划版本指纹与内容不一致")
        return self


# 先对规范化内容计算指纹，再构造快照；避免为了算 ref 而构造临时非法模型。
def _seal_snapshot[ModelT: VersionedPlanningSnapshot](
    model_type: type[ModelT],
    *,
    version_id: UUID,
    content: JsonObject,
) -> ModelT:
    digest = sha256_json(cast(JsonValue, content))
    payload: JsonObject = {
        **content,
        "ref": {"version_id": str(version_id), "sha256": digest},
    }
    return model_type.model_validate(payload)


# 成本与保证金资料共用的有效期规则：不得超过声明后 15 分钟或用户声明有效期。
def _validate_local_expiry(
    *,
    declared_at: datetime,
    expires_at: datetime,
    valid_until: datetime,
) -> None:
    _require_utc(declared_at)
    _require_utc(expires_at)
    _require_utc(valid_until)
    if expires_at <= declared_at:
        raise ValueError("资料有效期必须晚于声明时间")
    if expires_at > declared_at + PROFILE_VALIDITY:
        raise ValueError("资料有效期不能超过声明后 15 分钟")
    if expires_at > valid_until:
        raise ValueError("资料有效期不能超过用户声明有效期")


# 保证金证据的共享字段；来源固定为用户声明，不能伪装成公共 API 已核实。
class MarginEvidenceFields(AgentModel):
    margin_mode: MarginMode
    leverage: DecimalText
    applicable_notional: DecimalText
    maintenance_margin_rate: DecimalText | None = None
    maintenance_margin_amount: DecimalText | None = None
    required_margin: DecimalText
    liquidation_price_reference: DecimalText | None = None
    trigger_price_basis: Literal["mark_price", "last_price"] | None = None
    source: str = Field(min_length=1, max_length=200)

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("保证金来源不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.margin_mode is not MarginMode.ISOLATED:
            raise ValueError("首期规划只支持逐仓保证金模式")
        _require_positive(self.leverage, field="杠杆")
        _require_positive(self.applicable_notional, field="适用名义额")
        _require_non_negative(self.required_margin, field="所需保证金")
        if self.maintenance_margin_rate is not None:
            _require_non_negative(self.maintenance_margin_rate, field="维持保证金率")
            if self.maintenance_margin_rate >= 1:
                raise ValueError("维持保证金率必须小于 1")
        if self.maintenance_margin_amount is not None:
            _require_non_negative(self.maintenance_margin_amount, field="维持保证金额")
        if self.liquidation_price_reference is not None:
            _require_positive(self.liquidation_price_reference, field="强平参考价")
        return self

    # 维持保证金档位/预览与强平基准是必要核对项；缺失时标记待补而非通过。
    @property
    def missing_fields(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.maintenance_margin_rate is None and self.maintenance_margin_amount is None:
            missing.append("maintenance_margin_evidence")
        if self.liquidation_price_reference is None:
            missing.append("liquidation_price_reference")
        if self.trigger_price_basis is None:
            missing.append("trigger_price_basis")
        return tuple(missing)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields


class MarginEvidenceDraft(MarginEvidenceFields):
    valid_until: UtcDateTime

    @field_validator("valid_until")
    @classmethod
    def validate_valid_until(cls, value: datetime) -> datetime:
        return _require_utc(value)


class MarginEvidence(MarginEvidenceFields):
    valid_until: UtcDateTime
    declared_at: UtcDateTime
    expires_at: UtcDateTime
    source_type: Literal["user_declared"] = "user_declared"

    @field_validator("valid_until", "declared_at", "expires_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def validate_expiry(self) -> Self:
        _validate_local_expiry(
            declared_at=self.declared_at,
            expires_at=self.expires_at,
            valid_until=self.valid_until,
        )
        return self

    # 由用户草稿冻结证据和本地有效期；来源类型固定为用户声明。
    @classmethod
    def build(
        cls,
        *,
        draft: MarginEvidenceDraft,
        declared_at: datetime,
        expires_at: datetime,
    ) -> MarginEvidence:
        content = draft.model_dump(mode="json", by_alias=False)
        content.update(
            {
                "declared_at": _utc_json(declared_at),
                "expires_at": _utc_json(expires_at),
                "source_type": "user_declared",
            }
        )
        return cls.model_validate(content)


# 费用、滑点、价差与持有成本的共享字段；所有费率都是十进制小数而非百分数。
class CostAssumptionsFields(AgentModel):
    entry_fee_rate: DecimalText
    stop_exit_fee_rate: DecimalText
    target_exit_fee_rate: DecimalText
    slippage_rate: DecimalText
    spread_rate: DecimalText
    holding_cost_rate: DecimalText
    slippage_upper_bound: DecimalText
    spread_upper_bound: DecimalText
    holding_cost_upper_bound: DecimalText
    source: str = Field(min_length=1, max_length=200)

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("成本资料来源不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_costs(self) -> Self:
        for name in (
            "entry_fee_rate",
            "stop_exit_fee_rate",
            "target_exit_fee_rate",
            "slippage_rate",
            "spread_rate",
            "holding_cost_rate",
            "slippage_upper_bound",
            "spread_upper_bound",
            "holding_cost_upper_bound",
        ):
            value = cast(Decimal, getattr(self, name))
            _require_non_negative(value, field=name)
            if value > 1:
                raise ValueError(f"{name} 不能大于 1")
        if self.slippage_upper_bound < self.slippage_rate:
            raise ValueError("滑点上界不能低于情景值")
        if self.spread_upper_bound < self.spread_rate:
            raise ValueError("价差上界不能低于情景值")
        if self.holding_cost_upper_bound < self.holding_cost_rate:
            raise ValueError("持有成本上界不能低于情景值")
        return self


class CostAssumptionsDraft(CostAssumptionsFields):
    valid_until: UtcDateTime

    @field_validator("valid_until")
    @classmethod
    def validate_valid_until(cls, value: datetime) -> datetime:
        return _require_utc(value)


class CostAssumptions(CostAssumptionsFields, VersionedPlanningSnapshot):
    valid_until: UtcDateTime
    declared_at: UtcDateTime
    expires_at: UtcDateTime

    @field_validator("valid_until", "declared_at", "expires_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def validate_expiry(self) -> Self:
        _validate_local_expiry(
            declared_at=self.declared_at,
            expires_at=self.expires_at,
            valid_until=self.valid_until,
        )
        return self

    # 冻结成本版本；同一成本只允许通过新版本修改，不回写历史 profile。
    @classmethod
    def build(
        cls,
        *,
        version_id: UUID,
        draft: CostAssumptionsDraft,
        declared_at: datetime,
        expires_at: datetime,
    ) -> CostAssumptions:
        content = draft.model_dump(mode="json", by_alias=False)
        content.update(
            {
                "declared_at": _utc_json(declared_at),
                "expires_at": _utc_json(expires_at),
            }
        )
        return _seal_snapshot(cls, version_id=version_id, content=cast(JsonObject, content))


# 规划资料共享字段；未知值保持 None，由 missing_fields 暴露待补项。
class PlanningProfileFields(AgentModel):
    product: ProductKey
    planning_capital: DecimalText | None = None
    available_margin: DecimalText | None = None
    remaining_single_trade_risk: DecimalText | None = None
    remaining_daily_loss: DecimalText | None = None
    remaining_portfolio_risk: DecimalText | None = None
    existing_position_notional: DecimalText | None = None
    existing_position_margin: DecimalText | None = None
    existing_position_risk: DecimalText | None = None
    open_order_notional: DecimalText | None = None
    open_order_margin: DecimalText | None = None
    open_order_risk: DecimalText | None = None
    daily_risk_as_of: date | None = None
    cooldown_status: CooldownStatus | None = None
    cooldown_until: UtcDateTime | None = None
    circuit_breaker_active: bool | None = None
    leverage: DecimalText | None = None
    margin_mode: MarginMode | None = None
    position_mode: PositionMode | None = None

    @field_validator("cooldown_until")
    @classmethod
    def validate_cooldown(cls, value: datetime | None) -> datetime | None:
        return _optional_utc(value)

    @model_validator(mode="after")
    def validate_profile_fields(self) -> Self:
        _require_positive(self.planning_capital, field="规划资金")
        for name in (
            "available_margin",
            "remaining_single_trade_risk",
            "remaining_daily_loss",
            "remaining_portfolio_risk",
            "existing_position_notional",
            "existing_position_margin",
            "existing_position_risk",
            "open_order_notional",
            "open_order_margin",
            "open_order_risk",
        ):
            _require_non_negative(cast(Decimal | None, getattr(self, name)), field=name)
        _require_positive(self.leverage, field="杠杆")
        if self.margin_mode is not None and self.margin_mode is not MarginMode.ISOLATED:
            raise ValueError("首期规划只支持逐仓保证金模式")
        if self.position_mode is not None and self.position_mode is not PositionMode.ONE_WAY:
            raise ValueError("首期规划只支持单向持仓模式")
        return self

    # 冷却状态与截止时间必须成对；历史快照允许保留旧载荷“只有截止时间、没有状态”的形态，
    # 但读取后状态仍为未知，missing_fields 不通过，绝不推断为无冷却。
    def _validate_cooldown_consistency(self, *, allow_legacy_unknown: bool = False) -> None:
        if self.cooldown_status is None:
            if self.cooldown_until is not None and not allow_legacy_unknown:
                raise ValueError("未知冷却状态不能携带冷却截止时间")
        elif self.cooldown_status is CooldownStatus.NONE:
            if self.cooldown_until is not None:
                raise ValueError("已确认无冷却时不能携带冷却截止时间")
        elif self.cooldown_until is None:
            raise ValueError("存在冷却时必须提供冷却截止时间")

    # 资料完整所必需的显式字段；None 表示未知，不参与“未知当零”的推断。
    @property
    def missing_fields(self) -> tuple[str, ...]:
        required = (
            "planning_capital",
            "available_margin",
            "remaining_single_trade_risk",
            "remaining_daily_loss",
            "remaining_portfolio_risk",
            "existing_position_notional",
            "existing_position_margin",
            "existing_position_risk",
            "open_order_notional",
            "open_order_margin",
            "open_order_risk",
            "daily_risk_as_of",
            "cooldown_status",
            "circuit_breaker_active",
            "leverage",
            "margin_mode",
            "position_mode",
        )
        return tuple(name for name in required if getattr(self, name) is None)


class PlanningProfileDraft(PlanningProfileFields):
    margin_evidence: MarginEvidenceDraft | None = None
    costs: CostAssumptionsDraft | None = None

    @model_validator(mode="after")
    def validate_nested_inputs(self) -> Self:
        _validate_profile_margin(self.margin_mode, self.leverage, self.margin_evidence)
        self._validate_cooldown_consistency()
        return self

    # 草稿缺失项包括基础字段、成本/保证金资料及其内部待补项。
    @property
    def missing_fields(self) -> tuple[str, ...]:
        missing = list(super().missing_fields)
        if self.costs is None:
            missing.append("costs")
        if self.margin_evidence is None:
            missing.append("margin_evidence")
        else:
            missing.extend(self.margin_evidence.missing_fields)
        return tuple(missing)


class PlanningProfileSnapshot(PlanningProfileFields, VersionedPlanningSnapshot):
    pool_id: UUID
    pool_generation: int = Field(ge=0)
    margin_evidence: MarginEvidence | None = None
    costs_ref: VersionRef | None = None
    declared_at: UtcDateTime
    expires_at: UtcDateTime
    source: Literal["user_declared"] = "user_declared"

    # 首轮快照没有 cooldown_status 字段；Pydantic 的 fields_set 保留该字段是否实际出现。
    # 仅凭字段缺失进入历史兼容分支，不能把新版显式 null 或篡改后的载荷当作旧版。
    @property
    def is_legacy_profile(self) -> bool:
        return "cooldown_status" not in self.model_fields_set

    # 历史快照按旧字段集合校验原始指纹；新版按完整字段集合校验。
    # 这不是跳过校验：历史财务/嵌套字段仍参与旧字段集合的哈希。
    def content_sha256(self) -> str:
        excluded = {"ref", "cooldown_status"} if self.is_legacy_profile else {"ref"}
        payload = self.model_dump(mode="json", by_alias=False, exclude=excluded)
        return sha256_json(cast(JsonValue, payload))

    # 历史归档序列化保留原字段集合，避免把默认 None 物化后破坏旧 ref；
    # 新版快照仍序列化全部字段。
    def versioned_payload(self) -> JsonObject:
        return cast(
            JsonObject,
            self.model_dump(
                mode="json",
                by_alias=False,
                exclude_unset=self.is_legacy_profile,
            ),
        )

    @field_validator("declared_at", "expires_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        _require_utc(self.declared_at)
        _require_utc(self.expires_at)
        if self.expires_at <= self.declared_at:
            raise ValueError("规划资料有效期必须晚于声明时间")
        if self.expires_at > self.declared_at + PROFILE_VALIDITY:
            raise ValueError("规划资料有效期不能超过声明后 15 分钟")
        _validate_profile_margin(self.margin_mode, self.leverage, self.margin_evidence)
        # 首轮历史载荷允许只有 cooldown_until 而没有状态；读取后仍为未知/不完整。
        self._validate_cooldown_consistency(allow_legacy_unknown=self.is_legacy_profile)
        if self.margin_evidence is not None and self.expires_at > self.margin_evidence.expires_at:
            raise ValueError("规划资料有效期不能超过保证金证据有效期")
        if self.daily_risk_as_of is not None and self.daily_risk_as_of > self.declared_at.date():
            raise ValueError("当日损益资料日期不能晚于声明日")
        if (
            self.cooldown_status is CooldownStatus.ACTIVE
            and self.cooldown_until is not None
            and self.cooldown_until <= self.declared_at
        ):
            raise ValueError("冷却截止时间必须晚于资料声明时间")
        return self

    # 完整资料必须包含成本版本和完整保证金证据；缺失只标记待补。
    @property
    def missing_fields(self) -> tuple[str, ...]:
        missing = list(super().missing_fields)
        if self.costs_ref is None:
            missing.append("costs")
        if self.margin_evidence is None:
            missing.append("margin_evidence")
        else:
            missing.extend(self.margin_evidence.missing_fields)
        return tuple(missing)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields

    # 快照在 expires_at 时刻及之后失效；调用方还须核对当日损益日期。
    def is_expired(self, now: datetime) -> bool:
        return _require_utc(now) >= self.expires_at

    # 由完整草稿冻结服务端资料版本；costs 已单独冻结并通过 costs_ref 关联。
    @classmethod
    def build(
        cls,
        *,
        version_id: UUID,
        pool_id: UUID,
        pool_generation: int,
        draft: PlanningProfileDraft,
        margin_evidence: MarginEvidence | None,
        costs_ref: VersionRef | None,
        declared_at: datetime,
        expires_at: datetime,
    ) -> PlanningProfileSnapshot:
        content = draft.model_dump(
            mode="json",
            by_alias=False,
            exclude={"costs", "margin_evidence"},
        )
        content.update(
            {
                "pool_id": str(pool_id),
                "pool_generation": pool_generation,
                "margin_evidence": (
                    None
                    if margin_evidence is None
                    else margin_evidence.model_dump(mode="json", by_alias=False)
                ),
                "costs_ref": (
                    None if costs_ref is None else costs_ref.model_dump(mode="json", by_alias=False)
                ),
                "declared_at": _utc_json(declared_at),
                "expires_at": _utc_json(expires_at),
                "source": "user_declared",
            }
        )
        return _seal_snapshot(cls, version_id=version_id, content=cast(JsonObject, content))


# 校验资料与保证金证据的模式/杠杆一致；草稿和快照共用，避免只在某一层放行。
def _validate_profile_margin(
    margin_mode: MarginMode | None,
    leverage: Decimal | None,
    evidence: MarginEvidenceFields | None,
) -> None:
    if evidence is None:
        return
    if margin_mode is not None and evidence.margin_mode is not margin_mode:
        raise ValueError("规划资料与保证金证据的模式不一致")
    if leverage is not None and evidence.leverage != leverage:
        raise ValueError("规划资料与保证金证据的杠杆不一致")


# 风险政策共享字段；所有金额、比例和杠杆无默认值，None 表示尚未确认。
class PlanningRiskPolicyFields(AgentModel):
    max_risk_per_trade: DecimalText | None = None
    max_notional: DecimalText | None = None
    max_quantity: DecimalText | None = None
    max_leverage: DecimalText | None = None
    min_reward_risk_ratio: DecimalText | None = None
    max_daily_loss: DecimalText | None = None
    max_portfolio_risk: DecimalText | None = None
    stop_loss_required: bool | None = None
    enforce_cooldown: bool | None = None
    enforce_circuit_breaker: bool | None = None

    @model_validator(mode="after")
    def validate_policy_fields(self) -> Self:
        for name in ("max_risk_per_trade", "max_notional", "max_quantity", "max_leverage"):
            _require_positive(cast(Decimal | None, getattr(self, name)), field=name)
        _require_positive(self.min_reward_risk_ratio, field="最小净盈亏比")
        _require_non_negative(self.max_daily_loss, field="最大日损")
        _require_non_negative(self.max_portfolio_risk, field="最大组合风险")
        if self.stop_loss_required is False:
            raise ValueError("首期手动规划必须强制止损")
        if self.enforce_cooldown is False:
            raise ValueError("首期手动规划必须执行冷却约束")
        if self.enforce_circuit_breaker is False:
            raise ValueError("首期手动规划必须执行熔断约束")
        return self

    @property
    def missing_fields(self) -> tuple[str, ...]:
        required = (
            "max_risk_per_trade",
            "max_notional",
            "max_quantity",
            "max_leverage",
            "min_reward_risk_ratio",
            "max_daily_loss",
            "max_portfolio_risk",
            "stop_loss_required",
            "enforce_cooldown",
            "enforce_circuit_breaker",
        )
        return tuple(name for name in required if getattr(self, name) is None)


class PlanningRiskPolicyDraft(PlanningRiskPolicyFields):
    pass


class PlanningRiskPolicy(PlanningRiskPolicyFields, VersionedPlanningSnapshot):
    pool_id: UUID
    pool_generation: int = Field(ge=0)
    declared_at: UtcDateTime
    source: Literal["user_declared"] = "user_declared"

    @field_validator("declared_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields

    # 由用户明确确认的政策草稿冻结新版本；不会从资料或模拟盘配置推断默认值。
    @classmethod
    def build(
        cls,
        *,
        version_id: UUID,
        pool_id: UUID,
        pool_generation: int,
        draft: PlanningRiskPolicyDraft,
        declared_at: datetime,
    ) -> PlanningRiskPolicy:
        content = draft.model_dump(mode="json", by_alias=False)
        content.update(
            {
                "pool_id": str(pool_id),
                "pool_generation": pool_generation,
                "declared_at": _utc_json(declared_at),
                "source": "user_declared",
            }
        )
        return _seal_snapshot(cls, version_id=version_id, content=cast(JsonObject, content))


# 公开交易规则快照；过滤器以真实 step/tick 为准，不读取 pricePrecision/quantityPrecision 推断。
class VenueRuleSnapshot(VersionedPlanningSnapshot):
    product: ProductKey
    contract_multiplier: DecimalText
    quantity_unit: QuantityUnit
    price_tick: DecimalText
    min_price: DecimalText
    max_price: DecimalText
    quantity_step: DecimalText
    min_quantity: DecimalText
    max_quantity: DecimalText
    market_min_quantity: DecimalText
    market_max_quantity: DecimalText
    market_quantity_step: DecimalText
    min_notional: DecimalText
    trading_status: str = Field(min_length=1, max_length=32)
    order_types: tuple[str, ...]
    time_in_force: tuple[str, ...]
    observed_at: UtcDateTime
    expires_at: UtcDateTime
    source: str = Field(min_length=1, max_length=200)

    @field_validator("observed_at", "expires_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("trading_status", "source")
    @classmethod
    def strip_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("规则来源或交易状态不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_rules(self) -> Self:
        _require_positive(self.contract_multiplier, field="合约乘数")
        _require_positive(self.price_tick, field="价格步长")
        _require_positive(self.quantity_step, field="数量步长")
        _require_positive(self.market_quantity_step, field="市价数量步长")
        _require_positive(self.min_quantity, field="最小数量")
        _require_positive(self.min_notional, field="最小名义额")
        _validate_min_max(self.min_price, self.max_price, field="价格过滤器")
        _validate_min_max(self.min_quantity, self.max_quantity, field="数量过滤器")
        _validate_min_max(
            self.market_min_quantity,
            self.market_max_quantity,
            field="市价数量过滤器",
        )
        if self.observed_at >= self.expires_at:
            raise ValueError("规则有效期必须晚于观测时间")
        if self.expires_at > self.observed_at + VENUE_RULE_VALIDITY:
            raise ValueError("规则有效期不能超过观测后 60 分钟")
        if not self.order_types:
            raise ValueError("规则快照必须包含订单类型")
        if not self.time_in_force:
            raise ValueError("规则快照必须包含有效期类型")
        return self

    # 交易状态与订单类型检查是确定性的；调用方不能把未知当作支持。
    @property
    def is_trading(self) -> bool:
        return self.trading_status == "TRADING"

    def supports_order_type(self, order_type: str) -> bool:
        return order_type in self.order_types

    # 由公开规则适配器冻结快照；数字使用与模型序列化一致的规范十进制文本。
    @classmethod
    def build(
        cls,
        *,
        version_id: UUID,
        product: ProductKey | dict[str, str],
        contract_multiplier: Decimal | str,
        quantity_unit: QuantityUnit | str,
        price_tick: Decimal | str,
        min_price: Decimal | str,
        max_price: Decimal | str,
        quantity_step: Decimal | str,
        min_quantity: Decimal | str,
        max_quantity: Decimal | str,
        market_min_quantity: Decimal | str,
        market_max_quantity: Decimal | str,
        market_quantity_step: Decimal | str,
        min_notional: Decimal | str,
        trading_status: str,
        order_types: tuple[str, ...],
        time_in_force: tuple[str, ...],
        observed_at: datetime,
        expires_at: datetime,
        source: str,
    ) -> VenueRuleSnapshot:
        product_payload = (
            product.model_dump(mode="json", by_alias=False)
            if isinstance(product, ProductKey)
            else product
        )
        content: JsonObject = {
            "product": cast(JsonValue, product_payload),
            "contract_multiplier": _decimal_json(contract_multiplier),
            "quantity_unit": quantity_unit.value
            if isinstance(quantity_unit, QuantityUnit)
            else quantity_unit,
            "price_tick": _decimal_json(price_tick),
            "min_price": _decimal_json(min_price),
            "max_price": _decimal_json(max_price),
            "quantity_step": _decimal_json(quantity_step),
            "min_quantity": _decimal_json(min_quantity),
            "max_quantity": _decimal_json(max_quantity),
            "market_min_quantity": _decimal_json(market_min_quantity),
            "market_max_quantity": _decimal_json(market_max_quantity),
            "market_quantity_step": _decimal_json(market_quantity_step),
            "min_notional": _decimal_json(min_notional),
            "trading_status": trading_status,
            "order_types": list(order_types),
            "time_in_force": list(time_in_force),
            "observed_at": _utc_json(observed_at),
            "expires_at": _utc_json(expires_at),
            "source": source,
        }
        return _seal_snapshot(cls, version_id=version_id, content=content)


# 规划引用组合；只含不可变引用和池代次，不内嵌完整财务资料。
class PlanningRefs(AgentModel):
    profile: VersionRef
    policy: VersionRef
    venue_rules: VersionRef
    costs: VersionRef
    pool_id: UUID
    pool_generation: int = Field(ge=0)


__all__ = [
    "PROFILE_VALIDITY",
    "VENUE_RULE_VALIDITY",
    "CostAssumptions",
    "CostAssumptionsDraft",
    "CostAssumptionsFields",
    "CooldownStatus",
    "MarginEvidence",
    "MarginEvidenceDraft",
    "MarginEvidenceFields",
    "MarginMode",
    "PlanningGenerationConflictError",
    "PlanningInputError",
    "PlanningInputExpiredError",
    "PlanningIntegrityError",
    "PlanningProductUnsupportedError",
    "PlanningProfileDraft",
    "PlanningProfileFields",
    "PlanningProfileSnapshot",
    "PlanningRefs",
    "PlanningRepositoryError",
    "PlanningRequestConflictError",
    "PlanningRiskPolicy",
    "PlanningRiskPolicyDraft",
    "PlanningRiskPolicyFields",
    "PlanningRuleUnavailableError",
    "PositionMode",
    "QuantityUnit",
    "VenueRuleSnapshot",
    "VersionedPlanningSnapshot",
]
