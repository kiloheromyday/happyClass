import os
from typing import Literal
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from backend.app.controllers.auth import set_session
from backend.app.dependencies import COOKIE_NAME, require_same_origin
from backend.app.errors import success
from backend.app.models.auth import AdminCreateUserRequest
from backend.app.models.demo import DemoLoginRequest, MemberUpdateRequest, MemberStatusRequest, MemberPasswordRequest
from backend.app.repositories import users
from backend.app.security import token_hash
from backend.app.services import auth, demo as service

router = APIRouter(prefix='/api/demo', tags=['本地演示开发者模式'])


def developer(request: Request):
    service.access(request)


@router.get('/status')
def status(request: Request):
    return success(service.status(request))


@router.post('/enable', dependencies=[Depends(require_same_origin)])
def enable(request: Request, response: Response):
    token = service.enable(request)
    response.set_cookie(service.DEMO_COOKIE, token, max_age=service.DEMO_SECONDS, httponly=True, secure=os.getenv('EMOJI_COOKIE_SECURE', '0') == '1', samesite='strict', path='/api/demo')
    # The incoming request has no new cookie yet.
    return success({'enabled': True, 'active': True, 'accounts': [
        {'username': name, 'role': role, 'label': label} for name, (role, label) in service.ACCOUNTS.items()
        if (user := users.find_by_username(name)) and user['role'] == role and user['status'] == 'ACTIVE']}, '开发者模式已开启')


@router.post('/disable', dependencies=[Depends(developer), Depends(require_same_origin)])
def disable(request: Request, response: Response):
    service.disable(request)
    response.delete_cookie(service.DEMO_COOKIE, path='/api/demo', httponly=True, samesite='strict')
    return success({'enabled': True, 'active': False, 'accounts': []}, '开发者模式已关闭')


@router.post('/login', dependencies=[Depends(developer), Depends(require_same_origin)])
def login(payload: DemoLoginRequest, request: Request, response: Response):
    user = service.login(payload.username)
    old = request.cookies.get(COOKIE_NAME)
    if old:
        users.revoke_session(token_hash(old))
    set_session(response, user)
    return success(auth.public_user(user), '已切换演示账号')


@router.get('/members', dependencies=[Depends(developer)])
def members(q: str = Query(default='', max_length=120), role: Literal['ALL', 'STUDENT', 'TEACHER'] = 'ALL', status: Literal['ALL', 'ACTIVE', 'DISABLED'] = 'ALL', limit: int = Query(default=10, ge=1, le=50), offset: int = Query(default=0, ge=0, le=100000)):
    return success(service.members(q.strip(), role, status, limit, offset))


@router.post('/members', status_code=201, dependencies=[Depends(developer), Depends(require_same_origin)])
def create(payload: AdminCreateUserRequest):
    return success(service.create_member(payload), '成员已创建')


@router.put('/members/{user_id}', dependencies=[Depends(developer), Depends(require_same_origin)])
def update(payload: MemberUpdateRequest, user_id: int = Path(gt=0)):
    return success(service.update_member(user_id, payload), '成员资料已保存')


@router.put('/members/{user_id}/status', dependencies=[Depends(developer), Depends(require_same_origin)])
def status_update(payload: MemberStatusRequest, user_id: int = Path(gt=0)):
    return success(service.set_status(user_id, payload), '成员状态已更新，历史记录保留')


@router.put('/members/{user_id}/password', dependencies=[Depends(developer), Depends(require_same_origin)])
def password(payload: MemberPasswordRequest, user_id: int = Path(gt=0)):
    service.reset_password(user_id, payload)
    return success(message='密码已重设，该成员原有登录已失效')
