from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Response

from backend.app.dependencies import require_roles, require_same_origin
from backend.app.emotion.bookmarks import materials, reading, service, study, timeline
from backend.app.emotion.bookmarks.models import (
    BookmarkUpdate, CreateBookmark, CreateMaterial, EditMaterial, MaterialAction,
    MaterialProgress, MaterialState, Reason, ReviewSelection,
)
from backend.app.errors import success

router = APIRouter(prefix='/api/classroom-bookmarks', tags=['课堂卡点书签'])
student = require_roles('STUDENT')
staff = require_roles('TEACHER', 'ADMIN')
member = require_roles('STUDENT', 'TEACHER', 'ADMIN')
write = [Depends(require_same_origin)]
Bucket = Literal['1', '5', '10']
ReviewState = Literal['ALL', 'OPEN', 'REVIEWED']
BookmarkOrder = Literal['RECENT', 'LESSON']


@router.get('/catalog')
def catalog(user=Depends(member)):
    return success(service.catalog(user))


@router.get('/mine')
def mine(
    session_id: int | None = Query(default=None, gt=0),
    state: ReviewState = 'ALL',
    reason: Reason | None = None,
    term: str = Query(default='', max_length=100),
    order: BookmarkOrder = 'RECENT',
    limit: int = Query(default=15, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=100000),
    user=Depends(student),
):
    return success(service.list_for_student(user, session_id, state, reason, term.strip(), order, limit, offset))


@router.get('/mine.csv')
def export_personal(
    session_id: int | None = Query(default=None, gt=0),
    state: ReviewState = 'ALL',
    reason: Reason | None = None,
    term: str = Query(default='', max_length=100),
    order: BookmarkOrder = 'RECENT',
    user=Depends(student),
):
    return Response(
        reading.personal_export(user, session_id, state, reason, term.strip(), order),
        media_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename="my-classroom-bookmarks.csv"'},
    )


@router.get('/study-queue')
def study_queue(
    session_id: int | None = Query(default=None, gt=0),
    prefer: Literal['MATERIAL', 'TIME', 'RECENT'] = 'MATERIAL',
    limit: int = Query(default=10, ge=1, le=25),
    offset: int = Query(default=0, ge=0, le=100000),
    user=Depends(student),
):
    return success(study.queue(user, session_id, prefer, limit, offset))


@router.post('/sessions/{session_id}/mine', status_code=201, dependencies=write)
def create_bookmark(payload: CreateBookmark, session_id: int = Path(gt=0), user=Depends(student)):
    return success(service.create(session_id, payload, user))


@router.put('/mine/{bookmark_id}', dependencies=write)
def edit_bookmark(payload: BookmarkUpdate, bookmark_id: int = Path(gt=0), user=Depends(student)):
    return success(service.update(bookmark_id, payload, user))


@router.delete('/mine/{bookmark_id}', dependencies=write)
def delete_bookmark(bookmark_id: int = Path(gt=0), version: int = Query(ge=1), user=Depends(student)):
    return success(service.remove(bookmark_id, version, user))


@router.post('/mine/review', dependencies=write)
def mark_selection(payload: ReviewSelection, user=Depends(student)):
    return success(service.review_selected(payload, user))


@router.get('/sessions/{session_id}/timeline')
def classroom_timeline(
    session_id: int = Path(gt=0),
    bucket: Bucket = '5',
    user=Depends(staff),
):
    return success(timeline.get_timeline(session_id, int(bucket), user))


@router.get('/sessions/{session_id}/timeline.csv')
def download_timeline(
    session_id: int = Path(gt=0),
    bucket: Bucket = '5',
    user=Depends(staff),
):
    return Response(
        timeline.export_timeline(session_id, int(bucket), user),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="classroom-bookmarks-{session_id}.csv"'},
    )


@router.get('/sessions/{session_id}/materials')
def material_list(
    session_id: int = Path(gt=0),
    state: MaterialState | None = None,
    start_minute: int | None = Query(default=None, ge=0, le=100000),
    end_minute: int | None = Query(default=None, gt=0, le=100000),
    user=Depends(member),
):
    return success(materials.list_for_session(session_id, user, state, start_minute, end_minute))


@router.get('/sessions/{session_id}/reading-report')
def reading_report(session_id: int = Path(gt=0), user=Depends(staff)):
    return success(reading.report(session_id, user))


@router.get('/sessions/{session_id}/reading-report.csv')
def export_reading_report(session_id: int = Path(gt=0), user=Depends(staff)):
    return Response(
        reading.export_report(session_id, user),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="classroom-reading-{session_id}.csv"'},
    )


@router.post('/sessions/{session_id}/materials', status_code=201, dependencies=write)
def create_material(payload: CreateMaterial, session_id: int = Path(gt=0), user=Depends(staff)):
    return success(materials.create(session_id, payload, user))


@router.put('/materials/{material_id}', dependencies=write)
def edit_material(payload: EditMaterial, material_id: int = Path(gt=0), user=Depends(staff)):
    return success(materials.update(material_id, payload, user))


@router.post('/materials/{material_id}/state', dependencies=write)
def update_material_state(payload: MaterialAction, material_id: int = Path(gt=0), user=Depends(staff)):
    return success(materials.change_state(material_id, payload, user))


@router.put('/materials/{material_id}/progress', dependencies=write)
def update_material_progress(payload: MaterialProgress, material_id: int = Path(gt=0), user=Depends(student)):
    return success(materials.set_progress(material_id, payload, user))
