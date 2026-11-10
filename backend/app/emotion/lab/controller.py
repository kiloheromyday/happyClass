from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Response

from backend.app.dependencies import require_roles, require_same_origin
from backend.app.errors import success
from backend.app.emotion.lab import service
from backend.app.emotion.lab import governance
from backend.app.emotion.lab.models import (
    AnnotationRequest,
    ArchiveRequest,
    ReportUpdate,
    RunRequest,
    StudyRequest,
    TEMPLATES,
)

router = APIRouter(prefix='/api/emotion-lab', tags=['课堂情绪分析实验室'])
staff = require_roles('TEACHER', 'ADMIN')
write = [Depends(require_same_origin)]


@router.get('/dashboard')
def dashboard(user=Depends(staff)):
    return success(service.dashboard(user))


@router.get('/templates')
def templates(user=Depends(staff)):
    return success({'items': TEMPLATES})


@router.get('/storage')
def storage(user=Depends(staff)):
    return success(governance.storage(user))


@router.get('/studies/{identifier}/history')
def history(identifier: int = Path(gt=0), user=Depends(staff)):
    return success(governance.history(identifier, user))


@router.get('/reports/{identifier}/integrity')
def integrity(identifier: int = Path(gt=0), user=Depends(staff)):
    return success(governance.check_snapshot(identifier, user))


@router.delete('/reports/{identifier}', dependencies=write)
def remove_report(
    identifier: int = Path(gt=0),
    version: int = Query(ge=1),
    user=Depends(staff),
):
    return success(governance.delete_report(identifier, version, user), '已归档报告已清理')


@router.get('/catalog')
def catalog(
    search: str = Query(default='', max_length=120),
    course_id: int | None = Query(default=None, gt=0),
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=20, ge=1, le=100),
    user=Depends(staff),
):
    return success(service.catalog(user, search, course_id, offset, limit))


@router.get('/studies')
def studies(
    archived: bool | None = None,
    search: str = Query(default='', max_length=120),
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=20, ge=1, le=50),
    user=Depends(staff),
):
    return success(service.list_studies(user, archived, search, offset, limit))


@router.post('/studies', status_code=201, dependencies=write)
def create_study(payload: StudyRequest, user=Depends(staff)):
    return success(service.save_study(payload, user), '分析方案已保存')


@router.post('/preview', dependencies=write)
def preview(payload: StudyRequest, user=Depends(staff)):
    return success(service.preview(payload, user))


@router.get('/studies/{identifier}')
def study(identifier: int = Path(gt=0), user=Depends(staff)):
    return success(service.get_study(identifier, user))


@router.put('/studies/{identifier}', dependencies=write)
def save_study(payload: StudyRequest, identifier: int = Path(gt=0), user=Depends(staff)):
    return success(service.save_study(payload, user, identifier), '分析方案已更新')


@router.put('/studies/{identifier}/archive', dependencies=write)
def archive_study(payload: ArchiveRequest, identifier: int = Path(gt=0), user=Depends(staff)):
    return success(service.archive_study(identifier, payload, user), '方案归档状态已更新')


@router.post('/studies/{identifier}/runs', status_code=202, dependencies=write)
def run_study(payload: RunRequest, identifier: int = Path(gt=0), user=Depends(staff)):
    return success(service.enqueue(identifier, payload, user), '分析任务已进入后台队列')


@router.get('/jobs')
def jobs(
    state: Literal['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'] | None = None,
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=20, ge=1, le=50),
    user=Depends(staff),
):
    return success(service.list_jobs(user, state, offset, limit))


@router.get('/jobs/{identifier}')
def job(
    identifier: int = Path(gt=0),
    after_id: int = Query(default=0, ge=0),
    user=Depends(staff),
):
    return success(service.get_job(identifier, user, after_id))


@router.post('/jobs/{identifier}/cancel', dependencies=write)
def cancel(identifier: int = Path(gt=0), user=Depends(staff)):
    return success(service.cancel_job(identifier, user), '取消请求已提交')


@router.post('/jobs/{identifier}/retry', dependencies=write)
def retry(identifier: int = Path(gt=0), user=Depends(staff)):
    return success(service.retry_job(identifier, user), '失败任务已重新排队')


@router.get('/reports')
def reports(
    status: Literal['DRAFT', 'REVIEWED', 'ARCHIVED'] | None = None,
    bookmarked: bool = False,
    search: str = Query(default='', max_length=120),
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=20, ge=1, le=50),
    user=Depends(staff),
):
    return success(service.list_reports(user, status, bookmarked, search, offset, limit))


@router.get('/reports/{identifier}')
def report(identifier: int = Path(gt=0), user=Depends(staff)):
    return success(service.get_report(identifier, user))


@router.put('/reports/{identifier}', dependencies=write)
def edit_report(payload: ReportUpdate, identifier: int = Path(gt=0), user=Depends(staff)):
    return success(service.update_report(identifier, payload, user), '报告复核信息已保存')


@router.get('/reports/{identifier}/compare/{other_id}')
def compare(identifier: int = Path(gt=0), other_id: int = Path(gt=0), user=Depends(staff)):
    return success(service.compare_reports(identifier, other_id, user))


@router.post('/reports/{report_id}/annotations', status_code=201, dependencies=write)
def add_annotation(payload: AnnotationRequest, report_id: int = Path(gt=0), user=Depends(staff)):
    return success(service.save_annotation(report_id, payload, user), '批注已保存')


@router.put('/reports/{report_id}/annotations/{identifier}', dependencies=write)
def edit_annotation(
    payload: AnnotationRequest,
    report_id: int = Path(gt=0),
    identifier: int = Path(gt=0),
    user=Depends(staff),
):
    return success(service.save_annotation(report_id, payload, user, identifier), '批注已更新')


@router.delete('/reports/{report_id}/annotations/{identifier}', dependencies=write)
def delete_annotation(
    report_id: int = Path(gt=0),
    identifier: int = Path(gt=0),
    version: int = Query(ge=1),
    user=Depends(staff),
):
    return success(service.delete_annotation(report_id, identifier, version, user), '批注已删除')


@router.get('/reports/{identifier}/export')
def export(
    identifier: int = Path(gt=0),
    format: Literal['csv', 'json', 'html'] = 'csv',
    user=Depends(staff),
):
    from backend.app.emotion.lab.exports import export_report
    content, media_type = export_report(identifier, user, format)
    return Response(
        content,
        media_type=media_type,
        headers={
            'Content-Disposition': f'attachment; filename="emotion-lab-report-{identifier}.{format}"',
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
        },
    )
