import sqlite3
from contextlib import closing

import pytest

from backend.app.repositories.database import connect, initialize_database, SCHEMA_FILE
from backend.app.services.auth import provision_user
from backend.app.models.auth import ProfileRequest
from backend.app.repositories.profiles import save_profile

HEADERS = {'X-Requested-With': 'EmojiClassroom', 'Origin': 'http://127.0.0.1:18080'}
PASSWORD = 'SearchCheck123!'


@pytest.fixture
def peers(client):
    alice = provision_user('alice', PASSWORD, 'STUDENT', 'alice@example.test')
    bobby = provision_user('bobby', PASSWORD, 'STUDENT', 'private@example.test')
    carol = provision_user('carol', PASSWORD, 'STUDENT', None)
    teacher = provision_user('teacher', PASSWORD, 'TEACHER', None)
    with connect() as connection:
        save_profile(connection, bobby['id'], ProfileRequest(nickname='小林', interests='Python / 设计', bio='一起练习，完成项目', major='计算机科学', grade='大二', study_goal='课程项目与英语四级', learning_style='project', email='private@example.test'))
        save_profile(connection, carol['id'], ProfileRequest(nickname='小禾', interests='设计 / 英语', bio='喜欢安静自习', major='数字媒体', grade='大三', study_goal='英语四级', learning_style='focus'))
        course = connection.execute('INSERT INTO courses(name,teacher_id) VALUES (?,?)', ('Course', teacher['id'])).lastrowid
        session = connection.execute('INSERT INTO class_sessions(course_id,starts_at,ends_at,classroom,class_name) VALUES (?,?,?,?,?)', (course, '2026-01-01T00:00:00Z', '2027-01-01T00:00:00Z', '101', 'A')).lastrowid
        connection.executemany('INSERT INTO schedule_users(session_id,user_id) VALUES (?,?)', [(session, alice['id']), (session, bobby['id'])])
    assert client.post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD}, headers=HEADERS).status_code == 200
    return alice, bobby, carol, teacher


def search(client, **filters):
    response = client.get('/api/buddies/search', params=filters)
    assert response.status_code == 200, response.text
    return response.json()['data']


@pytest.mark.parametrize('query,expected', [('林', ['bobby']), ('设计', ['bobby', 'carol']), ('PYTHON', ['bobby']), ('练习', ['bobby']), ('计算机', ['bobby']), ('四级', ['bobby', 'carol']), ('设计 四级', ['bobby', 'carol']), ('Python 大三', []), ('大二', ['bobby']), ('项目协作', ['bobby'])])
def test_multifield_keyword_search(client, peers, query, expected):
    result = search(client, q=query)
    assert [item['username'] for item in result['items']] == expected
    for item in result['items']:
        assert not {'email', 'password_hash', 'requester_id', 'emotions', 'role'}.intersection(item)


def test_scopes_and_combined_filters(client, peers):
    assert search(client, q='四级', scope='bio')['total'] == 0
    assert search(client, q='四级', scope='study_goal')['total'] == 2
    assert search(client, q='BOB', scope='username')['items'][0]['username'] == 'bobby'
    assert search(client, interests='设计', major='计算机', grade='大二', learning_style='project')['items'][0]['username'] == 'bobby'
    assert search(client, interests='设计', major='计算机', grade='大三')['total'] == 0
    assert search(client, common_course=True)['items'][0]['username'] == 'bobby'
    assert search(client, common_course=True)['total'] == 1


def test_literal_wildcards_quotes_and_empty_criteria(client, peers):
    for keyword in ('%', '_', '\\', "' OR 1=1 --"):
        assert search(client, q=keyword)['total'] == 0
    with connect() as connection:
        connection.execute("UPDATE user_profiles SET bio='100% 完成率' WHERE user_id=?", (peers[1]['id'],))
    assert search(client, q='100%')['items'][0]['username'] == 'bobby'
    for params in ({}, {'q': '   '}, {'q': 'a b c d e f'}, {'q': 'abc', 'scope': 'email'}, {'grade': 'x' * 21}, {'q': 'x' * 121}, {'q': 'a\nb'}, {'q': '设计', 'limit': 25}, {'q': '设计', 'offset': -1}):
        assert client.get('/api/buddies/search', params=params).status_code == 422


