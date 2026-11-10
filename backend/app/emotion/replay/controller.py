from typing import Literal
from fastapi import APIRouter, Depends, Path, Query

from backend.app.dependencies import require_roles
from backend.app.errors import AppError, success
from backend.app.emotion.replay.service import get_replay

router = APIRouter(prefix='/api/sessions', tags=['课堂情绪回放'])


@router.get('/{session_id}/emotion-replay')
def replay(session_id: int = Path(gt=0), bucket_minutes: int = Query(default=1, ge=1, le=10),
           source: Literal['ALL', 'MANUAL', 'AI'] = 'ALL',
           data_scope: Literal['ALL', 'REAL', 'DEMO'] = 'ALL',
           user=Depends(require_roles('ADMIN', 'TEACHER'))):
    if bucket_minutes not in (1, 5, 10):
        raise AppError(422, 'INVALID_REPLAY_BUCKET', '回放粒度请选择 1、5 或 10 分钟')
    return success(get_replay(session_id, user, bucket_minutes, source, data_scope))
