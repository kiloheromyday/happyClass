from uuid import UUID
import secrets

from fastapi import APIRouter, Depends, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from ai_service.config import MAX_FRAME_BYTES, ingest_token
from backend.app.dependencies import require_roles, require_same_origin
from backend.app.errors import AppError
from backend.app.repositories.database import connect
from backend.app.services import ai
from backend.app.services.auth import limit_attempt
from backend.app.models.ai import AiBatchRequest

router = APIRouter(prefix='/api', tags=['课堂表情识别'])
staff = require_roles('TEACHER', 'ADMIN')
ingest_scheme = HTTPBearer(auto_error=False, scheme_name='AIIngestToken')


def require_ingest(credentials: HTTPAuthorizationCredentials | None = Depends(ingest_scheme)):
    expected = ingest_token()
    if not expected:
        raise AppError(503, 'AI_INGEST_NOT_CONFIGURED', 'AI 接收密钥尚未配置')
    supplied = credentials.credentials if credentials else ''
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise AppError(401, 'INVALID_AI_TOKEN', 'AI 接收令牌无效')


@router.get('/ai/status')
async def status(user=Depends(staff)):
    return await ai.status()


@router.post('/sessions/{session_id}/ai-frame', dependencies=[Depends(require_same_origin)])
async def frame(session_id: int, request: Request, request_id: UUID = Header(alias='X-Frame-ID'), user=Depends(staff)):
    with connect() as connection:
        ai.ongoing(connection, session_id, user)
    if request.headers.get('content-type', '').split(';')[0] != 'image/jpeg':
        raise AppError(415, 'INVALID_MEDIA_TYPE', '请提交 JPEG 图片')
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_FRAME_BYTES:
            raise AppError(413, 'FRAME_TOO_LARGE', '图片不能超过 1 MB')
    return await ai.process_frame(session_id, user, request_id, bytes(data))


@router.post('/ai/emoji-results', dependencies=[Depends(require_ingest)])
def ingest(payload: AiBatchRequest):
    limit_attempt(f'ai-ingest:{payload.device_id}', 120, 300)
    return ai.ingest_results(payload)
