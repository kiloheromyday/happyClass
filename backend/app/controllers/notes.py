from typing import Literal
from datetime import date, datetime

from fastapi import APIRouter, Depends, Path, Query, Response

from backend.app.dependencies import require_roles, require_same_origin
from backend.app.errors import success
from backend.app.models.notes import NoteCreate, NoteUpdate
from backend.app.services import notes as service

router = APIRouter(prefix='/api/personal', tags=['个人笔记与回顾'], dependencies=[Depends(require_roles('STUDENT'))])


@router.get('/notes/sessions')
def sessions(user=Depends(require_roles('STUDENT'))):
    return success(service.sessions(user))


@router.get('/notes')
def notes(q: str = Query(default='', max_length=80), session_id: int | None = Query(default=None, gt=0), review: Literal['ALL', 'PENDING', 'DONE'] = 'ALL', limit: int = Query(default=12, ge=1, le=24), offset: int = Query(default=0, ge=0, le=10000), user=Depends(require_roles('STUDENT'))):
    return success(service.listing(user, q, session_id, review, limit, offset))


@router.get('/notes/export')
def export(q: str = Query(default='', max_length=80), session_id: int | None = Query(default=None, gt=0), review: Literal['ALL', 'PENDING', 'DONE'] = 'ALL', user=Depends(require_roles('STUDENT'))):
    content, count = service.export(user, q, session_id, review)
    return Response(content, media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="my-classroom-notes.csv"', 'X-Export-Count': str(count)})


@router.post('/notes', dependencies=[Depends(require_same_origin)])
def create(payload: NoteCreate, response: Response, user=Depends(require_roles('STUDENT'))):
    item, created = service.create(payload, user)
    response.status_code = 201 if created else 200
    return success(item, '笔记已保存' if created else '这次笔记已保存，无需重复提交')


@router.get('/notes/{note_id}')
def get(note_id: int = Path(gt=0), user=Depends(require_roles('STUDENT'))):
    return success(service.get(note_id, user))


@router.put('/notes/{note_id}', dependencies=[Depends(require_same_origin)])
def update(payload: NoteUpdate, note_id: int = Path(gt=0), user=Depends(require_roles('STUDENT'))):
    return success(service.update(note_id, payload, user), '笔记已更新')


@router.delete('/notes/{note_id}', dependencies=[Depends(require_same_origin)])
def delete(note_id: int = Path(gt=0), version: int = Query(ge=1), user=Depends(require_roles('STUDENT'))):
    service.delete(note_id, version, user)
    return success(message='笔记已删除')


@router.get('/review')
def review(days: Literal['7', '30', '90'] = '7', session_id: int | None = Query(default=None, gt=0), user=Depends(require_roles('STUDENT'))):
    return success(service.review(user, int(days), session_id))


@router.get('/review/export')
def export_review(days: Literal['7', '30', '90'] = '7', session_id: int | None = Query(default=None, gt=0), user=Depends(require_roles('STUDENT'))):
    return Response(service.export_review(user, int(days), session_id), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="my-learning-review.csv"'})


@router.get('/review/day')
def review_day(day: date, starts_at: datetime, ends_at: datetime, session_id: int | None = Query(default=None, gt=0), feedback_offset: int = Query(default=0, ge=0, le=1000000), notes_offset: int = Query(default=0, ge=0, le=1000), user=Depends(require_roles('STUDENT'))):
    return success(service.review_day(user, day, starts_at, ends_at, session_id, feedback_offset, notes_offset))
