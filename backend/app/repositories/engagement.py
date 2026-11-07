from backend.app.repositories.classroom import one, rows


def question(connection, identifier):
    return one(connection.execute('SELECT * FROM classroom_questions WHERE id=?', (identifier,)))


def previous(connection, author_id, request_id):
    return one(connection.execute('SELECT * FROM classroom_questions WHERE author_id=? AND request_id=?', (author_id, request_id)))


def counts(connection, session_id):
    grouped = rows(connection.execute('SELECT category,status,count(*) AS count FROM classroom_questions WHERE session_id=? GROUP BY category,status', (session_id,)))
    return {'total': sum(item['count'] for item in grouped),
            'open': sum(item['count'] for item in grouped if item['status'] == 'OPEN'),
            'resolved': sum(item['count'] for item in grouped if item['status'] == 'RESOLVED'),
            'categories': [{'category': code, 'count': sum(item['count'] for item in grouped if item['category'] == code)} for code in ('PACE', 'EXAMPLE', 'REPEAT', 'OTHER')]}


def list_questions(connection, session_id, status='ALL', limit=12, offset=0):
    where, values = 'session_id=?', [session_id]
    if status != 'ALL':
        where += ' AND status=?'
        values.append(status)
    total = connection.execute(f'SELECT count(*) FROM classroom_questions WHERE {where}', values).fetchone()[0]
    items = rows(connection.execute(f'SELECT * FROM classroom_questions WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', [*values, limit, offset]))
    return items, total


def add_question(connection, session_id, user_id, payload, timestamp):
    identifier = connection.execute('INSERT INTO classroom_questions(session_id,author_id,request_id,category,text,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                                    (session_id, user_id, str(payload.request_id), payload.category, payload.text, timestamp, timestamp)).lastrowid
    return question(connection, identifier)


def reflection(connection, session_id):
    return one(connection.execute('SELECT reflection,version,updated_at FROM classroom_reflections WHERE session_id=?', (session_id,))) or {'reflection': '', 'version': 0, 'updated_at': None}


def emotion_counts(connection, session_id, start=None, end=None):
    where, values = 'session_id=?', [session_id]
    if start is not None:
        where += ' AND julianday(recorded_at)>=julianday(?) AND julianday(recorded_at)<julianday(?)'
        values += [start, end]
    return rows(connection.execute(f'SELECT emotion,count(*) AS count FROM emoji_records WHERE {where} GROUP BY emotion', values))
