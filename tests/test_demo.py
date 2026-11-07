import time

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.dependencies import COOKIE_NAME
from backend.app.repositories import users
from backend.app.repositories.database import connect
from backend.app.security import hash_password, verify_password, token_hash
from backend.app.services.auth import issue_session
from backend.app.services.demo import DEMO_COOKIE

HEADERS = {'Origin': 'http://127.0.0.1:18080', 'X-Requested-With': 'EmojiClassroom'}


@pytest.fixture
def demo(client, monkeypatch):
    monkeypatch.setenv('EMOJI_DEMO_MODE', '1')
    digest = hash_password('TestPassword123!')
    accounts = {name: users.create_user(name, digest, role) for name, role in (
        ('demo_student', 'STUDENT'), ('demo_teacher', 'TEACHER'), ('demo_buddy', 'STUDENT'), ('member_one', 'STUDENT'),
        ('member_teacher', 'TEACHER'), ('demo_admin', 'ADMIN'), ('protected_admin', 'ADMIN'))}
    with TestClient(app, base_url='http://127.0.0.1:18080', client=('127.0.0.1', 50000)) as local:
        yield local, accounts


def enable(local):
    result = local.post('/api/demo/enable', headers=HEADERS)
    assert result.status_code == 200
    return result


def update_body(**changes):
    return {'nickname': '新的昵称', 'email': 'member@example.test', 'expected_email': None, 'expected_nickname': '', **changes}


def test_demo_off_by_default_and_server_flag_blocks_all_paths(demo, monkeypatch):
    local, _ = demo
    monkeypatch.delenv('EMOJI_DEMO_MODE')
    assert local.get('/api/demo/status').json()['data'] == {'enabled': False, 'active': False, 'accounts': []}
    assert local.post('/api/demo/enable', headers=HEADERS).status_code == 404
    monkeypatch.setenv('EMOJI_DEMO_MODE', '1'); enable(local)
    monkeypatch.setenv('EMOJI_DEMO_MODE', '0')
    assert local.get('/api/demo/members').status_code == 404
    assert local.post('/api/demo/login', json={'username': 'demo_student'}, headers=HEADERS).status_code == 404


@pytest.mark.parametrize('peer,base', [('192.0.2.8', 'http://127.0.0.1:18080'), ('127.0.0.1', 'http://public.example.test'), ('192.0.2.8', 'http://localhost:18080')])
def test_demo_requires_real_loopback_peer_and_host(demo, peer, base):
    with TestClient(app, base_url=base, client=(peer, 50001)) as remote:
        assert remote.get('/api/demo/status', headers={'X-Forwarded-For': '127.0.0.1'}).json()['data']['enabled'] is False
        assert remote.post('/api/demo/enable', headers=HEADERS).status_code == 404


def test_enable_cookie_capability_and_origin(demo):
    local, accounts = demo
    assert local.get('/api/demo/members').status_code == 401
    local.cookies.set(COOKIE_NAME, issue_session(accounts['protected_admin']))
    assert local.get('/api/demo/members').status_code == 401, 'normal administrator cookie is not developer capability'
    assert local.post('/api/demo/enable').status_code == 403
    assert local.post('/api/demo/enable', headers={**HEADERS, 'Origin': 'https://evil.example'}).status_code == 403
    result = enable(local)
    cookie = result.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/api/demo' in cookie
    assert 'token' not in result.text and 'password' not in result.text
    assert [item['username'] for item in result.json()['data']['accounts']] == ['demo_student', 'demo_teacher', 'demo_admin']
    assert local.get('/api/demo/status').json()['data']['active'] is True


