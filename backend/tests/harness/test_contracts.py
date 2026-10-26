# 验证固定研究策略与请求的最小权限契约。
# 请求仅接受 UTC 与声明字段，重复能力和空版本在契约层拒绝。
# 静态研究策略不能因输入变化获得额外能力。
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.harness.contracts import (
    HarnessCapability,
    HarnessPolicy,
    HarnessRunKind,
    HarnessRunRequest,
)
from app.harness.policy import MARKET_RESEARCH_POLICY
from app.market.contracts import ContractSymbol

NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)


# 研究策略只有公开读取、受限模型和不可变报告保存能力，不能因请求载荷扩大权限。
def test_market_research_policy_is_static_and_minimally_privileged() -> None:
    assert MARKET_RESEARCH_POLICY.version == "market_research_v1"
    assert MARKET_RESEARCH_POLICY.run_kind is HarnessRunKind.MARKET_RESEARCH
    assert MARKET_RESEARCH_POLICY.allowed_symbols == (
        ContractSymbol.BTCUSDT,
        ContractSymbol.ETHUSDT,
    )
    # 逐项核对权限清单，额外能力加入时此断言必须让维护者重新审查边界。
    assert MARKET_RESEARCH_POLICY.allowed_capabilities == (
        HarnessCapability.READ_PUBLIC_MARKET,
        HarnessCapability.READ_APPROVED_NEWS,
        HarnessCapability.CALL_RESEARCH_MODEL,
        HarnessCapability.PERSIST_IMMUTABLE_REPORT,
    )


# 时间歧义与任意上下文分别在输入契约拒绝，协调层只接受规定请求字段。
def test_run_request_rejects_non_utc_and_extra_payload() -> None:
    with pytest.raises(ValidationError):
        HarnessRunRequest(
            run_id=UUID("00000000-0000-0000-0000-000000000901"),
            kind=HarnessRunKind.MARKET_RESEARCH,
            symbol=ContractSymbol.BTCUSDT,
            requested_at=datetime(2026, 8, 31, 20),
        )

    with pytest.raises(ValidationError):
        HarnessRunRequest.model_validate(
            {
                "run_id": UUID("00000000-0000-0000-0000-000000000901"),
                "kind": HarnessRunKind.MARKET_RESEARCH,
                "symbol": ContractSymbol.BTCUSDT,
                "requested_at": NOW,
                "raw_context": "must not be accepted",
            }
        )


# 重复声明不能被视作额外权限或静默去重，策略定义必须明确而唯一。
def test_policy_rejects_duplicate_capabilities() -> None:
    with pytest.raises(ValidationError):
        HarnessPolicy(
            version="market_research_v1",
            run_kind=HarnessRunKind.MARKET_RESEARCH,
            allowed_symbols=(ContractSymbol.BTCUSDT,),
            allowed_capabilities=(
                HarnessCapability.READ_PUBLIC_MARKET,
                HarnessCapability.READ_PUBLIC_MARKET,
            ),
        )


# 版本是策略哈希与审计归因的基础，缺失版本不能形成可运行策略。
def test_policy_requires_a_version() -> None:
    with pytest.raises(ValidationError):
        HarnessPolicy.model_validate(
            {
                "run_kind": HarnessRunKind.MARKET_RESEARCH,
                "allowed_symbols": (ContractSymbol.BTCUSDT,),
                "allowed_capabilities": (HarnessCapability.READ_PUBLIC_MARKET,),
            }
        )
