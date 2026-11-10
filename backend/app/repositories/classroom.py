import json
from backend.app.repositories.privacy import protect_records

DEPARTMENT_FIELDS = """c.department_id,d.name AS department_name,d.short_name AS department_short,
 coalesce(d.color,'#637a50') AS department_color,coalesce(d.background,'#f0f4e9') AS department_background"""
COURSE_SELECT = "SELECT c.*,coalesce(nullif(p.nickname,''),u.username) AS teacher_name," + DEPARTMENT_FIELDS.replace('c.department_id,', '') + " FROM courses c JOIN users u ON u.id=c.teacher_id LEFT JOIN user_profiles p ON p.user_id=u.id LEFT JOIN departments d ON d.id=c.department_id"
SESSION_SELECT = """SELECT s.*,c.name AS course_name,c.teacher_id,c.is_demo,
 coalesce(nullif(p.nickname,''),u.username) AS teacher_name,""" + DEPARTMENT_FIELDS + """,
 (SELECT count(*) FROM schedule_users r WHERE r.session_id=s.id) AS scheduled_count,
 (SELECT count(*) FROM emoji_records e WHERE e.session_id=s.id) AS record_count,
 coalesce((SELECT mode FROM session_privacy WHERE session_id=s.id),'STANDARD') AS privacy_mode
 FROM class_sessions s JOIN courses c ON c.id=s.course_id JOIN users u ON u.id=c.teacher_id
 LEFT JOIN user_profiles p ON p.user_id=u.id LEFT JOIN departments d ON d.id=c.department_id"""
RECORD_SELECT = """SELECT e.*,u.username,c.name AS course_name,s.class_name,s.classroom
 FROM emoji_records e JOIN class_sessions s ON s.id=e.session_id
 JOIN courses c ON c.id=s.course_id LEFT JOIN users u ON u.id=e.user_id"""


def rows(cursor):
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def one(cursor):
    result = rows(cursor)
    return result[0] if result else None


def get_course(connection, course_id):
    return one(connection.execute(COURSE_SELECT + ' WHERE c.id=?', (course_id,)))


def get_user(connection, user_id):
    return one(connection.execute('SELECT id,username,role,status FROM users WHERE id=?', (user_id,)))


def courses(connection, user):
    query = COURSE_SELECT
    values = ()
    if user['role'] == 'TEACHER':
        query += ' WHERE c.teacher_id=?'
        values = (user['id'],)
    elif user['role'] == 'STUDENT':
        query += ' WHERE EXISTS(SELECT 1 FROM course_enrollments e WHERE e.course_id=c.id AND e.user_id=?) OR EXISTS(SELECT 1 FROM class_sessions s JOIN schedule_users r ON r.session_id=s.id WHERE s.course_id=c.id AND r.user_id=?)'
        values = (user['id'], user['id'])
    return rows(connection.execute(query + ' ORDER BY c.id DESC', values))


def sessions(connection, user, course_id=None):
    query, values = SESSION_SELECT, ()
    if user['role'] == 'TEACHER':
        query += ' WHERE c.teacher_id=?'
        values = (user['id'],)
    elif user['role'] == 'STUDENT':
        query += ' WHERE EXISTS(SELECT 1 FROM schedule_users r WHERE r.session_id=s.id AND r.user_id=?)'
        values = (user['id'],)
    if course_id is not None:
        query += (' AND ' if values else ' WHERE ') + 's.course_id=?'
        values = (*values, course_id)
    return rows(connection.execute(query + ' ORDER BY s.starts_at DESC,s.id DESC', values))


def course_personal_counts(connection, course_id, user_id):
    feedback = rows(connection.execute('''SELECT e.session_id,count(*) AS feedback_count
        FROM emoji_records e JOIN class_sessions s ON s.id=e.session_id
        WHERE s.course_id=? AND e.user_id=? AND e.source='MANUAL' GROUP BY e.session_id''', (course_id, user_id)))
    notes = rows(connection.execute('''SELECT n.session_id,count(*) AS note_count,
        coalesce(sum(n.reviewed=0),0) AS pending_count
        FROM personal_notes n JOIN class_sessions s ON s.id=n.session_id
        WHERE s.course_id=? AND n.user_id=? GROUP BY n.session_id''', (course_id, user_id)))
    result = {row['session_id']: row for row in feedback}
    for row in notes:
        result.setdefault(row['session_id'], {}).update(row)
    return result


def get_session(connection, session_id):
    return one(connection.execute(SESSION_SELECT + ' WHERE s.id=?', (session_id,)))


def is_scheduled(connection, session_id, user_id):
    return connection.execute('SELECT 1 FROM schedule_users WHERE session_id=? AND user_id=?', (session_id, user_id)).fetchone() is not None