def test_demo_switch_real_sessions_revokes_old_and_preserves_passwords(demo):
    local, accounts = demo
    enable(local)
    student = local.post('/api/demo/login', json={'username': 'demo_student'}, headers=HEADERS)
    assert student.json()['data']['role'] == 'STUDENT'
    old = local.cookies.get(COOKIE_NAME)
    teacher = local.post('/api/demo/login', json={'username': 'demo_teacher'}, headers=HEADERS)
    assert teacher.json()['data']['role'] == 'TEACHER'
    assert local.get('/api/users/me').json()['data']['username'] == 'demo_teacher'
    assert users.find_by_session(token_hash(old)) is None
    teacher_token = local.cookies.get(COOKIE_NAME)
    administrator = local.post('/api/demo/login', json={'username': 'demo_admin'}, headers=HEADERS)
    assert administrator.json()['data']['role'] == 'ADMIN'
    assert local.get('/api/admin/users').status_code == 200
    assert users.find_by_session(token_hash(teacher_token)) is None
    assert users.find_by_username('demo_admin')['password_hash'] == accounts['demo_admin']['password_hash']
    admin_token = local.cookies.get(COOKIE_NAME)
    local.post('/api/demo/login', json={'username': 'demo_student'}, headers=HEADERS).raise_for_status()
    assert local.get('/api/admin/users').status_code == 403
    assert users.find_by_session(token_hash(admin_token)) is None
    assert users.find_by_username('demo_student')['password_hash'] == accounts['demo_student']['password_hash']
    assert local.post('/api/demo/login', json={'username': 'member_one'}, headers=HEADERS).status_code == 422
    assert local.post('/api/demo/login', json={'username': 'demo_buddy'}, headers=HEADERS).status_code == 422
    assert local.post('/api/demo/login', json={'username': 'demo_student', 'role': 'ADMIN'}, headers=HEADERS).status_code == 422
    local.post('/api/demo/disable', headers=HEADERS).raise_for_status()
    assert local.get('/api/demo/status').json()['data']['active'] is False
    assert local.post('/api/demo/login', json={'username': 'demo_student'}, headers=HEADERS).status_code == 401
    assert local.get('/api/users/me').status_code == 200, 'closing developer mode retains ordinary login'


def test_disabled_or_wrong_role_demo_is_not_available(demo):
    local, accounts = demo
    with connect() as connection:
        connection.execute("UPDATE users SET status='DISABLED' WHERE id=?", (accounts['demo_student']['id'],))
        connection.execute("UPDATE users SET role='STUDENT' WHERE id=?", (accounts['demo_teacher']['id'],))
        connection.execute("UPDATE users SET role='TEACHER' WHERE id=?", (accounts['demo_admin']['id'],))
    assert enable(local).json()['data']['accounts'] == []
    assert local.post('/api/demo/login', json={'username': 'demo_student'}, headers=HEADERS).status_code == 409
    assert local.post('/api/demo/login', json={'username': 'demo_teacher'}, headers=HEADERS).status_code == 409
    assert local.post('/api/demo/login', json={'username': 'demo_admin'}, headers=HEADERS).status_code == 409


def test_expired_or_revoked_capability_cannot_manage_members(demo):
    local, _ = demo
    enable(local)
    with connect() as connection:
        connection.execute('UPDATE demo_access_sessions SET expires_at=?', (int(time.time())-1,))
    assert local.get('/api/demo/status').json()['data']['active'] is False
    assert local.get('/api/demo/members').status_code == 401
    enable(local)
    token = local.cookies.get(DEMO_COOKIE)
    local.post('/api/demo/disable', headers=HEADERS).raise_for_status()
    local.cookies.set(DEMO_COOKIE, token, domain='127.0.0.1', path='/api/demo')
    assert local.get('/api/demo/members').status_code == 401


@pytest.mark.parametrize('state', ['missing', 'disabled'])
def test_admin_shortcut_requires_existing_active_admin(demo, state):
    local, accounts = demo
    assert local.post('/api/demo/login', json={'username': 'demo_admin'}, headers=HEADERS).status_code == 401
    with connect() as connection:
        if state == 'missing':
            connection.execute("UPDATE users SET username='unlisted_admin' WHERE id=?", (accounts['demo_admin']['id'],))
        else:
            connection.execute("UPDATE users SET status='DISABLED' WHERE id=?", (accounts['demo_admin']['id'],))
    assert all(item['username'] != 'demo_admin' for item in enable(local).json()['data']['accounts'])
    assert local.post('/api/demo/login', json={'username': 'demo_admin'}, headers=HEADERS).status_code == 409


def test_member_search_role_status_pagination_and_whitelist(demo):
    local, _ = demo; enable(local)
    data = local.get('/api/demo/members?limit=2').json()['data']
    assert data['total'] == 5 and len(data['items']) == 2
    buddy = local.get('/api/demo/members?q=demo_buddy').json()['data']['items'][0]
    assert buddy['role'] == 'STUDENT' and buddy['protected'] is False
    assert not any(key in str(data) for key in ('password', 'token_hash', 'protected_admin'))
    result = local.get('/api/demo/members?q=member&role=TEACHER').json()['data']
    assert result['total'] == 1 and result['items'][0]['username'] == 'member_teacher'
    assert local.get('/api/demo/members?q=%25').json()['data']['total'] == 0
    assert local.get('/api/demo/members?role=ADMIN').status_code == 422


