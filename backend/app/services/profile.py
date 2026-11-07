from backend.app.repositories.classroom import courses
from backend.app.repositories.database import connect


def overview(user):
    with connect() as connection:
        connection.execute('BEGIN')
        def count(query, values=()):
            return connection.execute(query, values).fetchone()[0]
        course_count = len(courses(connection, user))
        if user['role'] == 'STUDENT':
            metrics = [
                ('已加入课程', course_count, 'courses'),
                ('累计反馈', count("SELECT count(*) FROM emoji_records WHERE user_id=? AND source='MANUAL'", (user['id'],)), 'history'),
                ('个人笔记', count('SELECT count(*) FROM personal_notes WHERE user_id=?', (user['id'],)), 'notes'),
                ('好友学伴', count("SELECT count(*) FROM buddy_connections b JOIN users u ON u.id=CASE WHEN b.low_user_id=? THEN b.high_user_id ELSE b.low_user_id END WHERE (b.low_user_id=? OR b.high_user_id=?) AND b.status='ACCEPTED' AND u.status='ACTIVE'", (user['id'], user['id'], user['id'])), 'buddies'),
            ]
            pending = count('SELECT count(*) FROM personal_notes WHERE user_id=? AND reviewed=0', (user['id'],))
        elif user['role'] == 'TEACHER':
            metrics = [('所授课程', course_count, 'courses'), ('所授课堂', count('SELECT count(*) FROM class_sessions s JOIN courses c ON c.id=s.course_id WHERE c.teacher_id=?', (user['id'],)), 'classroom'), ('收到反馈', count('SELECT count(*) FROM emoji_records e JOIN class_sessions s ON s.id=e.session_id JOIN courses c ON c.id=s.course_id WHERE c.teacher_id=?', (user['id'],)), 'reports')]
            pending = None
        else:
            metrics = [('全部课程', course_count, 'courses'), ('用户', count('SELECT count(*) FROM users'), 'users'), ('课堂反馈', count('SELECT count(*) FROM emoji_records'), 'reports')]
            pending = None
    return {'metrics': [{'label': label, 'value': value, 'target': target} for label, value, target in metrics], 'pending_notes': pending}
