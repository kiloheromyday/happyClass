import json
import time

from backend.app.repositories.database import connect

USER_COLUMNS = "id, username, password_hash, role, email, status, created_at"


def user_dict(row):
    return dict(zip(USER_COLUMNS.split(", "), row)) if row else None


def find_by_username(username: str):
    with connect() as connection:
        return user_dict(connection.execute(f"SELECT {USER_COLUMNS} FROM users WHERE username = ?", (username,)).fetchone())


def create_user(username, password_hash, role, email=None, actor_id=None):
    with connect() as connection:
        cursor = connection.execute("INSERT INTO users (username,password_hash,role,email) VALUES (?,?,?,?)", (username, password_hash, role, email))
        connection.execute("INSERT INTO audit_logs (actor_id,action,detail) VALUES (?,?,?)", (actor_id or cursor.lastrowid, "USER_CREATED", json.dumps({'user_id': cursor.lastrowid, 'role': role})))
        return user_dict(connection.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())


def create_session(user, digest, expires_at):
    with connect() as connection:
        connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (int(time.time()),))
        cursor = connection.execute("INSERT INTO auth_sessions (token_hash,user_id,expires_at) SELECT ?,id,? FROM users WHERE id=? AND password_hash=? AND status='ACTIVE'", (digest, expires_at, user["id"], user["password_hash"]))
        if cursor.rowcount != 1:
            return False
        connection.execute("INSERT INTO audit_logs (actor_id,action) VALUES (?,?)", (user["id"], "LOGIN"))
        return True


def find_by_session(digest):
    with connect() as connection:
        columns = ", ".join(f"u.{column}" for column in USER_COLUMNS.split(", "))
        row = connection.execute(f"SELECT {columns} FROM users u JOIN auth_sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>? AND u.status='ACTIVE'", (digest, int(time.time()))).fetchone()
        return user_dict(row)


def revoke_session(digest):
    with connect() as connection:
        row = connection.execute("SELECT user_id FROM auth_sessions WHERE token_hash=?", (digest,)).fetchone()
        connection.execute("DELETE FROM auth_sessions WHERE token_hash=?", (digest,))
        if row:
            connection.execute("INSERT INTO audit_logs (actor_id,action) VALUES (?,?)", (row[0], "LOGOUT"))


def change_password(user, new_hash):
    with connect() as connection:
        cursor = connection.execute("UPDATE users SET password_hash=? WHERE id=? AND password_hash=? AND status='ACTIVE'", (new_hash, user["id"], user["password_hash"]))
        if cursor.rowcount != 1:
            return False
        connection.execute("DELETE FROM auth_sessions WHERE user_id=?", (user["id"],))
        connection.execute("INSERT INTO audit_logs (actor_id,action) VALUES (?,?)", (user["id"], "PASSWORD_CHANGED"))
        return True


def consume_attempt(key, maximum, window_seconds):
    now = int(time.time())
    with connect() as connection:
        connection.execute("DELETE FROM auth_rate_limits WHERE reset_at <= ?", (now,))
        connection.execute("INSERT INTO auth_rate_limits (key,attempts,reset_at) VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET attempts=attempts+1", (key, now + window_seconds))
        attempts = connection.execute("SELECT attempts FROM auth_rate_limits WHERE key=?", (key,)).fetchone()[0]
        return attempts <= maximum


def reset_attempts(key):
    with connect() as connection:
        connection.execute("DELETE FROM auth_rate_limits WHERE key=?", (key,))


def record_login_failure(username):
    with connect() as connection:
        connection.execute("INSERT INTO audit_logs (action,detail) VALUES (?,?)", ("LOGIN_FAILED", json.dumps({"username": username}, ensure_ascii=False)))


def list_users(limit, offset):
    with connect() as connection:
        rows = connection.execute(f"SELECT {USER_COLUMNS} FROM users ORDER BY id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        count = connection.execute("SELECT count(*) FROM users").fetchone()[0]
        return [user_dict(row) for row in rows], count


def teacher_courses(user_id):
    with connect() as connection:
        return [{"id": row[0], "name": row[1]} for row in connection.execute("SELECT id,name FROM courses WHERE teacher_id=? ORDER BY id", (user_id,))]
