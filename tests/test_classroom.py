from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.dependencies import COOKIE_NAME
from backend.app.models.classroom import utc_text
from backend.app.models.auth import RegisterRequest
from backend.app.repositories import users
from backend.app.repositories.database import connect
from backend.app.security import hash_password
from backend.app.services.auth import issue_session

HEADERS = {'X-Requested-With': 'EmojiClassroom', 'Origin': 'http://127.0.0.1:18080'}


@pytest.fixture
def actors(client):
    password_hash = hash_password('TestPassword123!')
    with ExitStack() as stack:
        result = {}
        for name, role in [('admin', 'ADMIN'), ('teacher', 'TEACHER'), ('other_teacher', 'TEACHER'), ('student', 'STUDENT'), ('other_student', 'STUDENT')]:
            account = RegisterRequest(username=name, password='TestPassword123!')
            user = users.create_user(account.username, password_hash, role)
            actor = stack.enter_context(TestClient(app))
            actor.cookies.set(COOKIE_NAME, issue_session(user))
            result[name] = {'user': user, 'client': actor}
        yield result


def course_for(actors, owner='teacher'):
    response = actors['admin']['client'].post('/api/admin/courses', json={'name': '软件工程', 'teacher_id': actors[owner]['user']['id']}, headers=HEADERS)
    assert response.status_code == 201
    return response.json()['data']


def classroom_for(actors, owner='teacher', upcoming=False):
    course = course_for(actors, owner)
    now = datetime.now(UTC)
    start = now + timedelta(hours=1) if upcoming else now - timedelta(minutes=5)
    response = actors['admin']['client'].post('/api/admin/sessions', json={'course_id': course['id'], 'starts_at': start.isoformat(), 'ends_at': (now + timedelta(hours=2)).isoformat(), 'classroom': 'A101', 'class_name': '软件一班'}, headers=HEADERS)
    assert response.status_code == 201
    return response.json()['data']


def schedule(actors, session, names=('student',)):
    return actors['admin']['client'].put(f"/api/admin/sessions/{session['id']}/schedule", json={'user_ids': [actors[name]['user']['id'] for name in names]}, headers=HEADERS)


def submit(actor, session, emotion='HAPPY', request_id=None, **extra):
    return actor['client'].post('/api/emoji', json={'session_id': session['id'], 'emotion': emotion, 'request_id': request_id or str(uuid4()), **extra}, headers=HEADERS)


def end_session(session):
    with connect() as connection:
        connection.execute('UPDATE class_sessions SET starts_at=?,ends_at=? WHERE id=?', (utc_text(datetime.now(UTC) - timedelta(hours=2)), utc_text(datetime.now(UTC) - timedelta(hours=1)), session['id']))


def test_admin_to_student_to_teacher_flow(actors):
    session = classroom_for(actors)
    assert schedule(actors, session).status_code == 200
    student = actors['student']['client']
    assert [item['id'] for item in student.get('/api/sessions').json()['data']['items']] == [session['id']]
    assert actors['other_student']['client'].get('/api/sessions').json()['data']['items'] == []
    response = submit(actors['student'], session)
    assert response.status_code == 201
    record = response.json()['data']
    assert record['source'] == 'MANUAL' and record['user_id'] == actors['student']['user']['id']
    stats = actors['teacher']['client'].get(f"/api/sessions/{session['id']}/statistics").json()['data']
    assert stats['total'] == 1 and stats['responding_students'] == 1
    assert stats['manual_count'] == 1 and stats['ai_count'] == 0
    assert next(item['count'] for item in stats['emotions'] if item['emotion'] == 'HAPPY') == 1
    history = student.get('/api/emoji/history').json()['data']
    assert history['total'] == 1 and history['items'][0]['id'] == record['id']
    with connect() as connection:
        actions = {row[0] for row in connection.execute('SELECT action FROM audit_logs')}
    assert {'COURSE_CREATED', 'SESSION_CREATED', 'ROSTER_REPLACED'}.issubset(actions)


