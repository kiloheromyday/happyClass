from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import ValidationError

from backend.app.dependencies import require_roles, require_same_origin
from backend.app.errors import AppError, success
from backend.app.emotion.feedback import (
    adjustment_report,
    cases,
    catalog,
    conversations,
    groups,
    inbox,
    progress,
    reporting,
    review_desk,
    reviews,
    settings,
    suggestions,
    workload,
)
from backend.app.emotion.feedback.models import (
    BatchAction,
    CaseAction,
    CaseState,
    CreateCase,
    EditCase,
    Filters,
    GroupCreate,
    GroupUpdate,
    LinkAdjustment,
    ManageCase,
    MessageCreate,
    MessageEdit,
    PolicyUpdate,
    Reason,
    ReplyTemplate,
    ReviewAnswer,
    ReviewClose,
    ReviewCreate,
    SavedView,
    VersionCommand,
)
from backend.app.models.classroom import Emotion

router = APIRouter(prefix='/api/emotion-feedback', tags=['课堂情绪反馈处理中心'])
member = require_roles('STUDENT', 'TEACHER', 'ADMIN')
staff = require_roles('TEACHER', 'ADMIN')
student = require_roles('STUDENT')
write = [Depends(require_same_origin)]


def filters(
    session_id: int | None = Query(default=None, gt=0),
    course_id: int | None = Query(default=None, gt=0),
    state: CaseState | Literal['ALL'] = 'ALL',
    reason: Reason | Literal['ALL'] = 'ALL',
    emotion: Emotion | Literal['ALL'] = 'ALL',
    priority: Literal['ALL', 'NORMAL', 'HIGH'] = 'ALL',
    search: str = Query(default='', max_length=120),
    watched: bool = False,
    overdue: bool = False,
    review_overdue: bool = False,
    active_only: bool = False,
    data_scope: Literal['ALL', 'REAL', 'DEMO'] = 'ALL',
    sort: Literal['UPDATED', 'CREATED', 'OLDEST', 'PRIORITY'] = 'UPDATED',
):
    try:
        return Filters(
            session_id=session_id,
            course_id=course_id,
            state=state,
            reason=reason,
            emotion=emotion,
            priority=priority,
            search=search,
            watched=watched,
            overdue=overdue,
            review_overdue=review_overdue,
            active_only=active_only,
            data_scope=data_scope,
            sort=sort,
        )
    except ValidationError as error:
        raise AppError(422, 'INVALID_FEEDBACK_FILTER', '请检查反馈筛选条件') from error


@router.get('/options')
def get_options(user=Depends(member)):
    return success(catalog.options(user))


@router.get('/sessions/{session_id}/context')
def get_context(
    session_id: int = Path(gt=0),
    user=Depends(member),
):
    return success(catalog.session_context(session_id, user))


@router.get('/cases')
def list_cases(
    selection=Depends(filters),
    offset: int = Query(default=0, ge=0, le=1000000),
    limit: int = Query(default=20, ge=1, le=100),
    user=Depends(member),
):
    return success(cases.listing(selection, user, offset, limit))


@router.post('/cases', status_code=201, dependencies=write)
def create_case(payload: CreateCase, user=Depends(student)):
    return success(cases.create(payload, user), '情绪反馈已送达老师')


@router.get('/cases/{case_id}')
def get_case(case_id: int = Path(gt=0), user=Depends(member)):
    return success(cases.detail(case_id, user))


@router.get('/cases/{case_id}/progress')
def get_case_progress(case_id: int = Path(gt=0), user=Depends(member)):
    return success(progress.read_progress(case_id, user))


@router.put('/cases/{case_id}', dependencies=write)
def edit_case(
    payload: EditCase,
    case_id: int = Path(gt=0),
    user=Depends(student),
):
    return success(cases.edit(case_id, payload, user), '反馈内容已更新')


