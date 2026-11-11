import csv
from io import StringIO

from backend.app.emotion.bookmarks import repository as repo, service
from backend.app.emotion.bookmarks.models import REASONS
from backend.app.errors import AppError
from backend.app.repositories.classroom import rows
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session
from backend.app.services.reports import safe_csv_cell

MAX_PERSONAL_EXPORT = 5000


def personal_export(user, session_id, state, reason, term, order):
    service.require_student(user)
    with connect() as connection:
        connection.execute('BEGIN')
        if session_id is not None:
            accessible_session(connection, session_id, user)
        items, count = repo.list_bookmarks(
            connection, user['id'], session_id, state, reason, term, order, MAX_PERSONAL_EXPORT, 0,
        )
        if count > MAX_PERSONAL_EXPORT:
            raise AppError(422, 'BOOKMARK_EXPORT_TOO_LARGE', '书签太多，请先按课堂或复习状态缩小范围')
        resources = repo.published_for_bookmarks(connection, items, user['id'])
        buffer = StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow([
            '课程', '班级', '开课时间 UTC', '开课后分钟', '原因', '标题', '我的笔记',
            '复习状态', '最近修改 UTC', '对应资料',
        ])
        for item in items:
            attached = [
                resource['title']
                for resource in resources[item['session_id']]
                if resource['start_minute'] <= item['minute'] < resource['end_minute']
            ]
            writer.writerow([safe_csv_cell(value) for value in (
                item['course_name'], item['class_name'], item['starts_at'], item['minute'],
                REASONS[item['reason']], item['title'], item['note'],
                '已复习' if item['reviewed_at'] else '待复习',
                item['updated_at'], '、'.join(attached),
            )])
        return '\ufeff' + buffer.getvalue()


def audience(connection, session_id):
    return connection.execute(
        '''SELECT count(*) FROM schedule_users su JOIN users u ON u.id=su.user_id
           WHERE su.session_id=? AND u.status='ACTIVE' AND u.role='STUDENT' ''',
        (session_id,),
    ).fetchone()[0]


def material_summary(connection, session_id):
    return rows(connection.execute(
        '''SELECT m.id,m.title,m.start_minute,m.end_minute,m.updated_at,m.published_at,
                  sum(CASE WHEN u.id IS NOT NULL AND p.material_version=m.version THEN 1 ELSE 0 END) AS read_current,
                  sum(CASE WHEN u.id IS NOT NULL AND p.material_version<>m.version THEN 1 ELSE 0 END) AS read_older
           FROM bookmark_materials m
           LEFT JOIN bookmark_material_progress p ON p.material_id=m.id
           LEFT JOIN schedule_users su ON su.user_id=p.student_id AND su.session_id=m.session_id
           LEFT JOIN users u ON u.id=su.user_id AND u.status='ACTIVE' AND u.role='STUDENT'
           WHERE m.session_id=? AND m.state='PUBLISHED'
           GROUP BY m.id ORDER BY m.start_minute,m.id''',
        (session_id,),
    ))


def distinct_readers(connection, session_id):
    return connection.execute(
        '''SELECT count(DISTINCT p.student_id)
           FROM bookmark_materials m
           JOIN bookmark_material_progress p ON p.material_id=m.id AND p.material_version=m.version
           JOIN schedule_users su ON su.user_id=p.student_id AND su.session_id=m.session_id
           JOIN users u ON u.id=su.user_id AND u.status='ACTIVE' AND u.role='STUDENT'
           WHERE m.session_id=? AND m.state='PUBLISHED' ''',
        (session_id,),
    ).fetchone()[0]


def report(session_id, user):
    service.require_teacher(user)
    with connect() as connection:
        connection.execute('BEGIN')
        session = accessible_session(connection, session_id, user)
        enrolled = audience(connection, session_id)
        materials = material_summary(connection, session_id)
        for item in materials:
            item['read_rate'] = round(100 * item['read_current'] / enrolled, 1) if enrolled else None
        return {
            'session': service.session_public(session),
            'items': materials,
            'summary': {
                'published': len(materials),
                'enrolled': enrolled,
                'read_at_least_one': distinct_readers(connection, session_id),
                'without_reads': sum(item['read_current'] == 0 for item in materials),
            },
        }


def export_report(session_id, user):
    data = report(session_id, user)
    buffer = StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow([
        '资料', '开始分钟', '结束分钟（不含）', '已看当前版', '只看过旧版',
        '当前课堂学生人数', '当前版阅读比例（%）', '发布时间 UTC', '更新时间 UTC',
    ])
    enrolled = data['summary']['enrolled']
    for item in data['items']:
        writer.writerow([safe_csv_cell(value) for value in (
            item['title'], item['start_minute'], item['end_minute'],
            item['read_current'], item['read_older'], enrolled,
            item['read_rate'], item['published_at'], item['updated_at'],
        )])
    return '\ufeff' + buffer.getvalue()
