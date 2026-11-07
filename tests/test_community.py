from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.repositories.database import connect, initialize_database
from backend.app.services.auth import provision_user

HEADERS = {'X-Requested-With': 'EmojiClassroom', 'Origin': 'http://127.0.0.1:18080'}
PASSWORD = 'CommunityCheck123!'


def login(client, username):
    response = client.post('/api/auth/login', json={'username': username, 'password': PASSWORD}, headers=HEADERS)
    assert response.status_code == 200


def accounts(client):
    people = [provision_user(name, PASSWORD, 'STUDENT', name + '@example.test') for name in ('alice', 'bobby', 'carol')]
    login(client, 'alice')
    return people


def test_profile_defaults_roundtrip_persistence_and_no_privilege_change(client):
    alice, _, _ = accounts(client)
    assert client.get('/api/users/me').json()['data']['nickname'] == ''
    payload = {'nickname': '  小林  ', 'email': 'New@Example.test', 'bio': '一起学设计', 'interests': '设计 / Python', 'avatar_color': 'sky'}
    response = client.put('/api/users/me', json=payload, headers=HEADERS)
    assert response.status_code == 200
    result = response.json()['data']
    assert result['nickname'] == '小林' and result['email'] == 'new@example.test'
    assert result['username'] == 'alice' and result['role'] == 'STUDENT'
    initialize_database()  # Additive initialization remains safe on an existing database.
    assert client.get('/api/users/me').json()['data']['avatar_color'] == 'sky'
    login(client, 'alice')
    assert client.get('/api/users/me').json()['data']['bio'] == '一起学设计'
    assert client.put('/api/users/me', json={**payload, 'role': 'ADMIN'}, headers=HEADERS).status_code == 422
    assert client.put('/api/users/me', json={**payload, 'username': 'changed'}, headers=HEADERS).status_code == 422
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM audit_logs WHERE action='PROFILE_UPDATED' AND actor_id=?", (alice['id'],)).fetchone()[0] == 1


@pytest.mark.parametrize('invalid', [{'nickname': 'x' * 33}, {'bio': 'x' * 161}, {'interests': 'x' * 81}, {'email': 'bad-email'}, {'avatar_color': 'javascript:red'}, {'nickname': 'bad\nname'}])
def test_profile_validation_and_conflict_are_atomic(client, invalid):
    accounts(client)
    assert client.put('/api/users/me', json=invalid, headers=HEADERS).status_code == 422
    assert client.put('/api/users/me', json={'email': 'bobby@example.test', 'nickname': 'should roll back'}, headers=HEADERS).status_code == 409
    me = client.get('/api/users/me').json()['data']
    assert me['nickname'] == '' and me['email'] == 'alice@example.test'


def test_profile_writes_require_session_and_origin(client):
    assert client.put('/api/users/me', json={}, headers=HEADERS).status_code == 401
    accounts(client)
    assert client.put('/api/users/me', json={}).status_code == 403
    assert client.put('/api/users/me', json={}, headers={**HEADERS, 'Origin': 'https://evil.test'}).status_code == 403


def test_buddy_flow_is_mutual_private_and_persistent(client):
    alice, bobby, _ = accounts(client)
    found = client.get('/api/buddies/search', params={'username': 'BOBBY'}).json()['data']['items']
    assert len(found) == 1 and found[0]['relationship'] == 'NONE'
    assert not {'email', 'role', 'password_hash', 'created_at'}.intersection(found[0])
    assert client.get('/api/buddies/search?username=alice').json()['data']['items'] == []
    assert client.get('/api/buddies/search?username=bob').json()['data']['items'] == []
    request = client.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS).json()['data']
    request_id = request['request_id']
    assert request['relationship'] == 'OUTGOING'
    assert client.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS).json()['data']['request_id'] == request_id
    assert client.post(f'/api/buddies/requests/{request_id}/accept', headers=HEADERS).status_code == 403
    assert client.get('/api/buddies').json()['data']['friends'] == []
    login(client, 'bobby')
    assert client.get('/api/buddies').json()['data']['incoming'][0]['id'] == alice['id']
    # A reversed request does not silently accept the invitation.
    assert client.post('/api/buddies/requests', json={'user_id': alice['id']}, headers=HEADERS).json()['data']['relationship'] == 'INCOMING'
    assert client.post(f'/api/buddies/requests/{request_id}/accept', headers=HEADERS).status_code == 200
    assert client.post(f'/api/buddies/requests/{request_id}/accept', headers=HEADERS).status_code == 200
    friends = client.get('/api/buddies').json()['data']['friends']
    assert len(friends) == 1 and friends[0]['id'] == alice['id'] and 'email' not in friends[0]
    assert client.delete(f'/api/buddies/requests/{request_id}', headers=HEADERS).status_code == 409
    login(client, 'alice')
    assert client.get('/api/buddies').json()['data']['friends'][0]['id'] == bobby['id']
    assert client.delete(f'/api/buddies/{bobby["id"]}', headers=HEADERS).status_code == 200
    login(client, 'bobby')
    assert client.get('/api/buddies').json()['data']['friends'] == []


def test_request_authorization_rejection_cancellation_and_stale_ids(client):
    alice, bobby, carol = accounts(client)
    request_id = client.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS).json()['data']['request_id']
    login(client, 'carol')
    assert client.post(f'/api/buddies/requests/{request_id}/accept', headers=HEADERS).status_code == 404
    assert client.delete(f'/api/buddies/requests/{request_id}', headers=HEADERS).status_code == 404
    assert client.delete(f'/api/buddies/{alice["id"]}', headers=HEADERS).status_code == 404
    login(client, 'bobby')
    assert client.delete(f'/api/buddies/requests/{request_id}', headers=HEADERS).status_code == 200
    login(client, 'alice')
    next_id = client.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS).json()['data']['request_id']
    assert next_id > request_id
    assert client.delete(f'/api/buddies/requests/{request_id}', headers=HEADERS).status_code == 404
    assert client.delete(f'/api/buddies/requests/{next_id}', headers=HEADERS).status_code == 200


