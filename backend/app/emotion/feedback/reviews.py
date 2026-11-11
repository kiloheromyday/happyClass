from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import audit
from backend.app.repositories.database import connect
from backend.app.emotion.feedback import access
from backend.app.emotion.feedback import cases
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback import serialization as serial
from backend.app.emotion.feedback.workflow import require_version


def validate_request(connection, item):
    if item['state'] not in ('ACKNOWLEDGED', 'IN_PROGRESS', 'WAITING_STUDENT'):
        raise AppError(409, 'REVIEW_NOT_READY', '请先确认收到或开始处理，再向学生发起回访')
    if repo.open_review(connection, item['id']):
        raise AppError(409, 'REVIEW_ALREADY_OPEN', '本条反馈已有未完成的回访')


def request(identifier, payload, user):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = access.case(connection, identifier, user)
        previous = repo.previous(connection, user, payload, 'REVIEW_CREATE', identifier)
        if previous is not None:
            return previous
        require_version(item, payload.version)
        validate_request(connection, item)
        review_id = repo.add_review(connection, item, user, payload.prompt, payload.due_days)
        cases.first_response(connection, item)
        repo.bump(connection, identifier, 'WAITING_REVIEW')
        repo.event(connection, item, user, 'REVIEW_REQUESTED', payload.prompt, 'WAITING_REVIEW')
        repo.notify(connection, item, user, 'REVIEW_REQUESTED', '老师邀请你回访这次课堂体验')
        audit(connection, user['id'], 'FEEDBACK_REVIEW_REQUESTED', {'case_id': identifier, 'review_id': review_id})
        result = serial.case(connection, repo.case(connection, identifier), user, True)
        return repo.remember(connection, user, payload, 'REVIEW_CREATE', result, identifier)


def answer(identifier, payload, user):
    access.student(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        review, item = access.review(connection, identifier, user)
        previous = repo.previous(connection, user, payload, 'REVIEW_ANSWER', identifier)
        if previous is not None:
            return previous
        if review['state'] != 'OPEN' or item['state'] != 'WAITING_REVIEW':
            raise AppError(409, 'REVIEW_CLOSED', '本轮回访已结束，请刷新后查看处理进度')
        stamp = utc_text(now_utc())
        connection.execute(
            '''INSERT INTO feedback_review_answers(review_id,outcome,emotion,content,created_at)
            VALUES (?,?,?,?,?)''',
            (identifier, payload.outcome, payload.emotion, payload.content, stamp),
        )
        connection.execute(
            "UPDATE feedback_reviews SET state='ANSWERED',version=version+1,closed_at=? WHERE id=?",
            (stamp, identifier),
        )
        state = 'RESOLVED' if payload.outcome == 'HELPED' else 'IN_PROGRESS'
        if state == 'RESOLVED':
            connection.execute(
                "UPDATE feedback_cases SET resolved_at=?,resolution='STUDENT_CONFIRMED' WHERE id=?",
                (stamp, item['id']),
            )
        repo.bump(connection, item['id'], state)
        repo.event(connection, item, user, 'REVIEW_ANSWERED', payload.content, state)
        repo.notify(connection, item, user, 'REVIEW_ANSWERED', '学生已完成课堂情绪回访')
        audit(connection, user['id'], 'FEEDBACK_REVIEW_ANSWERED', {
            'case_id': item['id'], 'review_id': identifier, 'outcome': payload.outcome,
        })
        result = serial.case(connection, repo.case(connection, item['id']), user, True)
        return repo.remember(connection, user, payload, 'REVIEW_ANSWER', result, identifier)


def cancel(identifier, payload, user):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        review, item = access.review(connection, identifier, user)
        previous = repo.previous(connection, user, payload, 'REVIEW_CANCEL', identifier)
        if previous is not None:
            return previous
        require_version(review, payload.version)
        if review['state'] != 'OPEN':
            raise AppError(409, 'REVIEW_CLOSED', '本轮回访已经结束')
        connection.execute(
            "UPDATE feedback_reviews SET state='CANCELLED',version=version+1,closed_at=? WHERE id=?",
            (utc_text(now_utc()), identifier),
        )
        state = 'IN_PROGRESS' if item['state'] == 'WAITING_REVIEW' else item['state']
        repo.bump(connection, item['id'], state)
        repo.event(connection, item, user, 'REVIEW_CANCELLED', payload.content, state)
        repo.notify(connection, item, user, 'REVIEW_CANCELLED', '老师调整了本条反馈的回访安排')
        result = serial.case(connection, repo.case(connection, item['id']), user, True)
        return repo.remember(connection, user, payload, 'REVIEW_CANCEL', result, identifier)


def pending(user, limit=50):
    from backend.app.repositories.classroom import rows
    with connect() as connection:
        conditions, values = repo.scope(user)
        conditions.extend(["r.state='OPEN'", "f.state='WAITING_REVIEW'"])
        items = rows(connection.execute(
            '''SELECT r.*,f.title,f.emotion,f.session_id,c.name AS course_name,s.class_name
            FROM feedback_reviews r JOIN feedback_cases f ON f.id=r.case_id
            JOIN class_sessions s ON s.id=f.session_id JOIN courses c ON c.id=s.course_id
            WHERE ''' + ' AND '.join(conditions) + ' ORDER BY r.due_at,r.id LIMIT ?',
            (*values, limit),
        ))
        return {
            'items': [{
                'id': item['id'],
                'case_id': item['case_id'],
                'case_title': item['title'],
                'prompt': item['prompt'],
                'due_at': item['due_at'],
                'session_id': item['session_id'],
                'course_name': item['course_name'],
                'class_name': item['class_name'],
                'overdue': item['due_at'] < utc_text(now_utc()),
            } for item in items],
            'limit': limit,
        }
