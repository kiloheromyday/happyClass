from datetime import UTC, datetime, timedelta
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app.repositories.database import connect
from test_classroom import actors, course_for, HEADERS
from test_extensions import update_course


def test_course_creation_retry_cannot_duplicate_or_reuse_key(actors):
    admin = actors['admin']['client']
    body = {'name': '重试课程', 'teacher_id': actors['teacher']['user']['id'], 'request_id': str(uuid4())}
    first = admin.post('/api/admin/courses', json=body, headers=HEADERS)
    assert first.status_code == 201
    repeated = admin.post('/api/admin/courses', json=body, headers=HEADERS)
    assert repeated.status_code == 201 and repeated.json()['data']['id'] == first.json()['data']['id']
    assert admin.post('/api/admin/courses', json={**body, 'name': '不同内容'}, headers=HEADERS).status_code == 409
    with connect() as c:
        assert c.execute('SELECT count(*) FROM courses').fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM audit_logs WHERE action='COURSE_CREATED'").fetchone()[0] == 1


@pytest.mark.parametrize('actor,route', [('teacher', '/api/teaching/sessions'), ('admin', '/api/admin/sessions')])
def test_successful_classroom_retry_survives_course_archive(actors, actor, route):
    course = course_for(actors)
    now = datetime.now(UTC)
    body = {'course_id': course['id'], 'starts_at': now.isoformat(), 'ends_at': (now + timedelta(hours=1)).isoformat(), 'classroom': 'A101', 'class_name': '一班', 'request_id': str(uuid4())}
    teacher = actors[actor]['client']
    first = teacher.post(route, json=body, headers=HEADERS)
    assert first.status_code == 201
    update_course(actors, course, archived=True).raise_for_status()
    repeated = teacher.post(route, json=body, headers=HEADERS)
    assert repeated.status_code == 201 and repeated.json()['data']['id'] == first.json()['data']['id']
    assert teacher.post(route, json={**body, 'request_id': str(uuid4())}, headers=HEADERS).status_code == 409


def test_concurrent_course_creation_retry_is_atomic(actors):
    from backend.app.models.classroom import CourseCreateRequest
    from backend.app.services.classroom import create_course
    body = CourseCreateRequest(name='并行重试', teacher_id=actors['teacher']['user']['id'], request_id=uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: create_course(body, actors['admin']['user']), range(4)))
    assert len({item['id'] for item in results}) == 1
    with connect() as c:
        assert c.execute('SELECT count(*) FROM courses').fetchone()[0] == 1
        assert c.execute('SELECT count(*) FROM course_creation_keys').fetchone()[0] == 1


def test_classroom_retry_cannot_bypass_teacher_transfer(actors):
    course = course_for(actors)
    now = datetime.now(UTC)
    body = {'course_id': course['id'], 'starts_at': now.isoformat(), 'ends_at': (now + timedelta(hours=1)).isoformat(), 'classroom': 'A101', 'class_name': '一班', 'request_id': str(uuid4())}
    teacher = actors['teacher']['client']
    assert teacher.post('/api/teaching/sessions', json=body, headers=HEADERS).status_code == 201
    update_course(actors, course, teacher_id=actors['other_teacher']['user']['id']).raise_for_status()
    assert teacher.post('/api/teaching/sessions', json=body, headers=HEADERS).status_code == 403