def test_buddy_limits_validation_disabled_and_nonstudent_targets(client):
    alice, bobby, _ = accounts(client)
    teacher = provision_user('teacher', PASSWORD, 'TEACHER', None)
    assert client.post('/api/buddies/requests', json={'user_id': alice['id']}, headers=HEADERS).status_code == 422
    assert client.post('/api/buddies/requests', json={'user_id': teacher['id']}, headers=HEADERS).status_code == 404
    assert client.post('/api/buddies/requests', json={'user_id': True}, headers=HEADERS).status_code == 422
    assert client.get('/api/buddies/search?username=teacher').json()['data']['items'] == []
    assert client.get('/api/buddies/search?username=a%20b').status_code == 422
    assert client.post('/api/buddies/requests', json={'user_id': bobby['id']}).status_code == 403
    with connect() as connection:
        connection.execute("UPDATE users SET status='DISABLED' WHERE id=?", (bobby['id'],))
    assert client.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS).status_code == 404
    assert client.get('/api/buddies/search?username=bobby').json()['data']['items'] == []
    login(client, 'teacher')
    assert client.get('/api/buddies').status_code == 403
    assert client.post('/api/buddies/requests', json={'user_id': alice['id']}, headers=HEADERS).status_code == 403


def test_pending_sender_disabled_cannot_be_accepted(client):
    alice, bobby, _ = accounts(client)
    request_id = client.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS).json()['data']['request_id']
    login(client, 'bobby')
    with connect() as connection:
        connection.execute("UPDATE users SET status='DISABLED' WHERE id=?", (alice['id'],))
    assert client.post(f'/api/buddies/requests/{request_id}/accept', headers=HEADERS).status_code == 404
    assert client.get('/api/buddies').json()['data']['incoming'] == []


def test_concurrent_duplicate_requests_create_one_relationship(client):
    _, bobby, _ = accounts(client)
    token = client.cookies.get('classroom_session')
    def send(_):
        with TestClient(app) as other:
            other.cookies.set('classroom_session', token)
            return other.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(send, range(2)))
    assert all(response.status_code == 200 for response in replies)
    assert len({response.json()['data']['request_id'] for response in replies}) == 1
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM buddy_connections').fetchone()[0] == 1


def test_friendship_does_not_grant_access_to_emotion_history(client):
    alice, bobby, _ = accounts(client)
    teacher = provision_user('teacher', PASSWORD, 'TEACHER', None)
    with connect() as connection:
        course = connection.execute('INSERT INTO courses(name,teacher_id) VALUES (?,?)', ('Private', teacher['id'])).lastrowid
        session = connection.execute('INSERT INTO class_sessions(course_id,starts_at,ends_at,classroom,class_name) VALUES (?,?,?,?,?)', (course, '2026-01-01T00:00:00Z', '2027-01-01T00:00:00Z', 'Room', 'Class')).lastrowid
        connection.execute("INSERT INTO emoji_records(user_id,session_id,emotion,source) VALUES (?,?,'SAD','MANUAL')", (bobby['id'], session))
    request_id = client.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS).json()['data']['request_id']
    login(client, 'bobby')
    client.post(f'/api/buddies/requests/{request_id}/accept', headers=HEADERS)
    login(client, 'alice')
    assert client.get('/api/emoji/history').json()['data']['total'] == 0
    assert client.get(f'/api/sessions/{session}/statistics').status_code == 403


def test_search_and_send_rate_limits(client):
    _, bobby, _ = accounts(client)
    for _ in range(20):
        assert client.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS).status_code == 200
    assert client.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS).status_code == 429
    for _ in range(60):
        assert client.get('/api/buddies/search?username=bobby').status_code == 200
    assert client.get('/api/buddies/search?username=bobby').status_code == 429


def test_connection_cap_prevents_unbounded_lists(client):
    alice, bobby, _ = accounts(client)
    with connect() as connection:
        for index in range(200):
            identifier = connection.execute("INSERT INTO users(username,password_hash,role) VALUES (?,?,'STUDENT')", (f'cap_student_{index}', 'unused')).lastrowid
            low, high = sorted((alice['id'], identifier))
            connection.execute('INSERT INTO buddy_connections(low_user_id,high_user_id,requester_id) VALUES (?,?,?)', (low, high, alice['id']))
    assert client.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS).status_code == 409
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM buddy_connections').fetchone()[0] == 200


def test_additive_upgrade_preserves_existing_account_data(client, tmp_path, monkeypatch):
    import sqlite3
    from contextlib import closing
    from backend.app.repositories.database import SCHEMA_FILE
    legacy_path = tmp_path / 'legacy.db'
    with closing(sqlite3.connect(legacy_path)) as connection:
        with connection:
            connection.executescript(SCHEMA_FILE.read_text(encoding='utf-8').split('CREATE TABLE IF NOT EXISTS user_profiles')[0])
            connection.execute("INSERT INTO users(username,password_hash,role,email) VALUES ('legacy_student','legacy-hash','STUDENT','legacy@example.test')")
    monkeypatch.setenv('EMOJI_DATABASE_PATH', str(legacy_path))
    initialize_database()
    initialize_database()
    with connect() as connection:
        assert connection.execute('SELECT username,password_hash,email FROM users').fetchone() == ('legacy_student', 'legacy-hash', 'legacy@example.test')
        assert connection.execute('SELECT count(*) FROM user_profiles').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM buddy_connections').fetchone()[0] == 0
