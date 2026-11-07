from fastapi import APIRouter, Depends, Query, Response
from typing import Literal

from backend.app.dependencies import current_user, require_roles, require_same_origin
from backend.app.errors import success
from backend.app.models.classroom import CourseCreateRequest, EmojiRequest, ScheduleRequest, SessionRequest
from backend.app.services import classroom as service
from backend.app.services import campus

router = APIRouter(prefix='/api', tags=['课程与课堂反馈'])
Scope = Literal['ALL', 'REAL', 'DEMO']


@router.get('/departments')
def departments(user=Depends(current_user)):
    return success(campus.departments())


@router.get('/admin/campus')
def campus_overview(data_scope: Scope = 'ALL', user=Depends(require_roles('ADMIN'))):
    return success(campus.overview(user, data_scope))


@router.get('/courses')
def courses(data_scope: Scope = 'ALL', user=Depends(current_user)):
    return success(service.list_courses(user, data_scope))


@router.get('/courses/{course_id}')
def course_detail(course_id: int, user=Depends(current_user)):
    return success(service.course_detail(course_id, user))


@router.post('/admin/courses', status_code=201, dependencies=[Depends(require_same_origin)])
def create_course(payload: CourseCreateRequest, user=Depends(require_roles('ADMIN'))):
    return success(service.create_course(payload, user), '课程已创建')


@router.get('/admin/people')
def people(user=Depends(require_roles('ADMIN'))):
    return success(service.get_people())


@router.get('/sessions')
def sessions(data_scope: Scope = 'ALL', user=Depends(current_user)):
    return success(service.list_sessions(user, data_scope))


@router.post('/admin/sessions', status_code=201, dependencies=[Depends(require_same_origin)])
def create_session(payload: SessionRequest, user=Depends(require_roles('ADMIN'))):
    return success(service.create_session(payload, user), '课堂已创建，请继续安排学生名单')


@router.get('/sessions/{session_id}/roster')
def roster(session_id: int, user=Depends(require_roles('ADMIN', 'TEACHER'))):
    return success(service.get_roster(session_id, user))


@router.put('/admin/sessions/{session_id}/schedule', dependencies=[Depends(require_same_origin)])
def schedule(session_id: int, payload: ScheduleRequest, user=Depends(require_roles('ADMIN'))):
    return success(service.replace_roster(session_id, payload, user), '课堂名单已保存')


@router.post('/emoji', status_code=201, dependencies=[Depends(require_same_origin)])
def emoji(payload: EmojiRequest, response: Response, user=Depends(require_roles('STUDENT'))):
    record, created = service.submit_emoji(payload, user)
    response.status_code = 201 if created else 200
    return success(record, '感受已记录，谢谢你的反馈' if created else '本次反馈已记录，无需重复提交')


@router.get('/emoji/history')
def history(session_id: int | None = Query(default=None, gt=0), limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0), data_scope: Scope = 'ALL', user=Depends(current_user)):
    return success(service.get_history(user, session_id, limit, offset, data_scope))


@router.get('/sessions/{session_id}/statistics')
def statistics(session_id: int, data_scope: Scope = 'ALL', user=Depends(require_roles('ADMIN', 'TEACHER'))):
    return success(service.get_statistics(session_id, user, data_scope))
