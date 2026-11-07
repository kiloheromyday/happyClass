from datetime import datetime

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories import leaves as repo
from backend.app.repositories.classroom import audit
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session
from backend.app.services.inbox import notify


def listing(user, status, course_id, session_id, limit, offset):
    with connect() as connection:
        connection.execute('BEGIN')
        return repo.listing(connection, user, status, course_id, session_id, limit, offset)


def create(payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        existing = connection.execute('SELECT id,session_id,category,reason FROM leave_requests WHERE student_id=? AND request_id=?', (user['id'], str(payload.request_id))).fetchone()
        if existing:
            if existing[1:] != (payload.session_id, payload.category, payload.reason):
                raise AppError(409, 'REQUEST_ID_REUSED', '重复请求内容不一致，请重新填写申请')
            return repo.get(connection, existing[0], user), False
        session = accessible_session(connection, payload.session_id, user)
        now = now_utc()
        if now >= datetime.fromisoformat(session['ends_at']):
            raise AppError(409, 'LEAVE_CLOSED', '课堂已结束，请选择未开始或进行中的课堂')
        if connection.execute("SELECT 1 FROM leave_requests WHERE student_id=? AND session_id=? AND status IN ('PENDING','APPROVED')", (user['id'], payload.session_id)).fetchone():
            raise AppError(409, 'LEAVE_EXISTS', '该课堂已有待审批或已批准的请假申请')
        timestamp = utc_text(now)
        identifier = connection.execute('INSERT INTO leave_requests(session_id,student_id,request_id,category,reason,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
            (payload.session_id, user['id'], str(payload.request_id), payload.category, payload.reason, timestamp, timestamp)).lastrowid
        audit(connection, user['id'], 'LEAVE_CREATED', {'leave_id': identifier, 'session_id': payload.session_id})
        notify(connection, session['teacher_id'], f'leave:{identifier}:created', 'LEAVE', '收到新的请假申请', f"{session['course_name']}有一份请假申请待审批。", 'leaves', payload.session_id, session['course_id'])
        return repo.get(connection, identifier, user), True


def cancel(identifier, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = repo.get(connection, identifier, user)
        if not item:
            raise AppError(404, 'LEAVE_NOT_FOUND', '请假申请不存在')
        if item['status'] == 'CANCELLED' and item['version'] == payload.version + 1:
            return item
        if item['status'] != 'PENDING' or item['version'] != payload.version:
            raise AppError(409, 'LEAVE_CONFLICT', '申请已被处理或更新，请刷新后查看')
        connection.execute("UPDATE leave_requests SET status='CANCELLED',version=version+1,updated_at=? WHERE id=?", (utc_text(now_utc()), identifier))
        audit(connection, user['id'], 'LEAVE_CANCELLED', {'leave_id': identifier})
        notify(connection, item['teacher_id'], f'leave:{identifier}:cancelled', 'LEAVE', '请假申请已撤回', f"{item['course_name']}的一份待审批申请已撤回。", 'leaves', item['session_id'], item['course_id'])
        return repo.get(connection, identifier, user)


def decide(identifier, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = repo.get(connection, identifier, user)
        if not item:
            raise AppError(404, 'LEAVE_NOT_FOUND', '请假申请不存在或不属于所授课程')
        if item['version'] == payload.version + 1 and item['status'] == payload.decision and item['reviewer_id'] == user['id'] and item['reply'] == payload.reply:
            return item
        if item['status'] != 'PENDING' or item['version'] != payload.version:
            raise AppError(409, 'LEAVE_CONFLICT', '申请已被处理或更新，请刷新后查看')
        timestamp = utc_text(now_utc())
        connection.execute('UPDATE leave_requests SET status=?,reply=?,reviewer_id=?,reviewed_at=?,version=version+1,updated_at=? WHERE id=?',
            (payload.decision, payload.reply, user['id'], timestamp, timestamp, identifier))
        audit(connection, user['id'], 'LEAVE_' + payload.decision, {'leave_id': identifier, 'session_id': item['session_id']})
        notify(connection, item['student_id'], f'leave:{identifier}:decision', 'LEAVE', '请假审批结果', f"{item['course_name']}的请假申请已{'同意' if payload.decision == 'APPROVED' else '驳回'}，进入申请查看回复。", 'leaves', item['session_id'], item['course_id'])
        return repo.get(connection, identifier, user)
