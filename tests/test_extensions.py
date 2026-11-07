import csv
import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.models.classroom import utc_text
from backend.app.repositories.database import connect, initialize_database
from test_classroom import actors, classroom_for, course_for, schedule, submit, end_session, HEADERS
from test_leaves import apply, decide, cancel
from test_engagement import ask, answer
from test_teaching import save as guide_save


def evaluate(actors, session, who='student', **changes):
    body = {'clarity': 5, 'pace': 4, 'engagement': 3, 'gain': 5, 'comment': '希望增加一些例子。', 'version': 0, 'request_id': str(uuid4()), **changes}
    return actors[who]['client'].put(f"/api/sessions/{session['id']}/evaluation", json=body, headers=HEADERS)


def messages(actors, who='student', **query):
    return actors[who]['client'].get('/api/messages', params=query).json()['data']


def update_course(actors, item, **changes):
    body = {key: item[key] for key in ('name', 'teacher_id', 'department_id', 'version')}
    body['archived'] = bool(item['archived'])
    body.update(changes)
    return actors['admin']['client'].put(f"/api/admin/courses/{item['id']}", json=body, headers=HEADERS)


def test_evaluation_create_modify_retry_and_anonymous_export(actors):
    s = classroom_for(actors); schedule(actors, s)
    client = actors['student']['client']; path = f"/api/sessions/{s['id']}/evaluation"
    assert client.get(path).json()['data']['item'] is None
    key = str(uuid4())
    first = evaluate(actors, s, request_id=key).json()['data']
    assert first['version'] == 1
    assert evaluate(actors, s, request_id=key).json()['data'] == first
    assert evaluate(actors, s, request_id=key, clarity=4).status_code == 409
    assert evaluate(actors, s).status_code == 409
    assert evaluate(actors, s, version=1, clarity=3, comment='=SUM(1,2)').status_code == 200
    assert client.get(path).json()['data']['item']['version'] == 2
    teacher = actors['teacher']['client']
    result = teacher.get('/api/evaluations/report').json()['data']
    assert result['summary']['total'] == 1 and result['summary']['clarity'] == 3
    assert not {'student_id', 'username', 'author_id', 'id', 'created_at', 'updated_at', 'request_id'} & set(result['items'][0])
    export = teacher.get('/api/evaluations/export')
    assert export.status_code == 200 and export.headers['X-Export-Count'] == '1'
    records = list(csv.reader(io.StringIO(export.content.decode('utf-8-sig'))))
    assert records[1][-2] == "'=SUM(1,2)"
    initialize_database()
    assert client.get(path).json()['data']['item']['comment'] == '=SUM(1,2)'
    with connect() as c:
        assert c.execute('SELECT count(*) FROM course_evaluations').fetchone()[0] == 1
        assert not c.execute("SELECT 1 FROM audit_logs WHERE detail LIKE '%SUM%'").fetchone()


def test_evaluation_permissions_time_and_teacher_transfer(actors):
    s = classroom_for(actors); schedule(actors, s)
    for who in ('teacher', 'admin', 'other_student'):
        assert evaluate(actors, s, who=who).status_code == 403
    assert actors['student']['client'].get('/api/evaluations/report').status_code == 403
    evaluate(actors, s).raise_for_status()
    assert actors['other_teacher']['client'].get('/api/evaluations/report', params={'course_id': s['course_id']}).status_code == 404
    assert actors['other_teacher']['client'].get('/api/evaluations/report').json()['data']['total'] == 0
    course = actors['admin']['client'].get(f"/api/courses/{s['course_id']}").json()['data']['course']
    update_course(actors, course, teacher_id=actors['other_teacher']['user']['id']).raise_for_status()
    assert actors['teacher']['client'].get('/api/evaluations/report').json()['data']['total'] == 0
    assert actors['other_teacher']['client'].get('/api/evaluations/report').json()['data']['total'] == 1
    upcoming = classroom_for(actors, upcoming=True); schedule(actors, upcoming)
    assert evaluate(actors, upcoming).status_code == 409
    end_session(s)
    assert evaluate(actors, s, version=1).status_code == 409
    assert actors['student']['client'].get(f"/api/sessions/{s['id']}/evaluation").status_code == 200


@pytest.mark.parametrize('field,value', [('clarity', 0), ('pace', 6), ('gain', True), ('engagement', '3'), ('comment', 'x'*1001), ('comment', '\x00bad')])
def test_evaluation_input_validation(actors, field, value):
    s = classroom_for(actors); schedule(actors, s)
    assert evaluate(actors, s, **{field: value}).status_code == 422


