from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.repositories.database import connect, initialize_database
from test_classroom import actors, classroom_for, schedule, end_session, HEADERS


def apply(actors, session, who='student', **changes):
    body = {'session_id': session['id'], 'category': 'PERSONAL', 'reason': '需要办理个人事务', 'request_id': str(uuid4()), **changes}
    return actors[who]['client'].post('/api/leaves', headers=HEADERS, json=body)


def decide(actors, item, who='teacher', **changes):
    return actors[who]['client'].put(f"/api/leaves/{item['id']}/decision", headers=HEADERS,
        json={'version': item['version'], 'decision': 'APPROVED', 'reply': '请课后补上学习内容。', **changes})


def cancel(actors, item, who='student'):
    return actors[who]['client'].put(f"/api/leaves/{item['id']}/cancel", headers=HEADERS, json={'version': item['version']})


def test_student_teacher_admin_correspond_and_approval_marks_roster(actors):
    session = classroom_for(actors, upcoming=True)
    schedule(actors, session)
    item = apply(actors, session).json()['data']
    assert item['status'] == 'PENDING' and item['student_id'] == actors['student']['user']['id']
    overview = actors['teacher']['client'].get('/api/teaching/overview').json()['data']
    assert overview['summary']['pending_leaves'] == 1 and overview['sessions'][0]['pending_leaves'] == 1
    approved = decide(actors, item).json()['data']
    assert approved['status'] == 'APPROVED' and approved['version'] == 2 and approved['reviewer_id'] == actors['teacher']['user']['id']
    student = actors['student']['client'].get('/api/leaves').json()['data']
    assert student['items'][0]['reply'] == '请课后补上学习内容。' and student['summary']['APPROVED'] == 1
    assert actors['admin']['client'].get('/api/leaves').json()['data']['total'] == 1
    roster = actors['teacher']['client'].get(f"/api/sessions/{session['id']}/roster").json()['data']['items']
    assert roster[0]['leave_status'] == 'APPROVED' and 'reason' not in roster[0]
    assert actors['student']['client'].get('/api/courses').json()['data']['items']
    assert actors['teacher']['client'].get('/api/teaching/overview').json()['data']['summary']['pending_leaves'] == 0


def test_listing_is_private_and_only_current_teacher_can_decide(actors):
    session = classroom_for(actors)
    schedule(actors, session, ('student', 'other_student'))
    item = apply(actors, session).json()['data']
    assert actors['other_student']['client'].get('/api/leaves').json()['data']['items'] == []
    assert actors['other_teacher']['client'].get('/api/leaves').json()['data']['items'] == []
    assert decide(actors, item, who='other_teacher').status_code == 404
    assert cancel(actors, item, who='other_student').status_code == 404
    assert decide(actors, item, who='admin').status_code == 403
    assert decide(actors, item, who='student').status_code == 403
    assert cancel(actors, item, who='teacher').status_code == 403
    assert apply(actors, session, who='teacher').status_code == 403


def test_enrollment_time_and_approval_validation(actors):
    session = classroom_for(actors)
    assert apply(actors, session).status_code == 403
    schedule(actors, session)
    end_session(session)
    assert apply(actors, session).status_code == 409
    upcoming = classroom_for(actors, upcoming=True); schedule(actors, upcoming)
    item = apply(actors, upcoming).json()['data']
    assert apply(actors, upcoming).status_code == 409
    assert decide(actors, item, decision='REJECTED', reply='   ').status_code == 422
    assert decide(actors, item, version=999).status_code == 409
    assert decide(actors, item, decision='CANCELLED').status_code == 422


def test_request_id_and_terminal_action_retries_are_idempotent(actors):
    session = classroom_for(actors); schedule(actors, session)
    key = str(uuid4())
    first = apply(actors, session, request_id=key)
    second = apply(actors, session, request_id=key)
    assert first.status_code == 201 and second.status_code == 200
    item = first.json()['data']; assert second.json()['data']['id'] == item['id']
    assert apply(actors, session, request_id=key, reason='不同原因').status_code == 409
    rejected = decide(actors, item, decision='REJECTED', reply='请补充具体原因。')
    assert rejected.status_code == 200
    assert decide(actors, item, decision='REJECTED', reply='请补充具体原因。').json()['data'] == rejected.json()['data']
    assert cancel(actors, item).status_code == 409
    again = apply(actors, session).json()['data']
    assert again['id'] != item['id']
    withdrawn = cancel(actors, again)
    assert withdrawn.status_code == 200 and withdrawn.json()['data']['status'] == 'CANCELLED'
    assert cancel(actors, again).json()['data'] == withdrawn.json()['data']
    assert decide(actors, again).status_code == 409
    assert apply(actors, session).status_code == 201
    with connect() as connection:
        logs = str(connection.execute('SELECT detail FROM audit_logs').fetchall())
        assert '需要办理个人事务' not in logs and '请补充具体原因' not in logs


def test_approved_request_cannot_be_reapplied_or_cancelled(actors):
    session = classroom_for(actors); schedule(actors, session)
    item = apply(actors, session).json()['data']
    decide(actors, item).raise_for_status()
    assert cancel(actors, item).status_code == 409
    assert apply(actors, session).status_code == 409


@pytest.mark.parametrize('changes', [dict(reason=' '), dict(reason='a'*501), dict(reason='a\x00b'), dict(category='INVALID'), dict(student_id=9)])
def test_invalid_request_content_is_rejected(actors, changes):
    session = classroom_for(actors); schedule(actors, session)
    assert apply(actors, session, **changes).status_code == 422


def test_filters_pagination_and_restart_preserve_records(actors):
    first = classroom_for(actors); second = classroom_for(actors)
    schedule(actors, first); schedule(actors, second)
    item = apply(actors, first).json()['data']; apply(actors, second).raise_for_status()
    decide(actors, item, decision='REJECTED', reply='需补充原因。').raise_for_status()
    initialize_database()
    student = actors['student']['client']
    data = student.get('/api/leaves?status=PENDING&limit=1').json()['data']
    assert data['total'] == 1 and data['summary']['REJECTED'] == data['summary']['PENDING'] == 1
    assert data['items'][0]['session_id'] == second['id']
    assert student.get('/api/leaves', params={'course_id': first['course_id']}).json()['data']['total'] == 1
    assert student.get('/api/leaves?limit=1&offset=1').json()['data']['items'][0]['status'] == 'REJECTED'
    assert student.get('/api/leaves?status=UNKNOWN').status_code == 422


def test_sources_and_login_are_required(actors, client):
    session = classroom_for(actors); schedule(actors, session)
    body = {'session_id': session['id'], 'category': 'SICK', 'reason': '身体不舒服', 'request_id': str(uuid4())}
    assert client.get('/api/leaves').status_code == 401
    assert actors['student']['client'].post('/api/leaves', json=body).status_code == 403
    item = apply(actors, session).json()['data']
    assert actors['teacher']['client'].put(f"/api/leaves/{item['id']}/decision", json={'version': 1, 'decision': 'APPROVED'}).status_code == 403
