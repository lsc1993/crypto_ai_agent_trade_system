# 把 HTTP、参数校验及领域异常统一映射成错误响应。
# 按异常类型选择状态码与 ErrorEnvelope，未处理异常只记录类型和请求路径。
# 校验错误不回显输入值；HTTP detail 与显式领域消息仍由产生异常的调用方负责安全性。
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.harness.audit import HarnessAuditStorageUnavailableError
from app.harness.contracts import HarnessPolicyViolation
from app.market.contracts import MarketDataUnavailableError
from app.paper_trading.contracts import (
    PaperAccountNotFoundError,
    PaperAccountStateError,
    PaperStorageUnavailableError,
)
from app.reports.contracts import ReportStorageUnavailableError
from app.research.backtests.contracts import (
    BacktestNotFoundError,
    BacktestStorageUnavailableError,
)
from app.symbols.contracts import SymbolError
from app.trades.contracts import TradeStorageUnavailableError
from app.trades.service import TradeNotFoundError

logger = structlog.get_logger(__name__)


# ErrorEnvelope 定义当前接口的结构化字段，供 Pydantic 校验与响应序列化使用。
# 主要字段：code、message、details；完整契约以下方声明为准。
class ErrorEnvelope(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


# 把安全错误信封经 jsonable_encoder 转换为 JSONResponse，状态码由具体处理器提供。
def _response(status_code: int, envelope: ErrorEnvelope) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(envelope),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _http_exception_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, StarletteHTTPException):
        raise TypeError("HTTP 异常处理器收到了不支持的异常类型")

    code = "not_found" if exception.status_code == 404 else "http_error"
    detail: Any = exception.detail
    if isinstance(detail, str):
        message = detail
        details: dict[str, Any] = {}
    else:
        message = "请求无法处理"
        details = {"detail": jsonable_encoder(detail)}

    return _response(
        exception.status_code,
        ErrorEnvelope(
            code=code,
            message=message,
            details=details,
        ),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _validation_exception_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, RequestValidationError):
        raise TypeError("参数校验异常处理器收到了不支持的异常类型")

    # 只返回位置、类型与消息，避免把请求中的潜在敏感值原样回显。
    errors = [
        {
            "location": list(error["loc"]),
            "type": error["type"],
            "message": error["msg"],
        }
        for error in exception.errors()
    ]
    return _response(
        422,
        ErrorEnvelope(
            code="validation_error",
            message="请求参数校验失败",
            details={"errors": errors},
        ),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _unhandled_exception_handler(
    request: Request,
    exception: Exception,
) -> JSONResponse:
    # 日志不记录异常正文，避免第三方异常意外携带配置或凭证。
    logger.error(
        "unhandled_request_error",
        error_type=type(exception).__name__,
        method=request.method,
        path=request.url.path,
    )
    return _response(
        500,
        ErrorEnvelope(
            code="internal_server_error",
            message="服务内部错误",
        ),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _market_data_unavailable_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, MarketDataUnavailableError):
        raise TypeError("市场数据异常处理器收到了不支持的异常类型")
    return _response(
        503,
        ErrorEnvelope(
            code=exception.code,
            message=str(exception),
        ),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _harness_policy_violation_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, HarnessPolicyViolation):
        raise TypeError("Harness 策略异常处理器收到了不支持的异常类型")
    return _response(
        403,
        ErrorEnvelope(
            code="harness_policy_rejected",
            message="当前运行不符合受限 Harness 策略",
        ),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _harness_audit_storage_unavailable_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, HarnessAuditStorageUnavailableError):
        raise TypeError("Harness 审计存储异常处理器收到了不支持的异常类型")
    return _response(
        503,
        ErrorEnvelope(
            code="harness_audit_unavailable",
            message="Harness 审计存储不可用",
        ),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _trade_storage_unavailable_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, TradeStorageUnavailableError):
        raise TypeError("交易存储异常处理器收到了不支持的异常类型")
    return _response(
        503,
        ErrorEnvelope(
            code="trade_storage_unavailable",
            message="交易日志存储不可用",
        ),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _report_storage_unavailable_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, ReportStorageUnavailableError):
        raise TypeError("报告存储异常处理器收到了不支持的异常类型")
    return _response(
        503,
        ErrorEnvelope(
            code="report_storage_unavailable",
            message="研究报告存储暂不可用",
        ),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _backtest_storage_unavailable_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, BacktestStorageUnavailableError):
        raise TypeError("回测存储异常处理器收到了不支持的异常类型")
    return _response(
        503,
        ErrorEnvelope(
            code="backtest_storage_unavailable",
            message="回测存储不可用",
        ),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _backtest_not_found_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, BacktestNotFoundError):
        raise TypeError("回测不存在异常处理器收到了不支持的异常类型")
    return _response(
        404,
        ErrorEnvelope(code="not_found", message="回测运行不存在"),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _paper_storage_unavailable_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, PaperStorageUnavailableError):
        raise TypeError("模拟盘存储异常处理器收到了不支持的异常类型")
    return _response(
        503,
        ErrorEnvelope(code="paper_storage_unavailable", message="模拟盘存储不可用"),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _paper_not_found_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, PaperAccountNotFoundError):
        raise TypeError("模拟盘账户不存在异常处理器收到了不支持的异常类型")
    return _response(404, ErrorEnvelope(code="not_found", message="模拟账户不存在"))


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _paper_state_error_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, PaperAccountStateError):
        raise TypeError("模拟盘账户状态异常处理器收到了不支持的异常类型")
    return _response(
        409,
        ErrorEnvelope(code="paper_account_state_invalid", message="模拟账户状态不允许当前操作"),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _trade_not_found_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, TradeNotFoundError):
        raise TypeError("交易不存在异常处理器收到了不支持的异常类型")
    return _response(
        404,
        ErrorEnvelope(code="not_found", message="交易不存在或已归档"),
    )


