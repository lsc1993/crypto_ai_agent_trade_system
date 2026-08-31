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


def test_market_research_policy_is_static_and_minimally_privileged() -> None:
    assert MARKET_RESEARCH_POLICY.version == "market_research_v1"
    assert MARKET_RESEARCH_POLICY.run_kind is HarnessRunKind.MARKET_RESEARCH
    assert MARKET_RESEARCH_POLICY.allowed_symbols == (
        ContractSymbol.BTCUSDT,
        ContractSymbol.ETHUSDT,
    )
    assert MARKET_RESEARCH_POLICY.allowed_capabilities == (
        HarnessCapability.READ_PUBLIC_MARKET,
        HarnessCapability.READ_APPROVED_NEWS,
        HarnessCapability.CALL_RESEARCH_MODEL,
        HarnessCapability.PERSIST_IMMUTABLE_REPORT,
    )


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


def test_policy_requires_a_version() -> None:
    with pytest.raises(ValidationError):
        HarnessPolicy.model_validate(
            {
                "run_kind": HarnessRunKind.MARKET_RESEARCH,
                "allowed_symbols": (ContractSymbol.BTCUSDT,),
                "allowed_capabilities": (HarnessCapability.READ_PUBLIC_MARKET,),
            }
        )
