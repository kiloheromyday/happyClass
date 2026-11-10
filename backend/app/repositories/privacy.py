"""Presentation privacy; personal history and internal ownership stay intact."""
from backend.app.errors import AppError


def policy(connection, session_id):
    row = connection.execute('SELECT mode,version,updated_at FROM session_privacy WHERE session_id=?', (session_id,)).fetchone()
    return {'session_id': session_id, 'mode': row[0] if row else 'STANDARD', 'version': row[1] if row else 0, 'updated_at': row[2] if row else None}


def protect_records(connection, records, user):
    if user['role'] == 'STUDENT':
        return records
    modes = {}
    result = []
    for record in records:
        session_id = record['session_id']
        if session_id not in modes:
            modes[session_id] = policy(connection, session_id)['mode']
        if modes[session_id] == 'AGGREGATE':
            continue
        if modes[session_id] == 'ANONYMOUS':
            record = {**record, 'user_id': None, 'username': None, 'device_id': None}
        result.append(record)
    return result


def require_detail_export(connection, records):
    if any(policy(connection, item['session_id'])['mode'] == 'AGGREGATE' for item in records):
        raise AppError(409, 'AGGREGATE_ONLY', '所选范围包含仅聚合课堂，请缩小范围或使用反馈隐私页的聚合导出')