@pytest.mark.parametrize('role', ['STUDENT', 'TEACHER'])
def test_create_members_without_admin_role_or_password_leak(demo, role):
    local, _ = demo; enable(local)
    body = {'username': 'new_member', 'role': role, 'password': 'NewMember123!', 'email': None}
    result = local.post('/api/demo/members', json=body, headers=HEADERS)
    assert result.status_code == 201 and result.json()['data']['role'] == role
    assert 'NewMember123!' not in result.text and 'password_hash' not in result.text
    assert local.post('/api/demo/members', json=body, headers=HEADERS).status_code == 409
    assert local.post('/api/demo/members', json={**body, 'username': 'new_admin', 'role': 'ADMIN'}, headers=HEADERS).status_code == 422
    assert local.post('/api/demo/members', json={**body, 'username': 'weak_pass', 'password': '123'}, headers=HEADERS).status_code == 422


@pytest.mark.parametrize('name,expected', [('demo_student', 409), ('demo_teacher', 409), ('demo_admin', 404), ('protected_admin', 404)])
def test_protected_demo_and_administrators_cannot_be_modified(demo, name, expected):
    local, accounts = demo; enable(local)
    identifier = accounts[name]['id']
    assert local.put(f'/api/demo/members/{identifier}', json=update_body(), headers=HEADERS).status_code == expected
    assert local.put(f'/api/demo/members/{identifier}/status', json={'status': 'DISABLED', 'expected_status': 'ACTIVE'}, headers=HEADERS).status_code == expected
    assert local.put(f'/api/demo/members/{identifier}/password', json={'new_password': 'ResetPassword123!'}, headers=HEADERS).status_code == expected


def test_edit_preserves_other_profile_fields_and_detects_conflicts(demo):
    local, accounts = demo; enable(local)
    identifier = accounts['member_one']['id']
    with connect() as connection:
        connection.execute("INSERT INTO user_profiles(user_id,bio,interests) VALUES (?,'原简介','原兴趣')", (identifier,))
    response = local.put(f'/api/demo/members/{identifier}', json=update_body(), headers=HEADERS)
    assert response.status_code == 200 and response.json()['data']['nickname'] == '新的昵称'
    assert local.put(f'/api/demo/members/{identifier}', json=update_body(nickname='过时修改'), headers=HEADERS).status_code == 409
    with connect() as connection:
        assert connection.execute('SELECT bio,interests FROM user_profiles WHERE user_id=?', (identifier,)).fetchone() == ('原简介', '原兴趣')


def test_disable_revoke_sessions_reenable_and_password_reset(demo):
    local, accounts = demo; enable(local)
    member = accounts['member_one']; identifier = member['id']
    token = issue_session(member)
    response = local.put(f'/api/demo/members/{identifier}/status', json={'status': 'DISABLED', 'expected_status': 'ACTIVE'}, headers=HEADERS)
    assert response.status_code == 200 and users.find_by_session(token_hash(token)) is None
    assert local.get('/api/demo/members?status=DISABLED').json()['data']['total'] == 1
    assert local.put(f'/api/demo/members/{identifier}/status', json={'status': 'DISABLED', 'expected_status': 'ACTIVE'}, headers=HEADERS).status_code == 409
    local.put(f'/api/demo/members/{identifier}/status', json={'status': 'ACTIVE', 'expected_status': 'DISABLED'}, headers=HEADERS).raise_for_status()
    token = issue_session(users.find_by_username('member_one'))
    response = local.put(f'/api/demo/members/{identifier}/password', json={'new_password': 'ResetPassword123!'}, headers=HEADERS)
    assert response.status_code == 200 and users.find_by_session(token_hash(token)) is None
    assert verify_password('ResetPassword123!', users.find_by_username('member_one')['password_hash'])
    with connect() as connection:
        audits = str(connection.execute('SELECT action,detail FROM audit_logs').fetchall())
        assert 'DEMO_MEMBER_PASSWORD_RESET' in audits and 'ResetPassword123!' not in audits


def test_member_writes_require_origin_and_active_capability(demo):
    local, accounts = demo; enable(local)
    identifier = accounts['member_one']['id']
    assert local.put(f'/api/demo/members/{identifier}', json=update_body()).status_code == 403
    assert local.put(f'/api/demo/members/{identifier}/password', json={'new_password': 'ResetPassword123!'}, headers={**HEADERS, 'Origin': 'https://evil.example'}).status_code == 403
    local.post('/api/demo/disable', headers=HEADERS).raise_for_status()
    assert local.put(f'/api/demo/members/{identifier}/status', json={'status': 'DISABLED', 'expected_status': 'ACTIVE'}, headers=HEADERS).status_code == 401
