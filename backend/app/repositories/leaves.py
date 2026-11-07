from backend.app.repositories.classroom import one, rows, DEPARTMENT_FIELDS

SELECT = '''SELECT l.*,s.course_id,c.name AS course_name,s.starts_at,s.ends_at,s.classroom,s.class_name,
    c.teacher_id,coalesce(nullif(tp.nickname,''),t.username) AS teacher_name,
    u.username AS student_username,coalesce(nullif(p.nickname,''),u.username) AS student_name,
    coalesce(nullif(rp.nickname,''),r.username) AS reviewer_name,'''+ DEPARTMENT_FIELDS + '''
    FROM leave_requests l JOIN class_sessions s ON s.id=l.session_id
    JOIN courses c ON c.id=s.course_id JOIN users u ON u.id=l.student_id
    JOIN users t ON t.id=c.teacher_id LEFT JOIN users r ON r.id=l.reviewer_id
    LEFT JOIN user_profiles p ON p.user_id=u.id LEFT JOIN user_profiles tp ON tp.user_id=t.id
    LEFT JOIN user_profiles rp ON rp.user_id=r.id LEFT JOIN departments d ON d.id=c.department_id'''


def scope(user):
    if user['role'] == 'STUDENT':
        return 'l.student_id=?', [user['id']]
    if user['role'] == 'TEACHER':
        return 'c.teacher_id=?', [user['id']]
    return '1=1', []


def get(connection, identifier, user):
    clause, values = scope(user)
    return one(connection.execute(SELECT + ' WHERE l.id=? AND ' + clause, [identifier, *values]))


def listing(connection, user, status, course_id, session_id, limit, offset):
    clause, values = scope(user)
    for field, value in [('s.course_id', course_id), ('l.session_id', session_id)]:
        if value is not None:
            clause += ' AND ' + field + '=?'; values.append(value)
    counts = rows(connection.execute('SELECT status,count(*) AS count FROM (' + SELECT + ' WHERE ' + clause + ') GROUP BY status', values))
    summary = {key: 0 for key in ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')}
    summary.update({item['status']: item['count'] for item in counts})
    if status != 'ALL':
        clause += ' AND l.status=?'; values.append(status)
    total = sum(summary.values()) if status == 'ALL' else summary[status]
    items = rows(connection.execute(SELECT + ' WHERE ' + clause + " ORDER BY (l.status='PENDING') DESC,l.created_at DESC,l.id DESC LIMIT ? OFFSET ?", [*values, limit, offset]))
    return {'items': items, 'total': total, 'summary': summary, 'limit': limit, 'offset': offset}
