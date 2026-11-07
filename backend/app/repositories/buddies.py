from backend.app.repositories.classroom import one, rows

CARD_SELECT = '''SELECT u.id,u.username,coalesce(p.nickname,'') AS nickname,
 coalesce(p.bio,'') AS bio,coalesce(p.interests,'') AS interests,
 coalesce(p.avatar_color,'sage') AS avatar_color,coalesce(p.major,'') AS major,
 coalesce(p.grade,'') AS grade,coalesce(p.study_goal,'') AS study_goal,
 coalesce(p.learning_style,'') AS learning_style,
 (SELECT '/api/avatars/'||a.user_id||'/'||a.digest FROM user_avatars a WHERE a.user_id=u.id) AS avatar_url
 FROM users u LEFT JOIN user_profiles p ON p.user_id=u.id'''


def student_card(connection, user_id=None, username=None):
    field, value = ('u.id', user_id) if user_id is not None else ('u.username', username)
    return one(connection.execute(CARD_SELECT + f" WHERE {field}=? AND u.role='STUDENT' AND u.status='ACTIVE'", (value,)))


def relation(connection, user_id, target_id):
    low, high = sorted((user_id, target_id))
    return one(connection.execute('SELECT * FROM buddy_connections WHERE low_user_id=? AND high_user_id=?', (low, high)))


def by_id(connection, request_id):
    return one(connection.execute('SELECT * FROM buddy_connections WHERE id=?', (request_id,)))


def count_connections(connection, user_id):
    return connection.execute('SELECT count(*) FROM buddy_connections WHERE low_user_id=? OR high_user_id=?', (user_id, user_id)).fetchone()[0]


def list_connections(connection, user_id):
    return rows(connection.execute('''SELECT b.id AS request_id,b.requester_id,b.status,b.created_at,b.accepted_at,
        u.id,u.username,coalesce(p.nickname,'') AS nickname,coalesce(p.bio,'') AS bio,
        coalesce(p.interests,'') AS interests,coalesce(p.avatar_color,'sage') AS avatar_color,
        coalesce(p.major,'') AS major,coalesce(p.grade,'') AS grade,
        coalesce(p.study_goal,'') AS study_goal,coalesce(p.learning_style,'') AS learning_style,
        (SELECT '/api/avatars/'||a.user_id||'/'||a.digest FROM user_avatars a WHERE a.user_id=u.id) AS avatar_url
        FROM buddy_connections b JOIN users u ON u.id=CASE WHEN b.low_user_id=? THEN b.high_user_id ELSE b.low_user_id END
        LEFT JOIN user_profiles p ON p.user_id=u.id
        WHERE (b.low_user_id=? OR b.high_user_id=?) AND u.status='ACTIVE' AND u.role='STUDENT'
        ORDER BY b.created_at DESC,b.id DESC''', (user_id, user_id, user_id)))


def literal_pattern(value):
    return '%' + value.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def search_students(connection, user_id, filters):
    fields = {'username': 'u.username', 'nickname': "coalesce(p.nickname,'')", 'interests': "coalesce(p.interests,'')", 'bio': "coalesce(p.bio,'')", 'major': "coalesce(p.major,'')", 'grade': "coalesce(p.grade,'')", 'study_goal': "coalesce(p.study_goal,'')", 'learning_style': "CASE p.learning_style WHEN 'pair' THEN '结对练习' WHEN 'questions' THEN '互相答疑' WHEN 'project' THEN '项目协作' WHEN 'focus' THEN '打卡自习' ELSE '' END"}
    parts = ["u.role='STUDENT'", "u.status='ACTIVE'", 'u.id<>?']
    values = [user_id, user_id, user_id]
    if filters.username:
        parts.append('u.username=?'); values.append(filters.username.casefold())
    for word in filters.q.split():
        expressions = list(fields.values()) if filters.scope == 'all' else [fields[filters.scope]]
        parts.append('(' + ' OR '.join(f"lower({field}) LIKE ? ESCAPE '\\'" for field in expressions) + ')')
        values.extend([literal_pattern(word)] * len(expressions))
    for name in ('interests', 'major', 'grade'):
        value = getattr(filters, name)
        if value:
            parts.append(f"lower(coalesce(p.{name},'')) LIKE ? ESCAPE '\\'"); values.append(literal_pattern(value))
    if filters.learning_style:
        parts.append('p.learning_style=?'); values.append(filters.learning_style)
    if filters.relationship == 'new':
        parts.append('b.id IS NULL')
    elif filters.relationship == 'friends':
        parts.append("b.status='ACCEPTED'")
    elif filters.relationship == 'pending':
        parts.append("b.status='PENDING'")
    if filters.common_course:
        parts.append('''EXISTS(SELECT 1 FROM schedule_users candidate JOIN class_sessions candidate_session ON candidate_session.id=candidate.session_id
            JOIN class_sessions my_session ON my_session.course_id=candidate_session.course_id
            JOIN schedule_users mine ON mine.session_id=my_session.id
            WHERE candidate.user_id=u.id AND mine.user_id=?)''')
        values.append(user_id)
    joined = ''' FROM users u LEFT JOIN user_profiles p ON p.user_id=u.id
        LEFT JOIN buddy_connections b ON (b.low_user_id=? AND b.high_user_id=u.id) OR (b.high_user_id=? AND b.low_user_id=u.id)'''
    where = ' WHERE ' + ' AND '.join(parts)
    total = connection.execute('SELECT count(*)' + joined + where, values).fetchone()[0]
    columns = CARD_SELECT.split(' FROM users')[0] + ',b.id AS request_id,b.status AS connection_status,b.requester_id'
    items = rows(connection.execute(columns + joined + where + ' ORDER BY u.username,u.id LIMIT ? OFFSET ?', (*values, filters.limit, filters.offset)))
    return items, total
