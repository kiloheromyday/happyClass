from fastapi import APIRouter, Depends, Path, Query, Request

from backend.app.dependencies import require_roles, require_same_origin
from backend.app.errors import success
from backend.app.models.join_codes import JoinClassroom, JoinCodeCreate
from backend.app.services import join_codes as service

router = APIRouter(prefix='/api', tags=['课堂加入码'])


@router.get('/sessions/{session_id}/join-code')
def get(session_id: int = Path(gt=0), user=Depends(require_roles('TEACHER', 'ADMIN'))):
    return success(service.get(session_id, user))


@router.post('/sessions/{session_id}/join-code', dependencies=[Depends(require_same_origin)])
def create(payload: JoinCodeCreate, session_id: int = Path(gt=0), user=Depends(require_roles('TEACHER', 'ADMIN'))):
    return success(service.create(session_id, payload, user), '加入码已生成')


@router.delete('/sessions/{session_id}/join-code', dependencies=[Depends(require_same_origin)])
def revoke(session_id: int = Path(gt=0), version: int = Query(ge=1), user=Depends(require_roles('TEACHER', 'ADMIN'))):
    return success(service.revoke(session_id, version, user), '已停止使用此加入码')


@router.post('/sessions/join', dependencies=[Depends(require_same_origin)])
def join(payload: JoinClassroom, request: Request, user=Depends(require_roles('STUDENT'))):
    result = service.join(payload, user, request.client.host if request.client else 'unknown')
    return success(result, '课程已添加，后续课堂会自动安排' if result['joined'] else '你已加入这门课程')
