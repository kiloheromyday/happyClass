import os

from fastapi import Depends, Header, Request
from fastapi.security import APIKeyCookie

from backend.app.errors import AppError
from backend.app.repositories import users
from backend.app.security import token_hash

COOKIE_NAME = "classroom_session"
cookie_scheme = APIKeyCookie(name=COOKIE_NAME, auto_error=False)


def require_same_origin(request: Request, x_requested_with: str | None = Header(default=None, alias="X-Requested-With")):
    allowed = {origin.strip() for origin in os.getenv("EMOJI_ALLOWED_ORIGINS", "http://127.0.0.1:18080,http://localhost:18080,http://127.0.0.1:15173,http://localhost:15173").split(",")}
    origin = request.headers.get("origin")
    if x_requested_with != "EmojiClassroom" or (origin is not None and origin not in allowed):
        raise AppError(403, "CSRF_REJECTED", "请求来源校验失败，请从项目页面操作")


def current_user(token: str | None = Depends(cookie_scheme)):
    user = users.find_by_session(token_hash(token)) if token and len(token) <= 256 else None
    if user is None:
        raise AppError(401, "UNAUTHENTICATED", "请先登录，或重新登录已过期的账号")
    return user


def require_roles(*roles):
    def check(user=Depends(current_user)):
        if user["role"] not in roles:
            raise AppError(403, "FORBIDDEN", "当前账号没有此操作权限")
        return user
    return check
