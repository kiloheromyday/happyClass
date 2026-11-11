import hashlib
import json

from backend.app.errors import AppError
from backend.app.repositories.classroom import one, rows

SESSION_JOIN = '''
    JOIN class_sessions s ON s.id=b.session_id
    JOIN courses c ON c.id=s.course_id
'''
BOOKMARK_SELECT = '''
    SELECT b.id,b.session_id,b.minute,b.reason,b.title,b.note,b.reviewed_at,
           b.version,b.created_at,b.updated_at,s.class_name,s.starts_at,c.name AS course_name
    FROM classroom_bookmarks b
''' + SESSION_JOIN


def bookmark(connection, identifier, student_id):
    return one(connection.execute(
        BOOKMARK_SELECT + ' WHERE b.id=? AND b.student_id=?',
        (identifier, student_id),
    ))


def list_bookmarks(connection, student_id, session_id, state, reason, term, order, limit, offset):
    conditions = [
        'b.student_id=?',
        'EXISTS(SELECT 1 FROM schedule_users su WHERE su.session_id=b.session_id AND su.user_id=b.student_id)',
    ]
    arguments = [student_id]
    if session_id is not None:
        conditions.append('b.session_id=?')
        arguments.append(session_id)
    if state == 'OPEN':
        conditions.append('b.reviewed_at IS NULL')
    elif state == 'REVIEWED':
        conditions.append('b.reviewed_at IS NOT NULL')
    if reason is not None:
        conditions.append('b.reason=?')
        arguments.append(reason)
    if term:
        conditions.append('(instr(lower(b.title),lower(?))>0 OR instr(lower(b.note),lower(?))>0)')
        arguments.extend((term, term))
    where = ' WHERE ' + ' AND '.join(conditions)
    count = one(connection.execute(
        'SELECT count(*) AS total FROM classroom_bookmarks b' + where,
        arguments,
    ))['total']
    sorts = {
        'RECENT': 'b.updated_at DESC,b.id DESC',
        'LESSON': 's.starts_at DESC,b.minute ASC,b.id ASC',
        'WITH_MATERIAL': '''EXISTS(
            SELECT 1 FROM bookmark_materials m
            WHERE m.session_id=b.session_id AND m.state='PUBLISHED'
              AND m.start_minute<=b.minute AND m.end_minute>b.minute
        ) DESC,s.starts_at DESC,b.minute ASC,b.id ASC''',
    }
    items = rows(connection.execute(
        BOOKMARK_SELECT + where + ' ORDER BY ' + sorts[order] + ' LIMIT ? OFFSET ?',
        (*arguments, limit, offset),
    ))
    return items, count


def student_totals(connection, student_id, session_id):
    conditions = [
        'b.student_id=?',
        'EXISTS(SELECT 1 FROM schedule_users su WHERE su.session_id=b.session_id AND su.user_id=b.student_id)',
    ]
    arguments = [student_id]
    if session_id is not None:
        conditions.append('b.session_id=?')
        arguments.append(session_id)
    return one(connection.execute(
        '''SELECT count(*) AS total,
                  count(b.reviewed_at) AS reviewed,
                  count(DISTINCT b.session_id) AS lessons
           FROM classroom_bookmarks b WHERE ''' + ' AND '.join(conditions),
        arguments,
    ))


def material(connection, identifier):
    return one(connection.execute(
        'SELECT * FROM bookmark_materials WHERE id=?',
        (identifier,),
    ))


def materials(connection, session_id, state=None, interval=None, student_id=None):
    params = []
    fields = 'm.*'
    join = ''
    if student_id is not None:
        fields += ',p.completed_at,p.material_version AS completed_version'
        join = '''
            LEFT JOIN bookmark_material_progress p
              ON p.material_id=m.id AND p.student_id=?
        '''
        params.append(student_id)
    where = ['m.session_id=?']
    params.append(session_id)
    if state is not None:
        where.append('m.state=?')
        params.append(state)
    if interval is not None:
        start, end = interval
        where.extend(('m.start_minute<?', 'm.end_minute>?'))
        params.extend((end, start))
    return rows(connection.execute(
        'SELECT ' + fields + ' FROM bookmark_materials m ' + join +
        ' WHERE ' + ' AND '.join(where) + ' ORDER BY m.start_minute,m.id DESC',
        params,
    ))


def published_for_bookmarks(connection, bookmarks, student_id):
    by_session = {}
    for item in bookmarks:
        session_id = item['session_id']
        if session_id not in by_session:
            by_session[session_id] = materials(
                connection, session_id, state='PUBLISHED', student_id=student_id,
            )
    return by_session


def count_bookmarks(connection, session_id):
    return connection.execute(
        'SELECT count(*) FROM classroom_bookmarks WHERE session_id=?',
        (session_id,),
    ).fetchone()[0]


def grouped_counts(connection, session_id, width, start=0, end=None):
    filters = ['session_id=?', 'minute>=?']
    params = [width, session_id, start]
    if end is not None:
        filters.append('minute<?')
        params.append(end)
    return rows(connection.execute(
        '''SELECT minute / ? AS bucket,reason,count(*) AS count
           FROM classroom_bookmarks
           WHERE ''' + ' AND '.join(filters) + ' GROUP BY bucket,reason ORDER BY bucket,reason',
        params,
    ))


def grouped_students(connection, session_id, width, end=None):
    clause = '' if end is None else ' AND minute<?'
    parameters = (width, session_id) if end is None else (width, session_id, end)
    return {
        item['bucket']: item['students']
        for item in rows(connection.execute(
            '''SELECT minute / ? AS bucket,count(DISTINCT student_id) AS students
               FROM classroom_bookmarks WHERE session_id=?''' + clause + ' GROUP BY bucket',
            parameters,
        ))
    }


def case_fingerprint(payload, session_id):
    data = payload.model_dump(mode='json', exclude={'request_id'})
    raw = json.dumps([session_id, data], sort_keys=True, ensure_ascii=False).encode('utf8')
    return hashlib.sha256(raw).hexdigest()


def previous_request(connection, user, payload, session_id, action):
    item = one(connection.execute(
        '''SELECT action,fingerprint,result_id FROM bookmark_request_keys
           WHERE actor_id=? AND request_id=?''',
        (user['id'], str(payload.request_id)),
    ))
    if not item:
        return None
    if item['action'] != action or item['fingerprint'] != case_fingerprint(payload, session_id):
        raise AppError(409, 'REQUEST_ID_REUSED', '请求编号已用过，请重新提交')
    return item['result_id']


def remember_request(connection, user, payload, session_id, action, result_id, stamp):
    connection.execute(
        '''INSERT INTO bookmark_request_keys(actor_id,request_id,action,fingerprint,result_id,created_at)
           VALUES (?,?,?,?,?,?)''',
        (user['id'], str(payload.request_id), action, case_fingerprint(payload, session_id), result_id, stamp),
    )
