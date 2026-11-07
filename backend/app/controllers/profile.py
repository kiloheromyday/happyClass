from fastapi import APIRouter, Depends, Path, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from backend.app.dependencies import current_user, require_same_origin
from backend.app.errors import AppError, success
from backend.app.services import auth, avatars
from backend.app.services.profile import overview

router = APIRouter(prefix='/api', tags=['个人主页与头像'])


@router.get('/users/me/overview')
def get_overview(user=Depends(current_user)):
    return success(overview(user))


@router.put('/users/me/avatar', dependencies=[Depends(require_same_origin)])
async def upload(request: Request, zoom: float = Query(default=1, ge=1, le=3), x: float = Query(default=.5, ge=0, le=1), y: float = Query(default=.5, ge=0, le=1), user=Depends(current_user)):
    media_type = request.headers.get('content-type', '').split(';')[0].strip().lower()
    if media_type not in avatars.TYPES:
        raise AppError(415, 'AVATAR_TYPE', '请选择 JPG、PNG 或 WebP 静态图片')
    auth.limit_attempt(f'avatar-upload:{user["id"]}', 30, 3600)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > avatars.MAX_BYTES:
            raise AppError(413, 'AVATAR_SIZE', '头像图片不能超过 2 MB')
        data.extend(chunk)
    image = await run_in_threadpool(avatars.normalize, bytes(data), media_type, zoom, x, y)
    await run_in_threadpool(avatars.save, user, image)
    return success(auth.public_user(user), '头像已更新')


@router.delete('/users/me/avatar', dependencies=[Depends(require_same_origin)])
def remove(user=Depends(current_user)):
    avatars.remove(user)
    return success(auth.public_user(user), '已恢复默认头像')


@router.get('/avatars/{user_id}/{digest}')
def image(user_id: int = Path(gt=0), digest: str = Path(pattern='^[a-f0-9]{64}$'), user=Depends(current_user)):
    return Response(avatars.image_for(user_id, digest, user), media_type='image/jpeg', headers={'Cache-Control': 'private, no-store'})
