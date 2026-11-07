from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Response

from backend.app.dependencies import current_user, require_roles, require_same_origin
from backend.app.errors import success
from backend.app.models.engagement import AnswerRequest, QuestionRequest, ReflectionRequest
from backend.app.services import engagement as service

router = APIRouter(prefix='/api/sessions/{session_id}', tags=['匿名问题与课堂小结'])


@router.get('/questions')
def questions(session_id: int = Path(gt=0), status: Literal['ALL', 'OPEN', 'RESOLVED'] = 'ALL', limit: int = Query(default=12, ge=1, le=24), offset: int = Query(default=0, ge=0, le=10000), user=Depends(current_user)):
    return success(service.list_questions(session_id, user, status, limit, offset))


@router.post('/questions', dependencies=[Depends(require_same_origin)])
def submit(payload: QuestionRequest, response: Response, session_id: int = Path(gt=0), user=Depends(require_roles('STUDENT'))):
    item, created = service.submit_question(session_id, payload, user)
    response.status_code = 201 if created else 200
    return success(item, '问题已匿名送达' if created else '本次问题已送达')


@router.put('/questions/{question_id}', dependencies=[Depends(require_same_origin)])
def answer(payload: AnswerRequest, session_id: int = Path(gt=0), question_id: int = Path(gt=0), user=Depends(require_roles('TEACHER', 'ADMIN'))):
    return success(service.answer(session_id, question_id, payload, user), '回应已保存')


@router.get('/recap')
def recap(session_id: int = Path(gt=0), user=Depends(require_roles('TEACHER', 'ADMIN'))):
    return success(service.get_recap(session_id, user))


@router.put('/recap', dependencies=[Depends(require_same_origin)])
def reflection(payload: ReflectionRequest, session_id: int = Path(gt=0), user=Depends(require_roles('TEACHER', 'ADMIN'))):
    return success(service.save_reflection(session_id, payload, user), '教学反思已保存')


@router.get('/recap/export')
def export(session_id: int = Path(gt=0), user=Depends(require_roles('TEACHER', 'ADMIN'))):
    return Response(service.export_recap(session_id, user), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="classroom-recap-{session_id}.csv"'})
