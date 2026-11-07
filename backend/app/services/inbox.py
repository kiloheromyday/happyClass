from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import rows
from backend.app.repositories.database import connect


def notify(connection, user_id, event_key, kind, title, body, tab, session_id=None, course_id=None):
    # Call inside the business transaction. No private reason/reply or anonymous author is copied.
    connection.execute('''INSERT OR IGNORE INTO notifications
        (user_id,event_key,kind,title,body,target_tab,session_id,course_id,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)''', (user_id, event_key, kind, title, body, tab, session_id, course_id, utc_text(now_utc())))


def listing(user, unread, kind, limit, offset):
    with connect() as c:
        c.execute('BEGIN')
        where, values = 'user_id=?', [user['id']]
        unread_count = c.execute('SELECT count(*) FROM notifications WHERE user_id=? AND read_at IS NULL', values).fetchone()[0]
        if unread:
            where += ' AND read_at IS NULL'
        if kind != 'ALL':
            where += ' AND kind=?'; values.append(kind)
        total = c.execute('SELECT count(*) FROM notifications WHERE ' + where, values).fetchone()[0]
        items = rows(c.execute('SELECT id,kind,title,body,target_tab,session_id,course_id,created_at,read_at FROM notifications WHERE ' + where + ' ORDER BY id DESC LIMIT ? OFFSET ?', [*values, limit, offset]))
        return {'items': items, 'total': total, 'unread_count': unread_count, 'limit': limit, 'offset': offset}


def mark(user, identifier=None):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if identifier is not None and not c.execute('SELECT 1 FROM notifications WHERE id=? AND user_id=?', (identifier, user['id'])).fetchone():
            raise AppError(404, 'MESSAGE_NOT_FOUND', '消息不存在')
        c.execute('UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL' + (' AND id=?' if identifier is not None else ''),
                  [utc_text(now_utc()), user['id'], *([identifier] if identifier is not None else [])])
        return {'unread_count': c.execute('SELECT count(*) FROM notifications WHERE user_id=? AND read_at IS NULL', (user['id'],)).fetchone()[0]}
