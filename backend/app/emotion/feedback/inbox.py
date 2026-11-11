from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import rows
from backend.app.repositories.database import connect
from backend.app.emotion.feedback import access


def visible_where(user):
    condition = 'n.user_id=?'
    values = [user['id']]
    if user['role'] == 'TEACHER':
        condition += ' AND c.teacher_id=?'
        values.append(user['id'])
    elif user['role'] == 'STUDENT':
        condition += ' AND f.author_id=?'
        values.append(user['id'])
    return condition, values


JOIN = ''' FROM feedback_inbox n JOIN feedback_cases f ON f.id=n.case_id
JOIN class_sessions s ON s.id=f.session_id JOIN courses c ON c.id=s.course_id'''


def listing(user, unread_only=False, before_id=None, limit=30):
    with connect() as connection:
        condition, values = visible_where(user)
        unread_count = connection.execute(
            'SELECT count(*)' + JOIN + ' WHERE ' + condition + ' AND n.read_at IS NULL',
            values,
        ).fetchone()[0]
        if unread_only:
            condition += ' AND n.read_at IS NULL'
        if before_id is not None:
            condition += ' AND n.id<?'
            values.append(before_id)
        items = rows(connection.execute(
            '''SELECT n.id,n.case_id,n.code,n.title,n.created_at,n.read_at,
            f.session_id,c.name AS course_name,s.class_name''' + JOIN +
            ' WHERE ' + condition + ' ORDER BY n.id DESC LIMIT ?',
            (*values, limit + 1),
        ))
        has_more = len(items) > limit
        items = items[:limit]
        return {
            'items': items,
            'unread_count': unread_count,
            'has_more': has_more,
            'next_before_id': items[-1]['id'] if items and has_more else None,
        }


def mark(identifier, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = connection.execute(
            'SELECT case_id FROM feedback_inbox WHERE id=? AND user_id=?',
            (identifier, user['id']),
        ).fetchone()
        if item is None:
            raise AppError(404, 'NOTICE_NOT_FOUND', '通知不存在')
        access.case(connection, item[0], user)
        connection.execute(
            'UPDATE feedback_inbox SET read_at=coalesce(read_at,?) WHERE id=? AND user_id=?',
            (utc_text(now_utc()), identifier, user['id']),
        )
        return {'id': identifier, 'read': True}


def mark_all(user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        condition, values = visible_where(user)
        identifiers = [item[0] for item in connection.execute(
            'SELECT n.id' + JOIN + ' WHERE ' + condition + ' AND n.read_at IS NULL',
            values,
        )]
        connection.executemany(
            'UPDATE feedback_inbox SET read_at=? WHERE id=? AND user_id=?',
            [(utc_text(now_utc()), identifier, user['id']) for identifier in identifiers],
        )
        return {'marked_count': len(identifiers)}
