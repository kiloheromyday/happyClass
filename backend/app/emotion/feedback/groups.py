from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import audit
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session
from backend.app.emotion.feedback import access, cases, reviews
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback import serialization as serial
from backend.app.emotion.feedback.workflow import next_state, require_version


def validate_members(connection, identifiers, session_id, user):
    result = []
    for identifier in identifiers:
        item = access.case(connection, identifier, user)
        if item['session_id'] != session_id:
            raise AppError(422, 'GROUP_SESSION_MISMATCH', '集中处理组只能包含同一节课堂的反馈')
        result.append(item)
    return result


def listing(user, session_id=None, archived=False):
    access.staff(user)
    with connect() as connection:
        if session_id is not None:
            accessible_session(connection, session_id, user)
        return {'items': [serial.group(connection, item, user) for item in repo.groups(connection, user, session_id, archived)]}


def detail(identifier, user):
    with connect() as connection:
        item = access.group(connection, identifier, user)
        return serial.group(connection, item, user, True)


def save(payload, user, identifier=None):
    access.staff(user)
    operation = 'GROUP_CREATE' if identifier is None else 'GROUP_UPDATE'
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        existing = None
        if identifier is None:
            accessible_session(connection, payload.session_id, user)
            session_id = payload.session_id
        else:
            existing = access.group(connection, identifier, user)
            session_id = existing['session_id']
        previous = repo.previous(connection, user, payload, operation, identifier)
        if previous is not None:
            return previous
        validate_members(connection, payload.case_ids, session_id, user)
        stamp = utc_text(now_utc())
        if existing:
            require_version(existing, payload.version)
            connection.execute(
                '''UPDATE feedback_groups SET title=?,description=?,archived=?,
                version=version+1,updated_at=? WHERE id=?''',
                (payload.title, payload.description, int(payload.archived), stamp, identifier),
            )
            connection.execute('DELETE FROM feedback_group_members WHERE group_id=?', (identifier,))
        else:
            identifier = connection.execute(
                '''INSERT INTO feedback_groups(session_id,title,description,created_by,created_at,updated_at)
                VALUES (?,?,?,?,?,?)''',
                (session_id, payload.title, payload.description, user['id'], stamp, stamp),
            ).lastrowid
        connection.executemany(
            'INSERT INTO feedback_group_members(group_id,case_id) VALUES (?,?)',
            [(identifier, value) for value in payload.case_ids],
        )
        item = access.group(connection, identifier, user)
        result = serial.group(connection, item, user, True)
        return repo.remember(connection, user, payload, operation, result, existing['id'] if existing else None)


def batch(identifier, payload, user):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        group = access.group(connection, identifier, user)
        previous = repo.previous(connection, user, payload, 'GROUP_BATCH', identifier)
        if previous is not None:
            return previous
        require_version(group, payload.version)
        if group['archived']:
            raise AppError(409, 'GROUP_ARCHIVED', '处理组已归档，请先取消归档')
        if payload.action == 'REQUEST_REVIEW' and len(payload.content) > 1000:
            raise AppError(422, 'REVIEW_PROMPT_TOO_LONG', '回访问题最多 1000 字')
        member_ids = {item['id'] for item in repo.group_members(connection, identifier)}
        plan = []
        for member in payload.members:
            if member.case_id not in member_ids:
                raise AppError(422, 'NOT_GROUP_MEMBER', '选择中包含不属于本组的反馈')
            item = access.case(connection, member.case_id, user)
            require_version(item, member.version)
            if item['state'] in ('RESOLVED', 'WITHDRAWN'):
                raise AppError(409, 'BATCH_CLOSED_CASE', '选择中有已结束的反馈，请刷新后重新选择')
            state = item['state']
            if payload.action == 'REQUEST_REVIEW':
                reviews.validate_request(connection, item)
                state = 'WAITING_REVIEW'
            elif payload.action in ('ACKNOWLEDGE', 'START'):
                state = next_state(item, payload.action, user, {}, payload.content)
            elif state == 'NEW':
                state = 'ACKNOWLEDGED'
            plan.append((item, state))
        affected = []
        for item, state in plan:
            cases.first_response(connection, item)
            code = 'GROUP_REPLY'
            if payload.action == 'REQUEST_REVIEW':
                repo.add_review(connection, item, user, payload.content, payload.due_days)
                code = 'REVIEW_REQUESTED'
            else:
                repo.add_message(connection, item, user, payload.content)
                if payload.action in ('ACKNOWLEDGE', 'START'):
                    code = payload.action
            repo.event(connection, item, user, code, to_state=state)
            repo.bump(connection, item['id'], state)
            repo.notify(connection, item, user, code, '老师更新了本条情绪反馈的处理进度')
            affected.append(item['id'])
        connection.execute(
            'UPDATE feedback_groups SET version=version+1,updated_at=? WHERE id=?',
            (utc_text(now_utc()), identifier),
        )
        audit(connection, user['id'], 'FEEDBACK_BATCH_PROCESSED', {
            'group_id': identifier,
            'case_ids': affected,
            'action': payload.action,
        })
        result = {
            'affected_count': len(affected),
            'case_ids': affected,
            'group': serial.group(connection, access.group(connection, identifier, user), user, True),
        }
        return repo.remember(connection, user, payload, 'GROUP_BATCH', result, identifier)
