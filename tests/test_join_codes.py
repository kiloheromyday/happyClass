from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.models.classroom import utc_text
from backend.app.repositories.database import connect, initialize_database
from test_classroom import HEADERS, actors, classroom_for, end_session, schedule, submit


def next_class(actors, session, days=1):
    now = datetime.now(UTC)
    response = actors['admin']['client'].post('/api/admin/sessions', json={
        'course_id': session['course_id'], 'starts_at': (now + timedelta(days=days)).isoformat(),
        'ends_at': (now + timedelta(days=days, hours=1)).isoformat(), 'classroom': 'A102', 'class_name': '软件一班',
    }, headers=HEADERS)
    assert response.status_code == 201
    return response.json()['data']


def test_course_addition_arranges_existing_and_future_classes_once(actors):
    session = classroom_for(actors)
    following = next_class(actors, session)
    code = generate(actors, session).json()['data']['code']
    assert join(actors, code).json()['data']['joined'] is True
    later = next_class(actors, session, days=2)
    student = actors['student']['client']
    assert {row['id'] for row in student.get('/api/sessions').json()['data']['items']} == {session['id'], following['id'], later['id']}
    assert [row['id'] for row in student.get('/api/courses').json()['data']['items']] == [session['course_id']]
    assert join(actors, code).json()['data']['joined'] is False
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM course_enrollments').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM schedule_users').fetchone()[0] == 3
    actors['teacher']['client'].delete(path(session) + '?version=1', headers=HEADERS)
    assert submit(actors['student'], session).status_code == 201


def test_course_addition_rolls_back_if_one_class_is_full(actors, monkeypatch):
    session = classroom_for(actors)
    following = next_class(actors, session)
    code = generate(actors, session).json()['data']['code']
    from backend.app.repositories.classroom import get_session
    monkeypatch.setattr('backend.app.services.join_codes.classroom_repo.get_session', lambda connection, identifier: {**get_session(connection, identifier), **({'scheduled_count': 500} if identifier == following['id'] else {})})
    assert join(actors, code).status_code == 409
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM course_enrollments').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM schedule_users').fetchone()[0] == 0


