from backend.app.repositories.classroom import one, rows, sessions


def guide(connection, session_id):
    return one(connection.execute('SELECT * FROM classroom_guides WHERE session_id=?', (session_id,)))


def workspace_sessions(connection, user):
    items = sessions(connection, user)
    # Aggregate once per table; never load private student notes or question authors.
    where = ' WHERE c.teacher_id=?' if user['role'] == 'TEACHER' else ''
    values = (user['id'],) if user['role'] == 'TEACHER' else ()
    questions = {item['session_id']: item for item in rows(connection.execute('''
        SELECT q.session_id,count(*) AS question_count,sum(q.status='OPEN') AS open_questions
        FROM classroom_questions q JOIN class_sessions s ON s.id=q.session_id
        JOIN courses c ON c.id=s.course_id''' + where + ' GROUP BY q.session_id', values))}
    reflections = {item['session_id']: bool(item['reflection'].strip()) for item in rows(connection.execute('''
        SELECT r.session_id,r.reflection FROM classroom_reflections r
        JOIN class_sessions s ON s.id=r.session_id JOIN courses c ON c.id=s.course_id''' + where, values))}
    guides = {item['session_id']: item['published_at'] is not None for item in rows(connection.execute('''
        SELECT g.session_id,g.published_at FROM classroom_guides g
        JOIN class_sessions s ON s.id=g.session_id JOIN courses c ON c.id=s.course_id''' + where, values))}
    leaves = {item['session_id']: item for item in rows(connection.execute('''
        SELECT l.session_id,sum(l.status='PENDING') AS pending_leaves,sum(l.status='APPROVED') AS approved_leaves
        FROM leave_requests l JOIN class_sessions s ON s.id=l.session_id
        JOIN courses c ON c.id=s.course_id''' + where + ' GROUP BY l.session_id', values))}
    for item in items:
        counts = questions.get(item['id'], {})
        item.update(question_count=counts.get('question_count', 0), open_questions=counts.get('open_questions', 0),
                    has_reflection=reflections.get(item['id'], False), guide_published=guides.get(item['id'], False))
        item.update(pending_leaves=leaves.get(item['id'], {}).get('pending_leaves', 0), approved_leaves=leaves.get(item['id'], {}).get('approved_leaves', 0))
    return items