@router.post('/cases/{case_id}/actions', dependencies=write)
def case_action(
    payload: CaseAction,
    case_id: int = Path(gt=0),
    user=Depends(member),
):
    return success(cases.action(case_id, payload, user), '处理进度已更新')


@router.put('/cases/{case_id}/management', dependencies=write)
def manage_case(
    payload: ManageCase,
    case_id: int = Path(gt=0),
    user=Depends(staff),
):
    return success(cases.manage(case_id, payload, user), '内部处理信息已保存')


@router.put('/cases/{case_id}/watch', dependencies=write)
def watch_case(
    case_id: int = Path(gt=0),
    enabled: bool = True,
    user=Depends(staff),
):
    return success(cases.watch(case_id, enabled, user))


@router.get('/cases/{case_id}/messages')
def list_messages(
    case_id: int = Path(gt=0),
    before_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=40, ge=1, le=100),
    user=Depends(member),
):
    return success(conversations.page(case_id, user, before_id, limit))


@router.post('/cases/{case_id}/messages', status_code=201, dependencies=write)
def send_message(
    payload: MessageCreate,
    case_id: int = Path(gt=0),
    user=Depends(member),
):
    return success(conversations.reply(case_id, payload, user), '回应已发送')


@router.put('/cases/{case_id}/messages/{message_id}', dependencies=write)
def edit_message(
    payload: MessageEdit,
    case_id: int = Path(gt=0),
    message_id: int = Path(gt=0),
    user=Depends(member),
):
    return success(conversations.edit(case_id, message_id, payload, user), '消息已修订')


@router.post('/cases/{case_id}/messages/{message_id}/withdraw', dependencies=write)
def remove_message(
    payload: VersionCommand,
    case_id: int = Path(gt=0),
    message_id: int = Path(gt=0),
    user=Depends(member),
):
    return success(conversations.edit(case_id, message_id, payload, user, True), '消息已撤回')


@router.get('/cases/{case_id}/events')
def list_events(
    case_id: int = Path(gt=0),
    before_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=60, ge=1, le=100),
    user=Depends(member),
):
    return success(conversations.history(case_id, user, before_id, limit))


@router.post('/cases/{case_id}/reviews', status_code=201, dependencies=write)
def create_review(
    payload: ReviewCreate,
    case_id: int = Path(gt=0),
    user=Depends(staff),
):
    return success(reviews.request(case_id, payload, user), '回访邀请已发送')


@router.post('/reviews/{review_id}/answer', dependencies=write)
def answer_review(
    payload: ReviewAnswer,
    review_id: int = Path(gt=0),
    user=Depends(student),
):
    return success(reviews.answer(review_id, payload, user), '谢谢你的回访反馈')


@router.post('/reviews/{review_id}/cancel', dependencies=write)
def cancel_review(
    payload: ReviewClose,
    review_id: int = Path(gt=0),
    user=Depends(staff),
):
    return success(reviews.cancel(review_id, payload, user), '本轮回访已取消')


@router.get('/reviews/pending')
def pending_reviews(
    limit: int = Query(default=50, ge=1, le=100),
    user=Depends(member),
):
    return success(reviews.pending(user, limit))


@router.get('/review-desk')
def review_schedule(
    selection=Depends(filters),
    status: Literal['ALL', 'OPEN', 'OVERDUE', 'ANSWERED', 'CANCELLED'] = 'OPEN',
    review_sort: Literal['DUE', 'NEWEST'] = 'DUE',
    offset: int = Query(default=0, ge=0, le=1000000),
    limit: int = Query(default=20, ge=1, le=100),
    user=Depends(member),
):
    return success(review_desk.listing(selection, user, status, offset, limit, review_sort))


@router.post('/reviews/{review_id}/remind', dependencies=write)
def remind_review(
    payload: VersionCommand,
    review_id: int = Path(gt=0),
    user=Depends(staff),
):
    return success(review_desk.remind(review_id, payload, user), '回访提醒已发送')


