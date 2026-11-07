from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories import teaching as repo
from backend.app.repositories.classroom import audit, courses
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session, session_view
from backend.app.services.inbox import notify


def overview(user):
    with connect() as connection:
        connection.execute('BEGIN')
        items = [session_view(item) for item in repo.workspace_sessions(connection, user)]
        summary = {'courses': len(courses(connection, user)), 'sessions': len(items),
                   'ongoing': sum(item['status'] == 'ONGOING' for item in items),
                   'upcoming': sum(item['status'] == 'UPCOMING' for item in items),
                   'open_questions': sum(item['open_questions'] for item in items),
                   'pending_reflections': sum(item['status'] == 'ENDED' and not item['has_reflection'] for item in items),
                   'pending_leaves': sum(item['pending_leaves'] for item in items)}
        return {'summary': summary, 'sessions': items, 'updated_at': utc_text(now_utc())}


def guide_view(item, student=False):
    public = None
    if item and item['published_at']:
        public = {'title': item['published_title'], 'content': item['published_content'],
                  'practice': item['published_practice'], 'published_at': item['published_at']}
    if student:
        return {'published': public}
    return {'published': public, 'draft': {key: item[key] if item else '' for key in ('title', 'content', 'practice')},
            'version': item['version'] if item else 0, 'updated_at': item['updated_at'] if item else None}


def get_guide(session_id, user):
    with connect() as connection:
        accessible_session(connection, session_id, user)
        return guide_view(repo.guide(connection, session_id), user['role'] == 'STUDENT')


def save_guide(session_id, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        accessible_session(connection, session_id, user)
        item = repo.guide(connection, session_id)
        if payload.version != (item['version'] if item else 0):
            raise AppError(409, 'VERSION_CONFLICT', '学习指引已被更新，请先放弃修改并刷新后再编辑')
        if payload.action == 'PUBLISH' and (not payload.title or not payload.content):
            raise AppError(422, 'GUIDE_EMPTY', '发布前请填写标题与学习要点')
        published = [item[key] if item else '' for key in ('published_title', 'published_content', 'published_practice')]
        published_at = item['published_at'] if item else None
        timestamp = utc_text(now_utc())
        if payload.action == 'PUBLISH':
            published, published_at = [payload.title, payload.content, payload.practice], timestamp
        elif payload.action == 'UNPUBLISH':
            published, published_at = ['', '', ''], None
        connection.execute('''INSERT INTO classroom_guides(session_id,title,content,practice,published_title,
            published_content,published_practice,published_at,version,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET title=excluded.title,content=excluded.content,practice=excluded.practice,
            published_title=excluded.published_title,published_content=excluded.published_content,
            published_practice=excluded.published_practice,published_at=excluded.published_at,
            version=excluded.version,updated_at=excluded.updated_at''',
            (session_id, payload.title, payload.content, payload.practice, *published, published_at, payload.version + 1, timestamp))
        audit(connection, user['id'], 'GUIDE_' + payload.action, {'session_id': session_id})
        if payload.action == 'PUBLISH':
            for (student_id,) in connection.execute("SELECT r.user_id FROM schedule_users r JOIN users u ON u.id=r.user_id WHERE r.session_id=? AND u.status='ACTIVE' AND u.role='STUDENT'", (session_id,)).fetchall():
                notify(connection, student_id, f'guide:{session_id}:{payload.version + 1}', 'GUIDE', '学习指引已发布', payload.title, 'classroom', session_id)
        return guide_view(repo.guide(connection, session_id))
