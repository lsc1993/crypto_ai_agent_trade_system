# 验证 C4 Agent 任务契约：输入约束、请求指纹、快照水位与事件安全投影。
# 本文件只使用合成 UUID、版本指纹和公开币种，不包含真实资金、账户或凭证。
# 这些断言固定公共类型边界，防止后续实现把完整财务值或未经校验的默认值带入事件。
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.agent_runs.contracts import (
    RunInput,
    RunSnapshot,
    RunStatus,
    run_input_sha256,
)
from app.agent_runs.events import RunEvent, RunEventType
from app.shared.agent_types import ProductKey, VersionRef
from app.trade_planning.inputs import PlanningRefs

WORKSPACE_ID = uuid4()
NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)


# 构造合法的合成版本引用；只验证标识/指纹形状，不代表任何已发布策略。
def _version_ref() -> VersionRef:
    return VersionRef(version_id=uuid4(), sha256="a" * 64)


# 构造最小 PlanningRefs；只含引用和资金池代次，不含金额、数量或保证金值。
def _planning_refs() -> PlanningRefs:
    return PlanningRefs(
        profile=_version_ref(),
        policy=_version_ref(),
        venue_rules=_version_ref(),
        costs=_version_ref(),
        pool_id=uuid4(),
        pool_generation=3,
    )


# 构造当前模式的合成任务输入；未显式传 analysis_mode/budget_profile 以覆盖默认值。
def _payload(*, request_id: UUID | None = None) -> dict[str, object]:
    return {
        "request_id": request_id or uuid4(),
        "product": {
            "venue": "binance_usdm",
            "symbol": "BTCUSDT",
            "settlement": "USDT",
            "kind": "linear_perpetual",
        },
        "timeframes": ["1h", "4h"],
        "goal": "分析 BTCUSDT 当前结构与条件计划",
        "strategy": _version_ref().model_dump(mode="json"),
        "parameters": {"lookback": 20, "enabled": True},
        "planning": _planning_refs().model_dump(mode="json"),
    }


def test_run_input_rejects_extra_fields_and_financial_payloads() -> None:
    # 输入只允许公开产品、版本引用和策略参数；额外字段不能被默默忽略。
    payload = _payload()
    payload["financial_marker"] = "10000.00"
    with pytest.raises(ValidationError):
        RunInput.model_validate(payload)

    data = RunInput.model_validate(_payload())
    serialized = data.model_dump_json()
    assert "10000.00" not in serialized
    assert "quantity" not in serialized
    assert "margin" not in serialized


def test_goal_timeframes_and_as_of_are_bounded() -> None:
    # 空白目标、空周期和重复周期不能形成可执行任务。
    for goal in ("", "   ", "x" * 2001):
        with pytest.raises(ValidationError):
            RunInput.model_validate({**_payload(), "goal": goal})
    for timeframes in ([], ["1h", "1h"]):
        with pytest.raises(ValidationError):
            RunInput.model_validate({**_payload(), "timeframes": timeframes})

    # 策略参数必须能稳定序列化；NaN/Infinity 会破坏请求指纹。
    for invalid in ({"bad": float("nan")}, {"bad": float("inf")}):
        with pytest.raises(ValidationError):
            RunInput.model_validate({**_payload(), "parameters": invalid})

    # 历史模式必须带分析截至时刻；当前模式不能伪造历史观测时间。
    historical = {**_payload(), "analysis_mode": "historical", "as_of": NOW.isoformat()}
    assert RunInput.model_validate(historical).as_of == NOW
    with pytest.raises(ValidationError):
        RunInput.model_validate({**_payload(), "analysis_mode": "historical"})
    with pytest.raises(ValidationError):
        RunInput.model_validate(
            {**_payload(), "analysis_mode": "current", "as_of": NOW.isoformat()}
        )


def test_request_fingerprint_ignores_request_key_and_resolves_defaults() -> None:
    # 请求键是幂等标识，不属于内容指纹；同内容不同请求键可建立独立任务。
    base_payload = _payload(request_id=uuid4())
    first = RunInput.model_validate(base_payload)
    second = RunInput.model_validate({**base_payload, "request_id": uuid4()})
    assert run_input_sha256(WORKSPACE_ID, first) == run_input_sha256(WORKSPACE_ID, second)

    # 省略默认值与显式写出默认值必须得到同一指纹，便于首次解析后的重试复用任务。
    explicit_payload = {
        **base_payload,
        "analysis_mode": "current",
        "budget_profile": "standard",
    }
    explicit = RunInput.model_validate(explicit_payload)
    assert run_input_sha256(WORKSPACE_ID, first) == run_input_sha256(WORKSPACE_ID, explicit)

    # 策略参数、策略版本或工作台变化必须改变指纹，不能被错误合并。
    changed_parameters = first.model_copy(update={"parameters": {"lookback": 21}})
    changed_strategy = first.model_copy(update={"strategy": _version_ref()})
    assert run_input_sha256(WORKSPACE_ID, first) != run_input_sha256(
        WORKSPACE_ID, changed_parameters
    )
    assert run_input_sha256(WORKSPACE_ID, first) != run_input_sha256(WORKSPACE_ID, changed_strategy)
    assert run_input_sha256(WORKSPACE_ID, first) != run_input_sha256(uuid4(), first)


def test_run_snapshot_enforces_status_watermarks_and_terminal_time() -> None:
    data = RunInput.model_validate(_payload())
    snapshot = RunSnapshot(
        run_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        thread_id=uuid4(),
        parent_run_id=None,
        revision=1,
        status=RunStatus.QUEUED,
        state_version=0,
        input=data,
        received_message_seq=2,
        applied_message_seq=1,
        current_interaction_id=None,
        result_refs=(),
        result_quality=None,
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        finished_at=None,
    )
    assert snapshot.status is RunStatus.QUEUED

    # applied 不能超过 received；终态必须有完成时刻，非终态不能提前携带。
    def replace(**changes: object) -> RunSnapshot:
        return RunSnapshot.model_validate({**snapshot.model_dump(), **changes})

    with pytest.raises(ValidationError):
        replace(applied_message_seq=3)
    with pytest.raises(ValidationError):
        replace(status=RunStatus.COMPLETED)
    with pytest.raises(ValidationError):
        replace(finished_at=NOW)


def test_run_event_payload_is_an_explicit_safe_projection() -> None:
    # 事件只允许固定字段；完整计划、策略参数和财务值不能通过通用 JSON 载荷外泄。
    product = ProductKey(
        venue="binance_usdm",
        symbol="BTCUSDT",
        settlement="USDT",
        kind="linear_perpetual",
    )
    event = RunEvent(
        run_id=uuid4(),
        revision=1,
        sequence=1,
        event_type=RunEventType.RUN_QUEUED,
        occurred_at=NOW,
        payload={
            "status": "queued",
            "product": product.model_dump(mode="json", by_alias=False),
        },
    )
    assert event.sequence == 1

    with pytest.raises(ValidationError):
        RunEvent(
            run_id=uuid4(),
            revision=1,
            sequence=1,
            event_type=RunEventType.RUN_QUEUED,
            occurred_at=NOW,
            payload={
                "status": "queued",
                "product": product.model_dump(mode="json", by_alias=False),
                "financial_marker": "10000.00",
            },
        )
    with pytest.raises(ValidationError):
        RunEvent(
            run_id=uuid4(),
            revision=1,
            sequence=0,
            event_type=RunEventType.RUN_QUEUED,
            occurred_at=NOW,
            payload={"status": "queued"},
        )
