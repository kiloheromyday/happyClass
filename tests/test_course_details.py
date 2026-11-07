from uuid import uuid4

from backend.app.repositories.database import connect
from test_classroom import actors, classroom_for, course_for, schedule, submit, HEADERS


def note(actors, name, session):
    response = actors[name]['client'].post('/api/personal/notes', headers=HEADERS, json={
        'session_id': session['id'], 'title': '仅自己可见', 'content': '私人笔记正文',
        'takeaway': '', 'next_step': '', 'reviewed': False, 'request_id': str(uuid4())})
    assert response.status_code == 201


def test_course_detail_requires_membership_and_course_owner(actors):
    session = classroom_for(actors)
    path = f"/api/courses/{session['course_id']}"
    assert actors['student']['client'].get(path).status_code == 404
    assert actors['other_teacher']['client'].get(path).status_code == 404
    assert actors['admin']['client'].get('/api/courses/99999').status_code == 404
    schedule(actors, session)
    assert actors['student']['client'].get(path).status_code == 200
    assert actors['other_student']['client'].get(path).status_code == 404
    assert actors['teacher']['client'].get(path).status_code == 200


def test_course_detail_counts_only_own_visible_classrooms(actors):
    session = classroom_for(actors)
    schedule(actors, session, ('student', 'other_student'))
    submit(actors['student'], session)
    submit(actors['other_student'], session)
    submit(actors['other_student'], session, 'SAD')
    note(actors, 'student', session)
    note(actors, 'other_student', session)
    other_course = classroom_for(actors)
    schedule(actors, other_course)
    submit(actors['student'], other_course)
    path = f"/api/courses/{session['course_id']}"
    data = actors['student']['client'].get(path).json()['data']
    assert data['summary'] == {'total': 1, 'ongoing': 1, 'upcoming': 0, 'ended': 0,
        'feedback_count': 1, 'note_count': 1, 'pending_count': 1, 'participated_sessions': 1}
    assert [item['id'] for item in data['sessions']] == [session['id']]
    item = data['sessions'][0]
    assert item['personal'] == {'feedback_count': 1, 'note_count': 1, 'pending_count': 1}
    assert item['can_feedback'] and item['feedback_closes_at']
    assert 'record_count' not in item and 'scheduled_count' not in item
    assert '私人笔记正文' not in str(data)
    staff = actors['teacher']['client'].get(path).json()['data']
    assert staff['sessions'][0]['record_count'] == 3
    assert staff['sessions'][0]['scheduled_count'] == 2
    assert 'personal' not in staff['sessions'][0] and 'note_count' not in staff['summary']
    assert '私人笔记正文' not in str(staff)


def test_enrolled_course_does_not_bypass_removed_classroom_roster(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    submit(actors['student'], session)
    note(actors, 'student', session)
    schedule(actors, session, ())
    data = actors['student']['client'].get(f"/api/courses/{session['course_id']}").json()['data']
    assert data['sessions'] == []
    assert data['summary']['total'] == data['summary']['note_count'] == data['summary']['feedback_count'] == 0
    assert actors['student']['client'].get('/api/personal/notes').json()['data']['total'] == 1


def test_empty_course_and_upcoming_schedule(actors):
    course = course_for(actors)
    assert actors['teacher']['client'].get(f"/api/courses/{course['id']}").json()['data']['summary']['total'] == 0
    session = classroom_for(actors, upcoming=True)
    schedule(actors, session)
    data = actors['student']['client'].get(f"/api/courses/{session['course_id']}").json()['data']
    assert data['summary']['upcoming'] == 1
    assert data['sessions'][0]['can_feedback'] is False
