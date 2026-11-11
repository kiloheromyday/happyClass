from datetime import timedelta
import hashlib
import json

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import one, rows
from backend.app.emotion.feedback.workflow import DEFAULT_POLICY

JOIN = ''' FROM feedback_cases f
JOIN class_sessions s ON s.id=f.session_id
JOIN courses c ON c.id=s.course_id'''
SELECT = '''SELECT f.*,s.course_id,s.class_name,s.classroom,s.starts_at,s.ends_at,
c.name AS course_name,c.teacher_id''' + JOIN


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(payload, resource=None):
    content = payload.model_dump(mode='json', exclude={'request_id'})
    return hashlib.sha256(encode({'resource': resource, 'payload': content}).encode()).hexdigest()


def previous(connection, user, payload, operation, resource=None):
    item = one(connection.execute(
        'SELECT operation,payload_hash,result FROM feedback_commands WHERE actor_id=? AND request_id=?',
        (user['id'], str(payload.request_id)),
    ))
    if item is None:
        return None
    if item['operation'] != operation or item['payload_hash'] != digest(payload, resource):
        raise AppError(409, 'REQUEST_ID_REUSED', '请求编号已使用；重复请求必须保持内容和操作一致')
    return json.loads(item['result'])


def remember(connection, user, payload, operation, result, resource=None):
    connection.execute(
        '''INSERT INTO feedback_commands(actor_id,request_id,operation,payload_hash,result,created_at)
        VALUES (?,?,?,?,?,?)''',
        (user['id'], str(payload.request_id), operation, digest(payload, resource), encode(result), utc_text(now_utc())),
    )
    return result


def policy(connection, course_id):
    item = one(connection.execute('SELECT * FROM feedback_policies WHERE course_id=?', (course_id,)))
    if item:
        item.pop('course_id')
    return item or dict(DEFAULT_POLICY)


def case(connection, identifier):
    return one(connection.execute(SELECT + ' WHERE f.id=?', (identifier,)))


def scope(user):
    if user['role'] == 'STUDENT':
        return ['f.author_id=?'], [user['id']]
    if user['role'] == 'TEACHER':
        return ['c.teacher_id=?'], [user['id']]
    return ['1=1'], []


def filtered(user, filters):
    conditions, values = scope(user)
    for key, column in (('course_id', 's.course_id'), ('session_id', 'f.session_id')):
        value = getattr(filters, key)
        if value is not None:
            conditions.append(column + '=?')
            values.append(value)
    for key in ('state', 'priority', 'emotion'):
        value = getattr(filters, key)
        if value != 'ALL':
            conditions.append('f.' + key + '=?')
            values.append(value)
    if filters.reason != 'ALL':
        conditions.append('EXISTS(SELECT 1 FROM json_each(f.reasons) WHERE value=?)')
        values.append(filters.reason)
    if filters.search:
        conditions.append('(instr(lower(f.title),lower(?))>0 OR instr(lower(f.content),lower(?))>0)')
        values.extend([filters.search, filters.search])
    if filters.watched:
        conditions.append('EXISTS(SELECT 1 FROM feedback_watches w WHERE w.case_id=f.id AND w.user_id=?)')
        values.append(user['id'])
    if filters.data_scope != 'ALL':
        conditions.append('f.is_demo=?')
        values.append(int(filters.data_scope == 'DEMO'))
    if filters.overdue:
        conditions.append("f.state='NEW' AND f.acknowledged_at IS NULL AND julianday(f.created_at)+coalesce((SELECT response_hours FROM feedback_policies p WHERE p.course_id=c.id),24)/24.0<julianday(?)")
        values.append(utc_text(now_utc()))
    if filters.active_only:
        conditions.append("f.state NOT IN ('RESOLVED','WITHDRAWN')")
    if filters.review_overdue:
        conditions.append(
            """EXISTS (
                SELECT 1 FROM feedback_reviews r
                WHERE r.case_id=f.id AND r.state='OPEN' AND r.due_at<?
            )"""
        )
        values.append(utc_text(now_utc()))
    return ' WHERE ' + ' AND '.join(conditions), values


def listing(connection, user, filters, offset, limit):
    where, values = filtered(user, filters)
    count = connection.execute('SELECT count(*)' + JOIN + where, values).fetchone()[0]
    orders = {
        'UPDATED': 'f.updated_at DESC,f.id DESC',
        'CREATED': 'f.created_at DESC,f.id DESC',
        'OLDEST': 'f.created_at,f.id',
        'PRIORITY': "CASE f.priority WHEN 'HIGH' THEN 0 ELSE 1 END,f.created_at,f.id",
    }
    items = rows(connection.execute(
        SELECT + where + ' ORDER BY ' + orders[filters.sort] + ' LIMIT ? OFFSET ?',
        (*values, limit, offset),
    ))
    return items, count


