from datetime import timedelta
from uuid import uuid4

from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.database import connect

from test_classroom import HEADERS, actors, classroom_for, schedule

BASE = '/api/emotion-feedback'


def command(client, path, expected=200, method='post', **data):
    payload = {'request_id': str(uuid4()), **data}
    response = getattr(client, method)(BASE + path, json=payload, headers=HEADERS)
    assert response.status_code == expected, response.text
    return response.json()['data']


def get(client, path):
    response = client.get(BASE + path)
    assert response.status_code == 200, response.text
    return response.json()['data']


def create(student, session, title='希望增加例题', **extra):
    return command(
        student, '/cases', 201, session_id=session['id'], title=title,
        reasons=['NEED_EXAMPLE'], emotion='FEAR', **extra,
    )


def test_complete_anonymous_feedback_workflow(actors):
    session = classroom_for(actors)
    assert schedule(actors, session, ('student', 'other_student')).status_code == 200
    teacher = actors['teacher']['client']
    student = actors['student']['client']
    peer = actors['other_student']['client']
    unrelated = actors['other_teacher']['client']
    assert get(student, '/options')['sessions'][0]['submission']['can_submit']
    case = create(student, session, content='需要从例题第一步开始')
    path = '/cases/' + str(case['id'])
    assert peer.get(BASE + path).status_code == 404
    assert unrelated.get(BASE + path).status_code == 403
    assert get(peer, '/cases')['total'] == 0
    assert get(teacher, '/inbox')['unread_count'] == 1
    visible = get(teacher, path)
    assert 'author_id' not in visible and 'linked_record_id' not in visible
    case = command(teacher, path + '/actions', version=visible['version'], action='ASK_STUDENT', content='是第几道例题？')
    assert case['state'] == 'WAITING_STUDENT'
    reply = command(student, path + '/messages', 201, content='第二道')
    assert reply['case']['state'] == 'IN_PROGRESS'
    note = command(teacher, path + '/messages', 201, content='内部备课记录', visibility='STAFF')
    assert all(item['content'] != '内部备课记录' for item in get(student, path + '/messages')['items'])
    assert all(item['visibility'] == 'SHARED' for item in get(student, path + '/events')['items'])
    assert '内部备课记录' not in student.get(BASE + path + '/print.html').text
    case = command(teacher, path + '/reviews', 201, version=note['case']['version'], prompt='新例题对你有帮助吗？')
    review_id = case['open_review']['id']
    command(peer, '/reviews/' + str(review_id) + '/answer', 404, outcome='HELPED')
    case = command(student, '/reviews/' + str(review_id) + '/answer', outcome='PARTLY')
    assert case['state'] == 'IN_PROGRESS'
    case = command(teacher, path + '/reviews', 201, version=case['version'], prompt='课堂练习现在能独立完成吗？')
    case = command(student, '/reviews/' + str(case['open_review']['id']) + '/answer', outcome='HELPED', emotion='NEUTRAL')
    assert case['state'] == 'RESOLVED' and case['resolution'] == 'STUDENT_CONFIRMED'
    report = get(teacher, '/dashboard')
    assert report['confirmed_improved'] == 1 and report['reviews']['answered'] == 2
    assert '学生确认改善' in teacher.get(BASE + '/export.csv').text


def test_batch_retries_and_conflicts_are_atomic(actors):
    session = classroom_for(actors)
    assert schedule(actors, session, ('student', 'other_student')).status_code == 200
    teacher = actors['teacher']['client']
    student = actors['student']['client']
    peer = actors['other_student']['client']
    a = create(student, session)
    b = create(peer, session, title='需要更慢的讲解')
    group = command(teacher, '/groups', 201, session_id=session['id'], title='补充例题', case_ids=[a['id'], b['id']])
    path = '/groups/' + str(group['id']) + '/batch'
    payload = {
        'version': group['version'], 'action': 'REPLY', 'content': '下节课补充两道例题。',
        'members': [{'case_id': a['id'], 'version': a['version']}, {'case_id': b['id'], 'version': b['version'] + 1}],
    }
    command(teacher, path, 409, **payload)
    assert get(student, '/cases/' + str(a['id']) + '/messages')['items'] == []
    payload['members'][1]['version'] = b['version']
    payload['request_id'] = str(uuid4())
    first = teacher.post(BASE + path, json=payload, headers=HEADERS)
    retry = teacher.post(BASE + path, json=payload, headers=HEADERS)
    assert first.status_code == retry.status_code == 200, first.text
    assert first.json() == retry.json()
    assert len(get(student, '/cases/' + str(a['id']) + '/messages')['items']) == 1
    assert len(get(peer, '/cases/' + str(b['id']) + '/messages')['items']) == 1
    assert get(student, '/cases/' + str(a['id']))['groups'] == []


def test_course_policy_and_submission_limit(actors):
    session = classroom_for(actors)
    assert schedule(actors, session).status_code == 200
    teacher = actors['teacher']['client']
    student = actors['student']['client']
    course = '/courses/' + str(session['course_id']) + '/policy'
    policy = get(teacher, course)
    assert policy['version'] == 0
    updated = command(teacher, course, method='put', version=policy['version'], daily_case_limit=1)
    assert updated['daily_case_limit'] == 1
    create(student, session)
    command(student, '/cases', 409, session_id=session['id'], emotion='NEUTRAL', reasons=['POSITIVE'], title='第二条反馈')
    command(student, course, 403, method='put', version=updated['version'], daily_case_limit=4)