@router.post('/cases/{case_id}/adjustments', dependencies=write)
def link_adjustment(
    payload: LinkAdjustment,
    case_id: int = Path(gt=0),
    user=Depends(staff),
):
    return success(cases.link(case_id, payload, user), '教学调整已关联')


@router.post('/cases/{case_id}/adjustments/{adjustment_id}/unlink', dependencies=write)
def unlink_adjustment(
    payload: VersionCommand,
    case_id: int = Path(gt=0),
    adjustment_id: int = Path(gt=0),
    user=Depends(staff),
):
    return success(cases.unlink(case_id, adjustment_id, payload, user), '教学调整关联已移除')


@router.get('/groups')
def list_groups(
    session_id: int | None = Query(default=None, gt=0),
    archived: bool = False,
    user=Depends(staff),
):
    return success(groups.listing(user, session_id, archived))


@router.get('/group-suggestions')
def suggest_groups(
    selection=Depends(filters),
    minimum: int = Query(default=2, ge=2, le=10),
    topic_window: int | None = None,
    include_grouped: bool = False,
    user=Depends(staff),
):
    if topic_window is not None and topic_window not in (5, 10, 15, 30):
        raise AppError(422, 'INVALID_TOPIC_WINDOW', '请选择 5、10、15 或 30 分钟')
    return success(suggestions.suggest(selection, user, minimum, topic_window, include_grouped))


@router.post('/groups', status_code=201, dependencies=write)
def create_group(payload: GroupCreate, user=Depends(staff)):
    return success(groups.save(payload, user), '集中处理组已创建')


@router.get('/groups/{group_id}')
def get_group(group_id: int = Path(gt=0), user=Depends(staff)):
    return success(groups.detail(group_id, user))


@router.put('/groups/{group_id}', dependencies=write)
def update_group(
    payload: GroupUpdate,
    group_id: int = Path(gt=0),
    user=Depends(staff),
):
    return success(groups.save(payload, user, group_id), '集中处理组已更新')


@router.post('/groups/{group_id}/batch', dependencies=write)
def batch_group(
    payload: BatchAction,
    group_id: int = Path(gt=0),
    user=Depends(staff),
):
    return success(groups.batch(group_id, payload, user), '选中反馈已全部处理')


@router.get('/templates')
def list_templates(archived: bool = False, user=Depends(staff)):
    return success(settings.templates(user, archived))


@router.post('/templates', status_code=201, dependencies=write)
def create_template(payload: ReplyTemplate, user=Depends(staff)):
    return success(settings.save_template(payload, user), '回应模板已创建')


@router.put('/templates/{template_id}', dependencies=write)
def update_template(
    payload: ReplyTemplate,
    template_id: int = Path(gt=0),
    user=Depends(staff),
):
    return success(settings.save_template(payload, user, template_id), '回应模板已更新')


@router.get('/courses/{course_id}/policy')
def get_policy(course_id: int = Path(gt=0), user=Depends(member)):
    return success(settings.get_policy(course_id, user))


@router.put('/courses/{course_id}/policy', dependencies=write)
def update_policy(
    payload: PolicyUpdate,
    course_id: int = Path(gt=0),
    user=Depends(staff),
):
    return success(settings.save_policy(course_id, payload, user), '课程处理规则已保存')


@router.get('/views')
def list_views(user=Depends(member)):
    return success(settings.views(user))


@router.post('/views', status_code=201, dependencies=write)
def create_view(payload: SavedView, user=Depends(member)):
    return success(settings.save_view(payload, user), '筛选视图已保存')


@router.put('/views/{view_id}', dependencies=write)
def update_view(
    payload: SavedView,
    view_id: int = Path(gt=0),
    user=Depends(member),
):
    return success(settings.save_view(payload, user, view_id), '筛选视图已更新')


@router.post('/views/{view_id}/delete', dependencies=write)
def delete_view(
    payload: VersionCommand,
    view_id: int = Path(gt=0),
    user=Depends(member),
):
    return success(settings.delete_view(view_id, payload, user), '筛选视图已删除')


