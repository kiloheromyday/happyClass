from backend.app.repositories.classroom import one, rows

NOTE_SELECT = '''SELECT n.id,n.session_id,n.title,n.content,n.takeaway,n.next_step,n.reviewed,n.reviewed_at,
    n.version,n.created_at,n.updated_at,c.name AS course_name,s.class_name,s.starts_at AS session_starts_at
    FROM personal_notes n LEFT JOIN class_sessions s ON s.id=n.session_id LEFT JOIN courses c ON c.id=s.course_id'''


def owned(connection, user_id, note_id):
    return one(connection.execute(NOTE_SELECT + ' WHERE n.user_id=? AND n.id=?', (user_id, note_id)))


def choices(connection, user_id):
    return rows(connection.execute('''SELECT s.id,s.starts_at,s.ends_at,s.class_name,c.name AS course_name
        FROM class_sessions s JOIN courses c ON c.id=s.course_id WHERE
        EXISTS(SELECT 1 FROM schedule_users r WHERE r.session_id=s.id AND r.user_id=?) OR
        EXISTS(SELECT 1 FROM emoji_records e WHERE e.session_id=s.id AND e.user_id=? AND e.source='MANUAL') OR
        EXISTS(SELECT 1 FROM personal_notes n WHERE n.session_id=s.id AND n.user_id=?)
        ORDER BY s.starts_at DESC,s.id DESC''', (user_id, user_id, user_id)))


def may_link(connection, user_id, session_id):
    return connection.execute('''SELECT 1 FROM class_sessions s WHERE s.id=? AND (
        EXISTS(SELECT 1 FROM schedule_users r WHERE r.session_id=s.id AND r.user_id=?) OR
        EXISTS(SELECT 1 FROM emoji_records e WHERE e.session_id=s.id AND e.user_id=? AND e.source='MANUAL') OR
        EXISTS(SELECT 1 FROM personal_notes n WHERE n.session_id=s.id AND n.user_id=?))''', (session_id, user_id, user_id, user_id)).fetchone() is not None


def note_filter(user_id, q, session_id, review):
    where, values = 'n.user_id=?', [user_id]
    if session_id is not None:
        where += ' AND n.session_id=?'
        values.append(session_id)
    if review != 'ALL':
        where += ' AND n.reviewed=?'
        values.append(int(review == 'DONE'))
    if q:
        escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        where += " AND (n.title LIKE ? ESCAPE '\\' OR n.content LIKE ? ESCAPE '\\' OR n.takeaway LIKE ? ESCAPE '\\' OR n.next_step LIKE ? ESCAPE '\\')"
        values += ['%' + escaped + '%'] * 4
    return where, values


def listing(connection, user_id, q, session_id, review, limit, offset):
    where, values = note_filter(user_id, q, session_id, review)
    count = connection.execute('SELECT count(*) FROM personal_notes n WHERE ' + where, values).fetchone()[0]
    items = rows(connection.execute(NOTE_SELECT + ' WHERE ' + where + ' ORDER BY n.updated_at DESC,n.id DESC LIMIT ? OFFSET ?', [*values, limit, offset]))
    return items, count


def previous(connection, user_id, request_id):
    return one(connection.execute('SELECT note_id,payload_hash FROM personal_note_keys WHERE user_id=? AND request_id=?', (user_id, request_id)))


def add(connection, user_id, payload, timestamp, digest):
    identifier = connection.execute('''INSERT INTO personal_notes(user_id,session_id,title,content,takeaway,next_step,reviewed,reviewed_at,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)''', (user_id, payload.session_id, payload.title, payload.content, payload.takeaway, payload.next_step, int(payload.reviewed), timestamp if payload.reviewed else None, timestamp, timestamp)).lastrowid
    connection.execute('INSERT INTO personal_note_keys(user_id,request_id,note_id,payload_hash,created_at) VALUES (?,?,?,?,?)', (user_id, str(payload.request_id), identifier, digest, timestamp))
    return owned(connection, user_id, identifier)


def update(connection, user_id, note_id, payload, timestamp, reviewed_at):
    connection.execute('''UPDATE personal_notes SET session_id=?,title=?,content=?,takeaway=?,next_step=?,reviewed=?,reviewed_at=?,version=version+1,updated_at=?
        WHERE user_id=? AND id=?''', (payload.session_id, payload.title, payload.content, payload.takeaway, payload.next_step, int(payload.reviewed), reviewed_at, timestamp, user_id, note_id))
    return owned(connection, user_id, note_id)


