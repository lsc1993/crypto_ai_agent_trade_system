# 生成手动实施清单：把确定性数量/价格/保证金结果和逐项检查组织成用户可阅读的
# 操作步骤与异常分支。清单只是人工说明，不生成 TradeIntent、不创建/签名/发送/
# 撤改交易所订单；程序已验证、用户声明和仍需人工核对必须分开显示。
from __future__ import annotations

from decimal import Decimal

from app.trade_planning.contracts import (
    ChecklistVerification,
    CheckStatus,
    ManualChecklist,
    ManualChecklistItem,
    ManualExceptionBranch,
    OrderOperation,
    PlanningCalculationError,
    PlanningReason,
    PlanningRequest,
    SizingResult,
    ValidationCheck,
)
from app.trade_planning.order_rules import order_type_for


# 固定操作步骤；required=True 表示用户实施前必须核对，不等于系统已核实交易所账户。
def _items(request: PlanningRequest) -> tuple[ManualChecklistItem, ...]:
    market = request.order_operation is OrderOperation.MARKET
    entry_code = "place_market_entry_manually" if market else "place_entry_order_manually"
    return (
        ManualChecklistItem(
            code="verify_product_and_venue",
            verification=ChecklistVerification.MANUAL_CONFIRMATION_REQUIRED,
        ),
        ManualChecklistItem(
            code="verify_margin_mode_and_leverage",
            verification=ChecklistVerification.USER_DECLARED,
        ),
        ManualChecklistItem(
            code="verify_available_margin_and_positions",
            verification=ChecklistVerification.MANUAL_CONFIRMATION_REQUIRED,
        ),
        ManualChecklistItem(
            code="verify_entry_condition",
            verification=ChecklistVerification.MANUAL_CONFIRMATION_REQUIRED,
        ),
        ManualChecklistItem(
            code=entry_code,
            verification=ChecklistVerification.MANUAL_CONFIRMATION_REQUIRED,
        ),
        ManualChecklistItem(
            code="place_protective_stop_manually",
            verification=ChecklistVerification.MANUAL_CONFIRMATION_REQUIRED,
        ),
        ManualChecklistItem(
            code="place_target_exit_manually",
            verification=ChecklistVerification.MANUAL_CONFIRMATION_REQUIRED,
        ),
        ManualChecklistItem(
            code="verify_order_quantity_and_notional",
            verification=ChecklistVerification.PROGRAM_VERIFIED,
        ),
        ManualChecklistItem(
            code="verify_expiry_and_cancel_condition",
            verification=ChecklistVerification.MANUAL_CONFIRMATION_REQUIRED,
        ),
        ManualChecklistItem(
            code="record_execution_feedback",
            verification=ChecklistVerification.USER_DECLARED,
        ),
    )


# 异常分支覆盖未成交、部分成交、跳价、超时、到期和成本/规则变化；
# 全部要求用户自行操作，系统不代替用户挂单、撤单或调整交易所参数。
def _exception_branches() -> tuple[ManualExceptionBranch, ...]:
    return (
        ManualExceptionBranch(code="entry_not_filled"),
        ManualExceptionBranch(code="entry_partially_filled", recalculate_required=True),
        ManualExceptionBranch(code="price_moved_outside_range", recalculate_required=True),
        ManualExceptionBranch(code="order_timeout"),
        ManualExceptionBranch(code="plan_expired"),
        ManualExceptionBranch(code="costs_or_rules_changed", recalculate_required=True),
        ManualExceptionBranch(code="margin_or_position_changed", recalculate_required=True),
    )


# C7 清单入口：只读取已求解结果和检查，不重新计算、不改变任何检查状态。
# 阻断项按检查顺序原样列出；T13 仍必须结合采纳、资金池占用和时效派生 readiness。
def build_manual_checklist(
    request: PlanningRequest,
    size: SizingResult,
    checks: tuple[ValidationCheck, ...],
) -> ManualChecklist:
    material_hash = request.material_sha256()
    if size.material_hash != material_hash:
        raise PlanningCalculationError(
            "数量结果不属于当前规划材料",
            code=PlanningReason.SIZING_MATERIAL_MISMATCH.value,
        )
    if any(check.material_hash != material_hash for check in checks):
        raise PlanningCalculationError(
            "人工清单检查不属于当前规划材料",
            code=PlanningReason.CALCULATION_FAILED.value,
        )
    blocking = tuple(
        check.name for check in checks if check.required and check.status is not CheckStatus.PASS
    )
    zero = Decimal("0")
    market = request.order_operation is OrderOperation.MARKET
    return ManualChecklist(
        material_hash=material_hash,
        direction=request.candidate.direction,
        order_operation=request.order_operation,
        order_type=order_type_for(request),
        time_in_force=None if market else "GTC",
        quantity_unit=request.rules.quantity_unit,
        quantity=size.quantity,
        notional=size.notional,
        initial_margin=size.initial_margin,
        stop_path_loss=size.stop_path_loss,
        target_net_reward=size.target_net_reward,
        entry_lower=(
            size.entry_lower if size.entry_lower is not None else request.candidate.entry_lower
        ),
        trigger=(size.trigger if size.trigger is not None else request.candidate.trigger),
        entry_upper=(
            size.entry_upper if size.entry_upper is not None else request.candidate.entry_upper
        ),
        planned_entry=size.entry_price if size.entry_price is not None else zero,
        stop_loss=size.stop_price if size.stop_price is not None else zero,
        target=size.target_price if size.target_price is not None else zero,
        expires_at=size.expires_at,
        items=_items(request),
        exception_branches=_exception_branches(),
        blocking_checks=blocking,
        checks=checks,
    )


__all__ = ["build_manual_checklist"]
