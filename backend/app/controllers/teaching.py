from fastapi import APIRouter, Depends, Path

from backend.app.dependencies import current_user, require_roles, require_same_origin
from backend.app.errors import success
from backend.app.models.classroom import TeachingSessionRequest
from backend.app.models.engagement import GuideRequest
from backend.app.services import teaching as service
from backend.app.services.classroom import create_session

router = APIRouter(prefix='/api', tags=['教学工作台与学习指引'])


@router.get('/teaching/overview')
def overview(user=Depends(require_roles('TEACHER', 'ADMIN'))):
    return success(service.overview(user))


@router.post('/teaching/sessions', status_code=201, dependencies=[Depends(require_same_origin)])
def schedule(payload: TeachingSessionRequest, user=Depends(require_roles('TEACHER', 'ADMIN'))):
    return success(create_session(payload, user), '课堂已安排，课程内有效学生已自动加入名单')


@router.get('/sessions/{session_id}/learning-guide')
def guide(session_id: int = Path(gt=0), user=Depends(current_user)):
    return success(service.get_guide(session_id, user))


@router.put('/sessions/{session_id}/learning-guide', dependencies=[Depends(require_same_origin)])
def save(payload: GuideRequest, session_id: int = Path(gt=0), user=Depends(require_roles('TEACHER', 'ADMIN'))):
    messages = {'SAVE': '草稿已保存，学生端显示原已发布版本', 'PUBLISH': '学习指引已发布到本节课堂', 'UNPUBLISH': '学习指引已撤下，草稿保留'}
    return success(service.save_guide(session_id, payload, user), messages[payload.action])
