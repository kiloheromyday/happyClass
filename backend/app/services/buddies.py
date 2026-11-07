from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories import buddies as repo
from backend.app.repositories.classroom import audit
from backend.app.repositories.database import connect
from backend.app.services.auth import limit_attempt
from backend.app.services.inbox import notify


def relationship(item, user_id):
    return 'NONE' if not item else 'FRIEND' if item['status'] == 'ACCEPTED' else 'OUTGOING' if item['requester_id'] == user_id else 'INCOMING'


def lookup(user, filters):
    limit_attempt(f'buddy-search:{user["id"]}', 60, 300)
    with connect() as connection:
        items, total = repo.search_students(connection, user['id'], filters)
    for item in items:
        status, requester = item.pop('connection_status'), item.pop('requester_id')
        item['relationship'] = 'NONE' if not status else 'FRIEND' if status == 'ACCEPTED' else 'OUTGOING' if requester == user['id'] else 'INCOMING'
    return {'items': items, 'total': total, 'limit': filters.limit, 'offset': filters.offset}


def list_buddies(user):
    with connect() as connection:
        items = repo.list_connections(connection, user['id'])
    return {
        'friends': [item for item in items if item['status'] == 'ACCEPTED'],
        'incoming': [item for item in items if item['status'] == 'PENDING' and item['requester_id'] != user['id']],
        'outgoing': [item for item in items if item['status'] == 'PENDING' and item['requester_id'] == user['id']],
    }


def send_request(user, target_id):
    if target_id == user['id']:
        raise AppError(422, 'SELF_REQUEST', '不能添加自己为学伴')
    limit_attempt(f'buddy-send:{user["id"]}', 20, 3600)
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        if not repo.student_card(connection, user_id=target_id):
            raise AppError(404, 'STUDENT_NOT_FOUND', '未找到该学生账号')
        previous = repo.relation(connection, user['id'], target_id)
        if previous:
            return {'request_id': previous['id'], 'relationship': relationship(previous, user['id'])}
        if any(repo.count_connections(connection, identifier) >= 200 for identifier in (user['id'], target_id)):
            raise AppError(409, 'BUDDY_LIMIT', '学伴及待处理申请已达上限，请先处理已有申请')
        low, high = sorted((user['id'], target_id))
        identifier = connection.execute('INSERT INTO buddy_connections(low_user_id,high_user_id,requester_id) VALUES (?,?,?)', (low, high, user['id'])).lastrowid
        audit(connection, user['id'], 'BUDDY_REQUEST_SENT', {'request_id': identifier, 'target_id': target_id})
        notify(connection, target_id, f'buddy:{identifier}:created', 'BUDDY', '收到学伴申请', '有同学希望成为你的学伴，进入好友学伴处理。', 'buddies')
        return {'request_id': identifier, 'relationship': 'OUTGOING'}


def owned_request(connection, user, request_id):
    item = repo.by_id(connection, request_id)
    if not item or user['id'] not in (item['low_user_id'], item['high_user_id']):
        raise AppError(404, 'REQUEST_NOT_FOUND', '申请不存在或已处理')
    return item


def accept(user, request_id):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = owned_request(connection, user, request_id)
        if item['requester_id'] == user['id']:
            raise AppError(403, 'NOT_RECIPIENT', '只有收到申请的一方可以同意')
        other = item['high_user_id'] if item['low_user_id'] == user['id'] else item['low_user_id']
        if not repo.student_card(connection, user_id=other):
            raise AppError(404, 'STUDENT_NOT_FOUND', '对方账号已不可用')
        if item['status'] == 'PENDING':
            connection.execute("UPDATE buddy_connections SET status='ACCEPTED',accepted_at=? WHERE id=?", (utc_text(now_utc()), request_id))
            audit(connection, user['id'], 'BUDDY_REQUEST_ACCEPTED', {'request_id': request_id})
            notify(connection, item['requester_id'], f'buddy:{request_id}:accepted', 'BUDDY', '学伴申请已通过', '你们已成为学伴，可以去留言墙打个招呼。', 'buddies')


def dismiss(user, request_id):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = owned_request(connection, user, request_id)
        if item['status'] != 'PENDING':
            raise AppError(409, 'REQUEST_ALREADY_ACCEPTED', '已成为学伴，请从学伴列表移除')
        connection.execute('DELETE FROM buddy_connections WHERE id=?', (request_id,))
        audit(connection, user['id'], 'BUDDY_REQUEST_CANCELLED' if item['requester_id'] == user['id'] else 'BUDDY_REQUEST_DECLINED', {'request_id': request_id})


def remove(user, target_id):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = repo.relation(connection, user['id'], target_id)
        if not item or item['status'] != 'ACCEPTED':
            raise AppError(404, 'BUDDY_NOT_FOUND', '学伴关系已不存在')
        connection.execute('DELETE FROM buddy_connections WHERE id=?', (item['id'],))
        audit(connection, user['id'], 'BUDDY_REMOVED', {'target_id': target_id})
