from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def success(data=None, message="操作成功"):
    return {"code": "OK", "message": message, "data": data}


async def app_error_handler(request: Request, error: AppError):
    return JSONResponse(status_code=error.status, content={"code": error.code, "message": error.message, "data": None})


async def validation_error_handler(request: Request, error: RequestValidationError):
    # Validation errors can contain submitted passwords. Never echo their input values.
    return JSONResponse(status_code=422, content={"code": "VALIDATION_ERROR", "message": "请检查填写内容", "data": {"errors": [{"field": ".".join(str(part) for part in item["loc"]), "type": item["type"]} for item in error.errors()]}})


async def http_error_handler(request: Request, error: HTTPException):
    return JSONResponse(status_code=error.status_code, content={"code": "NOT_FOUND" if error.status_code == 404 else "HTTP_ERROR", "message": "接口不存在" if error.status_code == 404 else "请求无法完成", "data": None}, headers=error.headers)
