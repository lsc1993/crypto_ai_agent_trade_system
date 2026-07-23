from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def _response(status_code: int, envelope: ErrorEnvelope) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(envelope),
    )


async def _http_exception_handler(
    _request: Request,
    exception: Exception,
) -> JSONResponse:
    if not isinstance(exception, StarletteHTTPException):
        raise TypeError("HTTP 异常处理器收到了不支持的异常类型")

    code = "not_found" if exception.status_code == 404 else "http_error"
    return _response(
        exception.status_code,
        ErrorEnvelope(code=code, message=exception.detail),
    )


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
        Exception,
        _unhandled_exception_handler,
    )
