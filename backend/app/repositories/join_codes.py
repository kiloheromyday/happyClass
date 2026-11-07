from backend.app.repositories.classroom import one


def get(connection, session_id):
    return one(connection.execute('SELECT * FROM session_join_codes WHERE session_id=?', (session_id,)))


def by_code(connection, code):
    return one(connection.execute('SELECT * FROM session_join_codes WHERE code=?', (code,)))


def save(connection, session_id, code, expires_at, timestamp, user_id, request_id, digest):
    connection.execute('''INSERT INTO session_join_codes(session_id,code,enabled,expires_at,version,updated_at,created_by,last_request_id,last_payload_hash)
        VALUES (?,?,1,?,1,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET code=excluded.code,enabled=1,
        expires_at=excluded.expires_at,version=session_join_codes.version+1,updated_at=excluded.updated_at,
        created_by=excluded.created_by,last_request_id=excluded.last_request_id,last_payload_hash=excluded.last_payload_hash''',
        (session_id, code, expires_at, timestamp, user_id, request_id, digest))
    return get(connection, session_id)
