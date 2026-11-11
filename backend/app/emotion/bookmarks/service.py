from datetime import datetime, timedelta
import math

from backend.app.emotion.bookmarks import repository as repo
from backend.app.emotion.bookmarks.models import REASONS
from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import sessions
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session

MAX_BOOKMARKS_PER_CLASS = 80
AFTER_CLASS_DAYS = 7


def require_student(user):
    if user['role'] != 'STUDENT':
        raise AppError(403, 'STUDENT_ONLY', '请用学生账号管理自己的课堂书签')


def require_teacher(user):
    if user['role'] not in ('TEACHER', 'ADMIN'):
        raise AppError(403, 'TEACHER_ONLY', '只有任课教师或管理员可以管理课堂资料')


def version_matches(item, version):
    if item['version'] != version:
        raise AppError(409, 'STALE_BOOKMARK_VERSION', '这条记录已更新，请刷新核对后再保存')


def window(session, now=None):
    now = now or now_utc()
    start = datetime.fromisoformat(session['starts_at'])
    end = datetime.fromisoformat(session['ends_at'])
    upper = max(1, math.ceil((end - start).total_seconds() / 60))
    elapsed = min(upper, max(0, math.floor((now - start).total_seconds() / 60) + 1))
    ongoing = start <= now < end
    return {
        'duration_minutes': upper,
        'elapsed_minutes': elapsed,
        'live': ongoing,
        'can_add_past': start <= now <= end + timedelta(days=AFTER_CLASS_DAYS),
        'current_minute': elapsed - 1 if ongoing else None,
        'manual_until': utc_text(end + timedelta(days=AFTER_CLASS_DAYS)),
    }


def session_public(session, now=None):
    return {
        **{key: session[key] for key in (
            'id', 'course_id', 'course_name', 'class_name', 'starts_at', 'ends_at',
        )},
        'is_demo': bool(session.get('is_demo')),
        **window(session, now),
    }


def catalog(user):
    with connect() as connection:
        stamp = now_utc()
        return {
            'sessions': [session_public(item, stamp) for item in sessions(connection, user)],
            'reasons': [{'value': value, 'label': label} for value, label in REASONS.items()],
            'max_bookmarks': MAX_BOOKMARKS_PER_CLASS,
            'manual_days': AFTER_CLASS_DAYS,
            'server_time': utc_text(stamp),
        }


def must_own(connection, bookmark_id, user):
    item = repo.bookmark(connection, bookmark_id, user['id'])
    if item is None:
        raise AppError(404, 'BOOKMARK_NOT_FOUND', '书签不存在')
    accessible_session(connection, item['session_id'], user)
    return item


def public_bookmark(row):
    return {**row, 'reviewed': row['reviewed_at'] is not None, 'reason_label': REASONS[row['reason']]}


def list_for_student(user, session_id, state, reason, term, order, limit, offset):
    require_student(user)
    with connect() as connection:
        connection.execute('BEGIN')
        if session_id is not None:
            accessible_session(connection, session_id, user)
        return student_page(connection, user, session_id, state, reason, term, order, limit, offset)


def student_page(connection, user, session_id, state, reason, term, order, limit, offset):
    from backend.app.emotion.bookmarks.materials import public_material

    records, total = repo.list_bookmarks(
        connection, user['id'], session_id, state, reason, term, order, limit, offset,
    )
    resources = repo.published_for_bookmarks(connection, records, user['id'])
    items = []
    for row in records:
        linked = [
            public_material(item, user)
            for item in resources.get(row['session_id'], [])
            if item['start_minute'] <= row['minute'] < item['end_minute']
        ]
        items.append({**public_bookmark(row), 'materials': linked})
    totals = repo.student_totals(connection, user['id'], session_id)
    return {
        'items': items,
        'total': total,
        'offset': offset,
        'limit': limit,
        'has_more': offset + len(items) < total,
        'summary': {**totals, 'open': totals['total'] - totals['reviewed']},
    }


