import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.errors import install_exception_handlers
from app.harness.audit import HarnessAuditStorageUnavailableError
from app.harness.contracts import HarnessPolicyViolation


@pytest.mark.asyncio
async def test_harness_policy_violation_uses_safe_rejection_envelope() -> None:
    app = FastAPI()
    install_exception_handlers(app)

    async def reject() -> None:
        raise HarnessPolicyViolation("symbol_not_allowed")

    app.add_api_route("/reject", reject, methods=["GET"])
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/reject")

    assert response.status_code == 403
    assert response.json() == {
        "code": "harness_policy_rejected",
        "message": "当前运行不符合受限 Harness 策略",
        "details": {},
    }


@pytest.mark.asyncio
async def test_harness_audit_outage_uses_safe_service_unavailable_envelope() -> None:
    app = FastAPI()
    install_exception_handlers(app)

    async def fail_audit() -> None:
        raise HarnessAuditStorageUnavailableError

    app.add_api_route("/audit-outage", fail_audit, methods=["GET"])
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/audit-outage")

    assert response.status_code == 503
    assert response.json() == {
        "code": "harness_audit_unavailable",
        "message": "Harness 审计存储不可用",
        "details": {},
    }
