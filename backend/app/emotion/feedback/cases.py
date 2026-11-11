from datetime import datetime, timedelta

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import audit, one
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session
from backend.app.emotion.feedback import access
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback import serialization as serial
from backend.app.emotion.feedback.workflow import next_state, require_version


def validate_filters(connection, filters, user):
    if filters.session_id is not None:
        if user['role'] == 'STUDENT':
            historical = connection.execute(
                'SELECT 1 FROM feedback_cases WHERE session_id=? AND author_id=?',
                (filters.session_id, user['id']),
            ).fetchone()
            if not historical:
                accessible_session(connection, filters.session_id, user)
        else:
            accessible_session(connection, filters.session_id, user)
    if filters.course_id is not None:
        access.course(connection, filters.course_id, user)
    if user['role'] == 'STUDENT' and (
        filters.priority != 'ALL' or filters.watched or filters.sort == 'PRIORITY'
    ):
        raise AppError(403, 'STAFF_FILTER', '学生端不提供内部优先级与关注列表')


def listing(filters, user, offset=0, limit=20):
    with connect() as connection:
        validate_filters(connection, filters, user)
        items, total = repo.listing(connection, user, filters, offset, limit)
        return {
            'items': [serial.case(connection, item, user) for item in items],
            'total': total,
            'offset': offset,
            'limit': limit,
            'has_more': offset + len(items) < total,
        }


def detail(identifier, user):
    with connect() as connection:
        access.case(connection, identifier, user)
        return serial.case(connection, repo.case(connection, identifier), user, True)


def submission_window(connection, session, user):
    policy = repo.policy(connection, session['course_id'])
    starts = datetime.fromisoformat(session['starts_at'])
    ends = datetime.fromisoformat(session['ends_at'])
    timestamp = now_utc()
    deadline = ends + timedelta(hours=policy['submit_grace_hours'])
    count = connection.execute(
        '''SELECT count(*) FROM feedback_cases
        WHERE author_id=? AND session_id=? AND substr(created_at,1,10)=?''',
        (user['id'], session['id'], utc_text(timestamp)[:10]),
    ).fetchone()[0]
    return {
        'can_submit': starts <= timestamp <= deadline and count < policy['daily_case_limit'],
        'starts_at': session['starts_at'],
        'deadline': utc_text(deadline),
        'used_today': count,
        'remaining_today': max(0, policy['daily_case_limit'] - count),
        'daily_limit': policy['daily_case_limit'],
        'reason': '课堂还未开始' if timestamp < starts else '课后反馈时限已过' if timestamp > deadline else '今天本节课提交次数已用完' if count >= policy['daily_case_limit'] else '',
    }


