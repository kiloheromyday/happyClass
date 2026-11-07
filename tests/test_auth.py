import time

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.dependencies import COOKIE_NAME
from backend.app.repositories.database import connect
from backend.app.security import hash_password, token_hash, verify_password
from backend.app.services.auth import provision_user

HEADERS = {"X-Requested-With": "EmojiClassroom", "Origin": "http://127.0.0.1:18080"}
CREDENTIALS = {"username": "student_one", "password": "Classroom123!"}


@pytest.mark.parametrize('length,accepted', [(2, False), (3, True), (32, True), (33, True), (254, True), (255, False)])
def test_username_length_boundaries_match_registration_and_login(client, length, accepted):
    username = 'u' * length
    response = register(client, username=username)
    assert response.status_code == (201 if accepted else 422)
    response = login(client, username=username)
    assert response.status_code == (200 if accepted else 422)


@pytest.mark.parametrize('username', ['ab', 'x' * 255, 'user name', '学生账号'])
def test_local_provisioning_cannot_create_accounts_rejected_by_login(client, username):
    with pytest.raises(ValidationError):
        provision_user(username, 'TestPassword123!', 'STUDENT', None)
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM users').fetchone()[0] == 0


def test_local_provisioning_normalizes_username_and_can_log_in(client):
    account = provision_user('Test_Student', 'TestPassword123!', 'STUDENT', None)
    assert account['username'] == 'test_student'
    assert login(client, username='TEST_STUDENT', password='TestPassword123!').status_code == 200


@pytest.mark.parametrize('username', ['evidence-3478091101-owner@exampl', 'regression-owner-1234567890@example.test', 'student.name+course@example.test'])
def test_email_style_usernames_register_and_log_in_without_truncation(client, username):
    response = register(client, username=username)
    assert response.status_code == 201
    assert response.json()['data']['username'] == username
    assert login(client, username=username).status_code == 200


def register(client, **overrides):
    return client.post('/api/auth/register', json={**CREDENTIALS, **overrides}, headers=HEADERS)


def login(client, **overrides):
    return client.post('/api/auth/login', json={**CREDENTIALS, **overrides}, headers=HEADERS)


def test_student_session_roundtrip_and_storage(client):
    response = register(client, email='student@example.com')
    assert response.status_code == 201
    assert response.json()['data']['role'] == 'STUDENT'
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie
    assert response.headers['cache-control'] == 'no-store'
    token = client.cookies.get(COOKIE_NAME)
    with connect() as connection:
        digest = connection.execute('SELECT token_hash FROM auth_sessions').fetchone()[0]
        encoded = connection.execute('SELECT password_hash FROM users').fetchone()[0]
    assert token != digest and token_hash(token) == digest
    assert CREDENTIALS['password'] not in encoded
    assert verify_password(CREDENTIALS['password'], encoded)
    me = client.get('/api/users/me')
    assert me.status_code == 200 and 'password_hash' not in me.text
    with TestClient(app) as refreshed:
        refreshed.cookies.set(COOKIE_NAME, token)
        assert refreshed.get('/api/users/me').status_code == 200
    assert client.post('/api/auth/logout', headers=HEADERS).status_code == 200
    client.cookies.set(COOKIE_NAME, token)
    assert client.get('/api/users/me').status_code == 401


@pytest.mark.parametrize('role', ['ADMIN', 'TEACHER'])
def test_registration_cannot_select_privileged_role(client, role):
    response = register(client, role=role)
    assert response.status_code == 422
    assert CREDENTIALS['password'] not in response.text
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM users').fetchone()[0] == 0


@pytest.mark.parametrize('payload', [
    {'password': 'short'}, {'password': 'abcdefghijk'}, {'username': 'a b'}, {'email': 'bad-email'},
])
def test_registration_validates_fields_without_echoing_secrets(client, payload):
    response = register(client, **payload)
    assert response.status_code == 422
    assert response.json()['code'] == 'VALIDATION_ERROR'
    assert CREDENTIALS['password'] not in response.text
    assert 'input' not in response.text


def test_case_normalization_and_duplicates(client):
    assert register(client, username='Student_One', email='Student@Example.com').status_code == 201
    assert login(client, username='STUDENT_ONE').status_code == 200
    assert register(client).status_code == 409
    assert register(client, username='another_student', email='student@example.com').status_code == 409


