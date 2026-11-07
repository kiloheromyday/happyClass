import json

from backend.app.errors import AppError


def previous_frame(connection, session_id, user_id, request_id, digest):
    row = connection.execute('SELECT frame_hash,result FROM ai_frame_keys WHERE actor_id=? AND session_id=? AND request_id=?', (user_id, session_id, str(request_id))).fetchone()
    if row:
        if row[0] != digest:
            raise AppError(409, 'REQUEST_ID_REUSED', '重复请求的图片不一致')
        return json.loads(row[1])


def add_predictions(connection, session_id, user_id, faces, recorded_at, device_id=None):
    for face in faces:
        connection.execute("INSERT INTO emoji_records (session_id,emotion,source,confidence,device_id,recorded_at) VALUES (?,?,'AI',?,?,?)", (session_id, face.emotion, face.confidence, device_id or f'web:{user_id}', recorded_at))


def remember_frame(connection, session_id, user_id, request_id, digest, result):
    connection.execute('INSERT INTO ai_frame_keys (actor_id,session_id,request_id,frame_hash,result) VALUES (?,?,?,?,?)', (user_id, session_id, str(request_id), digest, json.dumps(result)))


def previous_batch(connection, device_id, batch_id, digest):
    row = connection.execute('SELECT payload_hash,result FROM ai_batch_keys WHERE device_id=? AND batch_id=?', (device_id, str(batch_id))).fetchone()
    if row:
        if row[0] != digest:
            raise AppError(409, 'BATCH_ID_REUSED', '同一批次标识的内容不一致')
        return json.loads(row[1])


def remember_batch(connection, payload, digest, result):
    connection.execute('INSERT INTO ai_batch_keys (device_id,batch_id,session_id,payload_hash,result) VALUES (?,?,?,?,?)', (payload.device_id, str(payload.batch_id), payload.session_id, digest, json.dumps(result)))