def create(payload, user):
    access.student(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        session = accessible_session(connection, payload.session_id, user)
        previous = repo.previous(connection, user, payload, 'CREATE')
        if previous is not None:
            return previous
        window = submission_window(connection, session, user)
        if not window['can_submit']:
            raise AppError(409, 'SUBMISSION_CLOSED', window['reason'])
        if payload.topic_minute is not None:
            duration = (datetime.fromisoformat(session['ends_at']) - datetime.fromisoformat(session['starts_at'])).total_seconds() / 60
            if payload.topic_minute > duration:
                raise AppError(422, 'TOPIC_OUT_OF_CLASS', '课堂时间点不能超过课堂时长')
        if payload.linked_record_id is not None:
            record = one(connection.execute(
                'SELECT * FROM emoji_records WHERE id=? AND user_id=? AND session_id=?',
                (payload.linked_record_id, user['id'], session['id']),
            ))
            if record is None:
                raise AppError(422, 'INVALID_EMOTION_RECORD', '只能关联自己在本课堂的情绪记录')
        stamp = utc_text(now_utc())
        identifier = connection.execute(
            '''INSERT INTO feedback_cases(
            session_id,author_id,title,content,emotion,reasons,impact,topic_minute,
            linked_record_id,is_demo,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                payload.session_id, user['id'], payload.title, payload.content,
                payload.emotion, repo.encode(payload.reasons), payload.impact,
                payload.topic_minute, payload.linked_record_id,
                int(bool(session.get('is_demo', 0))), stamp, stamp,
            ),
        ).lastrowid
        item = repo.case(connection, identifier)
        repo.event(connection, item, user, 'CREATED')
        repo.notify(connection, item, user, 'CREATED', '课堂收到一条新的情绪反馈')
        audit(connection, user['id'], 'FEEDBACK_CREATED', {'case_id': identifier})
        result = serial.case(connection, item, user, True)
        return repo.remember(connection, user, payload, 'CREATE', result)


def edit(identifier, payload, user):
    access.student(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = access.case(connection, identifier, user)
        previous = repo.previous(connection, user, payload, 'EDIT', identifier)
        if previous is not None:
            return previous
        require_version(item, payload.version)
        if item['state'] != 'NEW':
            raise AppError(409, 'CASE_ALREADY_HANDLED', '老师已开始处理，请通过交流区补充说明')
        connection.execute(
            '''UPDATE feedback_cases SET title=?,content=?,emotion=?,reasons=?,impact=? WHERE id=?''',
            (payload.title, payload.content, payload.emotion, repo.encode(payload.reasons), payload.impact, identifier),
        )
        repo.bump(connection, identifier)
        repo.event(connection, item, user, 'EDITED')
        result = serial.case(connection, repo.case(connection, identifier), user, True)
        return repo.remember(connection, user, payload, 'EDIT', result, identifier)


def acknowledge(connection, item):
    connection.execute(
        'UPDATE feedback_cases SET acknowledged_at=coalesce(acknowledged_at,?) WHERE id=?',
        (utc_text(now_utc()), item['id']),
    )


def first_response(connection, item):
    acknowledge(connection, item)
    connection.execute(
        'UPDATE feedback_cases SET first_response_at=coalesce(first_response_at,?) WHERE id=?',
        (utc_text(now_utc()), item['id']),
    )


def cancel_open_reviews(connection, item, user, detail):
    review = repo.open_review(connection, item['id'])
    if review:
        connection.execute(
            "UPDATE feedback_reviews SET state='CANCELLED',version=version+1,closed_at=? WHERE id=?",
            (utc_text(now_utc()), review['id']),
        )
        repo.event(connection, item, user, 'REVIEW_CANCELLED', detail)


def action(identifier, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        access.case(connection, identifier, user)
        item = repo.case(connection, identifier)
        previous = repo.previous(connection, user, payload, 'ACTION', identifier)
        if previous is not None:
            return previous
        require_version(item, payload.version)
        policy = repo.policy(connection, item['course_id'])
        state = next_state(item, payload.action, user, policy, payload.content)
        if user['role'] != 'STUDENT':
            acknowledge(connection, item)
            if payload.content:
                first_response(connection, item)
        if state in ('RESOLVED', 'WITHDRAWN'):
            cancel_open_reviews(connection, item, user, '反馈单已结束，本轮回访取消')
        if state == 'RESOLVED':
            connection.execute(
                "UPDATE feedback_cases SET resolved_at=?,resolution='STAFF_CLOSED' WHERE id=?",
                (utc_text(now_utc()), identifier),
            )
        if payload.action == 'REOPEN':
            connection.execute(
                'UPDATE feedback_cases SET resolved_at=NULL,resolution=NULL WHERE id=?',
                (identifier,),
            )
        if payload.content:
            repo.add_message(connection, item, user, payload.content)
        repo.event(connection, item, user, payload.action, to_state=state)
        repo.bump(connection, identifier, state)
        repo.notify(connection, item, user, payload.action, '情绪反馈的处理进度已更新')
        audit(connection, user['id'], 'FEEDBACK_STATE_CHANGED', {'case_id': identifier, 'state': state})
        result = serial.case(connection, repo.case(connection, identifier), user, True)
        return repo.remember(connection, user, payload, 'ACTION', result, identifier)


def manage(identifier, payload, user):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = access.case(connection, identifier, user)
        previous = repo.previous(connection, user, payload, 'MANAGE', identifier)
        if previous is not None:
            return previous
        require_version(item, payload.version)
        if item['state'] == 'WITHDRAWN':
            raise AppError(409, 'CASE_WITHDRAWN', '已撤回的反馈不能继续处理')
        connection.execute(
            'UPDATE feedback_cases SET priority=?,tags=? WHERE id=?',
            (payload.priority, repo.encode(payload.tags), identifier),
        )
        if payload.watch is not None:
            set_watch(connection, identifier, user, payload.watch)
        repo.bump(connection, identifier)
        repo.event(connection, item, user, 'MANAGED', visibility='STAFF')
        result = serial.case(connection, repo.case(connection, identifier), user, True)
        return repo.remember(connection, user, payload, 'MANAGE', result, identifier)


def set_watch(connection, identifier, user, enabled):
    if enabled:
        connection.execute(
            'INSERT OR IGNORE INTO feedback_watches(user_id,case_id,created_at) VALUES (?,?,?)',
            (user['id'], identifier, utc_text(now_utc())),
        )
    else:
        connection.execute(
            'DELETE FROM feedback_watches WHERE user_id=? AND case_id=?',
            (user['id'], identifier),
        )


def watch(identifier, enabled, user):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        access.case(connection, identifier, user)
        set_watch(connection, identifier, user, enabled)
        return {'case_id': identifier, 'watched': enabled}


def link(identifier, payload, user):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = access.case(connection, identifier, user)
        previous = repo.previous(connection, user, payload, 'LINK', identifier)
        if previous is not None:
            return previous
        require_version(item, payload.version)
        if item['state'] == 'WITHDRAWN':
            raise AppError(409, 'CASE_WITHDRAWN', '已撤回的反馈不能关联新调整')
        entry = one(connection.execute(
            "SELECT * FROM emotion_insight_entries WHERE id=? AND session_id=? AND kind='ACTION'",
            (payload.adjustment_id, item['session_id']),
        ))
        if entry is None:
            raise AppError(422, 'INVALID_ADJUSTMENT', '只能关联本节课堂的教学调整')
        connection.execute(
            '''INSERT INTO feedback_adjustments(case_id,adjustment_id,public_summary,created_at)
            VALUES (?,?,?,?) ON CONFLICT(case_id,adjustment_id)
            DO UPDATE SET public_summary=excluded.public_summary''',
            (identifier, payload.adjustment_id, payload.public_summary, utc_text(now_utc())),
        )
        repo.bump(connection, identifier)
        repo.event(connection, item, user, 'ADJUSTMENT_LINKED', payload.public_summary)
        repo.notify(connection, item, user, 'ADJUSTMENT_LINKED', '老师补充了一项教学调整')
        result = serial.case(connection, repo.case(connection, identifier), user, True)
        return repo.remember(connection, user, payload, 'LINK', result, identifier)


def unlink(identifier, adjustment_id, payload, user):
    access.staff(user)
    resource = f'{identifier}:{adjustment_id}'
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = access.case(connection, identifier, user)
        previous = repo.previous(connection, user, payload, 'UNLINK', resource)
        if previous is not None:
            return previous
        require_version(item, payload.version)
        changed = connection.execute(
            'DELETE FROM feedback_adjustments WHERE case_id=? AND adjustment_id=?',
            (identifier, adjustment_id),
        ).rowcount
        if not changed:
            raise AppError(404, 'LINK_NOT_FOUND', '关联不存在')
        repo.bump(connection, identifier)
        repo.event(connection, item, user, 'ADJUSTMENT_UNLINKED')
        result = serial.case(connection, repo.case(connection, identifier), user, True)
        return repo.remember(connection, user, payload, 'UNLINK', result, resource)
