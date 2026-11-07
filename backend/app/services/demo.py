import os
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from backend.app.errors import AppError
from backend.app.repositories import users
from backend.app.repositories.classroom import audit, one, rows
from backend.app.repositories.database import connect
from backend.app.security import hash_password, token_hash
from backend.app.services import auth

DEMO_COOKIE = 'classroom_developer'
DEMO_SECONDS = 8 * 3600
ACCOUNTS = {'demo_student': ('STUDENT', '演示学生'), 'demo_teacher': ('TEACHER', '演示教师'), 'demo_admin': ('ADMIN', '演示管理员')}
LOOPBACK = {'127.0.0.1', '::1', 'localhost'}


def enabled(request):
    # Both the network peer and the Host must be local; forwarded headers are ignored.
    return (os.getenv('EMOJI_DEMO_MODE', '0') == '1' and request.client is not None
            and request.client.host in LOOPBACK and request.url.hostname in LOOPBACK)


def require_local(request):
    if not enabled(request):
        raise AppError(404, 'NOT_FOUND', '演示开发者模式未开启')
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).hostname not in LOOPBACK:
        raise AppError(403, 'FORBIDDEN', '请从本地演示页面操作')


def access(request):
    require_local(request)
    token = request.cookies.get(DEMO_COOKIE)
    if token and len(token) <= 256:
        with connect() as connection:
            if connection.execute('SELECT 1 FROM demo_access_sessions WHERE token_hash=? AND expires_at>?', (token_hash(token), int(time.time()))).fetchone():
                return
    raise AppError(401, 'DEMO_EXPIRED', '开发者模式已关闭或过期，请重新开启')


def status(request):
    if not enabled(request):
        return {'enabled': False, 'active': False, 'accounts': []}
    try:
        access(request)
    except AppError:
        return {'enabled': True, 'active': False, 'accounts': []}
    available = []
    for username, (role, label) in ACCOUNTS.items():
        user = users.find_by_username(username)
        if user and user['role'] == role and user['status'] == 'ACTIVE':
            available.append({'username': username, 'role': role, 'label': label})
    return {'enabled': True, 'active': True, 'accounts': available}


def enable(request):
    require_local(request)
    auth.limit_attempt('demo-enable:' + request.client.host, 30, 3600)
    token = secrets.token_urlsafe(32)
    old = request.cookies.get(DEMO_COOKIE)
    with connect() as connection:
        connection.execute('DELETE FROM demo_access_sessions WHERE expires_at<=?', (int(time.time()),))
        if old:
            connection.execute('DELETE FROM demo_access_sessions WHERE token_hash=?', (token_hash(old),))
        connection.execute('INSERT INTO demo_access_sessions(token_hash,expires_at) VALUES (?,?)', (token_hash(token), int(time.time()) + DEMO_SECONDS))
        audit(connection, None, 'DEMO_ENABLED', {})
    return token


def disable(request):
    token = request.cookies.get(DEMO_COOKIE)
    with connect() as connection:
        if token:
            connection.execute('DELETE FROM demo_access_sessions WHERE token_hash=?', (token_hash(token),))
        audit(connection, None, 'DEMO_DISABLED', {})


def login(username):
    role, _ = ACCOUNTS[username]
    user = users.find_by_username(username)
    if not user or user['role'] != role or user['status'] != 'ACTIVE':
        raise AppError(409, 'DEMO_UNAVAILABLE', '此演示账号暂不可用，请选择其他演示账号')
    with connect() as connection:
        audit(connection, user['id'], 'DEMO_ACCOUNT_SWITCH', {'username': username})
    return user


MEMBER_SELECT = '''SELECT u.id,u.username,u.role,u.email,u.status,u.created_at,
    coalesce(p.nickname,'') AS nickname FROM users u LEFT JOIN user_profiles p ON p.user_id=u.id'''


def member_view(item):
    return {**item, 'protected': item['username'] in ACCOUNTS}


