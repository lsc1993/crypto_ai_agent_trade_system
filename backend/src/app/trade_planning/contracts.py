# 定义 T12 确定性手动交易规划的纯契约：规划请求、报价、数量结果、逐项检查和
# 人工实施清单。所有类型都是不可变 Pydantic 模型，输入是已完成解析的 C3 资料、
# T01 价格候选和公开规则；不查询数据库、不调用模型、不生成 TradeIntent 或订单。
# 财务值只进入受限规划域；检查与清单只保存来源引用、状态和指纹，不把账户或凭证
# 写入日志。数量、费用、保证金使用 Decimal，时间统一为 UTC。
from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from enum import StrEnum
from typing import Literal, Self, cast

from pydantic import Field, JsonValue, field_validator, model_validator

from app.research.strategies.contracts import PriceCandidate, StrategyDirection
from app.shared.agent_types import (
    AgentContractError,
    AgentModel,
    ArtifactRef,
    DecimalText,
    JsonObject,
    UtcDateTime,
    VersionRef,
    is_sha256,
    parse_decimal_text,
    require_utc,
    serialize_decimal_text,
    sha256_json,
)
from app.trade_planning.inputs import (
    CostAssumptions,
    PlanningProfileSnapshot,
    PlanningRefs,
    PlanningRiskPolicy,
    QuantityUnit,
    VenueRuleSnapshot,
)

# 当前公开报价只允许作为采纳/重验的短时参考；计划有效期与核验有效期分开。
QUOTE_VALIDITY = timedelta(seconds=60)
# 计算精度远高于输入允许的 30+18 位，避免中间乘除被默认 28 位精度截断。
CALCULATION_PRECISION = 80
# 对外 DecimalText 固定 18 位小数；结算金额向上、收益向下，避免低估风险/高估收益。
SETTLEMENT_PLACES = Decimal("0.000000000000000001")
_MAX_ABS_DECIMAL = Decimal("1" * 30)
_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CHECK_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


# 规划失败必须携带有限原因码；不把上游财务正文、异常栈或供应商细节放进原因。
class PlanningCalculationError(AgentContractError):
    def __init__(self, message: str, *, code: str = "planning_calculation_failed") -> None:
        super().__init__(message, code=code)


