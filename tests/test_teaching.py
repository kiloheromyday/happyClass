from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.repositories.database import connect, initialize_database
from test_classroom import actors, classroom_for, course_for, schedule, submit, end_session, HEADERS
from test_engagement import ask, answer


def path(session):
    return f"/api/sessions/{session['id']}/learning-guide"


def save(actors, session, actor='teacher', **changes):
    payload = {'title': '本节学习指引', 'content': '理解概念与例子', 'practice': '试着用自己的话复述', 'version': 0, 'action': 'SAVE', **changes}
    return actors[actor]['client'].put(path(session), json=payload, headers=HEADERS)


def test_guide_draft_publish_update_and_withdraw_correspond_to_student(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    student = actors['student']['client']
    assert student.get(path(session)).json()['data'] == {'published': None}
    draft = save(actors, session).json()['data']
    assert draft['version'] == 1 and draft['published'] is None
    assert student.get(path(session)).json()['data'] == {'published': None}
    assert student.get(f"/api/courses/{session['course_id']}").json()['data']['sessions'][0]['guide_published'] is False
    published = save(actors, session, version=1, action='PUBLISH').json()['data']
    public = student.get(path(session)).json()['data']
    assert set(public) == {'published'}
    assert public['published']['title'] == '本节学习指引'
    assert student.get(f"/api/courses/{session['course_id']}").json()['data']['sessions'][0]['guide_published'] is True
    save(actors, session, version=2, title='未发布的新草稿', content='私人备课内容').raise_for_status()
    assert student.get(path(session)).json()['data'] == public
    assert save(actors, session, version=2, action='PUBLISH').status_code == 409
    assert save(actors, session, version=3, title='更新后的指引', action='PUBLISH').status_code == 200
    assert student.get(path(session)).json()['data']['published']['title'] == '更新后的指引'
    withdrawn = save(actors, session, version=4, title='保留的草稿', action='UNPUBLISH').json()['data']
    assert withdrawn['draft']['title'] == '保留的草稿' and withdrawn['published'] is None
    assert student.get(path(session)).json()['data'] == {'published': None}
    assert student.get(f"/api/courses/{session['course_id']}").json()['data']['sessions'][0]['guide_published'] is False
    initialize_database()
    assert actors['teacher']['client'].get(path(session)).json()['data'] == withdrawn


def test_guide_permissions_source_and_roster_removal(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    for name in ('other_teacher', 'other_student'):
        assert actors[name]['client'].get(path(session)).status_code == 403
        assert save(actors, session, actor=name).status_code == 403
    assert save(actors, session, actor='student').status_code == 403
    assert actors['teacher']['client'].put(path(session), json={'title': 'x', 'content': 'x', 'version': 0}).status_code == 403
    assert save(actors, session, actor='admin', action='PUBLISH').status_code == 200
    schedule(actors, session, ())
    assert actors['student']['client'].get(path(session)).status_code == 403


@pytest.mark.parametrize('changes', [dict(title='x'*81), dict(content='x'*3001), dict(practice='x'*1501), dict(content='\x00'), dict(version=True), dict(version=-1), dict(action='DELETE'), dict(published_title='injected')])
def test_guide_validates_payload(actors, changes):
    session = classroom_for(actors)
    assert save(actors, session, **changes).status_code == 422


def test_empty_publish_rejected_but_blank_draft_allowed(actors):
    session = classroom_for(actors)
    assert save(actors, session, action='PUBLISH', title=' ').status_code == 422
    assert save(actors, session, action='PUBLISH', content=' ').status_code == 422
    assert save(actors, session, title='', content='', practice='').status_code == 200


def test_teacher_schedule_inherits_membership_and_isolates_course(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    now = datetime.now(UTC)
    payload = {'course_id': session['course_id'], 'starts_at': (now+timedelta(hours=2)).isoformat(), 'ends_at': (now+timedelta(hours=3)).isoformat(), 'classroom': 'B201', 'class_name': '软件一班', 'request_id': str(uuid4())}
    assert actors['student']['client'].post('/api/teaching/sessions', json=payload, headers=HEADERS).status_code == 403
    assert actors['other_teacher']['client'].post('/api/teaching/sessions', json=payload, headers=HEADERS).status_code == 403
    result = actors['teacher']['client'].post('/api/teaching/sessions', json=payload, headers=HEADERS)
    assert result.status_code == 201
    new = result.json()['data']
    retried = actors['teacher']['client'].post('/api/teaching/sessions', json=payload, headers=HEADERS)
    assert retried.json()['data']['id'] == new['id']
    assert actors['teacher']['client'].post('/api/teaching/sessions', json={**payload, 'classroom': 'B202'}, headers=HEADERS).status_code == 409
    assert new['scheduled_count'] == 1 and new['status'] == 'UPCOMING'
    assert new['id'] in [item['id'] for item in actors['student']['client'].get('/api/sessions').json()['data']['items']]
    assert actors['other_student']['client'].get('/api/sessions').json()['data']['items'] == []
    assert new['id'] in [item['id'] for item in actors['student']['client'].get(f"/api/courses/{session['course_id']}").json()['data']['sessions']]
    assert actors['student']['client'].get(path(new)).json()['data'] == {'published': None}


def test_teaching_overview_question_reply_and_reflection_counts(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    submit(actors['student'], session)
    question = ask(actors, session).json()['data']
    save(actors, session, action='PUBLISH')
    end_session(session)
    other = classroom_for(actors, owner='other_teacher')
    schedule(actors, other)
    ask(actors, other, text='其他教师的问题')
    teacher = actors['teacher']['client']
    data = teacher.get('/api/teaching/overview').json()['data']
    assert data['summary'] == {'courses': 1, 'sessions': 1, 'ongoing': 0, 'upcoming': 0, 'open_questions': 1, 'pending_reflections': 1, 'pending_leaves': 0}
    assert data['sessions'][0]['guide_published'] is True
    assert data['sessions'][0]['record_count'] == 1
    assert 'author_id' not in str(data) and '其他教师的问题' not in str(data)
    assert answer(actors, session, question).status_code == 200
    teacher.put(f"/api/sessions/{session['id']}/recap", json={'reflection': '私人教学反思', 'version': 0}, headers=HEADERS).raise_for_status()
    updated = teacher.get('/api/teaching/overview').json()['data']
    assert updated['summary']['open_questions'] == updated['summary']['pending_reflections'] == 0
    assert updated['sessions'][0]['has_reflection']
    assert '私人教学反思' not in str(updated)
    assert actors['student']['client'].get('/api/teaching/overview').status_code == 403
    assert actors['admin']['client'].get('/api/teaching/overview').json()['data']['summary']['courses'] == 2