# 接收已登记的异常类型并返回明确状态码和 ErrorEnvelope；不把任意异常对象直接序列化。
async def _symbol_error_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, SymbolError):
        raise TypeError("研究币对异常处理器收到了不支持的异常类型")
    return _response(
        exception.status_code,
        ErrorEnvelope(
            code=exception.code,
            message=str(exception),
            details=exception.details,
        ),
    )


# 将具体领域异常优先映射到其处理器，并注册最终未处理异常兜底响应。
def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        StarletteHTTPException,
        _http_exception_handler,
    )
    app.add_exception_handler(
        RequestValidationError,
        _validation_exception_handler,
    )
    app.add_exception_handler(
        HarnessPolicyViolation,
        _harness_policy_violation_handler,
    )
    app.add_exception_handler(
        HarnessAuditStorageUnavailableError,
        _harness_audit_storage_unavailable_handler,
    )
    app.add_exception_handler(
        MarketDataUnavailableError,
        _market_data_unavailable_handler,
    )
    app.add_exception_handler(
        ReportStorageUnavailableError,
        _report_storage_unavailable_handler,
    )
    app.add_exception_handler(
        TradeStorageUnavailableError,
        _trade_storage_unavailable_handler,
    )
    app.add_exception_handler(
        BacktestStorageUnavailableError,
        _backtest_storage_unavailable_handler,
    )
    app.add_exception_handler(
        BacktestNotFoundError,
        _backtest_not_found_handler,
    )
    app.add_exception_handler(
        PaperStorageUnavailableError,
        _paper_storage_unavailable_handler,
    )
    app.add_exception_handler(
        PaperAccountNotFoundError,
        _paper_not_found_handler,
    )
    app.add_exception_handler(
        PaperAccountStateError,
        _paper_state_error_handler,
    )
    app.add_exception_handler(
        TradeNotFoundError,
        _trade_not_found_handler,
    )
    app.add_exception_handler(
        SymbolError,
        _symbol_error_handler,
    )
    app.add_exception_handler(
        Exception,
        _unhandled_exception_handler,
    )
