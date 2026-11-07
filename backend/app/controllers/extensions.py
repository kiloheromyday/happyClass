from typing import Literal
from fastapi import APIRouter, Depends, Path, Query, Response
from backend.app.dependencies import current_user, require_roles, require_same_origin
from backend.app.errors import success
from backend.app.models.extensions import EvaluationRequest, DepartmentRequest, CourseUpdate
from backend.app.services import evaluations, inbox, catalog

router = APIRouter(prefix='/api', tags=['课程评价、站内消息与院系维护'])
Scope = Literal['ALL', 'REAL', 'DEMO']
Kind = Literal['ALL', 'LEAVE', 'QUESTION', 'GUIDE', 'BUDDY']


@router.get('/sessions/{session_id}/evaluation')
def mine(session_id: int = Path(gt=0), user=Depends(require_roles('STUDENT'))):
    return success(evaluations.mine(session_id, user))


@router.put('/sessions/{session_id}/evaluation', dependencies=[Depends(require_same_origin)])
def save(payload: EvaluationRequest, session_id: int = Path(gt=0), user=Depends(require_roles('STUDENT'))):
    return success(evaluations.save(session_id, payload, user), '课程评价已保存')


@router.get('/evaluations/report')
def report(course_id: int | None = Query(default=None, gt=0), session_id: int | None = Query(default=None, gt=0), data_scope: Scope = 'ALL', limit: int = Query(default=10, ge=1, le=100), offset: int = Query(default=0, ge=0), user=Depends(require_roles('TEACHER', 'ADMIN'))):
    return success(evaluations.report(user, course_id, session_id, data_scope, limit, offset))


@router.get('/evaluations/export')
def export(course_id: int | None = Query(default=None, gt=0), session_id: int | None = Query(default=None, gt=0), data_scope: Scope = 'ALL', user=Depends(require_roles('TEACHER', 'ADMIN'))):
    content, count = evaluations.export(user, course_id, session_id, data_scope)
    return Response(content, media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="course-evaluations.csv"', 'X-Export-Count': str(count)})


@router.get('/messages')
def messages(unread: bool = False, kind: Kind = 'ALL', limit: int = Query(default=10, ge=1, le=100), offset: int = Query(default=0, ge=0), user=Depends(current_user)):
    return success(inbox.listing(user, unread, kind, limit, offset))


@router.put('/messages/read-all', dependencies=[Depends(require_same_origin)])
def read_all(user=Depends(current_user)):
    return success(inbox.mark(user))


@router.put('/messages/{message_id}/read', dependencies=[Depends(require_same_origin)])
def read(message_id: int = Path(gt=0), user=Depends(current_user)):
    return success(inbox.mark(user, message_id))


@router.post('/admin/departments', status_code=201, dependencies=[Depends(require_same_origin)])
def create_department(payload: DepartmentRequest, user=Depends(require_roles('ADMIN'))):
    return success(catalog.department_save(payload, user), '院系已添加')


@router.put('/admin/departments/{identifier}', dependencies=[Depends(require_same_origin)])
def edit_department(identifier: str, payload: DepartmentRequest, user=Depends(require_roles('ADMIN'))):
    return success(catalog.department_save(payload, user, identifier), '院系已更新')


@router.delete('/admin/departments/{identifier}', dependencies=[Depends(require_same_origin)])
def delete_department(identifier: str, version: int = Query(ge=1), user=Depends(require_roles('ADMIN'))):
    return success(catalog.department_delete(identifier, version, user), '院系已移除')


@router.put('/admin/courses/{course_id}', dependencies=[Depends(require_same_origin)])
def edit_course(payload: CourseUpdate, course_id: int = Path(gt=0), user=Depends(require_roles('ADMIN'))):
    return success(catalog.course_update(course_id, payload, user), '课程已更新')