def test_wrong_login_and_disabled_user_are_rejected(client):
    register(client)
    assert login(client, password='WrongPassword123').status_code == 401
    assert login(client, username='unknown_user').json()['message'] == login(client, password='WrongPassword123').json()['message']
    with connect() as connection:
        connection.execute("UPDATE users SET status='DISABLED'")
    assert client.get('/api/users/me').status_code == 401
    assert login(client).status_code == 401


def test_expired_or_random_session_is_rejected(client):
    register(client)
    with connect() as connection:
        connection.execute('UPDATE auth_sessions SET expires_at=?', (int(time.time()) - 1,))
    assert client.get('/api/users/me').status_code == 401
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, 'invented-token')
    assert client.get('/api/users/me').status_code == 401


def test_password_change_invalidates_every_device(client):
    register(client)
    with TestClient(app) as other_device:
        assert login(other_device).status_code == 200
        assert client.put('/api/auth/password', json={'current_password': CREDENTIALS['password'], 'new_password': 'ChangedPassword456!'}, headers=HEADERS).status_code == 200
        assert client.get('/api/users/me').status_code == 401
        assert other_device.get('/api/users/me').status_code == 401
    assert login(client).status_code == 401
    assert login(client, password='ChangedPassword456!').status_code == 200
    with connect() as connection:
        actions = {row[0] for row in connection.execute('SELECT action FROM audit_logs')}
    assert {'USER_CREATED', 'LOGIN', 'PASSWORD_CHANGED'}.issubset(actions)


def test_wrong_current_password_keeps_session_valid(client):
    register(client)
    response = client.put('/api/auth/password', json={'current_password': 'WrongPassword123', 'new_password': 'ChangedPassword456!'}, headers=HEADERS)
    assert response.status_code == 400
    assert client.get('/api/users/me').status_code == 200
    response = client.put('/api/auth/password', json={'current_password': CREDENTIALS['password'], 'new_password': CREDENTIALS['password']}, headers=HEADERS)
    assert response.status_code == 400


def test_roles_enforced_on_backend_and_no_hashes_in_admin_list(client):
    assert client.get('/api/admin/users').status_code == 401
    register(client)
    assert client.get('/api/admin/users').status_code == 403
    assert client.get('/api/teacher/courses').status_code == 403
    provision_user('teacher_one', 'TeacherPassword123', 'TEACHER', None)
    login(client, username='teacher_one', password='TeacherPassword123')
    assert client.get('/api/admin/users').status_code == 403
    assert client.get('/api/teacher/courses').status_code == 200
    provision_user('admin_one', 'AdminPassword123', 'ADMIN', None)
    login(client, username='admin_one', password='AdminPassword123')
    response = client.get('/api/admin/users?limit=2&offset=1')
    assert response.status_code == 200
    assert response.json()['data']['total'] == 3
    assert len(response.json()['data']['items']) == 2
    assert 'password_hash' not in response.text
    assert client.get('/api/admin/users?limit=999').status_code == 422


def test_teacher_cannot_read_another_teachers_courses(client):
    teacher = provision_user('teacher_one', 'TeacherPassword123', 'TEACHER', None)
    another = provision_user('teacher_two', 'TeacherPassword123', 'TEACHER', None)
    with connect() as connection:
        connection.execute('INSERT INTO courses (name,teacher_id) VALUES (?,?)', ('Own course', teacher['id']))
        connection.execute('INSERT INTO courses (name,teacher_id) VALUES (?,?)', ('Other course', another['id']))
    login(client, username='teacher_one', password='TeacherPassword123')
    assert [course['name'] for course in client.get('/api/teacher/courses').json()['data']['items']] == ['Own course']


def test_mutations_require_csrf_header_and_allowed_origin(client):
    assert client.post('/api/auth/register', json=CREDENTIALS).status_code == 403
    assert client.post('/api/auth/register', json=CREDENTIALS, headers={**HEADERS, 'Origin': 'https://untrusted.example'}).status_code == 403
    register(client)
    assert client.post('/api/auth/logout').status_code == 403
    assert client.get('/api/users/me').status_code == 200


def test_wrong_password_attempts_are_limited(client):
    register(client)
    for _ in range(10):
        assert login(client, password='WrongPassword123').status_code == 401
    assert login(client).status_code == 429


def test_password_hashes_use_unique_salts():
    one, two = hash_password('SecurePassword123'), hash_password('SecurePassword123')
    assert one != two
    assert verify_password('SecurePassword123', one)
    assert not verify_password('WrongPassword123', one)