def create_course(connection, payload):
    cursor = connection.execute('INSERT INTO courses (name,teacher_id,department_id) VALUES (?,?,?)', (payload.name, payload.teacher_id, payload.department_id))
    return get_course(connection, cursor.lastrowid)


def create_session(connection, payload, start, end):
    cursor = connection.execute('INSERT INTO class_sessions (course_id,starts_at,ends_at,classroom,class_name) VALUES (?,?,?,?,?)', (payload.course_id, start, end, payload.classroom, payload.class_name))
    return get_session(connection, cursor.lastrowid)


def people(connection):
    return rows(connection.execute("SELECT id,username,role FROM users WHERE status='ACTIVE' AND role IN ('TEACHER','STUDENT') ORDER BY username"))


def roster(connection, session_id):
    return rows(connection.execute("""SELECT u.id,u.username,u.status,
        coalesce((SELECT l.status FROM leave_requests l WHERE l.session_id=r.session_id AND l.student_id=u.id
        AND l.status IN ('PENDING','APPROVED') ORDER BY l.id DESC LIMIT 1),'') AS leave_status
        FROM schedule_users r JOIN users u ON u.id=r.user_id WHERE r.session_id=? ORDER BY u.username""", (session_id,)))


def replace_roster(connection, session_id, user_ids):
    course_id = connection.execute('SELECT course_id FROM class_sessions WHERE id=?', (session_id,)).fetchone()[0]
    connection.executemany("INSERT OR IGNORE INTO course_enrollments(course_id,user_id,joined_at) VALUES (?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))", [(course_id, user_id) for user_id in user_ids])
    connection.execute('DELETE FROM schedule_users WHERE session_id=?', (session_id,))
    connection.executemany('INSERT INTO schedule_users (session_id,user_id) VALUES (?,?)', [(session_id, user_id) for user_id in user_ids])


def audit(connection, actor_id, action, detail):
    connection.execute('INSERT INTO audit_logs (actor_id,action,detail) VALUES (?,?,?)', (actor_id, action, json.dumps(detail, ensure_ascii=False)))


def submission(connection, user_id, request_id):
    return one(connection.execute(RECORD_SELECT + ' JOIN emoji_submission_keys k ON k.record_id=e.id WHERE k.user_id=? AND k.request_id=?', (user_id, request_id)))


def add_emoji(connection, user_id, payload, timestamp):
    cursor = connection.execute("INSERT INTO emoji_records (user_id,session_id,emotion,source,recorded_at) VALUES (?,?,?,'MANUAL',?)", (user_id, payload.session_id, payload.emotion.value, timestamp))
    connection.execute('INSERT INTO emoji_submission_keys (user_id,request_id,record_id) VALUES (?,?,?)', (user_id, str(payload.request_id), cursor.lastrowid))
    return one(connection.execute(RECORD_SELECT + ' WHERE e.id=?', (cursor.lastrowid,)))


def history(connection, user, session_id, limit, offset, data_scope='ALL'):
    conditions, values = [], []
    if user['role'] == 'STUDENT':
        conditions.append('e.user_id=?')
        values.append(user['id'])
    elif user['role'] == 'TEACHER':
        conditions.append('c.teacher_id=?')
        values.append(user['id'])
    if user['role'] != 'STUDENT':
        conditions.append("NOT EXISTS(SELECT 1 FROM session_privacy p WHERE p.session_id=s.id AND p.mode='AGGREGATE')")
    if session_id is not None:
        conditions.append('e.session_id=?')
        values.append(session_id)
    if data_scope != 'ALL':
        conditions.append('e.is_demo=?')
        values.append(int(data_scope == 'DEMO'))
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    count = connection.execute('SELECT count(*) FROM emoji_records e JOIN class_sessions s ON s.id=e.session_id JOIN courses c ON c.id=s.course_id' + where, values).fetchone()[0]
    records = rows(connection.execute(RECORD_SELECT + where + ' ORDER BY e.recorded_at DESC,e.id DESC LIMIT ? OFFSET ?', (*values, limit, offset)))
    return {'items': protect_records(connection, records, user), 'total': count, 'limit': limit, 'offset': offset}


def statistics(connection, session_id, data_scope='ALL'):
    where = ' WHERE session_id=?' + (' AND is_demo=?' if data_scope != 'ALL' else '')
    values = [session_id] + ([int(data_scope == 'DEMO')] if data_scope != 'ALL' else [])
    grouped = rows(connection.execute('SELECT emotion,count(*) AS count FROM emoji_records' + where + ' GROUP BY emotion', values))
    summary = one(connection.execute("SELECT count(*) AS total,count(DISTINCT CASE WHEN source='MANUAL' THEN user_id END) AS responding_students,coalesce(sum(source='MANUAL'),0) AS manual_count,coalesce(sum(source='AI'),0) AS ai_count,coalesce(sum(is_demo),0) AS demo_count FROM emoji_records" + where, values))
    return grouped, summary
