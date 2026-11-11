from datetime import datetime, timedelta

from backend.app.emotion.feedback import access, cases
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback.workflow import STATE_NAMES, require_version
from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import one, rows
from backend.app.repositories.database import connect

REMINDER_INTERVAL = timedelta(hours=24)
JOIN = ''' FROM feedback_reviews r
JOIN feedback_cases f ON f.id=r.case_id
JOIN class_sessions s ON s.id=f.session_id
JOIN courses c ON c.id=s.course_id
LEFT JOIN feedback_review_answers a ON a.review_id=r.id
LEFT JOIN feedback_review_reminders m ON m.review_id=r.id'''


def schedule_fields(item, user, timestamp):
    open_round = item['state'] == 'OPEN'
    overdue = open_round and timestamp > datetime.fromisoformat(item['due_at'])
    previous = item.get('last_reminded_at')
    next_reminder = datetime.fromisoformat(previous) + REMINDER_INTERVAL if previous else None
    return {
        'overdue': overdue,
        'can_remind': user['role'] != 'STUDENT' and overdue and (
            next_reminder is None or timestamp >= next_reminder
        ),
        'last_reminded_at': previous,
        'next_reminder_at': utc_text(next_reminder) if overdue and next_reminder and next_reminder > timestamp else None,
        'reminder_count': item.get('reminder_count') or 0,
    }


def listing(filters, user, status, offset, limit, sort):
    with connect() as connection:
        connection.execute('BEGIN')
        cases.validate_filters(connection, filters, user)
        where, params = repo.filtered(user, filters)
        timestamp = now_utc()
        statuses = {
            'OPEN': ("r.state='OPEN'", []),
            'OVERDUE': ("r.state='OPEN' AND r.due_at<?", [utc_text(timestamp)]),
            'ANSWERED': ("r.state='ANSWERED'", []),
            'CANCELLED': ("r.state='CANCELLED'", []),
        }
        if status in statuses:
            clause, values = statuses[status]
            where += ' AND ' + clause
            params.extend(values)
        total = connection.execute('SELECT count(*)' + JOIN + where, params).fetchone()[0]
        order = 'r.due_at,r.id' if sort == 'DUE' else 'r.created_at DESC,r.id DESC'
        raw = rows(connection.execute(
            '''SELECT r.id,r.case_id,r.prompt,r.state,r.due_at,r.version,r.created_at,r.closed_at,
            f.title,f.state AS case_state,f.is_demo,s.id AS session_id,s.class_name,
            c.id AS course_id,c.name AS course_name,a.outcome,a.created_at AS answered_at,
            m.last_reminded_at,m.reminder_count''' + JOIN + where + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?',
            (*params, limit, offset),
        ))
        return {
            'items': [{
                'id': item['id'],
                'case_id': item['case_id'],
                'case_title': item['title'],
                'case_state': STATE_NAMES[item['case_state']],
                'session_id': item['session_id'],
                'class_name': item['class_name'],
                'course_id': item['course_id'],
                'course_name': item['course_name'],
                'is_demo': bool(item['is_demo']),
                'prompt': item['prompt'],
                'state': item['state'],
                'due_at': item['due_at'],
                'version': item['version'],
                'created_at': item['created_at'],
                'closed_at': item['closed_at'],
                'outcome': item['outcome'],
                'answered_at': item['answered_at'],
                **schedule_fields(item, user, timestamp),
            } for item in raw],
            'offset': offset,
            'limit': limit,
            'total': total,
            'has_more': offset + len(raw) < total,
            'generated_at': utc_text(timestamp),
        }


def remind(identifier, payload, user):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        review, item = access.review(connection, identifier, user)
        previous = repo.previous(connection, user, payload, 'REVIEW_REMIND', identifier)
        if previous is not None:
            return previous
        require_version(review, payload.version)
        if review['state'] != 'OPEN' or item['state'] != 'WAITING_REVIEW':
            raise AppError(409, 'REVIEW_CLOSED', '本轮回访已结束')
        timestamp = now_utc()
        if timestamp <= datetime.fromisoformat(review['due_at']):
            raise AppError(409, 'REVIEW_NOT_OVERDUE', '本轮回访尚未到期')
        stored = one(connection.execute(
            'SELECT * FROM feedback_review_reminders WHERE review_id=?',
            (identifier,),
        ))
        fields = schedule_fields({**review, **(stored or {})}, user, timestamp)
        if not fields['can_remind']:
            raise AppError(409, 'REVIEW_REMINDER_COOLDOWN', '已发送过提醒，请等到下次可提醒时间')
        stamp = utc_text(timestamp)
        connection.execute(
            '''INSERT INTO feedback_review_reminders(review_id,last_reminded_at,reminder_count)
            VALUES (?,?,1) ON CONFLICT(review_id) DO UPDATE SET
            last_reminded_at=excluded.last_reminded_at,reminder_count=reminder_count+1''',
            (identifier, stamp),
        )
        repo.event(connection, item, user, 'REVIEW_REMINDER')
        event_id = connection.execute('SELECT last_insert_rowid()').fetchone()[0]
        connection.execute(
            '''INSERT INTO feedback_inbox(user_id,case_id,event_key,code,title,created_at)
            VALUES (?,?,?,?,?,?)''',
            (
                item['author_id'], item['id'], f'reminder:{event_id}', 'REVIEW_REMINDER',
                '老师提醒你填写课堂体验回访', stamp,
            ),
        )
        result = {
            'id': identifier,
            'case_id': item['id'],
            'last_reminded_at': stamp,
            'next_reminder_at': utc_text(timestamp + REMINDER_INTERVAL),
            'reminder_count': fields['reminder_count'] + 1,
        }
        return repo.remember(connection, user, payload, 'REVIEW_REMIND', result, identifier)
