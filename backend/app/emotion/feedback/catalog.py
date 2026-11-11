from datetime import datetime

from backend.app.models.classroom import now_utc
from backend.app.repositories import classroom as classroom_repo
from backend.app.repositories.classroom import rows
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session
from backend.app.emotion.feedback import access, cases
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback.workflow import REASONS, STATE_NAMES

EMOTIONS = {
    'HAPPY': ('开心', '🙂'),
    'NEUTRAL': ('平静', '😐'),
    'SAD': ('低落', '🙁'),
    'ANGRY': ('生气', '😠'),
    'SURPRISED': ('惊讶', '😮'),
    'FEAR': ('担忧', '😟'),
    'DISGUST': ('反感', '😒'),
}


def options(user):
    with connect() as connection:
        courses = classroom_repo.courses(connection, user)
        sessions = classroom_repo.sessions(connection, user)
        current = now_utc()
        result = []
        for item in sessions:
            starts = datetime.fromisoformat(item['starts_at'])
            ends = datetime.fromisoformat(item['ends_at'])
            value = {
                'id': item['id'],
                'course_id': item['course_id'],
                'course_name': item['course_name'],
                'class_name': item['class_name'],
                'classroom': item['classroom'],
                'starts_at': item['starts_at'],
                'ends_at': item['ends_at'],
                'is_demo': bool(item.get('is_demo', 0)),
                'status': 'UPCOMING' if current < starts else 'LIVE' if current <= ends else 'ENDED',
            }
            if user['role'] == 'STUDENT':
                value['submission'] = cases.submission_window(connection, item, user)
            result.append(value)
        return {
            'role': user['role'],
            'courses': [{
                'id': item['id'],
                'name': item['name'],
                'is_demo': bool(item.get('is_demo', 0)),
            } for item in courses],
            'sessions': result,
            'reasons': [{'value': key, 'label': value} for key, value in REASONS.items()],
            'states': [{'value': key, 'label': value} for key, value in STATE_NAMES.items()],
            'emotions': [{
                'value': key,
                'label': value[0],
                'emoji': value[1],
            } for key, value in EMOTIONS.items()],
            'limits': {
                'title': 120,
                'content': 2000,
                'reasons': 3,
                'group_members': 50,
                'message_edit_minutes': 10,
                'templates': 100,
                'saved_views': 30,
            },
        }


def session_context(session_id, user):
    with connect() as connection:
        session = accessible_session(connection, session_id, user)
        result = {
            'session_id': session_id,
            'course_id': session['course_id'],
            'policy': repo.policy(connection, session['course_id']),
        }
        if user['role'] == 'STUDENT':
            result['submission'] = cases.submission_window(connection, session, user)
            records = rows(connection.execute(
                '''SELECT id,emotion,source,recorded_at FROM emoji_records
                WHERE session_id=? AND user_id=? ORDER BY recorded_at DESC,id DESC LIMIT 30''',
                (session_id, user['id']),
            ))
            result['emotion_records'] = records
        else:
            access.staff(user)
            result['adjustments'] = rows(connection.execute(
                '''SELECT id,title,start_minute,end_minute,status FROM emotion_insight_entries
                WHERE session_id=? AND kind='ACTION' ORDER BY start_minute,id''',
                (session_id,),
            ))
        return result
