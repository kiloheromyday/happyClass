from pydantic import ValidationError

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import audit, rows
from backend.app.repositories.database import connect
from backend.app.emotion.feedback import access, cases
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback import serialization as serial
from backend.app.emotion.feedback.models import Filters
from backend.app.emotion.feedback.workflow import require_version


def templates(user, archived=False):
    access.staff(user)
    with connect() as connection:
        items = rows(connection.execute(
            '''SELECT * FROM feedback_templates WHERE owner_id=? AND archived=?
            ORDER BY uses DESC,updated_at DESC,id DESC''',
            (user['id'], int(archived)),
        ))
        return {'items': [serial.template(item) for item in items]}


def save_template(payload, user, identifier=None):
    access.staff(user)
    operation = 'TEMPLATE_CREATE' if identifier is None else 'TEMPLATE_UPDATE'
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        existing = access.owned(connection, 'feedback_templates', identifier, user) if identifier else None
        previous = repo.previous(connection, user, payload, operation, identifier)
        if previous is not None:
            return previous
        stamp = utc_text(now_utc())
        if existing:
            require_version(existing, payload.version)
            connection.execute(
                '''UPDATE feedback_templates SET title=?,content=?,reason=?,archived=?,
                version=version+1,updated_at=? WHERE id=?''',
                (payload.title, payload.content, payload.reason, int(payload.archived), stamp, identifier),
            )
        else:
            if payload.version != 0:
                raise AppError(422, 'NEW_TEMPLATE_VERSION', '新模板的版本应为零')
            count = connection.execute(
                'SELECT count(*) FROM feedback_templates WHERE owner_id=?',
                (user['id'],),
            ).fetchone()[0]
            if count >= 100:
                raise AppError(409, 'TEMPLATE_LIMIT', '最多保存 100 条个人模板，请整理已有模板')
            identifier = connection.execute(
                '''INSERT INTO feedback_templates(owner_id,title,content,reason,archived,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?)''',
                (user['id'], payload.title, payload.content, payload.reason, int(payload.archived), stamp, stamp),
            ).lastrowid
        result = serial.template(access.owned(connection, 'feedback_templates', identifier, user))
        return repo.remember(connection, user, payload, operation, result, existing['id'] if existing else None)


def get_policy(course_id, user):
    with connect() as connection:
        course = access.course(connection, course_id, user)
        return {
            'course_id': course_id,
            'course_name': course['name'],
            'editable': user['role'] != 'STUDENT',
            **repo.policy(connection, course_id),
        }


def save_policy(course_id, payload, user):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        access.course(connection, course_id, user)
        previous = repo.previous(connection, user, payload, 'POLICY', course_id)
        if previous is not None:
            return previous
        current = repo.policy(connection, course_id)
        require_version(current, payload.version)
        stamp = utc_text(now_utc())
        connection.execute(
            '''INSERT INTO feedback_policies(
            course_id,response_hours,review_days,submit_grace_hours,daily_case_limit,reopen_days,version,updated_at)
            VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(course_id) DO UPDATE SET
            response_hours=excluded.response_hours,review_days=excluded.review_days,
            submit_grace_hours=excluded.submit_grace_hours,daily_case_limit=excluded.daily_case_limit,
            reopen_days=excluded.reopen_days,version=excluded.version,updated_at=excluded.updated_at''',
            (
                course_id, payload.response_hours, payload.review_days,
                payload.submit_grace_hours, payload.daily_case_limit,
                payload.reopen_days, current['version'] + 1, stamp,
            ),
        )
        audit(connection, user['id'], 'FEEDBACK_POLICY_UPDATED', {'course_id': course_id})
        result = {'course_id': course_id, **repo.policy(connection, course_id)}
        return repo.remember(connection, user, payload, 'POLICY', result, course_id)


def views(user):
    with connect() as connection:
        items = rows(connection.execute(
            'SELECT * FROM feedback_saved_views WHERE owner_id=? ORDER BY updated_at DESC,id DESC',
            (user['id'],),
        ))
        return {'items': [serial.saved_view(item) for item in items]}


def save_view(payload, user, identifier=None):
    operation = 'VIEW_CREATE' if identifier is None else 'VIEW_UPDATE'
    try:
        filters = Filters.model_validate(payload.filters)
    except ValidationError as error:
        raise AppError(422, 'INVALID_SAVED_FILTERS', '保存的筛选条件不合法') from error
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        existing = access.owned(connection, 'feedback_saved_views', identifier, user) if identifier else None
        cases.validate_filters(connection, filters, user)
        previous = repo.previous(connection, user, payload, operation, identifier)
        if previous is not None:
            return previous
        stamp = utc_text(now_utc())
        encoded = repo.encode(filters.model_dump(mode='json'))
        if existing:
            require_version(existing, payload.version)
            connection.execute(
                '''UPDATE feedback_saved_views SET title=?,filters=?,version=version+1,
                updated_at=? WHERE id=?''',
                (payload.title, encoded, stamp, identifier),
            )
        else:
            if payload.version != 0:
                raise AppError(422, 'NEW_VIEW_VERSION', '新视图的版本应为零')
            count = connection.execute(
                'SELECT count(*) FROM feedback_saved_views WHERE owner_id=?',
                (user['id'],),
            ).fetchone()[0]
            if count >= 30:
                raise AppError(409, 'VIEW_LIMIT', '最多保存 30 个筛选视图')
            identifier = connection.execute(
                '''INSERT INTO feedback_saved_views(owner_id,title,filters,created_at,updated_at)
                VALUES (?,?,?,?,?)''',
                (user['id'], payload.title, encoded, stamp, stamp),
            ).lastrowid
        result = serial.saved_view(access.owned(connection, 'feedback_saved_views', identifier, user))
        return repo.remember(connection, user, payload, operation, result, existing['id'] if existing else None)


def delete_view(identifier, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        previous = repo.previous(connection, user, payload, 'VIEW_DELETE', identifier)
        if previous is not None:
            return previous
        item = access.owned(connection, 'feedback_saved_views', identifier, user)
        require_version(item, payload.version)
        connection.execute('DELETE FROM feedback_saved_views WHERE id=?', (identifier,))
        result = {'id': identifier, 'deleted': True}
        return repo.remember(connection, user, payload, 'VIEW_DELETE', result, identifier)
