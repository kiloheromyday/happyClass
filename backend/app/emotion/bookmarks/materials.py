import json

from backend.app.emotion.bookmarks import repository as repo
from backend.app.emotion.bookmarks import service
from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import audit
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session

MAX_MATERIALS_PER_CLASS = 100
TRANSITIONS = {
    'PUBLISH': ({'DRAFT'}, 'PUBLISHED'),
    'UNPUBLISH': ({'PUBLISHED'}, 'DRAFT'),
    'ARCHIVE': ({'DRAFT', 'PUBLISHED'}, 'ARCHIVED'),
    'RESTORE': ({'ARCHIVED'}, 'DRAFT'),
}


def public_material(row, user):
    values = {key: row[key] for key in (
        'id', 'session_id', 'start_minute', 'end_minute', 'title', 'content',
        'state', 'published_at', 'version', 'created_at', 'updated_at',
    )}
    values['links'] = json.loads(row['links'])
    if user['role'] == 'STUDENT':
        completed = row.get('completed_at')
        values.update({
            'completed_at': completed,
            'completed': bool(completed) and row.get('completed_version') == row['version'],
            'changed_after_review': bool(completed) and row.get('completed_version') != row['version'],
        })
    return values


def validate_interval(session, start_minute, end_minute):
    limits = service.window(session)
    if start_minute >= end_minute or end_minute > limits['duration_minutes']:
        raise AppError(422, 'MATERIAL_INTERVAL_INVALID', '资料对应的时间段要在课堂时长内')


def list_for_session(session_id, user, state, start_minute, end_minute):
    with connect() as connection:
        connection.execute('BEGIN')
        session = accessible_session(connection, session_id, user)
        interval = None
        if start_minute is not None or end_minute is not None:
            if start_minute is None or end_minute is None:
                raise AppError(422, 'MATERIAL_INTERVAL_REQUIRED', '请同时填写开始和结束分钟')
            validate_interval(session, start_minute, end_minute)
            interval = (start_minute, end_minute)
        student = user['role'] == 'STUDENT'
        if student and state not in (None, 'PUBLISHED'):
            raise AppError(403, 'MATERIALS_NOT_PUBLIC', '学生可以查看已发布的资料')
        rows = repo.materials(
            connection, session_id, state='PUBLISHED' if student else state,
            interval=interval, student_id=user['id'] if student else None,
        )
        public = [public_material(row, user) for row in rows]
        return {
            'session': service.session_public(session),
            'items': public,
            'total': len(public),
            'completed': sum(item.get('completed', False) for item in public) if student else None,
        }


def need_material(connection, identifier, user, published=False):
    row = repo.material(connection, identifier)
    if row is None or (published and row['state'] != 'PUBLISHED'):
        raise AppError(404, 'MATERIAL_NOT_FOUND', '资料不存在或尚未发布')
    session = accessible_session(connection, row['session_id'], user)
    return row, session


def fields(payload):
    return (
        payload.start_minute, payload.end_minute, payload.title, payload.content,
        json.dumps([item.model_dump(mode='json') for item in payload.links], ensure_ascii=False),
    )


def create(session_id, payload, user):
    service.require_teacher(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        session = accessible_session(connection, session_id, user)
        old_id = repo.previous_request(connection, user, payload, session_id, 'CREATE_MATERIAL')
        if old_id is not None:
            existing, _ = need_material(connection, old_id, user)
            return public_material(existing, user)
        validate_interval(session, payload.start_minute, payload.end_minute)
        count = connection.execute(
            'SELECT count(*) FROM bookmark_materials WHERE session_id=?',
            (session_id,),
        ).fetchone()[0]
        if count >= MAX_MATERIALS_PER_CLASS:
            raise AppError(409, 'MATERIAL_LIMIT', '这节课的资料已达上限，可以继续编辑已有资料')
        stamp = utc_text(now_utc())
        state = 'PUBLISHED' if payload.publish else 'DRAFT'
        result = connection.execute(
            '''INSERT INTO bookmark_materials(session_id,creator_id,start_minute,end_minute,title,content,
                        links,state,published_at,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (session_id, user['id'], *fields(payload), state, stamp if payload.publish else None, stamp, stamp),
        )
        identifier = result.lastrowid
        repo.remember_request(connection, user, payload, session_id, 'CREATE_MATERIAL', identifier, stamp)
        audit(connection, user['id'], 'BOOKMARK_MATERIAL_CREATED', {
            'id': identifier, 'session_id': session_id, 'state': state,
        })
        return public_material(repo.material(connection, identifier), user)


def update(identifier, payload, user):
    service.require_teacher(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row, session = need_material(connection, identifier, user)
        service.version_matches(row, payload.version)
        if row['state'] == 'ARCHIVED':
            raise AppError(409, 'MATERIAL_ARCHIVED', '请先把资料恢复成草稿')
        validate_interval(session, payload.start_minute, payload.end_minute)
        connection.execute(
            '''UPDATE bookmark_materials SET start_minute=?,end_minute=?,title=?,content=?,links=?,
                      version=version+1,updated_at=? WHERE id=?''',
            (*fields(payload), utc_text(now_utc()), identifier),
        )
        audit(connection, user['id'], 'BOOKMARK_MATERIAL_UPDATED', {
            'id': identifier, 'session_id': session['id'],
        })
        return public_material(repo.material(connection, identifier), user)


def change_state(identifier, payload, user):
    service.require_teacher(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row, session = need_material(connection, identifier, user)
        service.version_matches(row, payload.version)
        allowed, state = TRANSITIONS[payload.action]
        if row['state'] not in allowed:
            raise AppError(409, 'MATERIAL_STATE_INVALID', '当前状态不能这样操作')
        stamp = utc_text(now_utc())
        published_at = stamp if state == 'PUBLISHED' else None
        if state == 'PUBLISHED':
            validate_interval(session, row['start_minute'], row['end_minute'])
        connection.execute(
            '''UPDATE bookmark_materials SET state=?,published_at=?,updated_at=?,version=version+1
               WHERE id=?''',
            (state, published_at, stamp, identifier),
        )
        audit(connection, user['id'], 'BOOKMARK_MATERIAL_STATE_CHANGED', {
            'id': identifier, 'session_id': session['id'], 'state': state,
        })
        return public_material(repo.material(connection, identifier), user)


def set_progress(identifier, payload, user):
    service.require_student(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row, _ = need_material(connection, identifier, user, published=True)
        service.version_matches(row, payload.version)
        completed_at = utc_text(now_utc()) if payload.completed else None
        if payload.completed:
            connection.execute(
                '''INSERT INTO bookmark_material_progress(material_id,student_id,material_version,completed_at)
                   VALUES (?,?,?,?) ON CONFLICT(material_id,student_id) DO UPDATE SET
                   material_version=excluded.material_version,completed_at=excluded.completed_at''',
                (identifier, user['id'], row['version'], completed_at),
            )
        else:
            connection.execute(
                'DELETE FROM bookmark_material_progress WHERE material_id=? AND student_id=?',
                (identifier, user['id']),
            )
        return {
            'id': identifier,
            'completed': payload.completed,
            'completed_at': completed_at,
            'changed_after_review': False,
        }
