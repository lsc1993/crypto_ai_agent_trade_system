from __future__ import annotations

from time import perf_counter

import structlog

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
    ) -> None:
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
        try:
            policy = self._policy_for(request.kind)
            workflow = self._workflow_for(request.kind)
            self._require_symbol_allowed(policy, request.symbol)
            self._require_capabilities_allowed(policy, workflow.required_capabilities)
        except HarnessPolicyViolation:
            self._log_rejected(request)
            raise
        return await self._run_logged(workflow, request)

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
    ) -> ResultT:
        started_at = perf_counter()
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

    def _log_rejected(self, request: HarnessRunRequest) -> None:
        self._log(
            "harness_run_rejected",
            request,
            phase="rejected",
            duration_ms=0,
            error_type=HarnessPolicyViolation.__name__,
        )