def test_roster_replace_is_atomic_validated_and_deduplicated(actors):
    session = classroom_for(actors)
    assert schedule(actors, session, ('student', 'student')).status_code == 200
    admin = actors['admin']['client']
    assert len(admin.get(f"/api/sessions/{session['id']}/roster").json()['data']['items']) == 1
    assert schedule(actors, session, ('other_student', 'teacher')).status_code == 422
    assert [item['id'] for item in admin.get(f"/api/sessions/{session['id']}/roster").json()['data']['items']] == [actors['student']['user']['id']]
    with connect() as connection:
        connection.execute("UPDATE users SET status='DISABLED' WHERE id=?", (actors['other_student']['user']['id'],))
    assert schedule(actors, session, ('other_student',)).status_code == 422
    assert schedule(actors, session, ()).status_code == 200
    assert actors['student']['client'].get('/api/sessions').json()['data']['items'] == []


def test_unassigned_student_and_staff_cannot_submit(actors):
    session = classroom_for(actors)
    assert submit(actors['student'], session).status_code == 403
    for role in ('teacher', 'admin'):
        assert submit(actors[role], session).status_code == 403


def test_upcoming_and_ended_classes_reject_submission(actors):
    session = classroom_for(actors, upcoming=True)
    schedule(actors, session)
    assert submit(actors['student'], session).status_code == 409
    end_session(session)
    assert submit(actors['student'], session).status_code == 409
    assert schedule(actors, session, ()).status_code == 409


def test_feedback_boundaries_include_thirty_minute_post_class_window(actors, monkeypatch):
    session = classroom_for(actors)
    schedule(actors, session)
    monkeypatch.setattr('backend.app.services.classroom.now_utc', lambda: datetime.fromisoformat(session['starts_at']))
    assert submit(actors['student'], session).status_code == 201
    monkeypatch.setattr('backend.app.services.classroom.now_utc', lambda: datetime.fromisoformat(session['ends_at']))
    assert submit(actors['student'], session).status_code == 201
    deadline = datetime.fromisoformat(session['ends_at']) + timedelta(minutes=30)
    monkeypatch.setattr('backend.app.services.classroom.now_utc', lambda: deadline - timedelta(milliseconds=1))
    response = actors['student']['client'].get('/api/sessions').json()['data']['items'][0]
    assert response['status'] == 'ENDED' and response['can_feedback'] is True
    assert submit(actors['student'], session).status_code == 201
    monkeypatch.setattr('backend.app.services.classroom.now_utc', lambda: deadline)
    assert actors['student']['client'].get('/api/sessions').json()['data']['items'][0]['can_feedback'] is False
    assert submit(actors['student'], session).status_code == 409