# 稳定原因码供检查、清单和后续 T13 readiness 映射；修改值需要同步消费者/测试。
class PlanningReason(StrEnum):
    INPUTS_INCOMPLETE = "planning_inputs_incomplete"
    PROFILE_INCOMPLETE = "profile_incomplete"
    POLICY_INCOMPLETE = "policy_incomplete"
    PROFILE_EXPIRED = "planning_profile_expired"
    COSTS_EXPIRED = "planning_costs_expired"
    RULES_EXPIRED = "planning_rules_expired"
    RULES_NOT_TRADING = "planning_rules_not_trading"
    QUOTE_EXPIRED = "planning_quote_expired"
    CANDIDATE_EXPIRED = "planning_candidate_expired"
    DAILY_RISK_STALE = "daily_risk_declaration_stale"
    COOLDOWN_ACTIVE = "cooldown_active"
    CIRCUIT_BREAKER_ACTIVE = "circuit_breaker_active"
    PRODUCT_UNSUPPORTED = "product_not_supported"
    MARGIN_MODE_UNSUPPORTED = "margin_mode_unsupported"
    POSITION_MODE_UNSUPPORTED = "position_mode_unsupported"
    EXPOSURE_UNKNOWN = "existing_exposure_unknown"
    EXISTING_POSITION_UNSUPPORTED = "existing_position_unsupported"
    OPEN_ORDERS_UNSUPPORTED = "open_orders_unsupported"
    ORDER_TYPE_UNSUPPORTED = "order_type_unsupported"
    TIME_IN_FORCE_UNSUPPORTED = "time_in_force_unsupported"
    LEVERAGE_EXCEEDS_POLICY = "leverage_exceeds_policy"
    PRICE_NOT_ON_TICK = "price_not_on_tick"
    PRICE_TOLERANCE_EXCEEDED = "price_tolerance_exceeded"
    PRICE_OUTSIDE_FILTERS = "price_outside_filters"
    PRICE_GEOMETRY_INVALID = "price_geometry_invalid"
    MARKET_PRICE_BOUND_MISSING = "market_price_bound_missing"
    MARKET_PRICE_BOUND_OUTSIDE_ENTRY = "market_price_bound_outside_entry"
    MARKET_PRICE_BOUND_INCONSISTENT = "market_price_bound_inconsistent"
    UNIT_INCONSISTENT = "quantity_unit_inconsistent"
    QUANTITY_NOT_SIZED = "quantity_not_sized"
    MIN_QUANTITY_NOT_MET = "min_quantity_not_met"
    MIN_NOTIONAL_NOT_MET = "min_notional_not_met"
    MAX_QUANTITY_EXCEEDED = "max_quantity_exceeded"
    MAX_NOTIONAL_EXCEEDED = "max_notional_exceeded"
    RISK_BUDGET_UNAVAILABLE = "risk_budget_unavailable"
    RISK_BUDGET_EXCEEDED = "risk_budget_exceeded"
    REWARD_NOT_POSITIVE = "target_net_reward_not_positive"
    LOSS_NOT_POSITIVE = "stop_path_loss_not_positive"
    REWARD_RISK_BELOW_MIN = "reward_risk_ratio_below_minimum"
    MARGIN_EXCEEDS_AVAILABLE = "initial_margin_exceeds_available"
    MARGIN_EVIDENCE_INCOMPLETE = "margin_evidence_incomplete"
    MARGIN_EVIDENCE_EXPIRED = "margin_evidence_expired"
    MARGIN_PREVIEW_NOT_APPLICABLE = "margin_preview_not_applicable"
    MARGIN_PREVIEW_MISMATCH = "margin_preview_mismatch"
    LIQUIDATION_DISTANCE_UNSAFE = "liquidation_distance_unsafe"
    EXIT_ALLOCATION_INCOMPLETE = "exit_allocation_incomplete"
    EXIT_ORDER_TYPE_UNSUPPORTED = "exit_order_type_unsupported"
    EXIT_QUANTITY_STEP_INVALID = "exit_quantity_step_invalid"
    SIZING_MATERIAL_MISMATCH = "sizing_material_mismatch"
    PRECISION_EXCEEDED = "planning_precision_exceeded"
    CALCULATION_FAILED = "planning_calculation_failed"


class SizingStatus(StrEnum):
    SIZED = "sized"
    BLOCKED = "blocked"


class OrderOperation(StrEnum):
    LIMIT = "limit"
    MARKET = "market"


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class CheckBasis(StrEnum):
    DETERMINISTIC_CALCULATION = "deterministic_calculation"
    PUBLIC_SOURCE = "public_source"
    USER_DECLARED = "user_declared"


# 核对项来源分层：程序计算不等于交易所账户核实，用户声明也不等于公共 API 核实。
class ChecklistVerification(StrEnum):
    PROGRAM_VERIFIED = "program_verified"
    USER_DECLARED = "user_declared"
    MANUAL_CONFIRMATION_REQUIRED = "manual_confirmation_required"


# 检查名称是 T13/T14 消费的公共集合；新增/删除必须同步 risk_checks、清单完整性和
# 下游 readiness，不能只在一处增加一个“总是 pass”的检查。
PLANNING_CHECK_NAMES: tuple[str, ...] = (
    "profile_complete",
    "policy_complete",
    "profile_current",
    "costs_current",
    "rules_current",
    "quote_current",
    "candidate_current",
    "daily_risk_current",
    "cooldown_inactive",
    "circuit_breaker_inactive",
    "product_supported",
    "existing_exposure_supported",
    "leverage_within_policy",
    "price_grid_valid",
    "order_type_supported",
    "order_time_in_force_supported",
    "market_price_bound_supported",
    "sizing_material_matches",
    "exit_order_types_supported",
    "quantity_sized",
    "min_quantity_met",
    "min_notional_met",
    "max_quantity_respected",
    "max_notional_respected",
    "risk_within_budget",
    "reward_risk_ratio_met",
    "initial_margin_within_capital",
    "margin_evidence_current",
    "margin_evidence_complete",
    "margin_preview_matches",
    "liquidation_distance_safe",
    "stop_exit_quantity_valid",
    "target_exit_quantity_valid",
    "exit_allocation_complete",
)


