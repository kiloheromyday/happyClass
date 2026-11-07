import csv
from datetime import datetime, timedelta
from io import StringIO

from backend.app.errors import AppError
from backend.app.models.classroom import Emotion, now_utc, utc_text
from backend.app.models.reports import ReportFilters
from backend.app.repositories import classroom, reports
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session, session_view

MAX_EXPORT_ROWS = 50_000


def resolve_filters(from_time=None, to_time=None, course_id=None, class_name=None, source=None, session_id=None, bucket='day', data_scope='ALL'):
    upper = to_time or now_utc()
    lower = from_time or upper - timedelta(days=7)
    if lower >= upper:
        raise AppError(422, 'INVALID_TIME_RANGE', '开始时间必须早于结束时间')
    maximum = 31 if bucket == 'hour' else 366
    if upper - lower > timedelta(days=maximum):
        raise AppError(422, 'TIME_RANGE_TOO_LARGE', f"按{'小时' if bucket == 'hour' else '天'}统计最多查询 {maximum} 天，请缩小范围")
    name = class_name.strip() if class_name is not None else None
    if name == '':
        raise AppError(422, 'INVALID_CLASS_NAME', '班级名称不能为空白')
    return ReportFilters(lower, upper, course_id, name, source, session_id, bucket, data_scope)


def authorize_filters(connection, user, filters):
    if filters.course_id is not None:
        course = classroom.get_course(connection, filters.course_id)
        if course is None:
            raise AppError(404, 'COURSE_NOT_FOUND', '课程不存在')
        if user['role'] == 'TEACHER' and course['teacher_id'] != user['id']:
            raise AppError(403, 'FORBIDDEN', '只能统计或导出自己所授课程的数据')
    if filters.session_id is not None:
        accessible_session(connection, filters.session_id, user)


def filter_view(filters):
    return {'from_time': utc_text(filters.from_time), 'to_time': utc_text(filters.to_time), 'course_id': filters.course_id, 'class_name': filters.class_name, 'source': filters.source, 'session_id': filters.session_id, 'bucket': filters.bucket, 'data_scope': filters.data_scope}


def emotion_view(grouped):
    counts = {item['emotion']: item['count'] for item in grouped}
    return [{'emotion': item.value, 'count': counts.get(item.value, 0)} for item in Emotion]


def floor_bucket(value, bucket):
    if bucket == 'day':
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value.replace(minute=0, second=0, microsecond=0)


def filled_trend(grouped, filters):
    # Buckets are UTC; query boundaries still apply exactly within the edge buckets.
    from datetime import UTC
    cursor = floor_bucket(filters.from_time.astimezone(UTC), filters.bucket)
    upper = filters.to_time.astimezone(UTC)
    step = timedelta(days=1) if filters.bucket == 'day' else timedelta(hours=1)
    by_time = {item['timestamp']: item for item in grouped}
    result = []
    while cursor < upper:
        timestamp = utc_text(cursor)
        result.append(by_time.get(timestamp, {'timestamp': timestamp, 'total': 0, 'manual_count': 0, 'ai_count': 0}))
        cursor += step
    return result


def statistics(user, filters):
    with connect() as connection:
        connection.execute('BEGIN')
        authorize_filters(connection, user, filters)
        return {'filters': filter_view(filters), 'updated_at': utc_text(now_utc()), 'summary': reports.summary(connection, user, filters), 'emotions': emotion_view(reports.emotions(connection, user, filters)), 'by_course': reports.dimensions(connection, user, filters, 'course'), 'by_class': reports.dimensions(connection, user, filters, 'class'), 'trend': filled_trend(reports.trend(connection, user, filters), filters)}


def realtime(user, session_id, data_scope='ALL'):
    now = now_utc()
    anchor = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0)
    lower = anchor - timedelta(minutes=55)
    filters = ReportFilters(lower, now, session_id=session_id, data_scope=data_scope)
    with connect() as connection:
        connection.execute('BEGIN')
        session = accessible_session(connection, session_id, user)
        grouped, summary = classroom.statistics(connection, session_id, data_scope)
        minute_rows = reports.trend(connection, user, filters, 'minute')
        buckets = {}
        for row in minute_rows:
            stamp = datetime.fromisoformat(row['timestamp'])
            stamp = utc_text(stamp.replace(minute=stamp.minute // 5 * 5, second=0, microsecond=0))
            target = buckets.setdefault(stamp, {'timestamp': stamp, 'total': 0, 'manual_count': 0, 'ai_count': 0})
            for key in ('total', 'manual_count', 'ai_count'):
                target[key] += row[key]
        trend = []
        for index in range(12):
            stamp = utc_text(lower + timedelta(minutes=5 * index))
            trend.append(buckets.get(stamp, {'timestamp': stamp, 'total': 0, 'manual_count': 0, 'ai_count': 0}))
        return {'updated_at': utc_text(now), 'session': session_view(session), 'summary': summary, 'emotions': emotion_view(grouped), 'trend': trend, 'data_scope': data_scope, 'window': {'from_time': utc_text(lower), 'to_time': utc_text(now), 'bucket_minutes': 5}, 'latest': classroom.history(connection, user, session_id, 10, 0, data_scope)['items']}


def safe_csv_cell(value):
    text = '' if value is None else str(value).replace('\x00', '')
    probe = text
    while probe and (probe[0].isspace() or ord(probe[0]) < 32 or probe[0] == '\ufeff'):
        probe = probe[1:]
    if probe.startswith(('=', '+', '-', '@', '＝', '＋', '－', '＠')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text


def export_csv(user, filters):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        authorize_filters(connection, user, filters)
        count = reports.summary(connection, user, filters)['total']
        if count > MAX_EXPORT_ROWS:
            raise AppError(422, 'EXPORT_TOO_LARGE', '导出最多支持 50000 条，请缩短时间范围或增加筛选条件')
        records = reports.export_records(connection, user, filters)
        buffer = StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow(['记录ID', '课程ID', '课程', '课堂ID', '班级', '教室', '用户ID', '用户名', '情绪', '来源', '置信度', '记录时间UTC', '演示数据'])
        fields = ('id', 'course_id', 'course_name', 'session_id', 'class_name', 'classroom', 'user_id', 'username', 'emotion', 'source', 'confidence', 'recorded_at')
        for record in records:
            writer.writerow([safe_csv_cell(record[field]) for field in fields] + ['是' if record['is_demo'] else '否'])
        classroom.audit(connection, user['id'], 'EXPORT_CSV', {'row_count': len(records), 'filters': filter_view(filters)})
        return ('\ufeff' + buffer.getvalue()).encode('utf-8'), len(records)
