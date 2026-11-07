import secrets
import sqlite3
import time

from backend.app.errors import AppError
from backend.app.models.auth import RegisterRequest
from backend.app.repositories import users
from backend.app.repositories import profiles
from backend.app.security import DUMMY_PASSWORD_HASH, hash_password, token_hash, verify_password

SESSION_SECONDS = 8 * 60 * 60


def public_user(user):
    return {**{key: user[key] for key in ("id", "username", "role", "email", "status", "created_at")}, **profiles.get_profile(user['id'])}


def update_profile(user, payload):
    from backend.app.repositories.database import connect
    from backend.app.repositories.classroom import audit
    try:
        with connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            profiles.save_profile(connection, user['id'], payload)
            audit(connection, user['id'], 'PROFILE_UPDATED', {'fields': list(payload.model_fields_set)})
    except sqlite3.IntegrityError as error:
        raise AppError(409, 'EMAIL_EXISTS', '该邮箱已被使用，请更换邮箱') from error
    return public_user(users.find_by_username(user['username']))


def limit_attempt(key, maximum, seconds):
    if not users.consume_attempt(token_hash(key), maximum, seconds):
        raise AppError(429, "TOO_MANY_ATTEMPTS", "尝试次数过多，请稍后再试")


def provision_user(username, password, role, email, actor_id=None):
    # Local provisioning and registration must enforce the same account rules.
    payload = RegisterRequest(username=username, password=password, email=email)
    try:
        return users.create_user(payload.username, hash_password(payload.password), role, payload.email, actor_id=actor_id)
    except sqlite3.IntegrityError as error:
        raise AppError(409, "USER_EXISTS", "用户名或邮箱已被使用") from error


def register(payload, client_ip):
    limit_attempt(f"register:{client_ip}", 10, 3600)
    # The role is set on the server. Registration never accepts a caller-supplied role.
    return provision_user(payload.username, payload.password, "STUDENT", payload.email)


def login(payload, client_ip):
    limit_attempt(f"login-ip:{client_ip}", 60, 900)
    account_key = f"login-account:{client_ip}:{payload.username}"
    limit_attempt(account_key, 10, 900)
    user = users.find_by_username(payload.username)
    valid = verify_password(payload.password, user["password_hash"] if user else DUMMY_PASSWORD_HASH)
    if not valid or not user or user["status"] != "ACTIVE":
        users.record_login_failure(payload.username)
        raise AppError(401, "INVALID_CREDENTIALS", "用户名或密码不正确")
    users.reset_attempts(token_hash(account_key))
    return user


def issue_session(user):
    token = secrets.token_urlsafe(32)
    if not users.create_session(user, token_hash(token), int(time.time()) + SESSION_SECONDS):
        raise AppError(401, "SESSION_INVALID", "账号状态已变化，请重新登录")
    return token


def update_password(user, payload):
    limit_attempt(f"password:{user['id']}", 10, 900)
    if not verify_password(payload.current_password, user["password_hash"]):
        raise AppError(400, "WRONG_PASSWORD", "当前密码不正确")
    if payload.current_password == payload.new_password:
        raise AppError(400, "PASSWORD_UNCHANGED", "新密码需要与当前密码不同")
    if not users.change_password(user, hash_password(payload.new_password)):
        raise AppError(401, "SESSION_INVALID", "账号状态已变化，请重新登录")
