from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.app.models.classroom import utc_text
from backend.app.repositories.database import connect, initialize_database
from test_classroom import HEADERS, actors


def befriend(actors):
    low, high = sorted([actors['student']['user']['id'], actors['other_student']['user']['id']])
    with connect() as connection:
        connection.execute("INSERT INTO buddy_connections(low_user_id,high_user_id,requester_id,status,accepted_at) VALUES (?,?,?,'ACCEPTED',?)", (low, high, low, utc_text(datetime.now(UTC))))


def path(actors, owner='student', suffix=''):
    return f"/api/buddy-wall/{actors[owner]['user']['id']}" + suffix


def post(actors, author='student', owner='student', **changes):
    return actors[author]['client'].post(path(actors, owner), json={'content': '一起把这个小目标完成吧！', 'request_id': str(uuid4()), **changes}, headers=HEADERS)


def test_anonymous_list_never_contains_source_and_no_one_can_unmask(actors):
    befriend(actors)
    response = post(actors, author='other_student')
    assert response.status_code == 201
    item = response.json()['data']
    allowed = {'id', 'content', 'visibility', 'version', 'created_at', 'updated_at', 'is_mine', 'can_delete'}
    assert set(item) == allowed and item['visibility'] == 'ANONYMOUS'
    for actor in ('student', 'other_student'):
        client = actors[actor]['client']
        listing = client.get(path(actors)).json()['data']
        assert set(listing['items'][0]) == allowed
        assert listing['items'][0]['is_mine'] is (actor == 'other_student')
        assert client.get(path(actors, suffix=f"/{item['id']}/source")).status_code == 403
    for role in ('teacher', 'admin'):
        assert actors[role]['client'].get(path(actors, suffix=f"/{item['id']}/source")).status_code == 403


def test_revealable_source_explicit_whitelist_and_live_profile(actors):
    befriend(actors)
    response = post(actors, author='other_student', visibility='REVEALABLE')
    item = response.json()['data']
    assert 'username' not in item and 'author_id' not in item
    client = actors['student']['client']
    with connect() as connection:
        connection.execute("INSERT INTO user_profiles(user_id,nickname,bio,interests,major,grade) VALUES (?,'小禾','一起读书','阅读','数字媒体','大二')", (actors['other_student']['user']['id'],))
    source = client.get(path(actors, suffix=f"/{item['id']}/source")).json()['data']
    assert set(source) == {'username', 'nickname', 'avatar_color', 'avatar_url', 'bio', 'interests', 'major', 'grade', 'study_goal', 'learning_style'}
    assert source['username'] == 'other_student' and source['nickname'] == '小禾'
    with connect() as connection:
        connection.execute("UPDATE user_profiles SET nickname='新昵称' WHERE user_id=?", (actors['other_student']['user']['id'],))
    assert client.get(path(actors, suffix=f"/{item['id']}/source")).json()['data']['nickname'] == '新昵称'
    # Identity mode is fixed at publication, including when the author edits content.
    forged = actors['other_student']['client'].put(path(actors, suffix=f"/{item['id']}"), json={'content': '更改', 'version': 1, 'visibility': 'ANONYMOUS'}, headers=HEADERS)
    assert forged.status_code == 422


def test_wall_requires_accepted_relation_and_student_role(actors):
    item = post(actors).json()['data']
    peer = actors['other_student']['client']
    assert peer.get(path(actors)).status_code == 403
    assert post(actors, author='other_student').status_code == 403
    low, high = sorted([actors['student']['user']['id'], actors['other_student']['user']['id']])
    with connect() as connection:
        connection.execute('INSERT INTO buddy_connections(low_user_id,high_user_id,requester_id) VALUES (?,?,?)', (low, high, low))
    assert peer.get(path(actors)).status_code == 403
    with connect() as connection:
        connection.execute("UPDATE buddy_connections SET status='ACCEPTED',accepted_at=?", (utc_text(datetime.now(UTC)),))
    assert peer.get(path(actors)).status_code == 200
    assert post(actors, author='other_student').status_code == 201
    for role in ('teacher', 'admin', 'other_teacher'):
        client = actors[role]['client']
        assert client.get(path(actors)).status_code == 403
        assert client.get('/api/buddy-wall/sent').status_code == 403
        assert post(actors, author=role).status_code == 403
        assert client.delete(path(actors, suffix=f"/{item['id']}?version=1"), headers=HEADERS).status_code == 403
    assert peer.get('/api/buddy-wall/99999').status_code == 404


def test_edit_delete_owner_permissions_and_versions(actors):
    befriend(actors)
    item = post(actors, author='other_student').json()['data']
    url = path(actors, suffix=f"/{item['id']}")
    owner, author = actors['student']['client'], actors['other_student']['client']
    assert owner.put(url, json={'content': '代为修改', 'version': 1}, headers=HEADERS).status_code == 403
    updated = author.put(url, json={'content': ' 我们明天一起复习\n第一章。 ', 'version': 1}, headers=HEADERS)
    assert updated.status_code == 200 and updated.json()['data']['version'] == 2
    assert updated.json()['data']['content'] == '我们明天一起复习\n第一章。'
    assert 'author_id' not in updated.json()['data']
    assert author.put(url, json={'content': '旧版覆盖', 'version': 1}, headers=HEADERS).status_code == 409
    assert owner.delete(url + '?version=1', headers=HEADERS).status_code == 409
    assert owner.delete(url + '?version=2', headers=HEADERS).status_code == 200
    assert owner.get(path(actors)).json()['data']['total'] == 0


