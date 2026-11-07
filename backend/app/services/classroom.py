from datetime import datetime, timedelta
import hashlib
import json

from backend.app.errors import AppError
from backend.app.models.classroom import Emotion, now_utc, utc_text
from backend.app.repositories import classroom as repo
from backend.app.repositories.database import connect


def session_status(item):
    now = now_utc()
    start = datetime.fromisoformat(item['starts_at'])
    end = datetime.fromisoformat(item['ends_at'])
    return 'UPCOMING' if now < start else 'ENDED' if now >= end else 'ONGOING'


FEEDBACK_GRACE = timedelta(minutes=30)


def feedback_open(item, timestamp=None):
    timestamp = timestamp or now_utc()
    return datetime.fromisoformat(item['starts_at']) <= timestamp < datetime.fromisoformat(item['ends_at']) + FEEDBACK_GRACE


def session_view(item):
    return {**item, 'status': session_status(item), 'can_feedback': feedback_open(item),
            'feedback_closes_at': utc_text(datetime.fromisoformat(item['ends_at']) + FEEDBACK_GRACE)}


def accessible_session(connection, session_id, user):
    item = repo.get_session(connection, session_id)
    if item is None:
        raise AppError(404, 'SESSION_NOT_FOUND', '课堂不存在')
    if user['role'] == 'TEACHER' and item['teacher_id'] != user['id']:
        raise AppError(403, 'FORBIDDEN', '只能查看自己所授课程的课堂')
    if user['role'] == 'STUDENT' and not repo.is_scheduled(connection, session_id, user['id']):
        raise AppError(403, 'NOT_SCHEDULED', '你不在这节课堂的名单中')
    return item


def list_courses(user, data_scope='ALL'):
    with connect() as connection:
        return {'items': [item for item in repo.courses(connection, user) if data_scope == 'ALL' or bool(item['is_demo']) == (data_scope == 'DEMO')]}


def list_sessions(user, data_scope='ALL'):
    with connect() as connection:
        return {'items': [session_view(item) for item in repo.sessions(connection, user) if data_scope == 'ALL' or bool(item['is_demo']) == (data_scope == 'DEMO')]}


def course_detail(course_id, user):
    with connect() as connection:
        connection.execute('BEGIN')
        course = next((item for item in repo.courses(connection, user) if item['id'] == course_id), None)
        if course is None:
            # Do not reveal the existence of another user's course.
            raise AppError(404, 'COURSE_NOT_FOUND', '课程不存在或尚未加入')
        personal = repo.course_personal_counts(connection, course_id, user['id']) if user['role'] == 'STUDENT' else {}
        classrooms = []
        guide_flags = dict(connection.execute('SELECT g.session_id,g.published_at IS NOT NULL FROM classroom_guides g JOIN class_sessions s ON s.id=g.session_id WHERE s.course_id=?', (course_id,)))
        fields = ('id', 'course_id', 'course_name', 'teacher_name', 'starts_at', 'ends_at', 'classroom', 'class_name', 'department_id', 'department_name', 'department_short', 'department_color', 'department_background', 'is_demo')
        for raw in repo.sessions(connection, user, course_id):
            item = session_view({key: raw[key] for key in fields})
            item['guide_published'] = bool(guide_flags.get(raw['id'], False))
            if user['role'] == 'STUDENT':
                counts = personal.get(raw['id'], {})
                item['personal'] = {key: counts.get(key, 0) for key in ('feedback_count', 'note_count', 'pending_count')}
            else:
                item.update({key: raw[key] for key in ('scheduled_count', 'record_count')})
            classrooms.append(item)
        summary = {status.lower(): sum(item['status'] == status for item in classrooms) for status in ('UPCOMING', 'ONGOING', 'ENDED')}
        summary['total'] = len(classrooms)
        if user['role'] == 'STUDENT':
            summary.update({key: sum(item['personal'][key] for item in classrooms) for key in ('feedback_count', 'note_count', 'pending_count')})
            summary['participated_sessions'] = sum(item['personal']['feedback_count'] > 0 for item in classrooms)
        return {'course': course, 'sessions': classrooms, 'summary': summary}