def creation_minute(session, payload, stamp):
    limits = window(session, stamp)
    if payload.minute is None:
        if not limits['live']:
            raise AppError(409, 'CLASS_NOT_LIVE', '这节课现在不在进行中，可以手动补记之前的时间点')
        return limits['current_minute']
    if not limits['can_add_past']:
        raise AppError(409, 'BOOKMARK_WINDOW_CLOSED', '开课后到下课七天内可以补记书签')
    if payload.minute >= limits['elapsed_minutes']:
        raise AppError(422, 'BOOKMARK_MINUTE_INVALID', '请选择已经讲到的课堂分钟')
    return payload.minute


def create(session_id, payload, user):
    require_student(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        session = accessible_session(connection, session_id, user)
        old = repo.previous_request(connection, user, payload, session_id, 'CREATE_BOOKMARK')
        if old is not None:
            item = repo.bookmark(connection, old, user['id'])
            if item is None:
                raise AppError(409, 'BOOKMARK_REMOVED', '这次请求对应的书签已经删除')
            return {'bookmark': public_bookmark(item), 'created': False}
        stamp = now_utc()
        minute = creation_minute(session, payload, stamp)
        existing = connection.execute(
            'SELECT id FROM classroom_bookmarks WHERE session_id=? AND student_id=? AND minute=?',
            (session_id, user['id'], minute),
        ).fetchone()
        created = existing is None
        if existing:
            identifier = existing[0]
        else:
            count = connection.execute(
                'SELECT count(*) FROM classroom_bookmarks WHERE session_id=? AND student_id=?',
                (session_id, user['id']),
            ).fetchone()[0]
            if count >= MAX_BOOKMARKS_PER_CLASS:
                raise AppError(409, 'BOOKMARK_LIMIT', '这节课的书签已满，可以先删除用不到的书签')
            cursor = connection.execute(
                '''INSERT INTO classroom_bookmarks(session_id,student_id,minute,reason,title,note,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (session_id, user['id'], minute, payload.reason, payload.title, payload.note, utc_text(stamp), utc_text(stamp)),
            )
            identifier = cursor.lastrowid
        repo.remember_request(connection, user, payload, session_id, 'CREATE_BOOKMARK', identifier, utc_text(stamp))
        return {'bookmark': public_bookmark(repo.bookmark(connection, identifier, user['id'])), 'created': created}


def update(identifier, payload, user):
    require_student(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = must_own(connection, identifier, user)
        version_matches(item, payload.version)
        now = utc_text(now_utc())
        reviewed_at = (item['reviewed_at'] or now) if payload.reviewed else None
        connection.execute(
            '''UPDATE classroom_bookmarks SET reason=?,title=?,note=?,reviewed_at=?,
                      version=version+1,updated_at=? WHERE id=?''',
            (payload.reason, payload.title, payload.note, reviewed_at, now, identifier),
        )
        return public_bookmark(repo.bookmark(connection, identifier, user['id']))


def remove(identifier, version, user):
    require_student(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = must_own(connection, identifier, user)
        version_matches(item, version)
        connection.execute('DELETE FROM classroom_bookmarks WHERE id=?', (identifier,))
        return {'id': identifier, 'deleted': True}


def review_selected(payload, user):
    require_student(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        items = [must_own(connection, identifier, user) for identifier in payload.bookmark_ids]
        stamp = utc_text(now_utc())
        changed = []
        for item in items:
            if bool(item['reviewed_at']) == payload.reviewed:
                continue
            connection.execute(
                '''UPDATE classroom_bookmarks SET reviewed_at=?,updated_at=?,version=version+1 WHERE id=?''',
                (stamp if payload.reviewed else None, stamp, item['id']),
            )
            changed.append(item['id'])
        return {'changed': changed, 'reviewed': payload.reviewed}
