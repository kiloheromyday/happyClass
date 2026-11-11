from datetime import datetime, timedelta

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import one
from backend.app.repositories.database import connect
from backend.app.emotion.feedback import access
from backend.app.emotion.feedback import cases
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback import serialization as serial
from backend.app.emotion.feedback.workflow import require_version


def page(identifier, user, before_id=None, limit=40):
    with connect() as connection:
        parent = access.case(connection, identifier, user)
        items = repo.messages(connection, identifier, user, before_id, limit + 1)
        has_more = len(items) > limit
        items = items[:limit]
        return {
            'items': [
                {**serial.message(item, user), 'can_edit': False}
                if parent['state'] in ('RESOLVED', 'WITHDRAWN') else serial.message(item, user)
                for item in reversed(items)
            ],
            'has_more': has_more,
            'next_before_id': items[-1]['id'] if items and has_more else None,
        }


def history(identifier, user, before_id=None, limit=60):
    with connect() as connection:
        access.case(connection, identifier, user)
        items = repo.events(connection, identifier, user, before_id, limit + 1)
        has_more = len(items) > limit
        items = items[:limit]
        return {
            'items': [serial.event(item, user) for item in items],
            'has_more': has_more,
            'next_before_id': items[-1]['id'] if items and has_more else None,
        }


def ensure_active(item):
    if item['state'] in ('RESOLVED', 'WITHDRAWN'):
        raise AppError(409, 'CASE_CLOSED', '反馈已经结束，不能继续回复')


def reply(identifier, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = access.case(connection, identifier, user)
        if user['role'] == 'STUDENT' and payload.visibility != 'SHARED':
            raise AppError(403, 'INTERNAL_NOTE_FORBIDDEN', '学生不能添加教师内部备注')
        previous = repo.previous(connection, user, payload, 'MESSAGE', identifier)
        if previous is not None:
            return previous
        ensure_active(item)
        if payload.template_id is not None:
            access.staff(user)
            template = access.owned(connection, 'feedback_templates', payload.template_id, user)
            if template['archived']:
                raise AppError(409, 'TEMPLATE_ARCHIVED', '模板已归档，请刷新模板列表')
            connection.execute(
                'UPDATE feedback_templates SET uses=uses+1 WHERE id=?',
                (template['id'],),
            )
        message = repo.add_message(connection, item, user, payload.content, payload.visibility)
        state = item['state']
        if payload.visibility == 'SHARED':
            if user['role'] != 'STUDENT':
                cases.first_response(connection, item)
                if state == 'NEW':
                    state = 'ACKNOWLEDGED'
            elif state == 'WAITING_STUDENT':
                state = 'IN_PROGRESS'
        repo.bump(connection, identifier, state)
        repo.event(connection, item, user, 'MESSAGE', to_state=state, visibility=payload.visibility)
        if payload.visibility == 'SHARED':
            repo.notify(connection, item, user, 'MESSAGE', '情绪反馈收到一条新的回应')
        result = {
            'message': serial.message(message, user),
            'case': serial.case(connection, repo.case(connection, identifier), user, True),
        }
        return repo.remember(connection, user, payload, 'MESSAGE', result, identifier)


def editable(connection, case_id, message_id, user):
    item = one(connection.execute(
        'SELECT * FROM feedback_messages WHERE id=? AND case_id=?',
        (message_id, case_id),
    ))
    if item is None or (item['visibility'] == 'STAFF' and user['role'] == 'STUDENT'):
        raise AppError(404, 'MESSAGE_NOT_FOUND', '交流记录不存在')
    if item['actor_id'] != user['id']:
        raise AppError(403, 'MESSAGE_NOT_OWN', '只能修订或撤回自己发送的内容')
    if item['deleted']:
        raise AppError(409, 'MESSAGE_REMOVED', '这条交流记录已撤回')
    if now_utc() > datetime.fromisoformat(item['created_at']) + timedelta(minutes=10):
        raise AppError(409, 'MESSAGE_EDIT_EXPIRED', '发送已超过十分钟，请用新消息补充说明')
    return item


def edit(identifier, message_id, payload, user, remove=False):
    resource = f'{identifier}:{message_id}'
    operation = 'MESSAGE_REMOVE' if remove else 'MESSAGE_EDIT'
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        parent = access.case(connection, identifier, user)
        previous = repo.previous(connection, user, payload, operation, resource)
        if previous is not None:
            return previous
        ensure_active(parent)
        item = editable(connection, identifier, message_id, user)
        require_version(item, payload.version)
        connection.execute(
            '''UPDATE feedback_messages SET content=?,deleted=?,version=version+1,updated_at=?
            WHERE id=?''',
            ('' if remove else payload.content, int(remove), utc_text(now_utc()), message_id),
        )
        repo.event(
            connection, parent, user,
            'MESSAGE_REMOVED' if remove else 'MESSAGE_EDITED',
            visibility=item['visibility'],
        )
        repo.bump(connection, identifier)
        updated = one(connection.execute('SELECT * FROM feedback_messages WHERE id=?', (message_id,)))
        result = serial.message(updated, user)
        return repo.remember(connection, user, payload, operation, result, resource)