def review_data(connection, user_id, start, end, session_id=None):
    interval = 'user_id=? AND source=\'MANUAL\' AND recorded_at>=? AND recorded_at<?'
    parameters = (user_id, start, end)
    session_clause = ' AND session_id=?' if session_id is not None else ''
    parameters += (session_id,) if session_id is not None else ()
    interval += session_clause
    summary = one(connection.execute(f'''SELECT count(*) AS feedback_count,count(DISTINCT substr(recorded_at,1,10)) AS active_days
        FROM emoji_records WHERE {interval}''', parameters))
    summary.update(one(connection.execute('''SELECT count(*) AS note_count,coalesce(sum(reviewed),0) AS reviewed_count
        FROM personal_notes WHERE user_id=? AND created_at>=? AND created_at<?''' + session_clause, parameters)))
    summary['pending_count'] = connection.execute('SELECT count(*) FROM personal_notes WHERE user_id=? AND reviewed=0' + session_clause, (user_id, *((session_id,) if session_id is not None else ()))).fetchone()[0]
    emotions = rows(connection.execute(f'SELECT emotion,count(*) AS count FROM emoji_records WHERE {interval} GROUP BY emotion', parameters))
    daily = rows(connection.execute(f'SELECT substr(recorded_at,1,10) AS day,count(*) AS total FROM emoji_records WHERE {interval} GROUP BY day ORDER BY day', parameters))
    sessions = rows(connection.execute('''WITH feedback AS (
        SELECT session_id,count(*) AS feedback_count FROM emoji_records WHERE user_id=? AND source='MANUAL' AND recorded_at>=? AND recorded_at<?''' + session_clause + ''' GROUP BY session_id
        ), notes AS (SELECT session_id,count(*) AS note_count FROM personal_notes WHERE user_id=? AND created_at>=? AND created_at<?''' + session_clause + ''' GROUP BY session_id)
        SELECT s.id,c.name AS course_name,s.class_name,s.starts_at,coalesce(f.feedback_count,0) AS feedback_count,coalesce(n.note_count,0) AS note_count
        FROM class_sessions s JOIN courses c ON c.id=s.course_id LEFT JOIN feedback f ON f.session_id=s.id LEFT JOIN notes n ON n.session_id=s.id
        WHERE f.session_id IS NOT NULL OR n.session_id IS NOT NULL ORDER BY s.starts_at DESC,s.id DESC LIMIT 10''', (*parameters, *parameters)))
    return summary, emotions, daily, sessions


def review_notes(connection, user_id, start, end, session_id=None):
    where, values = 'n.user_id=? AND n.created_at>=? AND n.created_at<?', [user_id, start, end]
    if session_id is not None:
        where += ' AND n.session_id=?'
        values.append(session_id)
    return rows(connection.execute(NOTE_SELECT + ' WHERE ' + where + ' ORDER BY n.updated_at DESC,n.id DESC LIMIT 6', values))


def day_data(connection, user_id, start, end, session_id, feedback_offset, notes_offset):
    where, values = 'user_id=? AND recorded_at>=? AND recorded_at<? AND source=\'MANUAL\'', [user_id, start, end]
    note_where, note_values = 'n.user_id=? AND n.created_at>=? AND n.created_at<?', [user_id, start, end]
    if session_id is not None:
        where += ' AND session_id=?'; values.append(session_id)
        note_where += ' AND n.session_id=?'; note_values.append(session_id)
    emotions = rows(connection.execute('SELECT emotion,count(*) AS count FROM emoji_records WHERE ' + where + ' GROUP BY emotion', values))
    records = rows(connection.execute('''SELECT e.id,e.session_id,e.emotion,e.recorded_at,c.name AS course_name,s.class_name
        FROM emoji_records e JOIN class_sessions s ON s.id=e.session_id JOIN courses c ON c.id=s.course_id
        WHERE e.id IN (SELECT id FROM emoji_records WHERE ''' + where + ' ORDER BY recorded_at DESC,id DESC LIMIT 12 OFFSET ?) ORDER BY e.recorded_at DESC,e.id DESC', [*values, feedback_offset]))
    note_count = connection.execute('SELECT count(*) FROM personal_notes n WHERE ' + note_where, note_values).fetchone()[0]
    notes = rows(connection.execute(NOTE_SELECT + ' WHERE ' + note_where + ' ORDER BY n.created_at DESC,n.id DESC LIMIT 12 OFFSET ?', [*note_values, notes_offset]))
    return emotions, records, note_count, notes
