# 验证 Harness 和币种准入异常转换为统一安全错误信封。
# 策略拒绝与审计存储故障使用不同状态和错误码。
# 准入检查保留可操作的白名单详情，而不转发上游异常原文。
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.errors import install_exception_handlers
from app.harness.audit import HarnessAuditStorageUnavailableError
from app.harness.contracts import HarnessPolicyViolation
from app.symbols.contracts import SymbolError


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


@pytest.mark.asyncio
async def test_research_symbol_rejection_exposes_safe_check_details() -> None:
    app = FastAPI()
    install_exception_handlers(app)

    async def reject() -> None:
        raise SymbolError(
            "research_symbol_unsupported",
            "该币对暂不满足研究数据要求。",
            422,
            details={
                "check": {
                    "symbol": "ZECUSDT",
                    "supported": False,
                    "checks": [
                        {
                            "name": "market",
                            "status": "unverified",
                            "message": "公开合约信息响应超过系统可接受的大小上限，请稍后重试。",
                        }
                    ],
                    "metadata": None,
                }
            },
        )

    app.add_api_route("/reject", reject, methods=["GET"])
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/reject")

    assert response.status_code == 422
    assert response.json() == {
        "code": "research_symbol_unsupported",
        "message": "该币对暂不满足研究数据要求。",
        "details": {
            "check": {
                "symbol": "ZECUSDT",
                "supported": False,
                "checks": [
                    {
                        "name": "market",
                        "status": "unverified",
                        "message": "公开合约信息响应超过系统可接受的大小上限，请稍后重试。",
                    }
                ],
                "metadata": None,
            }
        },
    }