def test_relationship_filters_keep_request_state(client, peers):
    _, bobby, _, _ = peers
    assert search(client, q='设计', relationship='new')['total'] == 2
    result = client.post('/api/buddies/requests', json={'user_id': bobby['id']}, headers=HEADERS).json()['data']
    assert search(client, q='设计', relationship='new')['total'] == 1
    pending = search(client, relationship='pending')['items'][0]
    assert pending['relationship'] == 'OUTGOING' and pending['request_id'] == result['request_id']
    client.post('/api/auth/login', json={'username': 'bobby', 'password': PASSWORD}, headers=HEADERS)
    client.post(f'/api/buddies/requests/{result["request_id"]}/accept', headers=HEADERS)
    client.post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD}, headers=HEADERS)
    assert search(client, relationship='friends')['items'][0]['relationship'] == 'FRIEND'
    assert search(client, relationship='pending')['total'] == 0


def test_paginated_search_and_hidden_accounts(client, peers):
    with connect() as connection:
        connection.executemany("INSERT INTO users(username,password_hash,role) VALUES (?,?,'STUDENT')", [(f'search_peer_{i:02}', 'unused') for i in range(25)])
        connection.execute("UPDATE users SET status='DISABLED' WHERE username='search_peer_00'")
    first = search(client, q='search_peer', limit=12)
    second = search(client, q='search_peer', limit=12, offset=12)
    assert first['total'] == 24 and len(first['items']) == len(second['items']) == 12
    assert not {item['id'] for item in first['items']}.intersection(item['id'] for item in second['items'])
    assert search(client, q='search_peer', offset=24)['items'] == []
    assert search(client, q='teacher')['total'] == 0
    assert search(client, q='alice')['total'] == 0


def test_new_profile_fields_roundtrip_and_constraints(client, peers):
    payload = {'nickname': '小云', 'major': '软件工程', 'grade': '研一', 'study_goal': '论文阅读', 'learning_style': 'questions'}
    assert client.put('/api/users/me', json=payload, headers=HEADERS).status_code == 200
    me = client.get('/api/users/me').json()['data']
    assert all(me[key] == value for key, value in payload.items())
    for invalid in ({'major': 'x' * 61}, {'study_goal': 'x' * 101}, {'learning_style': 'unknown'}):
        assert client.put('/api/users/me', json=invalid, headers=HEADERS).status_code == 422


def test_upgrade_from_v070_preserves_existing_profiles(client, tmp_path, monkeypatch):
    path = tmp_path / 'v070.db'
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.executescript(SCHEMA_FILE.read_text(encoding='utf-8').split('CREATE TABLE IF NOT EXISTS user_profiles')[0])
            connection.execute("CREATE TABLE user_profiles(user_id INTEGER PRIMARY KEY REFERENCES users(id), nickname TEXT NOT NULL DEFAULT '', bio TEXT NOT NULL DEFAULT '', interests TEXT NOT NULL DEFAULT '', avatar_color TEXT NOT NULL DEFAULT 'sage')")
            connection.execute("INSERT INTO users(id,username,password_hash,role) VALUES (1,'legacy','unchanged','STUDENT')")
            connection.execute("INSERT INTO user_profiles(user_id,nickname,interests) VALUES (1,'保留昵称','设计')")
    monkeypatch.setenv('EMOJI_DATABASE_PATH', str(path))
    initialize_database(); initialize_database()
    with connect() as connection:
        assert connection.execute('SELECT nickname,interests,major,grade,study_goal,learning_style FROM user_profiles').fetchone() == ('保留昵称', '设计', '', '', '', '')
        assert connection.execute('SELECT password_hash FROM users').fetchone()[0] == 'unchanged'