def test_retry_is_idempotent_and_conflicting_reuse_is_rejected(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    request_id = str(uuid4())
    first = submit(actors['student'], session, request_id=request_id)
    second = submit(actors['student'], session, request_id=request_id)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()['data']['id'] == second.json()['data']['id']
    assert submit(actors['student'], session, 'SAD', request_id=request_id).status_code == 409
    end_session(session)
    assert submit(actors['student'], session, request_id=request_id).status_code == 200
    assert actors['student']['client'].get('/api/emoji/history').json()['data']['total'] == 1


@pytest.mark.parametrize('extra', [{'user_id': 999}, {'source': 'AI'}, {'recorded_at': '2020-01-01T00:00:00Z'}, {'confidence': 1}])
def test_student_cannot_forge_record_attributes(actors, extra):
    session = classroom_for(actors)
    schedule(actors, session)
    assert submit(actors['student'], session, **extra).status_code == 422


def test_student_history_remains_private_and_survives_roster_removal(actors):
    session = classroom_for(actors)
    schedule(actors, session, ('student', 'other_student'))
    submit(actors['student'], session, 'HAPPY')
    submit(actors['other_student'], session, 'SAD')
    history = actors['student']['client'].get('/api/emoji/history').json()['data']
    assert history['total'] == 1 and history['items'][0]['emotion'] == 'HAPPY'
    schedule(actors, session, ('other_student',))
    assert actors['student']['client'].get('/api/emoji/history').json()['data']['total'] == 1
    assert submit(actors['student'], session).status_code == 403
    assert actors['student']['client'].get(f"/api/sessions/{session['id']}/statistics").status_code == 403
    assert actors['student']['client'].get(f"/api/sessions/{session['id']}/roster").status_code == 403


def test_teachers_cannot_read_other_courses_rosters_history_or_statistics(actors):
    own, other = classroom_for(actors), classroom_for(actors, 'other_teacher')
    schedule(actors, own)
    schedule(actors, other)
    submit(actors['student'], own)
    submit(actors['student'], other, 'SAD')
    teacher = actors['teacher']['client']
    assert len(teacher.get('/api/courses').json()['data']['items']) == 1
    assert [item['id'] for item in teacher.get('/api/sessions').json()['data']['items']] == [own['id']]
    assert teacher.get('/api/emoji/history').json()['data']['total'] == 1
    for path in (f"/api/sessions/{other['id']}/roster", f"/api/sessions/{other['id']}/statistics", f"/api/emoji/history?session_id={other['id']}"):
        assert teacher.get(path).status_code == 403
    assert actors['admin']['client'].get('/api/emoji/history').json()['data']['total'] == 2


def test_non_admin_cannot_manage_courses_sessions_or_rosters(actors):
    session = classroom_for(actors)
    for role in ('student', 'teacher'):
        actor = actors[role]['client']
        assert actor.get('/api/admin/people').status_code == 403
        assert actor.post('/api/admin/courses', json={'name': 'Invalid', 'teacher_id': actors['teacher']['user']['id']}, headers=HEADERS).status_code == 403
        assert actor.put(f"/api/admin/sessions/{session['id']}/schedule", json={'user_ids': []}, headers=HEADERS).status_code == 403


def test_course_requires_active_teacher(actors):
    admin = actors['admin']['client']
    assert admin.post('/api/admin/courses', json={'name': 'Invalid', 'teacher_id': actors['student']['user']['id']}, headers=HEADERS).status_code == 422
    with connect() as connection:
        connection.execute("UPDATE users SET status='DISABLED' WHERE id=?", (actors['teacher']['user']['id'],))
    assert admin.post('/api/admin/courses', json={'name': 'Invalid', 'teacher_id': actors['teacher']['user']['id']}, headers=HEADERS).status_code == 422


def test_session_time_validation_and_timezone_normalization(actors):
    course = course_for(actors)
    admin = actors['admin']['client']
    now = datetime.now(UTC)
    body = {'course_id': course['id'], 'classroom': 'A101', 'class_name': 'A', 'starts_at': (now + timedelta(hours=1)).isoformat(), 'ends_at': (now + timedelta(hours=2)).isoformat()}
    assert admin.post('/api/admin/sessions', json={**body, 'ends_at': body['starts_at']}, headers=HEADERS).status_code == 422
    assert admin.post('/api/admin/sessions', json={**body, 'starts_at': '2026-11-02T10:00:00'}, headers=HEADERS).status_code == 422
    assert admin.post('/api/admin/sessions', json={**body, 'starts_at': utc_text(now - timedelta(hours=2)), 'ends_at': utc_text(now - timedelta(hours=1))}, headers=HEADERS).status_code == 422
    assert admin.post('/api/admin/sessions', json={**body, 'course_id': 99999}, headers=HEADERS).status_code == 404
    response = admin.post('/api/admin/sessions', json=body, headers=HEADERS)
    assert response.status_code == 201
    assert response.json()['data']['starts_at'].endswith('Z')


def test_empty_statistics_and_history_pagination(actors):
    session = classroom_for(actors)
    admin = actors['admin']['client']
    stats = admin.get(f"/api/sessions/{session['id']}/statistics").json()['data']
    assert stats['total'] == 0 and len(stats['emotions']) == 7
    assert all(item['count'] == 0 for item in stats['emotions'])
    schedule(actors, session)
    for emotion in ('HAPPY', 'SAD', 'NEUTRAL'):
        submit(actors['student'], session, emotion)
    history = actors['student']['client'].get('/api/emoji/history?limit=1&offset=1').json()['data']
    assert history['total'] == 3 and len(history['items']) == 1
    assert history['items'][0]['emotion'] == 'SAD'
    assert actors['student']['client'].get('/api/emoji/history?limit=9999').status_code == 422