def event(connection, item, user, code, detail='', to_state=None, visibility='SHARED'):
    connection.execute(
        '''INSERT INTO feedback_events(case_id,actor_id,actor_role,code,from_state,to_state,detail,visibility,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (item['id'], user['id'], user['role'], code, item['state'], to_state or item['state'], detail, visibility, utc_text(now_utc())),
    )


def bump(connection, identifier, state=None):
    if state is None:
        connection.execute('UPDATE feedback_cases SET version=version+1,updated_at=? WHERE id=?', (utc_text(now_utc()), identifier))
    else:
        connection.execute('UPDATE feedback_cases SET state=?,version=version+1,updated_at=? WHERE id=?', (state, utc_text(now_utc()), identifier))


def messages(connection, identifier, user, before_id=None, limit=50):
    conditions = ['case_id=?']
    values = [identifier]
    if user['role'] == 'STUDENT':
        conditions.append("visibility='SHARED'")
    if before_id is not None:
        conditions.append('id<?')
        values.append(before_id)
    return rows(connection.execute(
        'SELECT * FROM feedback_messages WHERE ' + ' AND '.join(conditions) + ' ORDER BY id DESC LIMIT ?',
        (*values, limit),
    ))


def events(connection, identifier, user, before_id=None, limit=100):
    conditions = ['case_id=?']
    values = [identifier]
    if user['role'] == 'STUDENT':
        conditions.append("visibility='SHARED'")
    if before_id:
        conditions.append('id<?')
        values.append(before_id)
    return rows(connection.execute(
        'SELECT * FROM feedback_events WHERE ' + ' AND '.join(conditions) + ' ORDER BY id DESC LIMIT ?',
        (*values, limit),
    ))


def add_message(connection, item, user, content, visibility='SHARED'):
    timestamp = utc_text(now_utc())
    cursor = connection.execute(
        '''INSERT INTO feedback_messages(case_id,actor_id,actor_role,visibility,content,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?)''',
        (item['id'], user['id'], user['role'], visibility, content, timestamp, timestamp),
    )
    return one(connection.execute('SELECT * FROM feedback_messages WHERE id=?', (cursor.lastrowid,)))


def reviews(connection, identifier):
    return rows(connection.execute(
        '''SELECT r.*,a.outcome,a.emotion AS answer_emotion,a.content AS answer_content,a.created_at AS answered_at
        FROM feedback_reviews r LEFT JOIN feedback_review_answers a ON a.review_id=r.id
        WHERE r.case_id=? ORDER BY r.id DESC''',
        (identifier,),
    ))


def add_review(connection, item, user, prompt, days):
    timestamp = now_utc()
    identifier = connection.execute(
        'INSERT INTO feedback_reviews(case_id,prompt,due_at,opened_by,created_at) VALUES (?,?,?,?,?)',
        (item['id'], prompt, utc_text(timestamp+timedelta(days=days)), user['id'], utc_text(timestamp)),
    ).lastrowid
    return identifier


def open_review(connection, identifier):
    return one(connection.execute("SELECT * FROM feedback_reviews WHERE case_id=? AND state='OPEN'", (identifier,)))


def notify(connection, item, user, code, title):
    session = one(connection.execute(
        'SELECT c.teacher_id FROM class_sessions s JOIN courses c ON c.id=s.course_id WHERE s.id=?',
        (item['session_id'],),
    ))
    recipients = {item['author_id']} if user['role'] != 'STUDENT' else {session['teacher_id']}
    recipients.update(row[0] for row in connection.execute('SELECT user_id FROM feedback_watches WHERE case_id=?', (item['id'],)))
    recipients.discard(user['id'])
    sequence = connection.execute('SELECT coalesce(max(id),0) FROM feedback_events WHERE case_id=?', (item['id'],)).fetchone()[0]
    for identifier in recipients:
        if identifier != item['author_id']:
            role = one(connection.execute('SELECT role,status FROM users WHERE id=?', (identifier,)))
            if not role or role['status'] != 'ACTIVE':
                continue
            if role['role'] == 'TEACHER' and identifier != session['teacher_id']:
                continue
            if role['role'] not in ('TEACHER', 'ADMIN'):
                continue
        connection.execute(
            '''INSERT OR IGNORE INTO feedback_inbox(user_id,case_id,event_key,code,title,created_at)
            VALUES (?,?,?,?,?,?)''',
            (identifier, item['id'], f'{item["id"]}:{sequence}:{code}', code, title, utc_text(now_utc())),
        )


def visible_adjustments(connection, identifier):
    return rows(connection.execute(
        '''SELECT l.adjustment_id,l.public_summary,l.created_at,e.title,e.start_minute,e.status
        FROM feedback_adjustments l JOIN emotion_insight_entries e ON e.id=l.adjustment_id
        WHERE l.case_id=? ORDER BY l.created_at,l.adjustment_id''',
        (identifier,),
    ))


def group_members(connection, identifier):
    return rows(connection.execute(
        SELECT + ' JOIN feedback_group_members m ON m.case_id=f.id WHERE m.group_id=? ORDER BY f.created_at,f.id',
        (identifier,),
    ))


def groups(connection, user, session_id=None, archived=False):
    conditions, values = [], []
    if user['role'] == 'TEACHER':
        conditions.append('c.teacher_id=?')
        values.append(user['id'])
    if session_id is not None:
        conditions.append('g.session_id=?')
        values.append(session_id)
    conditions.append('g.archived=?')
    values.append(int(archived))
    return rows(connection.execute(
        '''SELECT g.*,c.name AS course_name,s.class_name,
        (SELECT count(*) FROM feedback_group_members m WHERE m.group_id=g.id) AS member_count
        FROM feedback_groups g JOIN class_sessions s ON s.id=g.session_id JOIN courses c ON c.id=s.course_id
        WHERE ''' + ' AND '.join(conditions) + ' ORDER BY g.updated_at DESC,g.id DESC LIMIT 100',
        values,
    ))