def members(q, role, status_filter, limit, offset):
    where, values = ["u.role IN ('STUDENT','TEACHER')"], []
    if q:
        # instr treats %, _ and backslash as ordinary text.
        where.append("(instr(lower(u.username),lower(?))>0 OR instr(lower(coalesce(p.nickname,'')),lower(?))>0 OR instr(lower(coalesce(u.email,'')),lower(?))>0)")
        values.extend([q]*3)
    if role != 'ALL':
        where.append('u.role=?'); values.append(role)
    if status_filter != 'ALL':
        where.append('u.status=?'); values.append(status_filter)
    clause = ' WHERE ' + ' AND '.join(where)
    with connect() as connection:
        connection.execute('BEGIN')
        count = connection.execute('SELECT count(*) FROM users u LEFT JOIN user_profiles p ON p.user_id=u.id' + clause, values).fetchone()[0]
        items = rows(connection.execute(MEMBER_SELECT + clause + ' ORDER BY u.id DESC LIMIT ? OFFSET ?', (*values, limit, offset)))
    return {'items': [member_view(item) for item in items], 'total': count, 'limit': limit, 'offset': offset}


def editable(connection, user_id):
    item = one(connection.execute(MEMBER_SELECT + ' WHERE u.id=?', (user_id,)))
    if not item or item['role'] not in ('STUDENT', 'TEACHER'):
        raise AppError(404, 'MEMBER_NOT_FOUND', '学生或教师成员不存在')
    if item['username'] in ACCOUNTS:
        raise AppError(409, 'DEMO_PROTECTED', '固定演示账号受保护，请管理其他成员')
    return item


def create_member(payload):
    auth.limit_attempt('demo-member-create', 60, 3600)
    if payload.username in ACCOUNTS:
        raise AppError(409, 'DEMO_PROTECTED', '该名称保留给固定演示账号')
    created = auth.provision_user(payload.username, payload.password, payload.role, payload.email)
    with connect() as connection:
        audit(connection, None, 'DEMO_MEMBER_CREATED', {'user_id': created['id'], 'role': created['role']})
        return member_view(one(connection.execute(MEMBER_SELECT + ' WHERE u.id=?', (created['id'],))))


def update_member(user_id, payload):
    try:
        with connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            item = editable(connection, user_id)
            if (item['email'], item['nickname']) != (payload.expected_email, payload.expected_nickname):
                raise AppError(409, 'MEMBER_CONFLICT', '成员资料已被修改，请刷新列表后重新编辑')
            connection.execute('UPDATE users SET email=? WHERE id=?', (payload.email, user_id))
            connection.execute('INSERT INTO user_profiles(user_id,nickname) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname', (user_id, payload.nickname))
            audit(connection, None, 'DEMO_MEMBER_UPDATED', {'user_id': user_id})
            return member_view(one(connection.execute(MEMBER_SELECT + ' WHERE u.id=?', (user_id,))))
    except sqlite3.IntegrityError as error:
        raise AppError(409, 'EMAIL_EXISTS', '邮箱已被其他成员使用') from error


def set_status(user_id, payload):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = editable(connection, user_id)
        if item['status'] != payload.expected_status:
            raise AppError(409, 'MEMBER_CONFLICT', '成员状态已变化，请刷新后再操作')
        connection.execute('UPDATE users SET status=? WHERE id=?', (payload.status, user_id))
        if payload.status == 'DISABLED':
            connection.execute('DELETE FROM auth_sessions WHERE user_id=?', (user_id,))
        audit(connection, None, 'DEMO_MEMBER_STATUS', {'user_id': user_id, 'status': payload.status})
        return member_view(one(connection.execute(MEMBER_SELECT + ' WHERE u.id=?', (user_id,))))


def reset_password(user_id, payload):
    auth.limit_attempt('demo-password-reset', 30, 900)
    password_hash = hash_password(payload.new_password)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        editable(connection, user_id)
        connection.execute('UPDATE users SET password_hash=? WHERE id=?', (password_hash, user_id))
        connection.execute('DELETE FROM auth_sessions WHERE user_id=?', (user_id,))
        audit(connection, None, 'DEMO_MEMBER_PASSWORD_RESET', {'user_id': user_id})
