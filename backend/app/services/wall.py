import hashlib
import json
from datetime import timedelta

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories import wall as repo
from backend.app.repositories.buddies import relation, student_card
from backend.app.repositories.database import connect


def access(connection, owner_id, user):
    owner = student_card(connection, user_id=owner_id)
    if not owner:
        raise AppError(404, 'WALL_NOT_FOUND', '留言墙暂不可访问')
    if owner_id != user['id']:
        connection_item = relation(connection, user['id'], owner_id)
        if not connection_item or connection_item['status'] != 'ACCEPTED':
            raise AppError(403, 'WALL_FORBIDDEN', '成为已确认学伴后才能访问这面留言墙')
    return {key: owner[key] for key in ('id', 'username', 'nickname', 'avatar_color', 'avatar_url')}


def view(item, owner_id, user):
    result = {key: item[key] for key in ('id', 'content', 'visibility', 'version', 'created_at', 'updated_at')}
    result.update(is_mine=item['author_id'] == user['id'], can_delete=user['id'] in (item['author_id'], owner_id))
    return result


def get_message(connection, owner_id, message_id):
    item = repo.message(connection, owner_id, message_id)
    if not item:
        raise AppError(404, 'WALL_MESSAGE_NOT_FOUND', '留言不存在或已删除')
    return item


def listing(owner_id, user, mine, limit, offset):
    with connect() as connection:
        connection.execute('BEGIN')
        owner = access(connection, owner_id, user)
        items, total = repo.listing(connection, owner_id, user['id'], mine, limit, offset)
        return {'owner': owner, 'items': [view(item, owner_id, user) for item in items], 'total': total, 'limit': limit, 'offset': offset}


def create(owner_id, payload, user):
    digest = hashlib.sha256(json.dumps({'owner_id': owner_id, 'content': payload.content, 'visibility': payload.visibility}, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        access(connection, owner_id, user)
        old = repo.previous(connection, user['id'], str(payload.request_id))
        if old:
            if old['payload_hash'] != digest:
                raise AppError(409, 'REQUEST_ID_REUSED', '重复请求的留言内容不一致，请重新提交')
            if old['message_id'] is None:
                raise AppError(410, 'WALL_MESSAGE_DELETED', '这次请求的留言已删除，请重新填写后发送')
            return view(get_message(connection, owner_id, old['message_id']), owner_id, user), False
        if connection.execute('SELECT count(*) FROM buddy_wall_messages WHERE owner_id=?', (owner_id,)).fetchone()[0] >= 1000:
            raise AppError(409, 'WALL_LIMIT', '这面墙的留言已达 1000 条，请先整理已有留言')
        now = now_utc()
        count = connection.execute('SELECT count(*) FROM buddy_wall_keys WHERE author_id=? AND created_at>=?', (user['id'], utc_text(now - timedelta(hours=1)))).fetchone()[0]
        if count >= 30:
            raise AppError(429, 'WALL_RATE_LIMIT', '这一小时已发送 30 条留言，请稍后再试')
        return view(repo.add(connection, owner_id, user['id'], payload, digest, utc_text(now)), owner_id, user), True


def source(owner_id, message_id, user):
    with connect() as connection:
        connection.execute('BEGIN')
        access(connection, owner_id, user)
        item = get_message(connection, owner_id, message_id)
        if item['visibility'] != 'REVEALABLE':
            raise AppError(403, 'SOURCE_PRIVATE', '作者选择了匿名，这条留言不公开来源')
        card = student_card(connection, user_id=item['author_id'])
        if not card:
            raise AppError(404, 'SOURCE_UNAVAILABLE', '来源账号暂不可用')
        # Only explicit source requests expose public study-profile fields.
        return {key: card[key] for key in ('username', 'nickname', 'avatar_color', 'avatar_url', 'bio', 'interests', 'major', 'grade', 'study_goal', 'learning_style')}


def update(owner_id, message_id, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        access(connection, owner_id, user)
        item = get_message(connection, owner_id, message_id)
        if item['author_id'] != user['id']:
            raise AppError(403, 'WALL_EDIT_FORBIDDEN', '只能编辑自己发送的留言')
        if item['version'] != payload.version:
            raise AppError(409, 'VERSION_CONFLICT', '留言已被更新，请先保留草稿，再刷新后编辑')
        connection.execute('UPDATE buddy_wall_messages SET content=?,version=version+1,updated_at=? WHERE id=?', (payload.content, utc_text(now_utc()), message_id))
        return view(repo.message(connection, owner_id, message_id), owner_id, user)


def delete(owner_id, message_id, version, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        item = get_message(connection, owner_id, message_id)
        # Authors may remove their own content even after the buddy relationship ends.
        if item['author_id'] != user['id']:
            access(connection, owner_id, user)
            if owner_id != user['id']:
                raise AppError(403, 'WALL_DELETE_FORBIDDEN', '只能删除自己的留言')
        if item['version'] != version:
            raise AppError(409, 'VERSION_CONFLICT', '留言已被更新，请刷新后再删除')
        connection.execute('DELETE FROM buddy_wall_messages WHERE id=?', (message_id,))


def sent(user, limit, offset):
    with connect() as connection:
        connection.execute('BEGIN')
        items, total = repo.sent(connection, user['id'], limit, offset)
        return {'items': [{**view(item, item['owner_id'], user), 'owner_id': item['owner_id'], 'owner_username': item['owner_username'], 'owner_nickname': item['owner_nickname']} for item in items], 'total': total, 'limit': limit, 'offset': offset}
