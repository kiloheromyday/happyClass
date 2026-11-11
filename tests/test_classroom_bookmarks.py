from datetime import timedelta
from uuid import uuid4

from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.database import connect
from test_classroom import HEADERS, actors, classroom_for, schedule

BASE = '/api/classroom-bookmarks'


def get(client, path, expected=200, **params):
    result = client.get(BASE + path, params=params)
    assert result.status_code == expected, result.text
    return result.json()['data']


def mutate(client, method, path, body=None, expected=200, **kwargs):
    result = getattr(client, method)(BASE + path, json=body, headers=HEADERS, **kwargs) if body is not None else (
        getattr(client, method)(BASE + path, headers=HEADERS, **kwargs)
    )
    assert result.status_code == expected, result.text
    return result.json()['data']


def session_path(session, tail):
    return '/sessions/' + str(session['id']) + '/' + tail


def add(student, session, minute=None, expected=201, **fields):
    return mutate(student, 'post', session_path(session, 'mine'), {
        'request_id': str(uuid4()), 'minute': minute, **fields,
    }, expected)['bookmark']


def draft_content(**fields):
    return {
        'title': '尾指针移动的顺序', 'content': '先写入元素，再移动尾指针。',
        'start_minute': 0, 'end_minute': 5, **fields,
    }


def make_class(actors):
    session = classroom_for(actors)
    assert schedule(actors, session, ('student', 'other_student')).status_code == 200
    return session


def test_bookmark_time_and_request_retry(actors):
    session = make_class(actors)
    student = actors['student']['client']
    path = session_path(session, 'mine')
    payload = {'request_id': str(uuid4()), 'note': '自己的笔记'}
    first = mutate(student, 'post', path, payload, 201)
    second = mutate(student, 'post', path, payload, 201)
    assert first['created'] and not second['created']
    assert first['bookmark'] == second['bookmark']
    item = first['bookmark']
    duplicate = mutate(student, 'post', path, {'request_id': str(uuid4()), 'minute': item['minute']}, 201)
    assert not duplicate['created'] and duplicate['bookmark']['id'] == item['id']
    mutate(student, 'post', path, {**payload, 'note': '不同内容'}, 409)
    mutate(student, 'post', path, {'request_id': str(uuid4()), 'minute': 1000}, 422)
    with connect() as db:
        stamp = now_utc()
        db.execute('UPDATE class_sessions SET starts_at=?,ends_at=? WHERE id=?', (
            utc_text(stamp - timedelta(hours=2)), utc_text(stamp - timedelta(hours=1)), session['id'],
        ))
    mutate(student, 'post', path, {'request_id': str(uuid4())}, 409)
    assert add(student, session, 16)['minute'] == 16
    assert get(student, '/mine')['summary']['total'] == 2


def test_anonymous_timeline_and_bookmark_access(actors):
    session = make_class(actors)
    student = actors['student']['client']
    peer = actors['other_student']['client']
    teacher = actors['teacher']['client']
    identifier = add(student, session, 1, title='我的私人书签', note='给自己看的内容', reason='EXAMPLE')['id']
    add(student, session, 2, reason='PACE')
    add(peer, session, 1, reason='PACE')
    path = '/mine/' + str(identifier)
    update = {'version': 1, 'reason': 'EXAMPLE', 'title': '复习内容', 'note': '私密说明', 'reviewed': True}
    mutate(peer, 'put', path, update, 404)
    mutate(teacher, 'put', path, update, 403)
    assert get(teacher, '/mine', 403) is None
    report_path = session_path(session, 'timeline')
    get(actors['other_teacher']['client'], report_path, 403)
    get(student, report_path, 403)
    report = get(teacher, report_path, bucket='5')
    first = report['segments'][0]
    assert first['count'] == 3 and first['student_count'] == 2
    assert [(reason['value'], reason['count']) for reason in first['reasons']] == [('PACE', 2), ('EXAMPLE', 1)]
    assert '我的私人书签' not in str(report) and '给自己看的内容' not in str(report)
    assert get(peer, '/mine')['total'] == 1
    saved = mutate(student, 'put', path, update)
    assert saved['version'] == 2 and saved['reviewed']
    mutate(student, 'put', path, update, 409)
    assert get(student, '/mine', state='REVIEWED', term='私密')['items'][0]['id'] == identifier
    mutate(student, 'delete', path, expected=409, params={'version': 1})
    mutate(student, 'delete', path, params={'version': 2})
    assert get(student, '/mine', state='REVIEWED')['total'] == 0


