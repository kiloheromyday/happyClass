from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories import classroom as repo
from backend.app.repositories.database import connect
from backend.app.services.classroom import session_view


def departments():
    with connect() as connection:
        return {'items': repo.rows(connection.execute('SELECT * FROM departments ORDER BY rowid'))}


def overview(user, data_scope='ALL'):
    with connect() as connection:
        connection.execute('BEGIN')
        courses = repo.courses(connection, user)
        sessions = [session_view(item) for item in repo.sessions(connection, user)]
        if data_scope != 'ALL':
            courses = [item for item in courses if bool(item['is_demo']) == (data_scope == 'DEMO')]
            ids = {item['id'] for item in courses}
            sessions = [item for item in sessions if item['course_id'] in ids]
        where = '' if data_scope == 'ALL' else ' WHERE e.is_demo=' + str(int(data_scope == 'DEMO'))
        grouped = repo.rows(connection.execute('''SELECT s.course_id,count(*) AS feedback_count,
            sum(e.source='MANUAL') AS manual_count,sum(e.source='AI') AS ai_count,
            sum(e.is_demo) AS demo_feedback_count,
            count(DISTINCT CASE WHEN e.source='MANUAL' THEN e.user_id END) AS responding_students,
            count(DISTINCT CASE WHEN e.source='MANUAL' THEN CAST(e.session_id AS TEXT)||':'||e.user_id END) AS responses,
            sum(e.emotion='HAPPY') AS happy_count,sum(e.emotion='NEUTRAL') AS neutral_count
            FROM emoji_records e JOIN class_sessions s ON s.id=e.session_id''' + where + ' GROUP BY s.course_id'))
        feedback = {item['course_id']: item for item in grouped}
        emotions = repo.rows(connection.execute('''SELECT s.course_id,e.emotion,count(*) AS count
            FROM emoji_records e JOIN class_sessions s ON s.id=e.session_id''' + where + ' GROUP BY s.course_id,e.emotion'))
        session_counts = dict(connection.execute('SELECT e.session_id,count(*) FROM emoji_records e' + where + ' GROUP BY e.session_id'))
        for item in sessions:
            item['record_count'] = session_counts.get(item['id'], 0)
        by_course = {}
        for session in sessions:
            by_course.setdefault(session['course_id'], []).append(session)
        for course in courses:
            items = by_course.get(course['id'], [])
            counts = feedback.get(course['id'], {})
            course['summary'] = {key: counts.get(key, 0) for key in ('feedback_count', 'manual_count', 'ai_count', 'demo_feedback_count', 'responding_students', 'responses', 'happy_count', 'neutral_count')}
            course['summary'].update(session_count=len(items), scheduled_count=sum(item['scheduled_count'] for item in items),
                ongoing=sum(item['status'] == 'ONGOING' for item in items), upcoming=sum(item['status'] == 'UPCOMING' for item in items),
                ended=sum(item['status'] == 'ENDED' for item in items))
            course['emotions'] = [{'emotion': item['emotion'], 'count': item['count']} for item in emotions if item['course_id'] == course['id']]
        summary = {'courses': len(courses), 'departments': len({c['department_id'] for c in courses if c['department_id']}),
                   'sessions': len(sessions), 'ongoing': sum(item['status'] == 'ONGOING' for item in sessions),
                   'feedback_count': sum(item['summary']['feedback_count'] for item in courses),
                   'demo_feedback_count': sum(item['summary']['demo_feedback_count'] for item in courses)}
        return {'courses': courses, 'sessions': sessions, 'summary': summary, 'data_scope': data_scope, 'updated_at': utc_text(now_utc())}
