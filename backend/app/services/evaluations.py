import csv
import hashlib
import json
from io import StringIO

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories import classroom as repo
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session, feedback_open
from backend.app.services.reports import safe_csv_cell

FIELDS = ('clarity', 'pace', 'engagement', 'gain', 'comment')


def mine(session_id, user):
    with connect() as c:
        accessible_session(c, session_id, user)
        return {'item': repo.one(c.execute('SELECT clarity,pace,engagement,gain,comment,version,updated_at FROM course_evaluations WHERE session_id=? AND student_id=?', (session_id, user['id'])))}


def save(session_id, payload, user):
    signature = hashlib.sha256(json.dumps([session_id, payload.version, *[getattr(payload, key) for key in FIELDS]], ensure_ascii=False).encode()).hexdigest()
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        previous = c.execute('SELECT payload_hash,result FROM evaluation_keys WHERE student_id=? AND request_id=?', (user['id'], str(payload.request_id))).fetchone()
        if previous:
            if previous[0] != signature:
                raise AppError(409, 'REQUEST_ID_REUSED', '重试内容已改变，请重新提交')
            return json.loads(previous[1])
        session = accessible_session(c, session_id, user)
        if not feedback_open(session):
            raise AppError(409, 'FEEDBACK_CLOSED', '请在课堂进行中或结束后 30 分钟内评价')
        item = repo.one(c.execute('SELECT * FROM course_evaluations WHERE student_id=? AND session_id=?', (user['id'], session_id)))
        if payload.version != (item['version'] if item else 0):
            raise AppError(409, 'VERSION_CONFLICT', '评价已更新，草稿已保留；请放弃草稿后刷新')
        timestamp = utc_text(now_utc())
        c.execute('''INSERT INTO course_evaluations(session_id,student_id,clarity,pace,engagement,gain,comment,version,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,1,?,?) ON CONFLICT(session_id,student_id) DO UPDATE SET clarity=excluded.clarity,
            pace=excluded.pace,engagement=excluded.engagement,gain=excluded.gain,comment=excluded.comment,
            version=course_evaluations.version+1,updated_at=excluded.updated_at''', (session_id, user['id'], *[getattr(payload, key) for key in FIELDS], timestamp, timestamp))
        result = repo.one(c.execute('SELECT clarity,pace,engagement,gain,comment,version,updated_at FROM course_evaluations WHERE session_id=? AND student_id=?', (session_id, user['id'])))
        c.execute('INSERT INTO evaluation_keys(student_id,request_id,payload_hash,result) VALUES (?,?,?,?)', (user['id'], str(payload.request_id), signature, json.dumps(result, ensure_ascii=False)))
        repo.audit(c, user['id'], 'EVALUATION_SAVED', {'session_id': session_id})
        return result


def conditions(c, user, course_id, session_id, data_scope):
    parts, values = ['1=1'], []
    if user['role'] == 'TEACHER':
        parts.append('c.teacher_id=?'); values.append(user['id'])
    if course_id is not None:
        course = repo.get_course(c, course_id)
        if not course or (user['role'] == 'TEACHER' and course['teacher_id'] != user['id']):
            raise AppError(404, 'COURSE_NOT_FOUND', '课程不存在或不属于所授课程')
        parts.append('c.id=?'); values.append(course_id)
    if session_id is not None:
        accessible_session(c, session_id, user)
        parts.append('s.id=?'); values.append(session_id)
    if data_scope != 'ALL':
        parts.append('e.is_demo=?'); values.append(int(data_scope == 'DEMO'))
    return ' WHERE ' + ' AND '.join(parts), values


JOINS = ' FROM course_evaluations e JOIN class_sessions s ON s.id=e.session_id JOIN courses c ON c.id=s.course_id'


def report(user, course_id, session_id, data_scope, limit, offset):
    with connect() as c:
        c.execute('BEGIN')
        where, values = conditions(c, user, course_id, session_id, data_scope)
        summary = repo.one(c.execute('SELECT count(*) AS total,' + ','.join(f'round(avg(e.{key}),2) AS {key}' for key in FIELDS[:-1]) + JOINS + where, values))
        # Anonymous report: no student IDs, usernames, request keys or per-person timestamps.
        items = repo.rows(c.execute('SELECT c.name AS course_name,s.id AS session_id,s.starts_at,e.clarity,e.pace,e.engagement,e.gain,e.comment,e.is_demo' + JOINS + where + ' ORDER BY s.starts_at DESC,e.id DESC LIMIT ? OFFSET ?', [*values, limit, offset]))
        by_course = repo.rows(c.execute('SELECT c.id AS course_id,c.name AS course_name,count(*) AS total,round(avg((e.clarity+e.pace+e.engagement+e.gain)/4.0),2) AS average' + JOINS + where + ' GROUP BY c.id ORDER BY c.name', values))
        return {'summary': summary, 'items': items, 'by_course': by_course, 'total': summary['total'], 'limit': limit, 'offset': offset, 'data_scope': data_scope}


def export(user, course_id, session_id, data_scope):
    data = report(user, course_id, session_id, data_scope, 10001, 0)
    if data['total'] > 10000:
        raise AppError(422, 'EXPORT_TOO_LARGE', '评价导出最多 10000 条，请缩小课程范围')
    buffer = StringIO(newline=''); writer = csv.writer(buffer)
    writer.writerow(['课程', '课堂ID', '上课时间UTC', '讲解清晰', '节奏合适', '课堂互动', '学习收获', '匿名建议', '演示数据'])
    for item in data['items']:
        writer.writerow([safe_csv_cell(item[key]) for key in ('course_name', 'session_id', 'starts_at', *FIELDS)] + ['是' if item['is_demo'] else '否'])
    return ('\ufeff' + buffer.getvalue()).encode('utf-8'), data['total']