def create_course(payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        request_id = getattr(payload, 'request_id', None)
        fields = {key: getattr(payload, key) for key in ('name', 'teacher_id', 'department_id')}
        payload_hash = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if request_id is not None:
            previous = connection.execute('SELECT course_id,payload_hash FROM course_creation_keys WHERE user_id=? AND request_id=?', (user['id'], str(request_id))).fetchone()
            if previous:
                if previous[1] != payload_hash:
                    raise AppError(409, 'REQUEST_ID_REUSED', '重复请求内容不一致，请重新填写课程')
                return repo.get_course(connection, previous[0])
        teacher = repo.get_user(connection, payload.teacher_id)
        if not teacher or teacher['role'] != 'TEACHER' or teacher['status'] != 'ACTIVE':
            raise AppError(422, 'INVALID_TEACHER', '请选择有效的教师账号')
        if payload.department_id and not connection.execute('SELECT 1 FROM departments WHERE id=?', (payload.department_id,)).fetchone():
            raise AppError(422, 'INVALID_DEPARTMENT', '请选择有效院系')
        item = repo.create_course(connection, payload)
        if request_id is not None:
            connection.execute('INSERT INTO course_creation_keys(user_id,request_id,course_id,payload_hash) VALUES (?,?,?,?)', (user['id'], str(request_id), item['id'], payload_hash))
        repo.audit(connection, user['id'], 'COURSE_CREATED', {'course_id': item['id']})
        return item


def create_session(payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        course = repo.get_course(connection, payload.course_id)
        if not course:
            raise AppError(404, 'COURSE_NOT_FOUND', '请选择有效课程')
        if user['role'] == 'TEACHER' and course['teacher_id'] != user['id']:
            raise AppError(403, 'FORBIDDEN', '只能为自己所授课程安排课堂')
        request_id = getattr(payload, 'request_id', None)
        payload_hash = None
        if request_id is not None:
            fields = {key: getattr(payload, key) for key in ('course_id', 'classroom', 'class_name')}
            fields.update(starts_at=utc_text(payload.starts_at), ends_at=utc_text(payload.ends_at))
            payload_hash = hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            previous = connection.execute('SELECT session_id,payload_hash FROM teaching_session_keys WHERE user_id=? AND request_id=?', (user['id'], str(request_id))).fetchone()
            if previous:
                if previous[1] != payload_hash:
                    raise AppError(409, 'REQUEST_ID_REUSED', '重复请求内容不一致，请重新填写课堂安排')
                return session_view(repo.get_session(connection, previous[0]))
        if course['archived']:
            raise AppError(409, 'COURSE_ARCHIVED', '课程已归档，请先在课程维护中恢复')
        if payload.ends_at <= now_utc():
            raise AppError(422, 'INVALID_SESSION_TIME', '新建课堂的结束时间应晚于当前时间')
        enrolled_count = connection.execute("SELECT count(*) FROM course_enrollments e JOIN users u ON u.id=e.user_id WHERE e.course_id=? AND u.status='ACTIVE' AND u.role='STUDENT'", (payload.course_id,)).fetchone()[0]
        if enrolled_count > 500:
            raise AppError(409, 'ROSTER_FULL', '这门课程的学生超过 500 人，请先调整课程安排')
        item = repo.create_session(connection, payload, utc_text(payload.starts_at), utc_text(payload.ends_at))
        connection.execute('''INSERT INTO schedule_users(session_id,user_id)
            SELECT ?,e.user_id FROM course_enrollments e JOIN users u ON u.id=e.user_id
            WHERE e.course_id=? AND u.role='STUDENT' AND u.status='ACTIVE' ''', (item['id'], payload.course_id))
        item = repo.get_session(connection, item['id'])
        if request_id is not None:
            connection.execute('INSERT INTO teaching_session_keys(user_id,request_id,session_id,payload_hash) VALUES (?,?,?,?)', (user['id'], str(request_id), item['id'], payload_hash))
        repo.audit(connection, user['id'], 'SESSION_CREATED', {'session_id': item['id']})
        return session_view(item)


def get_people():
    with connect() as connection:
        return {'items': repo.people(connection)}


def get_roster(session_id, user):
    with connect() as connection:
        accessible_session(connection, session_id, user)
        return {'items': repo.roster(connection, session_id)}


def replace_roster(session_id, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = accessible_session(connection, session_id, user)
        if session_status(item) == 'ENDED':
            raise AppError(409, 'SESSION_ENDED', '已结束课堂的名单不能修改')
        ids = list(dict.fromkeys(payload.user_ids))
        for user_id in ids:
            student = repo.get_user(connection, user_id)
            if not student or student['role'] != 'STUDENT' or student['status'] != 'ACTIVE':
                raise AppError(422, 'INVALID_STUDENT', '名单只能包含有效的学生账号；本次未保存')
        repo.replace_roster(connection, session_id, ids)
        repo.audit(connection, user['id'], 'ROSTER_REPLACED', {'session_id': session_id, 'student_count': len(ids)})
        return {'items': repo.roster(connection, session_id)}


def submit_emoji(payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        previous = repo.submission(connection, user['id'], str(payload.request_id))
        if previous:
            if previous['session_id'] != payload.session_id or previous['emotion'] != payload.emotion.value:
                raise AppError(409, 'REQUEST_ID_REUSED', '重复请求的内容不一致，请重新选择表情后提交')
            return previous, False
        item = accessible_session(connection, payload.session_id, user)
        timestamp = now_utc()
        if not feedback_open(item, timestamp):
            raise AppError(409, 'FEEDBACK_CLOSED', '请选择正在进行或结束后 30 分钟内的课堂评价')
        return repo.add_emoji(connection, user['id'], payload, utc_text(timestamp)), True


def get_history(user, session_id, limit, offset, data_scope='ALL'):
    with connect() as connection:
        if session_id is not None and user['role'] != 'STUDENT':
            accessible_session(connection, session_id, user)
        return repo.history(connection, user, session_id, limit, offset, data_scope)


def get_statistics(session_id, user, data_scope='ALL'):
    with connect() as connection:
        item = accessible_session(connection, session_id, user)
        grouped, summary = repo.statistics(connection, session_id, data_scope)
        counts = {row['emotion']: row['count'] for row in grouped}
        return {'session': session_view(item), **summary, 'emotions': [{'emotion': emotion.value, 'count': counts.get(emotion.value, 0)} for emotion in Emotion]}
