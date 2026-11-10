import json

from backend.app.errors import AppError
from backend.app.services.classroom import accessible_session


def staff(user):
    if user['role'] not in ('TEACHER', 'ADMIN'):
        raise AppError(403, 'FORBIDDEN', '分析实验室仅面向任课教师和管理员')


def owned(connection, table, identifier, user):
    staff(user)
    allowed = {'lab_studies', 'lab_jobs', 'lab_reports'}
    if table not in allowed:
        raise ValueError('Unknown laboratory resource')
    cursor = connection.execute(
        f'SELECT * FROM {table} WHERE id=? AND owner_id=?',
        (identifier, user['id']),
    )
    row = cursor.fetchone()
    if row is None:
        raise AppError(404, 'LAB_NOT_FOUND', '分析资源不存在或不属于当前账号')
    return dict(zip((item[0] for item in cursor.description), row))


def authorize_sessions(connection, identifiers, user):
    staff(user)
    result = []
    for identifier in identifiers:
        result.append(accessible_session(connection, identifier, user))
    return result


def authorize_snapshot(connection, snapshot, user):
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    return authorize_sessions(connection, snapshot['session_ids'], user)


def study(connection, identifier, user):
    item = owned(connection, 'lab_studies', identifier, user)
    authorize_snapshot(connection, item['definition'], user)
    return item


def job(connection, identifier, user):
    item = owned(connection, 'lab_jobs', identifier, user)
    authorize_snapshot(connection, item['definition'], user)
    return item


def report(connection, identifier, user):
    item = owned(connection, 'lab_reports', identifier, user)
    authorize_snapshot(connection, item['definition'], user)
    return item
