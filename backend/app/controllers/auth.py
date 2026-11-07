import os

from fastapi import APIRouter, Depends, Query, Request, Response

from backend.app.dependencies import COOKIE_NAME, current_user, require_roles, require_same_origin
from backend.app.errors import success
from backend.app.models.auth import LoginRequest, PasswordRequest, RegisterRequest, AdminCreateUserRequest, ProfileRequest
from backend.app.repositories import users
from backend.app.security import token_hash
from backend.app.services import auth

router = APIRouter(prefix="/api", tags=["账号与权限"])


def set_session(response, user):
    token = auth.issue_session(user)
    response.set_cookie(COOKIE_NAME, token, max_age=auth.SESSION_SECONDS, httponly=True, secure=os.getenv("EMOJI_COOKIE_SECURE", "0") == "1", samesite="strict", path="/")


def client_ip(request):
    # Do not trust caller-supplied X-Forwarded-For headers in this local deployment.
    return request.client.host if request.client else "unknown"


@router.post("/auth/register", status_code=201, dependencies=[Depends(require_same_origin)])
def register(payload: RegisterRequest, request: Request, response: Response):
    user = auth.register(payload, client_ip(request))
    set_session(response, user)
    return success(auth.public_user(user), "注册成功")


@router.post("/auth/login", dependencies=[Depends(require_same_origin)])
def login(payload: LoginRequest, request: Request, response: Response):
    user = auth.login(payload, client_ip(request))
    old_token = request.cookies.get(COOKIE_NAME)
    if old_token:
        users.revoke_session(token_hash(old_token))
    set_session(response, user)
    return success(auth.public_user(user), "登录成功")


@router.post("/auth/logout", dependencies=[Depends(require_same_origin)])
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        users.revoke_session(token_hash(token))
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    return success(message="已退出登录")


@router.put("/auth/password", dependencies=[Depends(require_same_origin)])
def password(payload: PasswordRequest, response: Response, user=Depends(current_user)):
    auth.update_password(user, payload)
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    return success(message="密码已修改，请重新登录；所有设备的旧会话已失效")


@router.get("/users/me")
def me(user=Depends(current_user)):
    return success(auth.public_user(user))


@router.put('/users/me', dependencies=[Depends(require_same_origin)])
def update_profile(payload: ProfileRequest, user=Depends(current_user)):
    return success(auth.update_profile(user, payload), '个人资料已保存')


@router.get("/admin/users")
def admin_users(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0), user=Depends(require_roles("ADMIN"))):
    records, count = users.list_users(limit, offset)
    return success({"items": [auth.public_user(item) for item in records], "total": count, "limit": limit, "offset": offset})


@router.get("/teacher/courses")
def teacher_courses(user=Depends(require_roles("TEACHER"))):
    return success({"items": users.teacher_courses(user["id"])})


@router.post('/admin/users', status_code=201, dependencies=[Depends(require_same_origin)])
def create_user(payload: AdminCreateUserRequest, user=Depends(require_roles('ADMIN'))):
    created = auth.provision_user(payload.username, payload.password, payload.role, payload.email, actor_id=user['id'])
    return success(auth.public_user(created), '账号已创建，请将登录信息交给对应使用者')