def test_teacher_publication_and_material_review_versions(actors):
    session = make_class(actors)
    student = actors['student']['client']
    teacher = actors['teacher']['client']
    peer_teacher = actors['other_teacher']['client']
    mark = add(student, session, 3)
    path = session_path(session, 'materials')
    payload = draft_content(request_id=str(uuid4()), links=[{'label': '课件', 'url': 'https://example.org/lesson'}])
    draft = mutate(teacher, 'post', path, payload, 201)
    assert mutate(teacher, 'post', path, payload, 201)['id'] == draft['id']
    assert get(student, path)['total'] == 0
    assert get(student, '/mine')['items'][0]['materials'] == []
    get(student, path, 403, state='DRAFT')
    get(peer_teacher, path, 403)
    mutate(student, 'post', path, payload, 403)
    mutate(teacher, 'post', path, draft_content(
        request_id=str(uuid4()), links=[{'label': '坏链接', 'url': 'javascript:alert(1)'}],
    ), 422)
    material = '/materials/' + str(draft['id'])
    published = mutate(teacher, 'post', material + '/state', {'version': 1, 'action': 'PUBLISH'})
    assert published['state'] == 'PUBLISHED'
    assert get(student, '/mine')['items'][0]['materials'][0]['id'] == draft['id']
    assert get(student, path, start_minute=5, end_minute=10)['total'] == 0
    version = published['version']
    mutate(student, 'put', material + '/progress', {'version': version, 'completed': True})
    assert get(student, path)['items'][0]['completed']
    edited = mutate(teacher, 'put', material, draft_content(version=version, content='补上边界情况。'))
    mutate(student, 'put', material + '/progress', {'version': version, 'completed': True}, 409)
    refreshed = get(student, path)['items'][0]
    assert refreshed['changed_after_review'] and not refreshed['completed']
    mutate(teacher, 'post', material + '/state', {'version': edited['version'], 'action': 'ARCHIVE'})
    assert get(student, path)['total'] == 0
    assert get(student, '/mine')['items'][0]['id'] == mark['id']


def test_study_queue_batch_and_replay_overlay(actors):
    session = make_class(actors)
    student = actors['student']['client']
    peer = actors['other_student']['client']
    teacher = actors['teacher']['client']
    mark1 = add(student, session, 1)
    mark2 = add(student, session, 3, note='私人内容')
    peer_mark = add(peer, session, 3)
    material = mutate(teacher, 'post', session_path(session, 'materials'), draft_content(
        request_id=str(uuid4()), publish=True, start_minute=3, end_minute=4,
    ), 201)
    queue = get(student, '/study-queue')
    assert queue['coverage'] == {'pending': 2, 'ready': 1, 'waiting': 1}
    assert [entry['id'] for entry in queue['items']] == [mark2['id'], mark1['id']]
    mutate(student, 'post', '/mine/review', {'bookmark_ids': [mark1['id'], peer_mark['id']], 'reviewed': True}, 404)
    assert get(student, '/study-queue')['total'] == 2
    mutate(student, 'post', '/mine/review', {'bookmark_ids': [mark1['id'], mark2['id']], 'reviewed': True})
    assert get(student, '/study-queue')['total'] == 0
    path = '/api/sessions/' + str(session['id']) + '/emotion-replay'
    result = teacher.get(path)
    assert result.status_code == 200
    frame = result.json()['data']['frames'][3]
    assert frame['bookmark_count'] == 2 and frame['study_materials'][0]['id'] == material['id']
    assert '私人内容' not in str(frame) and frame['total'] == 0
    frame = teacher.get(path, params={'data_scope': 'DEMO'}).json()['data']['frames'][3]
    assert 'bookmark_count' not in frame
    assert student.get(path).status_code == 403


def test_personal_export_and_class_reading_summary(actors):
    session = make_class(actors)
    student = actors['student']['client']
    peer = actors['other_student']['client']
    teacher = actors['teacher']['client']
    add(student, session, 1, title='=1+2', note='自己的复习笔记')
    add(peer, session, 1, note='另一位学生的笔记')
    item = mutate(teacher, 'post', session_path(session, 'materials'), draft_content(
        title='=2+2', request_id=str(uuid4()), publish=True,
    ), 201)
    export = student.get(BASE + '/mine.csv')
    assert export.status_code == 200
    assert "'=1+2" in export.text and "'=2+2" in export.text
    assert '自己的复习笔记' in export.text and '另一位学生的笔记' not in export.text
    assert teacher.get(BASE + '/mine.csv').status_code == 403
    progress = '/materials/' + str(item['id']) + '/progress'
    mutate(student, 'put', progress, {'version': item['version'], 'completed': True})
    report_path = session_path(session, 'reading-report')
    report = get(teacher, report_path)
    assert report['summary']['enrolled'] == 2 and report['summary']['read_at_least_one'] == 1
    assert report['items'][0]['read_current'] == 1 and report['items'][0]['read_rate'] == 50
    assert 'student_id' not in str(report) and '自己的复习笔记' not in str(report)
    get(student, report_path, 403)
    update_path = '/materials/' + str(item['id'])
    mutate(teacher, 'put', update_path, draft_content(version=item['version'], title='=2+2', content='新版本'))
    report = get(teacher, report_path)
    assert report['items'][0]['read_older'] == 1 and report['items'][0]['read_current'] == 0
    assert "'=2+2" in teacher.get(BASE + report_path + '.csv').text