def test_evaluation_exact_feedback_boundary_and_source(actors, monkeypatch):
    s = classroom_for(actors); schedule(actors, s)
    from backend.app.services import classroom
    end = datetime.fromisoformat(s['ends_at']) + timedelta(minutes=30)
    monkeypatch.setattr(classroom, 'now_utc', lambda: end - timedelta(milliseconds=1))
    assert evaluate(actors, s).status_code == 200
    monkeypatch.setattr(classroom, 'now_utc', lambda: end)
    assert evaluate(actors, s, version=1).status_code == 409
    with connect() as c:
        c.execute('UPDATE course_evaluations SET is_demo=1')
    teacher = actors['teacher']['client']
    assert teacher.get('/api/evaluations/report?data_scope=REAL').json()['data']['total'] == 0
    assert teacher.get('/api/evaluations/report?data_scope=DEMO').json()['data']['total'] == 1
    assert teacher.get('/api/evaluations/export?data_scope=REAL').headers['X-Export-Count'] == '0'


def test_leave_notifications_atomic_owned_private_and_idempotent(actors):
    s = classroom_for(actors, upcoming=True); schedule(actors, s)
    key = str(uuid4())
    item = apply(actors, s, request_id=key).json()['data']
    apply(actors, s, request_id=key).raise_for_status()
    teacher = messages(actors, 'teacher')
    assert teacher['unread_count'] == teacher['total'] == 1
    assert 'reason' not in str(teacher) and '需要办理个人事务' not in str(teacher)
    assert messages(actors, 'other_teacher')['total'] == messages(actors)['total'] == 0
    decide(actors, item).raise_for_status(); decide(actors, item).raise_for_status()
    inbox = messages(actors)
    assert inbox['unread_count'] == inbox['total'] == 1 and inbox['items'][0]['target_tab'] == 'leaves'
    message_id = inbox['items'][0]['id']
    assert actors['other_student']['client'].put(f'/api/messages/{message_id}/read', headers=HEADERS).status_code == 404
    assert actors['student']['client'].put(f'/api/messages/{message_id}/read', headers=HEADERS).json()['data']['unread_count'] == 0
    assert messages(actors, unread=True)['total'] == 0 and messages(actors)['total'] == 1
    initialize_database()
    assert messages(actors)['items'][0]['read_at']
    assert actors['teacher']['client'].put('/api/messages/read-all', headers=HEADERS).status_code == 200
    assert messages(actors, 'teacher', unread=True)['total'] == 0


def test_cancel_question_guide_and_buddy_messages(actors):
    s = classroom_for(actors); schedule(actors, s)
    leave = apply(actors, s).json()['data']; cancel(actors, leave).raise_for_status()
    assert messages(actors, 'teacher', kind='LEAVE')['total'] == 2
    question = ask(actors, s).json()['data']; answer(actors, s, question).raise_for_status()
    assert messages(actors, kind='QUESTION')['total'] == 1
    assert messages(actors, 'other_student')['total'] == 0
    guide_save(actors, s).raise_for_status()
    assert messages(actors, kind='GUIDE')['total'] == 0
    guide_save(actors, s, version=1, action='PUBLISH').raise_for_status()
    assert messages(actors, kind='GUIDE')['total'] == 1
    assert messages(actors, 'other_student', kind='GUIDE')['total'] == 0
    response = actors['student']['client'].post('/api/buddies/requests', json={'user_id': actors['other_student']['user']['id']}, headers=HEADERS).json()['data']
    assert messages(actors, 'other_student', kind='BUDDY')['total'] == 1
    actors['other_student']['client'].post(f"/api/buddies/requests/{response['request_id']}/accept", headers=HEADERS).raise_for_status()
    assert messages(actors, kind='BUDDY')['total'] == 1


def test_department_maintenance_colors_conflicts_and_restart(actors):
    admin = actors['admin']['client']
    data = {'id': 'test_unit', 'name': '交叉科学', 'short_name': '交叉', 'color': '#6b8eb2', 'version': 0}
    first = admin.post('/api/admin/departments', json=data, headers=HEADERS)
    assert first.status_code == 201 and first.json()['data']['background'].startswith('#')
    assert admin.post('/api/admin/departments', json=data, headers=HEADERS).status_code == 409
    assert actors['teacher']['client'].post('/api/admin/departments', json=data, headers=HEADERS).status_code == 403
    course = course_for(actors)
    updated = update_course(actors, course, department_id=data['id']).json()['data']
    assert updated['department_color'] == data['color']
    data.update(version=1, color='#b57783', name='交叉研究学院')
    assert admin.put('/api/admin/departments/test_unit', json=data, headers=HEADERS).status_code == 200
    assert admin.put('/api/admin/departments/test_unit', json=data, headers=HEADERS).status_code == 409
    assert admin.get(f"/api/courses/{course['id']}").json()['data']['course']['department_color'] == data['color']
    assert admin.delete('/api/admin/departments/test_unit?version=2', headers=HEADERS).status_code == 409
    initialize_database()
    assert next(item for item in admin.get('/api/departments').json()['data']['items'] if item['id'] == data['id'])['name'] == data['name']
    update_course(actors, updated, department_id=None).raise_for_status()
    assert admin.delete('/api/admin/departments/test_unit?version=2', headers=HEADERS).status_code == 200


def test_builtin_department_removal_stays_removed(actors):
    admin = actors['admin']['client']; unit = admin.get('/api/departments').json()['data']['items'][0]
    assert admin.delete(f"/api/admin/departments/{unit['id']}?version={unit['version']}", headers=HEADERS).status_code == 200
    initialize_database()
    assert not any(item['id'] == unit['id'] for item in admin.get('/api/departments').json()['data']['items'])