def test_old_rosters_migrate_to_courses_without_changing_existing_schedules(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    with connect() as connection:
        before = connection.execute('SELECT * FROM schedule_users').fetchall()
        connection.execute('DROP TABLE course_enrollments')
    initialize_database()
    initialize_database()
    with connect() as connection:
        assert connection.execute('SELECT * FROM schedule_users').fetchall() == before
        assert connection.execute('SELECT course_id,user_id FROM course_enrollments').fetchall() == [(session['course_id'], actors['student']['user']['id'])]
    following = next_class(actors, session)
    assert following['scheduled_count'] == 1


def path(session):
    return f"/api/sessions/{session['id']}/join-code"


def generate(actors, session, actor='teacher', **changes):
    return actors[actor]['client'].post(path(session), json={'version': 0, 'ttl_minutes': 60, 'request_id': str(uuid4()), **changes}, headers=HEADERS)


def join(actors, code, actor='student'):
    return actors[actor]['client'].post('/api/sessions/join', json={'code': code}, headers=HEADERS)


def test_teacher_opens_code_student_joins_and_submits(actors):
    session = classroom_for(actors)
    assert actors['teacher']['client'].get(path(session)).json()['data']['status'] == 'NONE'
    response = generate(actors, session)
    assert response.status_code == 200
    item = response.json()['data']
    assert len(item['code']) == 8 and item['status'] == 'ACTIVE' and item['version'] == 1
    assert set(item) == {'code', 'status', 'expires_at', 'updated_at', 'version'}
    assert actors['student']['client'].get('/api/sessions').json()['data']['items'] == []
    result = join(actors, item['code'])
    assert result.status_code == 200 and result.json()['data']['joined'] is True
    assert result.json()['data']['session']['id'] == session['id']
    assert result.json()['data']['session']['scheduled_count'] == 1
    assert join(actors, item['code']).json()['data']['joined'] is False
    assert len(actors['student']['client'].get('/api/sessions').json()['data']['items']) == 1
    assert submit(actors['student'], session).status_code == 201
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM schedule_users WHERE session_id=?', (session['id'],)).fetchone()[0] == 1
        audits = connection.execute("SELECT detail FROM audit_logs WHERE action LIKE '%JOIN%' ").fetchall()
    assert all(item['code'] not in row[0] for row in audits)
    assert 'code' not in actors['student']['client'].get('/api/sessions').json()['data']['items'][0]


def test_rotate_revoke_and_expiry_do_not_remove_existing_students(actors):
    session = classroom_for(actors)
    item = generate(actors, session).json()['data']
    join(actors, item['code'])
    rotated = generate(actors, session, version=1).json()['data']
    assert rotated['code'] != item['code'] and rotated['version'] == 2
    assert join(actors, item['code'], actor='other_student').status_code == 404
    assert join(actors, rotated['code'], actor='other_student').status_code == 200
    response = actors['teacher']['client'].delete(path(session) + '?version=2', headers=HEADERS)
    assert response.status_code == 200 and response.json()['data']['status'] == 'DISABLED'
    assert join(actors, rotated['code']).status_code == 404
    assert submit(actors['student'], session).status_code == 201
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM schedule_users').fetchone()[0] == 2


def test_expiration_boundaries_and_end_time_cap(actors, monkeypatch):
    session = classroom_for(actors)
    item = generate(actors, session, ttl_minutes=1440).json()['data']
    assert datetime.fromisoformat(item['expires_at']) == datetime.fromisoformat(session['ends_at'])
    expires = datetime.fromisoformat(item['expires_at'])
    monkeypatch.setattr('backend.app.services.join_codes.now_utc', lambda: expires - timedelta(milliseconds=1))
    assert join(actors, item['code']).status_code == 200
    monkeypatch.setattr('backend.app.services.join_codes.now_utc', lambda: expires)
    assert join(actors, item['code'], actor='other_student').status_code == 404
    assert actors['teacher']['client'].get(path(session)).json()['data']['status'] == 'EXPIRED'
    end_session(session)
    assert actors['teacher']['client'].get(path(session)).json()['data']['status'] == 'CLOSED'
    assert generate(actors, session, version=1).status_code == 409


def test_upcoming_class_can_join_but_not_submit_feedback(actors):
    session = classroom_for(actors, upcoming=True)
    code = generate(actors, session).json()['data']['code']
    assert join(actors, code).status_code == 200
    assert submit(actors['student'], session).status_code == 409


def test_code_create_idempotence_and_versions(actors):
    session = classroom_for(actors)
    key = str(uuid4())
    first = generate(actors, session, request_id=key).json()['data']
    second = generate(actors, session, request_id=key)
    assert second.status_code == 200 and second.json()['data'] == first
    assert generate(actors, session, request_id=key, ttl_minutes=15).status_code == 409
    assert generate(actors, session).status_code == 409
    assert actors['teacher']['client'].delete(path(session) + '?version=2', headers=HEADERS).status_code == 409
    revoked = actors['teacher']['client'].delete(path(session) + '?version=1', headers=HEADERS).json()['data']
    assert generate(actors, session, request_id=key).json()['data']['status'] == 'DISABLED'
    assert generate(actors, session, version=revoked['version']).status_code == 200


def test_teacher_course_isolation_student_and_csrf(actors):
    session = classroom_for(actors)
    item = generate(actors, session).json()['data']
    for actor in ('student', 'other_student', 'other_teacher'):
        assert actors[actor]['client'].get(path(session)).status_code == 403
        assert generate(actors, session, actor=actor).status_code == 403
        assert actors[actor]['client'].delete(path(session) + '?version=1', headers=HEADERS).status_code == 403
    for actor in ('teacher', 'admin'):
        assert join(actors, item['code'], actor=actor).status_code == 403
    assert actors['admin']['client'].get(path(session)).status_code == 200
    assert actors['teacher']['client'].post(path(session), json={'version': 1, 'request_id': str(uuid4())}).status_code == 403
    assert actors['teacher']['client'].delete(path(session) + '?version=1').status_code == 403
    assert actors['student']['client'].post('/api/sessions/join', json={'code': item['code']}).status_code == 403


def test_code_normalization_and_join_limit(actors):
    session = classroom_for(actors)
    item = generate(actors, session).json()['data']
    code = item['code'].lower()
    assert join(actors, ' ' + code[:4] + '-' + code[4:] + ' ').status_code == 200
    for _ in range(11):
        assert join(actors, 'AAAAAAAA').status_code == 404
    assert join(actors, item['code']).status_code == 429


@pytest.mark.parametrize('changes', [dict(ttl_minutes=14), dict(ttl_minutes=1441), dict(ttl_minutes=True), dict(version=-1), dict(request_id='bad'), dict(code='ABCDEFGH')])
def test_code_settings_validation(actors, changes):
    assert generate(actors, classroom_for(actors), **changes).status_code == 422


@pytest.mark.parametrize('code', ['BAD', '00000000', 'IIIIIIII', "' OR 1=1 --", 'ＡＢＣＤＥＦＧＨ'])
def test_join_input_validation(actors, code):
    assert join(actors, code).status_code == 422


def test_roster_capacity_and_initialization_preserve_existing_rows(actors):
    session = classroom_for(actors)
    initialize_database()
    code = generate(actors, session).json()['data']['code']
    schedule(actors, session)
    initialize_database()
    assert actors['teacher']['client'].get(path(session)).json()['data']['code'] == code
    # Stub only the computed capacity to exercise rejection without creating 500 accounts.
    from unittest.mock import patch
    from backend.app.repositories.classroom import get_session
    with patch('backend.app.services.join_codes.classroom_repo.get_session', side_effect=lambda connection, identifier: {**get_session(connection, identifier), 'scheduled_count': 500}):
        assert join(actors, code, actor='other_student').status_code == 409
        assert join(actors, code).json()['data']['joined'] is False
    assert actors['teacher']['client'].get(f"/api/sessions/{session['id']}/roster").json()['data']['items'][0]['id'] == actors['student']['user']['id']