# 把中间 Decimal 规范到 18 位；向上用于风险/保证金，向下用于收益/比率。
# 超出 C1 数值边界时拒绝，而不是悄悄截断成另一个金额。
def quantize_decimal(value: Decimal, *, direction: Literal["up", "down"]) -> Decimal:
    if not value.is_finite():
        raise PlanningCalculationError(
            "规划计算产生非有限数值",
            code=PlanningReason.PRECISION_EXCEEDED.value,
        )
    rounding = ROUND_CEILING if direction == "up" else ROUND_FLOOR
    try:
        with localcontext() as context:
            context.prec = 100
            quantized = value.quantize(SETTLEMENT_PLACES, rounding=rounding)
        parsed = parse_decimal_text(quantized)
    except (ArithmeticError, ValueError) as error:
        raise PlanningCalculationError(
            "规划计算超出十进制边界",
            code=PlanningReason.PRECISION_EXCEEDED.value,
        ) from error
    if abs(parsed) > _MAX_ABS_DECIMAL:
        raise PlanningCalculationError(
            "规划计算超出十进制边界",
            code=PlanningReason.PRECISION_EXCEEDED.value,
        )
    return parsed


# 解析结果的价格/数量必须为正；阻断结果由调用方显式填写零，不从 None 推断。
def _require_positive(value: Decimal | None, *, field: str) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{field} 必须大于零")


