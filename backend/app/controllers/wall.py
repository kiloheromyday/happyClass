from fastapi import APIRouter, Depends, Path, Query, Response

from backend.app.dependencies import require_roles, require_same_origin
from backend.app.errors import success
from backend.app.models.wall import WallCreate, WallUpdate
from backend.app.services import wall as service

router = APIRouter(prefix='/api/buddy-wall', tags=['学伴留言墙'])
student = require_roles('STUDENT')


@router.get('/sent')
def sent(limit: int = Query(default=12, ge=1, le=24), offset: int = Query(default=0, ge=0, le=10000), user=Depends(student)):
    return success(service.sent(user, limit, offset))


@router.get('/{owner_id}')
def wall(owner_id: int = Path(gt=0), mine: bool = False, limit: int = Query(default=12, ge=1, le=24), offset: int = Query(default=0, ge=0, le=10000), user=Depends(student)):
    return success(service.listing(owner_id, user, mine, limit, offset))


@router.post('/{owner_id}', dependencies=[Depends(require_same_origin)])
def create(payload: WallCreate, response: Response, owner_id: int = Path(gt=0), user=Depends(student)):
    item, created = service.create(owner_id, payload, user)
    response.status_code = 201 if created else 200
    return success(item, '留言已送达' if created else '本次留言已送达，无需重复发送')


@router.get('/{owner_id}/{message_id}/source')
def source(owner_id: int = Path(gt=0), message_id: int = Path(gt=0), user=Depends(student)):
    return success(service.source(owner_id, message_id, user))


@router.put('/{owner_id}/{message_id}', dependencies=[Depends(require_same_origin)])
def update(payload: WallUpdate, owner_id: int = Path(gt=0), message_id: int = Path(gt=0), user=Depends(student)):
    return success(service.update(owner_id, message_id, payload, user), '留言已更新')


@router.delete('/{owner_id}/{message_id}', dependencies=[Depends(require_same_origin)])
def delete(owner_id: int = Path(gt=0), message_id: int = Path(gt=0), version: int = Query(ge=1), user=Depends(student)):
    service.delete(owner_id, message_id, version, user)
    return success(message='留言已删除')