@router.get('/inbox')
def list_inbox(
    unread_only: bool = False,
    before_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=30, ge=1, le=100),
    user=Depends(member),
):
    return success(inbox.listing(user, unread_only, before_id, limit))


@router.post('/inbox/read-all', dependencies=write)
def read_all(user=Depends(member)):
    return success(inbox.mark_all(user))


@router.post('/inbox/{notice_id}/read', dependencies=write)
def read_notice(notice_id: int = Path(gt=0), user=Depends(member)):
    return success(inbox.mark(notice_id, user))


@router.get('/dashboard')
def dashboard(
    selection=Depends(filters),
    days: int = Query(default=14, ge=7, le=90),
    user=Depends(member),
):
    return success(reporting.dashboard(selection, user, days))


@router.get('/todos')
def todos(selection=Depends(filters), user=Depends(member)):
    return success(reporting.todos(selection, user))


@router.get('/adjustment-report')
def list_adjustment_report(
    selection=Depends(filters),
    offset: int = Query(default=0, ge=0, le=1000000),
    limit: int = Query(default=15, ge=1, le=100),
    adjustment_sort: Literal['LATEST', 'WAITING', 'LINKS'] = 'LATEST',
    user=Depends(staff),
):
    return success(adjustment_report.listing(selection, user, offset, limit, adjustment_sort))


@router.get('/adjustment-report/export.csv')
def export_adjustment_report(
    selection=Depends(filters),
    adjustment_sort: Literal['LATEST', 'WAITING', 'LINKS'] = 'LATEST',
    user=Depends(staff),
):
    content, count = adjustment_report.export(selection, user, adjustment_sort)
    return Response(
        content,
        media_type='text/csv',
        headers={
            'Content-Disposition': 'attachment; filename="emotion-feedback-adjustments.csv"',
            'X-Export-Count': str(count),
        },
    )


@router.get('/adjustment-report/{adjustment_id}')
def show_adjustment_report(
    adjustment_id: int = Path(gt=0),
    selection=Depends(filters),
    followup: Literal['ALL', 'ANSWERED', 'WAITING', 'UNREQUESTED'] = 'ALL',
    offset: int = Query(default=0, ge=0, le=1000000),
    limit: int = Query(default=15, ge=1, le=100),
    user=Depends(staff),
):
    return success(adjustment_report.detail(adjustment_id, selection, user, followup, offset, limit))


@router.get('/export.csv')
def export_csv(selection=Depends(filters), user=Depends(member)):
    content, count = reporting.csv_report(selection, user)
    return Response(
        content,
        media_type='text/csv',
        headers={
            'Content-Disposition': 'attachment; filename="emotion-feedback.csv"',
            'X-Export-Count': str(count),
        },
    )


@router.get('/workload')
def get_workload(
    selection=Depends(filters),
    period_days: int = Query(default=7, ge=7, le=60),
    period_end: date | None = None,
    user=Depends(staff),
):
    return success(workload.report(selection, user, period_days, period_end))


@router.get('/workload/export.csv')
def export_workload(
    selection=Depends(filters),
    period_days: int = Query(default=7, ge=7, le=60),
    period_end: date | None = None,
    user=Depends(staff),
):
    content, count = workload.export(selection, user, period_days, period_end)
    return Response(
        content,
        media_type='text/csv',
        headers={
            'Content-Disposition': 'attachment; filename="emotion-feedback-workload.csv"',
            'X-Export-Count': str(count),
        },
    )


@router.get('/cases/{case_id}/print.html')
def print_case(case_id: int = Path(gt=0), user=Depends(member)):
    return Response(
        reporting.case_report(case_id, user),
        media_type='text/html',
        headers={
            'Content-Disposition': f'attachment; filename="emotion-feedback-{case_id}.html"',
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'",
        },
    )