def test_suggested_groups_only_contain_matching_visible_cases(actors):
    session = classroom_for(actors)
    other = classroom_for(actors, owner='other_teacher')
    for classroom in (session, other):
        assert schedule(actors, classroom, ('student', 'other_student')).status_code == 200
    teacher = actors['teacher']['client']
    student = actors['student']['client']
    peer = actors['other_student']['client']
    first = create(student, session, topic_minute=1)
    second = create(peer, session, topic_minute=2)
    create(student, other, topic_minute=1)
    create(peer, other, topic_minute=2)
    report = get(teacher, '/group-suggestions?topic_window=5')
    assert report['candidate_count'] == 2
    item, = report['items']
    assert item['reason'] == 'NEED_EXAMPLE'
    assert item['minute_from'] == 0 and item['minute_to'] == 5
    assert {value['id'] for value in item['members']} == {first['id'], second['id']}
    command(teacher, '/groups', 201, session_id=session['id'], title='补充例题',
            case_ids=[first['id'], second['id']])
    assert get(teacher, '/group-suggestions')['items'] == []
    assert get(teacher, '/group-suggestions?include_grouped=true')['suggestion_count'] == 1
    assert student.get(BASE + '/group-suggestions').status_code == 403


def test_review_desk_reminder_is_scoped_and_rate_limited(actors):
    session = classroom_for(actors)
    assert schedule(actors, session, ('student', 'other_student')).status_code == 200
    teacher = actors['teacher']['client']
    student = actors['student']['client']
    peer = actors['other_student']['client']
    case = create(student, session)
    path = '/cases/' + str(case['id'])
    case = command(teacher, path + '/actions', version=case['version'], action='ACKNOWLEDGE')
    case = command(teacher, path + '/reviews', 201, version=case['version'], prompt='练习完成了吗？')
    review = case['open_review']
    reminder = '/reviews/' + str(review['id']) + '/remind'
    command(teacher, reminder, 409, version=review['version'])
    with connect() as db:
        db.execute(
            'UPDATE feedback_reviews SET due_at=? WHERE id=?',
            (utc_text(now_utc() - timedelta(minutes=15)), review['id']),
        )
    row, = get(teacher, '/review-desk?status=OVERDUE')['items']
    assert row['can_remind'] and row['case_id'] == case['id']
    assert get(peer, '/review-desk?status=OVERDUE')['items'] == []
    assert get(teacher, '/cases?review_overdue=true')['total'] == 1
    result = command(teacher, reminder, version=row['version'])
    assert result['reminder_count'] == 1
    command(teacher, reminder, 409, version=row['version'])
    assert not get(teacher, '/review-desk')['items'][0]['can_remind']
    assert sum(item['code'] == 'REVIEW_REMINDER' for item in get(student, '/inbox')['items']) == 1
    student_progress = get(student, path + '/progress')
    assert student_progress['next']['action'] == 'REVIEW'
    assert student_progress['next']['overdue']
    assert student_progress['current']['state'] == 'WAITING_REVIEW'


def test_adjustment_report_tracks_only_subsequent_review_and_retains_compatibility(actors):
    session = classroom_for(actors)
    assert schedule(actors, session).status_code == 200
    teacher = actors['teacher']['client']
    student = actors['student']['client']
    case = create(student, session)
    path = '/cases/' + str(case['id'])
    entry_path = '/api/sessions/' + str(session['id']) + '/insights/entries'
    entry = teacher.post(entry_path, headers=HEADERS, json={
        'kind': 'ACTION', 'title': '私有备课标题', 'content': '教师备课正文',
        'start_minute': 1, 'end_minute': 1, 'status': 'DONE', 'request_id': str(uuid4()),
    })
    assert entry.status_code == 201, entry.text
    adjustment = entry.json()['data']
    case = command(teacher, path + '/actions', version=case['version'], action='START')
    case = command(teacher, path + '/reviews', 201, version=case['version'], prompt='原来的讲解可以跟上吗？')
    case = command(student, '/reviews/' + str(case['open_review']['id']) + '/answer', outcome='PARTLY')
    case = command(teacher, path + '/adjustments', version=case['version'],
                   adjustment_id=adjustment['id'], public_summary='在课堂上补充了练习题。')
    visible = get(student, path)['adjustments'][0]
    assert visible['public_summary'] == '在课堂上补充了练习题。'
    assert 'title' not in visible
    assert get(teacher, '/adjustment-report')['items'][0]['unrequested'] == 1
    case = command(teacher, path + '/reviews', 201, version=case['version'], prompt='新加的练习题有帮助吗？')
    command(student, '/reviews/' + str(case['open_review']['id']) + '/answer', outcome='HELPED')
    report = get(teacher, '/adjustment-report')
    assert report['items'][0]['helped'] == 1
    assert '私有备课标题' in teacher.get(BASE + '/adjustment-report/export.csv').text
    assert student.get(BASE + '/adjustment-report').status_code == 403
    workload = get(teacher, '/workload')
    assert workload['current']['summary']['total'] == 1
    assert workload['current']['activity']['answers'] == 2
    assert workload['previous']['summary']['total'] == 0
    removal = teacher.delete(entry_path + '/' + str(adjustment['id']),
                             params={'version': adjustment['version']}, headers=HEADERS)
    assert removal.status_code == 200, removal.text
    assert get(student, path)['adjustments'] == []
