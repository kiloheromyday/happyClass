import csv
import hashlib
import io
import json
from datetime import UTC, datetime, time, timedelta

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories import notes as repo
from backend.app.repositories.database import connect
from backend.app.services.engagement import distribution
from backend.app.services.reports import safe_csv_cell


def view(item):
    return {**item, 'reviewed': bool(item['reviewed'])}


def get_owned(connection, user, note_id):
    item = repo.owned(connection, user['id'], note_id)
    if not item:
        raise AppError(404, 'NOTE_NOT_FOUND', '笔记不存在或已删除')
    return item


def validate_link(connection, user, session_id):
    if session_id is not None and not repo.may_link(connection, user['id'], session_id):
        raise AppError(403, 'NOTE_SESSION_FORBIDDEN', '只能关联已安排或自己曾有记录的课堂')


def sessions(user):
    with connect() as connection:
        return {'items': repo.choices(connection, user['id'])}


def listing(user, q, session_id, review, limit, offset):
    with connect() as connection:
        connection.execute('BEGIN')
        items, total = repo.listing(connection, user['id'], q.strip(), session_id, review, limit, offset)
        return {'items': [view(item) for item in items], 'total': total, 'limit': limit, 'offset': offset}


def create(payload, user):
    fields = payload.model_dump(exclude={'request_id'}, mode='json')
    digest = hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        previous = repo.previous(connection, user['id'], str(payload.request_id))
        if previous:
            if previous['payload_hash'] != digest:
                raise AppError(409, 'REQUEST_ID_REUSED', '重复请求的笔记内容不一致，请重新保存')
            if previous['note_id'] is None:
                raise AppError(410, 'NOTE_DELETED', '这次请求创建的笔记已删除，请重新新建')
            return view(get_owned(connection, user, previous['note_id'])), False
        validate_link(connection, user, payload.session_id)
        if connection.execute('SELECT count(*) FROM personal_notes WHERE user_id=?', (user['id'],)).fetchone()[0] >= 1000:
            raise AppError(409, 'NOTE_LIMIT', '个人笔记已达 1000 条，请先整理已有笔记')
        now = now_utc()
        attempts = connection.execute('SELECT count(*) FROM personal_note_keys WHERE user_id=? AND created_at>=?', (user['id'], utc_text(now - timedelta(hours=1)))).fetchone()[0]
        if attempts >= 30:
            raise AppError(429, 'NOTE_RATE_LIMIT', '这一小时已新建 30 条笔记，请稍后再试')
        return view(repo.add(connection, user['id'], payload, utc_text(now), digest)), True


def get(note_id, user):
    with connect() as connection:
        return view(get_owned(connection, user, note_id))


