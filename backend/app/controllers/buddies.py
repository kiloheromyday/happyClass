from typing import Annotated
from fastapi import APIRouter, Depends, Path, Query
from backend.app.dependencies import require_roles, require_same_origin
from backend.app.errors import success
from backend.app.models.buddies import BuddyRequest, BuddySearch
from backend.app.services import buddies

router = APIRouter(prefix='/api/buddies', tags=['好友学伴'])
student = require_roles('STUDENT')


@router.get('')
def list_buddies(user=Depends(student)):
    return success(buddies.list_buddies(user))


@router.get('/search')
def search(filters: Annotated[BuddySearch, Query()], user=Depends(student)):
    return success(buddies.lookup(user, filters))


@router.post('/requests', dependencies=[Depends(require_same_origin)])
def send(payload: BuddyRequest, user=Depends(student)):
    return success(buddies.send_request(user, payload.user_id), '申请已处理')


@router.post('/requests/{request_id}/accept', dependencies=[Depends(require_same_origin)])
def accept(request_id: int = Path(gt=0), user=Depends(student)):
    buddies.accept(user, request_id)
    return success(message='已成为学伴')


@router.delete('/requests/{request_id}', dependencies=[Depends(require_same_origin)])
def dismiss(request_id: int = Path(gt=0), user=Depends(student)):
    buddies.dismiss(user, request_id)
    return success(message='申请已处理')


@router.delete('/{user_id}', dependencies=[Depends(require_same_origin)])
def remove(user_id: int = Path(gt=0), user=Depends(student)):
    buddies.remove(user, user_id)
    return success(message='已移除学伴')