def test_course_archive_restore_and_preserve_records(actors):
    s = classroom_for(actors); schedule(actors, s); submit(actors['student'], s).raise_for_status()
    admin = actors['admin']['client']; course = admin.get(f"/api/courses/{s['course_id']}").json()['data']['course']
    archived = update_course(actors, course, archived=True, name='新课程名').json()['data']
    assert archived['archived'] == 1
    assert update_course(actors, course, name='过时编辑').status_code == 409
    body = {key: s[key] for key in ('course_id', 'starts_at', 'ends_at', 'classroom', 'class_name')}
    assert admin.post('/api/admin/sessions', json=body, headers=HEADERS).status_code == 409
    assert actors['student']['client'].get(f"/api/courses/{course['id']}").json()['data']['course']['name'] == '新课程名'
    assert actors['student']['client'].get('/api/emoji/history').json()['data']['total'] == 1
    evaluate(actors, s).raise_for_status()
    update_course(actors, archived, archived=False).raise_for_status()
    assert admin.post('/api/admin/sessions', json=body, headers=HEADERS).status_code == 201


def test_demo_scope_consistent_across_history_report_export_and_campus(actors):
    s = classroom_for(actors); schedule(actors, s)
    submit(actors['student'], s, 'HAPPY').raise_for_status()
    submit(actors['student'], s, 'SAD').raise_for_status()
    with connect() as c:
        c.execute("UPDATE emoji_records SET is_demo=1 WHERE emotion='SAD'")
        c.execute('UPDATE courses SET is_demo=1 WHERE id=?', (s['course_id'],))
    teacher = actors['teacher']['client']
    for scope, expected in [('ALL', 2), ('REAL', 1), ('DEMO', 1)]:
        query = {'session_id': s['id'], 'data_scope': scope}
        assert teacher.get('/api/emoji/history', params=query).json()['data']['total'] == expected
        assert teacher.get('/api/reports/statistics', params=query).json()['data']['summary']['total'] == expected
        export = teacher.get('/api/reports/export', params=query)
        assert int(export.headers['X-Export-Count']) == expected
        realtime = teacher.get('/api/dashboard/realtime', params=query).json()['data']
        assert realtime['summary']['total'] == expected and len(realtime['latest']) == expected
        assert teacher.get(f"/api/sessions/{s['id']}/statistics", params={'data_scope': scope}).json()['data']['total'] == expected
    admin = actors['admin']['client']
    campus = admin.get('/api/admin/campus?data_scope=DEMO').json()['data']
    assert campus['summary']['courses'] == 1 and campus['summary']['feedback_count'] == 1
    assert campus['sessions'][0]['record_count'] == 1
    assert admin.get('/api/admin/campus?data_scope=REAL').json()['data']['summary']['courses'] == 0
    assert actors['student']['client'].get('/api/courses?data_scope=REAL').json()['data']['items'] == []
    assert len(actors['student']['client'].get('/api/sessions?data_scope=DEMO').json()['data']['items']) == 1


def test_new_endpoints_require_auth_origin_and_valid_filters(client, actors):
    assert client.get('/api/messages').status_code == 401
    assert actors['student']['client'].put('/api/messages/read-all').status_code == 403
    assert actors['teacher']['client'].get('/api/evaluations/report?data_scope=invalid').status_code == 422
    assert actors['student']['client'].get('/api/messages?limit=0').status_code == 422
    assert actors['student']['client'].get('/api/messages?kind=unknown').status_code == 422
    assert actors['admin']['client'].post('/api/admin/departments', json={'id': 'bad id', 'name': '名称', 'short_name': '简称', 'color': '#123456'}, headers=HEADERS).status_code == 422


def test_demo_evaluations_seed_is_labeled_repeatable_and_preserves_human_entries(actors):
    from scripts.seed_evaluations import seed
    s = classroom_for(actors); schedule(actors, s, ('student', 'other_student'))
    evaluate(actors, s).raise_for_status()
    end_session(s)
    with connect() as c:
        c.execute('UPDATE courses SET is_demo=1 WHERE id=?', (s['course_id'],))
        for name in ('student', 'other_student'):
            c.execute("INSERT INTO demo_seed_items VALUES ('user',?,?)", (name, actors[name]['user']['id']))
    assert seed()['created_evaluations'] == 1
    assert seed()['created_evaluations'] == 0
    with connect() as c:
        assert c.execute('SELECT count(*) FROM course_evaluations').fetchone()[0] == 2
        assert c.execute('SELECT is_demo,comment FROM course_evaluations WHERE student_id=?', (actors['student']['user']['id'],)).fetchone() == (0, '希望增加一些例子。')
        is_demo, comment = c.execute('SELECT is_demo,comment FROM course_evaluations WHERE student_id=?', (actors['other_student']['user']['id'],)).fetchone()
        assert is_demo == 1 and comment.startswith('演示：')
