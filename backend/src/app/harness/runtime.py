from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter

import structlog

from app.harness.audit import (
    HarnessAuditEvent,
    HarnessAuditEventKind,
    HarnessAuditRepository,
    HarnessAuditRun,
    HarnessEvaluation,
    HarnessEvaluationDecision,
    HarnessEvaluationDetails,
    HarnessEventDetails,
    HarnessInitiatorKind,
    policy_sha256,
    request_sha256,
)
from app.harness.contracts import (
    HarnessCapability,
    HarnessPolicy,
    HarnessPolicyViolation,
    HarnessRunKind,
    HarnessRunRequest,
    HarnessWorkflow,
)
from app.market.contracts import ContractSymbol


class HarnessRuntime[ResultT]:
    def __init__(
        self,
        policies: tuple[HarnessPolicy, ...],
        workflows: tuple[HarnessWorkflow[ResultT], ...],
        audit_repository: HarnessAuditRepository,
    ) -> None:
        self._audit_repository = audit_repository
        self._policies: dict[HarnessRunKind, HarnessPolicy] = {}
        for policy in policies:
            if policy.run_kind in self._policies:
                raise ValueError("duplicate Harness run kind registration")
            self._policies[policy.run_kind] = policy

        self._workflows: dict[HarnessRunKind, HarnessWorkflow[ResultT]] = {}
        for workflow in workflows:
            if workflow.kind in self._workflows:
                raise ValueError("duplicate Harness run kind registration")
            self._workflows[workflow.kind] = workflow

    async def run(self, request: HarnessRunRequest) -> ResultT:
        started_at = perf_counter()
        registered_policy = self._policies.get(request.kind)
        policy_version = (
            registered_policy.version
            if registered_policy is not None
            else _UNREGISTERED_POLICY_VERSION
        )
        run = HarnessAuditRun(
            run_id=request.run_id,
            run_kind=request.kind,
            policy_version=policy_version,
            policy_sha256=(
                policy_sha256(registered_policy)
                if registered_policy is not None
                else _unregistered_policy_sha256(request.kind)
            ),
            symbol=request.symbol,
            requested_at=request.requested_at,
            initiator_kind=HarnessInitiatorKind.MANUAL_API,
            request_sha256=request_sha256(request, policy_version),
        )
        await self._audit_repository.create_requested_run(
            run,
            HarnessAuditEvent(
                run_id=request.run_id,
                sequence=0,
                kind=HarnessAuditEventKind.REQUESTED,
                occurred_at=request.requested_at,
                duration_ms=0,
                error_code=None,
                details=HarnessEventDetails(workflow_kind=request.kind),
            ),
        )

        workflow: HarnessWorkflow[ResultT] | None = None
        try:
            policy = self._policy_for(request.kind)
            workflow = self._workflow_for(request.kind)
            self._require_symbol_allowed(policy, request.symbol)
            self._require_capabilities_allowed(policy, workflow.required_capabilities)
        except HarnessPolicyViolation as error:
            declared_count = (
                0 if workflow is None else len(workflow.required_capabilities)
            )
            allowed_count = (
                0
                if registered_policy is None
                else len(registered_policy.allowed_capabilities)
            )
            await self._audit_repository.append_policy_evaluation(
                HarnessEvaluation(
                    run_id=request.run_id,
                    sequence=0,
                    evaluator_name="policy_allowlist",
                    evaluator_version="1",
                    decision=HarnessEvaluationDecision.REJECTED,
                    reason_code=str(error),
                    evaluated_at=datetime.now(UTC),
                    details=HarnessEvaluationDetails(
                        declared_capability_count=declared_count,
                        allowed_capability_count=allowed_count,
                    ),
                ),
                HarnessAuditEvent(
                    run_id=request.run_id,
                    sequence=1,
                    kind=HarnessAuditEventKind.POLICY_REJECTED,
                    occurred_at=datetime.now(UTC),
                    duration_ms=0,
                    error_code=str(error),
                    details=HarnessEventDetails(
                        declared_capability_count=declared_count,
                        allowed_capability_count=allowed_count,
                    ),
                ),
            )
            self._log_rejected(
                request,
                declared_capability_count=declared_count,
                allowed_capability_count=allowed_count,
            )
            raise

        declared_count = len(workflow.required_capabilities)
        allowed_count = len(policy.allowed_capabilities)
        evaluated_at = datetime.now(UTC)
        await self._audit_repository.append_policy_evaluation(
            HarnessEvaluation(
                run_id=request.run_id,
                sequence=0,
                evaluator_name="policy_allowlist",
                evaluator_version="1",
                decision=HarnessEvaluationDecision.PASSED,
                reason_code=None,
                evaluated_at=evaluated_at,
                details=HarnessEvaluationDetails(
                    declared_capability_count=declared_count,
                    allowed_capability_count=allowed_count,
                ),
            ),
            HarnessAuditEvent(
                run_id=request.run_id,
                sequence=1,
                kind=HarnessAuditEventKind.POLICY_AUTHORIZED,
                occurred_at=evaluated_at,
                duration_ms=0,
                error_code=None,
                details=HarnessEventDetails(
                    allowed_capability_count=allowed_count,
                ),
            ),
        )
        await self._audit_repository.append_event(
            HarnessAuditEvent(
                run_id=request.run_id,
                sequence=2,
                kind=HarnessAuditEventKind.WORKFLOW_STARTED,
                occurred_at=datetime.now(UTC),
                duration_ms=self._duration_ms(started_at),
                error_code=None,
                details=HarnessEventDetails(workflow_kind=workflow.kind),
            )
        )
        return await self._run_logged(workflow, request, started_at=started_at)

    def _policy_for(self, kind: HarnessRunKind) -> HarnessPolicy:
        try:
            return self._policies[kind]
        except KeyError as error:
            raise HarnessPolicyViolation("run_kind_not_registered") from error

    def _workflow_for(self, kind: HarnessRunKind) -> HarnessWorkflow[ResultT]:
        try:
            return self._workflows[kind]
        except KeyError as error:
            raise HarnessPolicyViolation("run_kind_not_registered") from error

    @staticmethod
    def _require_symbol_allowed(policy: HarnessPolicy, symbol: ContractSymbol) -> None:
        if symbol not in policy.allowed_symbols:
            raise HarnessPolicyViolation("symbol_not_allowed")

    @staticmethod
    def _require_capabilities_allowed(
        policy: HarnessPolicy,
        required_capabilities: tuple[HarnessCapability, ...],
    ) -> None:
        if any(
            type(capability) is not HarnessCapability
            or capability not in policy.allowed_capabilities
            for capability in required_capabilities
        ):
            raise HarnessPolicyViolation("capability_not_allowed")

    async def _run_logged(
        self,
        workflow: HarnessWorkflow[ResultT],
        request: HarnessRunRequest,
        *,
        started_at: float,
    ) -> ResultT:
        self._log("harness_run_started", request, phase="started", duration_ms=0)
        self._log(
            "harness_run_details",
            request,
            phase="details",
            duration_ms=0,
            capability_count=len(workflow.required_capabilities),
        )
        try:
            result = await workflow.run(request)
        except Exception as error:
            try:
                await self._audit_repository.append_event(
                    HarnessAuditEvent(
                        run_id=request.run_id,
                        sequence=3,
                        kind=HarnessAuditEventKind.WORKFLOW_FAILED,
                        occurred_at=datetime.now(UTC),
                        duration_ms=self._duration_ms(started_at),
                        error_code="workflow_exception",
                        details=HarnessEventDetails(error_type=type(error).__name__),
                    )
                )
            finally:
                self._log(
                    "harness_run_failed",
                    request,
                    phase="failed",
                    duration_ms=self._duration_ms(started_at),
                    error_type=type(error).__name__,
                )
            raise
        self._log(
            "harness_run_completed",
            request,
            phase="completed",
            duration_ms=self._duration_ms(started_at),
        )
        return result

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return int((perf_counter() - started_at) * 1000)

    @staticmethod
    def _log(
        event: str,
        request: HarnessRunRequest,
        *,
        phase: str,
        duration_ms: int,
        **safe_details: int | str,
    ) -> None:
        structlog.get_logger(__name__).info(
            event,
            run_id=str(request.run_id),
            kind=request.kind,
            symbol=request.symbol,
            phase=phase,
            duration_ms=duration_ms,
            **safe_details,
        )

    def _log_rejected(
        self,
        request: HarnessRunRequest,
        *,
        declared_capability_count: int,
        allowed_capability_count: int,
    ) -> None:
        self._log(
            "harness_run_rejected",
            request,
            phase="rejected",
            duration_ms=0,
            error_type=HarnessPolicyViolation.__name__,
            declared_capability_count=declared_capability_count,
            allowed_capability_count=allowed_capability_count,
        )


_UNREGISTERED_POLICY_VERSION = "unregistered"


def _unregistered_policy_sha256(run_kind: HarnessRunKind) -> str:
    canonical_payload: dict[str, str | list[str]] = {
        "allowed_capabilities": [],
        "allowed_symbols": [],
        "run_kind": run_kind.value,
        "version": _UNREGISTERED_POLICY_VERSION,
    }
    serialized = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
