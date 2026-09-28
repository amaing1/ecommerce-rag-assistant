"""
统一异常处理模块

作用：
    - 统一所有接口的错误响应格式
    - 隐藏内部堆栈信息，提升安全性
    - 让前端开发者能按统一格式处理错误
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class BusinessException(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message


def error_response(code: int, message: str, data: dict = None) -> dict:
    response = {"code": code, "message": message}
    if data:
        response["data"] = data
    return response


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(
                code=exc.status_code,
                message=str(exc.detail)
            )
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        error_messages = []
        for error in errors:
            field = ".".join(str(loc) for loc in error["loc"])
            error_messages.append(f"{field}: {error['msg']}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_response(
                code=422,
                message="请求参数校验失败",
                data={"errors": error_messages}
            )
        )

    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        return JSONResponse(
            status_code=400,
            content=error_response(
                code=exc.code,
                message=exc.message
            )
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response(
                code=500,
                message="服务器内部错误，请稍后重试"
            )
        )