# 规划专用报价：引用不可变快照，保留观测/失效时刻和可选最大不利成交价。
# 当前价不是成交保证；市场单缺少明确上界时不得进入求解。
class PlanningQuote(AgentModel):
    artifact: ArtifactRef
    price: DecimalText
    observed_at: UtcDateTime
    expires_at: UtcDateTime
    source: str = Field(min_length=1, max_length=200)
    max_adverse_price: DecimalText | None = None

    @field_validator("observed_at", "expires_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("source")
    @classmethod
    def strip_source(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("报价来源不能为空")
        return normalized

    @model_validator(mode="after")
    def validate_quote(self) -> Self:
        _require_positive(self.price, field="报价")
        if self.expires_at <= self.observed_at:
            raise ValueError("报价有效期必须晚于观测时间")
        if self.expires_at > self.observed_at + QUOTE_VALIDITY:
            raise ValueError("报价有效期不能超过观测后 60 秒")
        _require_positive(self.max_adverse_price, field="最大不利成交价")
        return self


# 规划请求在一次评估时刻冻结全部已解析输入。它不是 API DTO：调用方必须先按
# VersionRef 读取并校验版本，不能让纯函数自行查库或读取“最新”版本。
class PlanningRequest(AgentModel):
    candidate: PriceCandidate
    strategy_ref: VersionRef
    refs: PlanningRefs
    profile: PlanningProfileSnapshot
    policy: PlanningRiskPolicy
    rules: VenueRuleSnapshot
    costs: CostAssumptions
    quote: PlanningQuote
    evaluated_at: UtcDateTime
    order_operation: OrderOperation = OrderOperation.LIMIT

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        return require_utc(value)

    # 所有版本引用必须精确对应内嵌正文；把旧 ref 套到新资料会让指纹和审计失真。
    def _validate_ref_bindings(self) -> None:
        if self.refs.profile != self.profile.ref:
            raise ValueError("规划资料的版本引用与正文不一致")
        if self.refs.policy != self.policy.ref:
            raise ValueError("风险政策的版本引用与正文不一致")
        if self.refs.venue_rules != self.rules.ref:
            raise ValueError("市场规则的版本引用与正文不一致")
        if self.refs.costs != self.costs.ref:
            raise ValueError("成本资料的版本引用与正文不一致")
        if self.profile.costs_ref != self.costs.ref:
            raise ValueError("规划资料关联的成本版本不一致")
        if self.refs.pool_id != self.profile.pool_id or self.refs.pool_id != self.policy.pool_id:
            raise ValueError("规划引用与资料不属于同一资金池")
        # profile/policy 是分别写入的不可变版本，共享池代次会在二者之间/规则刷新时
        # 前进；refs 表示当前池代次，只要求不早于两个版本，不能要求三者完全相等。
        if (
            self.profile.pool_generation > self.refs.pool_generation
            or self.policy.pool_generation > self.refs.pool_generation
        ):
            raise ValueError("规划资料的创建代次不能晚于当前资金池代次")
        if self.rules.product != self.profile.product:
            raise ValueError("市场规则产品与规划资料产品不一致")
        if self.candidate.strategy_ref != self.strategy_ref:
            raise ValueError("价格候选与所选策略版本不一致")

    # 未来观测/声明不能冒充当前资料；这里拒绝明显的时间倒置，具体时效由检查判定。
    def _validate_no_future_inputs(self) -> None:
        if self.quote.observed_at > self.evaluated_at:
            raise ValueError("报价观测时间不能晚于评估时刻")
        if self.profile.declared_at > self.evaluated_at:
            raise ValueError("规划资料声明时间不能晚于评估时刻")
        if self.policy.declared_at > self.evaluated_at:
            raise ValueError("风险政策声明时间不能晚于评估时刻")
        if self.costs.declared_at > self.evaluated_at:
            raise ValueError("成本资料声明时间不能晚于评估时刻")
        if self.rules.observed_at > self.evaluated_at:
            raise ValueError("市场规则观测时间不能晚于评估时刻")
        if self.candidate.evidence_as_of > self.evaluated_at:
            raise ValueError("价格候选证据截止时间不能晚于评估时刻")

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        self._validate_ref_bindings()
        self._validate_no_future_inputs()
        return self

    # 材料指纹绑定候选、精确版本引用、报价引用/时刻和操作选择；不内嵌原始财务值。
    # 评估时刻不是材料版本，刻意不进入指纹：同一报价/资料在有效期内重读应保持同一
    # 材料，T13 的时效由 derive_readiness 的 now 单独判断。
    def material_sha256(self) -> str:
        payload: JsonObject = {
            "candidateId": str(self.candidate.candidate_id),
            "strategyRef": self.strategy_ref.model_dump(mode="json", by_alias=False),
            "refs": self.refs.model_dump(mode="json", by_alias=False),
            "quoteArtifact": self.quote.artifact.model_dump(mode="json", by_alias=False),
            "quoteObservedAt": self.quote.observed_at.isoformat(),
            "quoteExpiresAt": self.quote.expires_at.isoformat(),
            "quotePrice": serialize_decimal_text(self.quote.price),
            "maxAdversePrice": (
                None
                if self.quote.max_adverse_price is None
                else serialize_decimal_text(self.quote.max_adverse_price)
            ),
            "orderOperation": self.order_operation.value,
        }
        return sha256_json(cast(JsonValue, payload))


# 止损/目标/入场价格和数量步长来自规则/候选的交叉结果；只含价格几何，不含金额。
class PriceGeometry(AgentModel):
    entry: DecimalText
    stop: DecimalText
    target: DecimalText
    entry_lower: DecimalText
    trigger: DecimalText
    entry_upper: DecimalText
    quantity_step: DecimalText
    price_tick: DecimalText

    @model_validator(mode="after")
    def validate_geometry(self) -> Self:
        for name in (
            "entry",
            "stop",
            "target",
            "entry_lower",
            "trigger",
            "entry_upper",
            "quantity_step",
            "price_tick",
        ):
            if cast(Decimal, getattr(self, name)) <= 0:
                raise ValueError("价格几何与步长必须为正")
        if not self.entry_lower <= self.trigger <= self.entry_upper:
            raise ValueError("触发价必须位于可执行入场区间")
        return self


# 数量求解结果。status=blocked 时 quantity=0，原因写入 reason_codes；
# 不以 None/默认值冒充已计算，也不让调用方从未完成的中间量继续生成清单。
class SizingResult(AgentModel):
    status: SizingStatus
    material_hash: str
    quantity: DecimalText
    notional: DecimalText
    initial_margin: DecimalText
    stop_path_loss: DecimalText
    target_net_reward: DecimalText
    net_reward_risk_ratio: DecimalText | None
    risk_budget: DecimalText | None
    entry_price: DecimalText | None
    stop_price: DecimalText | None
    target_price: DecimalText | None
    entry_lower: DecimalText | None
    trigger: DecimalText | None
    entry_upper: DecimalText | None
    stop_exit_quantity: DecimalText
    target_exit_quantity: DecimalText
    quantity_step: DecimalText
    price_tick: DecimalText
    expires_at: UtcDateTime
    calculation_version: Literal["manual_sizing_v1"] = "manual_sizing_v1"
    reason_codes: tuple[PlanningReason, ...] = ()

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime) -> datetime:
        return require_utc(value)

    @field_validator("material_hash")
    @classmethod
    def validate_material_hash(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("数量结果材料指纹必须是 64 位小写十六进制")
        return value

    @model_validator(mode="after")
    def validate_sizing(self) -> Self:
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("数量求解原因不能重复")
        if self.status is SizingStatus.SIZED:
            if self.quantity <= 0 or self.notional <= 0:
                raise ValueError("已求得数量必须为正")
            if self.stop_path_loss <= 0 or self.target_net_reward <= 0:
                raise ValueError("已求得风险与目标收益必须为正")
            if self.net_reward_risk_ratio is None or self.net_reward_risk_ratio <= 0:
                raise ValueError("已求得净盈亏比必须为正")
            if self.entry_price is None or self.stop_price is None or self.target_price is None:
                raise ValueError("已求得数量必须包含完整价格几何")
            if self.entry_lower is None or self.trigger is None or self.entry_upper is None:
                raise ValueError("已求得数量必须包含可执行入场区间")
            if self.reason_codes:
                raise ValueError("已求得数量不能携带阻断原因")
        else:
            if self.quantity != 0 or self.stop_path_loss != 0 or self.target_net_reward != 0:
                raise ValueError("阻断结果不能包含可执行数量或风险值")
            if not self.reason_codes:
                raise ValueError("阻断结果必须说明原因")
        return self


# 逐项检查只保存状态、来源、时刻和指纹，不复制完整财务载荷；T13 据此派生 readiness。
class ValidationCheck(AgentModel):
    name: str = Field(pattern=_CHECK_NAME_PATTERN)
    required: bool
    status: CheckStatus
    basis: CheckBasis
    source: str = Field(min_length=1, max_length=120)
    time: UtcDateTime | None = None
    material_hash: str
    expires_at: UtcDateTime | None = None
    reason_code: str | None = Field(default=None, pattern=_CODE_PATTERN.pattern)

    @field_validator("time", "expires_at")
    @classmethod
    def validate_times(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value)

    @field_validator("material_hash")
    @classmethod
    def validate_material_hash(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("检查材料指纹必须是 64 位小写十六进制")
        return value

    @model_validator(mode="after")
    def validate_reason(self) -> Self:
        if self.status is CheckStatus.PASS and self.reason_code is not None:
            raise ValueError("通过的检查不能携带失败原因")
        if self.status is not CheckStatus.PASS and self.reason_code is None:
            raise ValueError("未通过的检查必须说明原因")
        return self


# 人工清单条目：required 表示用户实施前必须核对，不等于系统已核验交易所账户。
class ManualChecklistItem(AgentModel):
    code: str = Field(pattern=_CHECK_NAME_PATTERN)
    verification: ChecklistVerification
    required: bool = True


# 异常/操作分支只是人工说明：系统不代用户发单、撤单或调整交易所参数。
class ManualExceptionBranch(AgentModel):
    code: str = Field(pattern=_CHECK_NAME_PATTERN)
    requires_user_action: bool = True
    automatic_order_action: Literal[False] = False
    recalculate_required: bool = False


# 完整手动清单绑定计划材料、数量/价格/保证金、检查结果和分支。
# execution_mode 固定 manual；不提供“可实施”布尔值，避免绕过 T13 的 adoption/时效。
class ManualChecklist(AgentModel):
    material_hash: str
    execution_mode: Literal["manual"] = "manual"
    direction: StrategyDirection
    order_operation: OrderOperation
    order_type: str = Field(pattern=r"^[A-Z][A-Z_]{1,31}$")
    time_in_force: str | None = Field(default=None, pattern=r"^[A-Z][A-Z_]{1,15}$")
    quantity_unit: QuantityUnit
    quantity: DecimalText
    notional: DecimalText
    initial_margin: DecimalText
    stop_path_loss: DecimalText
    target_net_reward: DecimalText
    entry_lower: DecimalText
    trigger: DecimalText
    entry_upper: DecimalText
    planned_entry: DecimalText
    stop_loss: DecimalText
    target: DecimalText
    expires_at: UtcDateTime
    items: tuple[ManualChecklistItem, ...]
    exception_branches: tuple[ManualExceptionBranch, ...]
    blocking_checks: tuple[str, ...]
    checks: tuple[ValidationCheck, ...]

    @field_validator("material_hash")
    @classmethod
    def validate_material_hash(cls, value: str) -> str:
        if not is_sha256(value):
            raise ValueError("清单材料指纹必须是 64 位小写十六进制")
        return value

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime) -> datetime:
        return require_utc(value)

    @model_validator(mode="after")
    def validate_checklist(self) -> Self:
        item_codes = tuple(item.code for item in self.items)
        branch_codes = tuple(branch.code for branch in self.exception_branches)
        if len(set(item_codes)) != len(item_codes):
            raise ValueError("人工清单条目不能重复")
        if len(set(branch_codes)) != len(branch_codes):
            raise ValueError("异常分支不能重复")
        expected_blocking = {
            check.name
            for check in self.checks
            if check.required and check.status is not CheckStatus.PASS
        }
        if expected_blocking != set(self.blocking_checks):
            raise ValueError("阻断清单与逐项检查不一致")
        if not self.items or not self.exception_branches or not self.checks:
            raise ValueError("人工清单必须包含操作步骤、异常分支和逐项检查")
        if tuple(check.name for check in self.checks) != PLANNING_CHECK_NAMES:
            raise ValueError("人工清单必须携带完整、固定顺序的检查集合")
        for check in self.checks:
            if check.name == "order_time_in_force_supported":
                expected_required = self.order_operation is OrderOperation.LIMIT
            elif check.name == "market_price_bound_supported":
                expected_required = self.order_operation is OrderOperation.MARKET
            else:
                expected_required = True
            if check.required is not expected_required:
                raise ValueError("人工清单检查的必需性与操作类型不一致")
        if len(set(self.blocking_checks)) != len(self.blocking_checks):
            raise ValueError("阻断清单不能重复")
        return self


__all__ = [
    "CALCULATION_PRECISION",
    "PLANNING_CHECK_NAMES",
    "QUOTE_VALIDITY",
    "SETTLEMENT_PLACES",
    "CheckBasis",
    "CheckStatus",
    "ChecklistVerification",
    "ManualChecklist",
    "ManualChecklistItem",
    "ManualExceptionBranch",
    "OrderOperation",
    "PlanningCalculationError",
    "PlanningQuote",
    "PlanningReason",
    "PlanningRequest",
    "PriceGeometry",
    "SizingResult",
    "SizingStatus",
    "ValidationCheck",
    "quantize_decimal",
]
