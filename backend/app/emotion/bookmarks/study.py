from backend.app.emotion.bookmarks import service
from backend.app.repositories.classroom import one
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session

MATERIAL_MATCH = '''
    SELECT 1 FROM bookmark_materials m
    WHERE m.session_id=b.session_id AND m.state='PUBLISHED'
      AND m.start_minute<=b.minute AND m.end_minute>b.minute
'''


def coverage(connection, student_id, session_id):
    conditions = [
        'b.student_id=?',
        'b.reviewed_at IS NULL',
        'EXISTS(SELECT 1 FROM schedule_users su WHERE su.session_id=b.session_id AND su.user_id=b.student_id)',
    ]
    args = [student_id]
    if session_id is not None:
        conditions.append('b.session_id=?')
        args.append(session_id)
    return one(connection.execute(
        '''SELECT count(*) AS pending,
                  coalesce(sum(EXISTS(''' + MATERIAL_MATCH + ''')),0) AS ready
           FROM classroom_bookmarks b WHERE ''' + ' AND '.join(conditions),
        args,
    ))


def queue(user, session_id, prefer, limit, offset):
    service.require_student(user)
    if prefer == 'MATERIAL':
        order = 'WITH_MATERIAL'
    elif prefer == 'TIME':
        order = 'LESSON'
    else:
        order = 'RECENT'
    with connect() as connection:
        connection.execute('BEGIN')
        if session_id is not None:
            accessible_session(connection, session_id, user)
        counts = coverage(connection, user['id'], session_id)
        result = service.student_page(connection, user, session_id, 'OPEN', None, '', order, limit, offset)
    return {
        **result,
        'coverage': {
            'pending': counts['pending'],
            'ready': counts['ready'],
            'waiting': counts['pending'] - counts['ready'],
        },
        'preference': prefer,
    }
