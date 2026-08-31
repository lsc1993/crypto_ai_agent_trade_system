from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.harness.audit import (
    HarnessAuditEvent,
    HarnessAuditEventKind,
    HarnessAuditRun,
    HarnessEvaluation,
    HarnessEvaluationDecision,
    HarnessEvaluationDetails,
    HarnessEventDetails,
    HarnessInitiatorKind,
    policy_sha256,
    request_sha256,
)
from app.harness.contracts import HarnessRunKind, HarnessRunRequest
from app.harness.policy import MARKET_RESEARCH_POLICY
from app.market.contracts import ContractSymbol

NOW = datetime(2026, 8, 31, 12, tzinfo=UTC)
RUN_ID = UUID("00000000-0000-0000-0000-000000000901")
REQUEST = HarnessRunRequest(
    run_id=RUN_ID,
    kind=HarnessRunKind.MARKET_RESEARCH,
    symbol=ContractSymbol.BTCUSDT,
    requested_at=NOW,
)
EXPECTED_REQUEST_SHA256 = "5dfd2af46cd2be9bc0574b10e98280a07d82760f40b1eb49f53ed80cb0ecb0d5"


def _audit_run() -> HarnessAuditRun:
    return HarnessAuditRun(
        run_id=RUN_ID,
        run_kind=HarnessRunKind.MARKET_RESEARCH,
        policy_version=MARKET_RESEARCH_POLICY.version,
        policy_sha256=policy_sha256(MARKET_RESEARCH_POLICY),
        symbol=ContractSymbol.BTCUSDT,
        requested_at=NOW,
        initiator_kind=HarnessInitiatorKind.MANUAL_API,
        request_sha256=request_sha256(REQUEST, MARKET_RESEARCH_POLICY.version),
    )


def test_audit_models_are_frozen_and_only_accept_safe_details() -> None:
    event = HarnessAuditEvent(
        run_id=RUN_ID,
        sequence=0,
        kind=HarnessAuditEventKind.REQUESTED,
        occurred_at=NOW,
        duration_ms=0,
        error_code=None,
        details=HarnessEventDetails(declared_capability_count=4),
    )
    assert event.details.model_dump(mode="json") == {"declared_capability_count": 4}
    with pytest.raises(ValidationError):
        HarnessAuditEvent.model_validate({**event.model_dump(), "raw_context": "secret"})
    with pytest.raises(ValidationError):
        event.duration_ms = 1


def test_policy_and_request_hashes_are_stable_and_safe() -> None:
    policy_hash = policy_sha256(MARKET_RESEARCH_POLICY)
    assert policy_hash == policy_sha256(MARKET_RESEARCH_POLICY)
    assert request_sha256(REQUEST, MARKET_RESEARCH_POLICY.version) == EXPECTED_REQUEST_SHA256
    assert "secret-looking-value" not in policy_hash


def test_audit_models_reject_invalid_times_hashes_and_durations() -> None:
    naive_payload = _audit_run().model_dump()
    naive_payload["requested_at"] = datetime(2026, 8, 31, 12)
    with pytest.raises(ValidationError):
        HarnessAuditRun.model_validate(naive_payload)
    invalid_hash_payload = _audit_run().model_dump()
    invalid_hash_payload["policy_sha256"] = "invalid"
    with pytest.raises(ValidationError):
        HarnessAuditRun.model_validate(invalid_hash_payload)
    with pytest.raises(ValidationError):
        HarnessAuditEvent(
            run_id=RUN_ID,
            sequence=0,
            kind=HarnessAuditEventKind.REQUESTED,
            occurred_at=NOW,
            duration_ms=-1,
            error_code=None,
            details=HarnessEventDetails(declared_capability_count=4),
        )


def test_audit_events_enforce_terminal_error_and_detail_rules() -> None:
    with pytest.raises(ValidationError):
        HarnessAuditEvent(
            run_id=RUN_ID,
            sequence=3,
            kind=HarnessAuditEventKind.WORKFLOW_COMPLETED,
            occurred_at=NOW,
            duration_ms=1,
            error_code="workflow_exception",
            details=HarnessEventDetails(),
        )
    with pytest.raises(ValidationError):
        HarnessAuditEvent(
            run_id=RUN_ID,
            sequence=0,
            kind=HarnessAuditEventKind.REQUESTED,
            occurred_at=NOW,
            duration_ms=0,
            error_code=None,
            details=HarnessEventDetails(),
        )


def test_rejected_evaluation_requires_a_reason_code() -> None:
    with pytest.raises(ValidationError):
        HarnessEvaluation(
            run_id=RUN_ID,
            sequence=0,
            evaluator_name="policy_allowlist",
            evaluator_version="1",
            decision=HarnessEvaluationDecision.REJECTED,
            reason_code=None,
            evaluated_at=NOW,
            details=HarnessEvaluationDetails(declared_capability_count=4),
        )
