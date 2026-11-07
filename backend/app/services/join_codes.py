import hashlib
import json
import secrets
from datetime import datetime, timedelta

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories import classroom as classroom_repo
from backend.app.repositories import join_codes as repo
from backend.app.repositories.database import connect
from backend.app.services.auth import limit_attempt
from backend.app.services.classroom import accessible_session, session_status, session_view

ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def code_view(item, session):
    if not item:
        return {'code': None, 'version': 0, 'expires_at': None, 'status': 'NONE', 'updated_at': None}
    status = 'CLOSED' if session_status(session) == 'ENDED' else 'DISABLED' if not item['enabled'] else 'EXPIRED' if datetime.fromisoformat(item['expires_at']) <= now_utc() else 'ACTIVE'
    return {**{key: item[key] for key in ('code', 'version', 'expires_at', 'updated_at')}, 'status': status}


def get(session_id, user):
    with connect() as connection:
        connection.execute('BEGIN')
        session = accessible_session(connection, session_id, user)
        return code_view(repo.get(connection, session_id), session)


def create(session_id, payload, user):
    digest = hashlib.sha256(json.dumps({'session_id': session_id, 'actor_id': user['id'], 'version': payload.version, 'ttl_minutes': payload.ttl_minutes}, sort_keys=True).encode()).hexdigest()
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        session = accessible_session(connection, session_id, user)
        old = repo.get(connection, session_id)
        if old and old['last_request_id'] == str(payload.request_id):
            if old['last_payload_hash'] != digest:
                raise AppError(409, 'REQUEST_ID_REUSED', '重复请求的加入码设置不一致，请重新操作')
            return code_view(old, session)
        if (old['version'] if old else 0) != payload.version:
            raise AppError(409, 'VERSION_CONFLICT', '加入码已被更新，请刷新后再操作')
        if session_status(session) == 'ENDED':
            raise AppError(409, 'SESSION_ENDED', '已结束的课堂不能生成加入码')
        timestamp = now_utc()
        expires = min(timestamp + timedelta(minutes=payload.ttl_minutes), datetime.fromisoformat(session['ends_at']))
        for _ in range(10):
            code = ''.join(secrets.choice(ALPHABET) for _ in range(8))
            if not repo.by_code(connection, code):
                break
        else:
            raise AppError(503, 'CODE_BUSY', '暂时无法生成加入码，请稍后重试')
        item = repo.save(connection, session_id, code, utc_text(expires), utc_text(timestamp), user['id'], str(payload.request_id), digest)
        classroom_repo.audit(connection, user['id'], 'JOIN_CODE_ROTATED', {'session_id': session_id, 'version': item['version'], 'expires_at': item['expires_at']})
        return code_view(item, session)


def revoke(session_id, version, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        session = accessible_session(connection, session_id, user)
        old = repo.get(connection, session_id)
        if not old or old['version'] != version:
            raise AppError(409, 'VERSION_CONFLICT', '加入码已被更新，请刷新后再操作')
        if old['enabled']:
            connection.execute('UPDATE session_join_codes SET enabled=0,version=version+1,updated_at=? WHERE session_id=?', (utc_text(now_utc()), session_id))
            classroom_repo.audit(connection, user['id'], 'JOIN_CODE_REVOKED', {'session_id': session_id})
        return code_view(repo.get(connection, session_id), session)


def join(payload, user, client_ip):
    limit_attempt(f'class-join-user:{user["id"]}', 12, 300)
    limit_attempt(f'class-join-ip:{client_ip}', 60, 300)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        code = repo.by_code(connection, payload.code)
        session = classroom_repo.get_session(connection, code['session_id']) if code else None
        if not code or not session or code_view(code, session)['status'] != 'ACTIVE':
            raise AppError(404, 'JOIN_CODE_INVALID', '加入码无效、已停用或已过期，请向老师确认')
        if classroom_repo.get_course(connection, session['course_id'])['archived']:
            raise AppError(409, 'COURSE_ARCHIVED', '课程已归档，暂不接受新增成员')
        enrolled = connection.execute('SELECT 1 FROM course_enrollments WHERE course_id=? AND user_id=?', (session['course_id'], user['id'])).fetchone() is not None
        # Existing and future classes are arranged once, when adding the course.
        targets = connection.execute('SELECT id FROM class_sessions WHERE course_id=? AND ends_at>?', (session['course_id'], utc_text(now_utc()))).fetchall()
        for (identifier,) in targets:
            target = classroom_repo.get_session(connection, identifier)
            if not classroom_repo.is_scheduled(connection, identifier, user['id']):
                if target['scheduled_count'] >= 500:
                    raise AppError(409, 'ROSTER_FULL', '课程中的课堂名单已达 500 人，请联系老师')
                connection.execute('INSERT INTO schedule_users(session_id,user_id) VALUES (?,?)', (identifier, user['id']))
        connection.execute('INSERT OR IGNORE INTO course_enrollments(course_id,user_id,joined_at) VALUES (?,?,?)', (session['course_id'], user['id'], utc_text(now_utc())))
        if not enrolled:
            classroom_repo.audit(connection, user['id'], 'COURSE_JOINED_BY_CODE', {'course_id': session['course_id'], 'session_id': session['id']})
        return {'session': session_view(classroom_repo.get_session(connection, session['id'])), 'joined': not enrolled}
