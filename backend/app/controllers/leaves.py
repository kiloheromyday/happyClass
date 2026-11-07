from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Response
from backend.app.dependencies import current_user, require_roles, require_same_origin
from backend.app.errors import success
from backend.app.models.leaves import LeaveRequest, LeaveVersion, LeaveDecision
from backend.app.services import leaves as service

router = APIRouter(prefix='/api/leaves', tags=['课堂请假'])


@router.get('')
def listing(status: Literal['ALL', 'PENDING', 'APPROVED', 'REJECTED', 'CANCELLED'] = 'ALL',
            course_id: int | None = Query(default=None, gt=0), session_id: int | None = Query(default=None, gt=0),
            limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0), user=Depends(current_user)):
    return success(service.listing(user, status, course_id, session_id, limit, offset))


@router.post('', status_code=201, dependencies=[Depends(require_same_origin)])
def create(payload: LeaveRequest, response: Response, user=Depends(require_roles('STUDENT'))):
    item, created = service.create(payload, user)
    response.status_code = 201 if created else 200
    return success(item, '请假申请已提交，等待任课教师审批' if created else '申请已提交，无需重复操作')


@router.put('/{leave_id}/cancel', dependencies=[Depends(require_same_origin)])
def cancel(payload: LeaveVersion, leave_id: int = Path(gt=0), user=Depends(require_roles('STUDENT'))):
    return success(service.cancel(leave_id, payload, user), '请假申请已撤回')


@router.put('/{leave_id}/decision', dependencies=[Depends(require_same_origin)])
def decide(payload: LeaveDecision, leave_id: int = Path(gt=0), user=Depends(require_roles('TEACHER'))):
    return success(service.decide(leave_id, payload, user), '请假审批已保存')