def test_cannot_edit_or_delete_other_wall_or_others_message(actors):
    befriend(actors)
    mine = post(actors).json()['data']
    peer = actors['other_student']['client']
    assert peer.delete(path(actors, suffix=f"/{mine['id']}?version=1"), headers=HEADERS).status_code == 403
    assert peer.put(path(actors, suffix=f"/{mine['id']}"), json={'content': '篡改', 'version': 1}, headers=HEADERS).status_code == 403
    assert peer.get(path(actors, owner='other_student', suffix=f"/{mine['id']}/source")).status_code == 404
    assert peer.delete(path(actors, owner='other_student', suffix=f"/{mine['id']}?version=1"), headers=HEADERS).status_code == 404


def test_sent_messages_allow_author_cleanup_after_unfriend(actors):
    befriend(actors)
    item = post(actors, author='other_student', visibility='REVEALABLE').json()['data']
    with connect() as connection:
        connection.execute('DELETE FROM buddy_connections')
    peer = actors['other_student']['client']
    assert peer.get(path(actors)).status_code == 403
    assert peer.get(path(actors, suffix=f"/{item['id']}/source")).status_code == 403
    assert peer.put(path(actors, suffix=f"/{item['id']}"), json={'content': '修改', 'version': 1}, headers=HEADERS).status_code == 403
    sent = peer.get('/api/buddy-wall/sent').json()['data']
    assert sent['total'] == 1 and sent['items'][0]['owner_username'] == 'student'
    assert actors['student']['client'].get('/api/buddy-wall/sent').json()['data']['total'] == 0
    assert peer.delete(path(actors, suffix=f"/{item['id']}?version=1"), headers=HEADERS).status_code == 200
    assert peer.get('/api/buddy-wall/sent').json()['data']['total'] == 0


def test_idempotent_create_and_deleted_request_never_resurrects(actors):
    key = str(uuid4())
    item = post(actors, request_id=key).json()['data']
    assert post(actors, request_id=key).status_code == 200
    assert post(actors, request_id=key, visibility='REVEALABLE').status_code == 409
    assert post(actors, request_id=key, content='另一条').status_code == 409
    actors['student']['client'].delete(path(actors, suffix=f"/{item['id']}?version=1"), headers=HEADERS)
    assert post(actors, request_id=key).status_code == 410


@pytest.mark.parametrize('changes', [dict(content=' '), dict(content='x' * 601), dict(content='\x00'), dict(author_id=999), dict(owner_id=999), dict(visibility='REAL'), dict(visibility=True), dict(request_id='bad')])
def test_wall_input_validation(actors, changes):
    assert post(actors, **changes).status_code == 422


def test_csrf_pagination_and_mine_filter(actors):
    befriend(actors)
    client = actors['student']['client']
    assert client.post(path(actors), json={'content': 'test', 'request_id': str(uuid4())}).status_code == 403
    for index in range(13):
        assert post(actors, content=f'自己的留言 {index}').status_code == 201
    other = post(actors, author='other_student').json()['data']
    first = client.get(path(actors)).json()['data']
    second = client.get(path(actors), params={'offset': 12}).json()['data']
    assert first['total'] == 14 and len(first['items']) == 12 and len(second['items']) == 2
    assert not {item['id'] for item in first['items']} & {item['id'] for item in second['items']}
    assert client.get(path(actors), params={'mine': True}).json()['data']['total'] == 13
    assert client.delete(path(actors, suffix=f"/{other['id']}?version=1")).status_code == 403
    for query in ('limit=100', 'offset=-1', 'mine=oops'):
        assert client.get(path(actors) + '?' + query).status_code == 422


def test_disabled_author_and_owner_do_not_expose_source(actors):
    befriend(actors)
    item = post(actors, author='other_student', visibility='REVEALABLE').json()['data']
    with connect() as connection:
        connection.execute("UPDATE users SET status='DISABLED' WHERE id=?", (actors['other_student']['user']['id'],))
    client = actors['student']['client']
    assert client.get(path(actors)).json()['data']['total'] == 0
    assert client.get(path(actors, suffix=f"/{item['id']}/source")).status_code == 404
    # An active student cannot open a disabled wall owner.
    assert client.get(path(actors, owner='other_student')).status_code == 404


def test_post_rate_limit_survives_deletion(actors):
    client = actors['student']['client']
    for index in range(30):
        response = post(actors, content=f'留言 {index}')
        assert response.status_code == 201
        item = response.json()['data']
        client.delete(path(actors, suffix=f"/{item['id']}?version=1"), headers=HEADERS)
    assert post(actors).status_code == 429


def test_wall_limit_and_old_database_initialization(actors):
    initialize_database()
    with connect() as connection:
        connection.execute('DROP TABLE buddy_wall_keys')
        connection.execute('DROP TABLE buddy_wall_messages')
    initialize_database()
    item = post(actors).json()['data']
    initialize_database()
    assert actors['student']['client'].get(path(actors)).json()['data']['items'][0]['id'] == item['id']
    stamp = utc_text(datetime.now(UTC))
    identifier = actors['student']['user']['id']
    with connect() as connection:
        connection.executemany('INSERT INTO buddy_wall_messages(owner_id,author_id,content,created_at,updated_at) VALUES (?,?,?,?,?)', [(identifier, identifier, f'留言 {index}', stamp, stamp) for index in range(999)])
    assert post(actors).status_code == 409