def update(note_id, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = get_owned(connection, user, note_id)
        if item['version'] != payload.version:
            raise AppError(409, 'VERSION_CONFLICT', '笔记已被更新，请先复制草稿，再重新打开最新版本')
        validate_link(connection, user, payload.session_id)
        timestamp = utc_text(now_utc())
        reviewed_at = (item['reviewed_at'] or timestamp) if payload.reviewed else None
        return view(repo.update(connection, user['id'], note_id, payload, timestamp, reviewed_at))


def delete(note_id, version, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = get_owned(connection, user, note_id)
        if item['version'] != version:
            raise AppError(409, 'VERSION_CONFLICT', '笔记已被更新，请重新打开后再删除')
        connection.execute('DELETE FROM personal_notes WHERE id=? AND user_id=?', (note_id, user['id']))


def review(user, days, session_id=None):
    end = now_utc()
    start = end - timedelta(days=days)
    with connect() as connection:
        connection.execute('BEGIN')
        summary, grouped, daily, sessions = repo.review_data(connection, user['id'], utc_text(start), utc_text(end), session_id)
        recent_notes = repo.review_notes(connection, user['id'], utc_text(start), utc_text(end), session_id)
    counts = {item['day']: item['total'] for item in daily}
    points, date = [], start.date()
    while date <= (end - timedelta(microseconds=1)).date():
        points.append({'timestamp': date.isoformat() + 'T00:00:00Z', 'total': counts.get(date.isoformat(), 0)})
        date += timedelta(days=1)
    return {'days': days, 'session_id': session_id, 'starts_at': utc_text(start), 'ends_at': utc_text(end), 'summary': summary, 'emotions': distribution(grouped), 'trend': points, 'sessions': sessions, 'recent_notes': [view(item) for item in recent_notes]}


def review_day(user, day, starts_at, ends_at, session_id, feedback_offset, notes_offset):
    if starts_at.utcoffset() is None or ends_at.utcoffset() is None:
        raise AppError(422, 'INVALID_REVIEW_WINDOW', '回顾时间需要包含时区，请刷新回顾后再试')
    start, end = starts_at.astimezone(UTC), ends_at.astimezone(UTC)
    if not timedelta(0) < end - start <= timedelta(days=90):
        raise AppError(422, 'INVALID_REVIEW_WINDOW', '回顾区间应在 90 天以内')
    day_start = datetime.combine(day, time.min, tzinfo=UTC)
    left, right = max(start, day_start), min(end, day_start + timedelta(days=1))
    if left >= right:
        raise AppError(422, 'DAY_OUTSIDE_REVIEW', '请选择当前回顾范围内的日期')
    with connect() as connection:
        connection.execute('BEGIN')
        grouped, records, note_count, notes = repo.day_data(connection, user['id'], utc_text(left), utc_text(right), session_id, feedback_offset, notes_offset)
    return {'day': day.isoformat(), 'session_id': session_id, 'starts_at': utc_text(left), 'ends_at': utc_text(right),
            'emotions': distribution(grouped),
            'feedback': {'items': records, 'total': sum(row['count'] for row in grouped), 'offset': feedback_offset, 'limit': 12},
            'notes': {'items': [view(item) for item in notes], 'total': note_count, 'offset': notes_offset, 'limit': 12}}


def export_review(user, days, session_id=None):
    from backend.app.services.engagement import EMOTIONS
    data = review(user, days, session_id)
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    def row(*values):
        writer.writerow([safe_csv_cell(value) for value in values])
    row('学生个人回顾', f'近 {days} 天', '课堂范围', session_id or '全部课堂与随记')
    row('开始时间（UTC，包含）', data['starts_at'], '结束时间（UTC，不包含）', data['ends_at'])
    row('本人手动反馈次数', data['summary']['feedback_count'], '记录天数（UTC）', data['summary']['active_days'])
    row('时段内新建笔记', data['summary']['note_count'], '其中当前已回顾', data['summary']['reviewed_count'])
    row('此课堂范围内全部待回顾笔记（不限时间）', data['summary']['pending_count'])
    row('感受', '次数')
    for item in data['emotions']:
        row(EMOTIONS[item['emotion']], item['count'])
    row('日期（UTC）', '手动反馈次数')
    for item in data['trend']:
        row(item['timestamp'][:10], item['total'])
    row('时段内笔记摘记（最近更新的最多 6 篇）', '关联课程', '我的收获', '下一步', '当前状态')
    for item in data['recent_notes']:
        row(item['title'], item['course_name'], item['takeaway'], item['next_step'], '已回顾' if item['reviewed'] else '待回顾')
    row('仅含本人记录，不包含匿名 AI；感受分布不代表心理诊断或教学评价。')
    return ('\ufeff' + buffer.getvalue()).encode('utf-8')


def export(user, q, session_id, review):
    with connect() as connection:
        connection.execute('BEGIN')
        items, total = repo.listing(connection, user['id'], q.strip(), session_id, review, 1000, 0)
        if total > 1000:
            raise AppError(409, 'EXPORT_LIMIT', '请缩小筛选范围后再导出')
        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow(['标题', '课程', '班级', '笔记正文', '我的收获', '下一步', '回顾状态', '回顾时间（UTC）', '创建时间（UTC）', '修改时间（UTC）'])
        for item in items:
            writer.writerow([safe_csv_cell(value) for value in [item['title'], item['course_name'], item['class_name'], item['content'], item['takeaway'], item['next_step'], '已回顾' if item['reviewed'] else '待回顾', item['reviewed_at'], item['created_at'], item['updated_at']]])
        return ('\ufeff' + buffer.getvalue()).encode('utf-8'), total
