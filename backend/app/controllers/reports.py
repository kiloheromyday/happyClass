from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime

from backend.app.dependencies import require_roles
from backend.app.errors import success
from backend.app.models.classroom import now_utc
from backend.app.services import reports as service

router = APIRouter(prefix='/api', tags=['看板统计与导出'])
staff = require_roles('ADMIN', 'TEACHER')


def report_filters(from_time: AwareDatetime | None = Query(default=None), to_time: AwareDatetime | None = Query(default=None), course_id: int | None = Query(default=None, gt=0), class_name: str | None = Query(default=None, min_length=1, max_length=120), source: Literal['MANUAL', 'AI'] | None = Query(default=None), session_id: int | None = Query(default=None, gt=0), bucket: Literal['day', 'hour'] = Query(default='day'), data_scope: Literal['ALL', 'REAL', 'DEMO'] = 'ALL'):
    return service.resolve_filters(from_time, to_time, course_id, class_name, source, session_id, bucket, data_scope)


@router.get('/reports/statistics')
def statistics(user=Depends(staff), filters=Depends(report_filters)):
    return success(service.statistics(user, filters))


@router.get('/dashboard/realtime')
def realtime(session_id: int = Query(gt=0), data_scope: Literal['ALL', 'REAL', 'DEMO'] = 'ALL', user=Depends(staff)):
    return success(service.realtime(user, session_id, data_scope))


@router.get('/reports/export', response_class=Response)
def export(user=Depends(staff), filters=Depends(report_filters)):
    content, count = service.export_csv(user, filters)
    filename = 'emoji-feedback-' + now_utc().strftime('%Y%m%dT%H%M%SZ') + '.csv'
    return Response(content=content, media_type='text/csv', headers={'Content-Disposition': f'attachment; filename="{filename}"', 'X-Export-Count': str(count)})
