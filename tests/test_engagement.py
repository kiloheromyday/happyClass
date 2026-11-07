import csv
import io
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.models.classroom import utc_text
from backend.app.repositories.database import connect, initialize_database
from test_classroom import HEADERS, actors, classroom_for, end_session, schedule, submit


def path(session, suffix='questions'):
    return f"/api/sessions/{session['id']}/{suffix}"


def ask(actors, session, actor='student', category='EXAMPLE', text='', request_id=None, **extra):
    return actors[actor]['client'].post(path(session), json={'category': category, 'text': text, 'request_id': request_id or str(uuid4()), **extra}, headers=HEADERS)


def answer(actors, session, item, actor='teacher', **extra):
    return actors[actor]['client'].put(path(session, f"questions/{item['id']}"), json={'reply': '这里用一个生活中的例子说明。', 'status': 'RESOLVED', 'version': item['version'], **extra}, headers=HEADERS)


def test_anonymous_question_reply_and_reopen(actors):
    session = classroom_for(actors)
    schedule(actors, session, ('student', 'other_student'))
    response = ask(actors, session, text=' 能举一个例子吗？ ')
    assert response.status_code == 201
    item = response.json()['data']
    assert item['text'] == '能举一个例子吗？' and item['is_mine']
    allowed = {'id', 'category', 'text', 'reply', 'status', 'version', 'created_at', 'updated_at'}
    teacher_list = actors['teacher']['client'].get(path(session)).json()['data']
    assert set(teacher_list['items'][0]) == allowed
    peer_list = actors['other_student']['client'].get(path(session)).json()['data']
    assert set(peer_list['items'][0]) == allowed | {'is_mine'}
    assert peer_list['items'][0]['is_mine'] is False
    assert answer(actors, session, item).status_code == 200
    listing = actors['student']['client'].get(path(session)).json()['data']
    assert listing['summary'] == {'total': 1, 'open': 0, 'resolved': 1, 'categories': [{'category': code, 'count': int(code == 'EXAMPLE')} for code in ('PACE', 'EXAMPLE', 'REPEAT', 'OTHER')]}
    replied = listing['items'][0]
    assert replied['reply'] and replied['version'] == 2
    assert answer(actors, session, item).status_code == 409  # lost-update defense
    assert answer(actors, session, replied, reply='', status='OPEN').status_code == 200


def test_question_authorization_and_origin(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    assert ask(actors, session, actor='other_student').status_code == 403
    assert ask(actors, session, actor='teacher').status_code == 403
    item = ask(actors, session).json()['data']
    for actor in ('other_teacher', 'other_student'):
        assert actors[actor]['client'].get(path(session)).status_code == 403
        assert answer(actors, session, item, actor=actor).status_code == 403
    assert answer(actors, session, item, actor='student').status_code == 403
    assert actors['student']['client'].post(path(session), json={'category': 'PACE', 'request_id': str(uuid4())}).status_code == 403
    assert actors['teacher']['client'].put(path(session, 'recap'), json={'reflection': '反思', 'version': 0}).status_code == 403
    other = classroom_for(actors)
    assert answer(actors, other, item).status_code == 404
    assert actors['admin']['client'].get(path(session)).status_code == 200


def test_question_retry_and_time_window(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    request_id = str(uuid4())
    first = ask(actors, session, request_id=request_id)
    assert ask(actors, session, request_id=request_id).status_code == 200
    assert ask(actors, session, request_id=request_id, text='不同内容').status_code == 409
    end_session(session)
    assert ask(actors, session).status_code == 409
    assert ask(actors, session, request_id=request_id).json()['data']['id'] == first.json()['data']['id']
    assert actors['student']['client'].get(path(session)).status_code == 200
    assert answer(actors, session, first.json()['data']).status_code == 200
    upcoming = classroom_for(actors, upcoming=True)
    schedule(actors, upcoming)
    assert ask(actors, upcoming).status_code == 409
    assert ask(actors, upcoming, request_id=request_id).status_code == 409


@pytest.mark.parametrize('payload', [dict(category='FAKE'), dict(text='x' * 301), dict(text='\x00'), dict(author_id=999), dict(status='RESOLVED'), dict(request_id='bad')])
def test_question_validation(actors, payload):
    session = classroom_for(actors)
    schedule(actors, session)
    assert ask(actors, session, **payload).status_code == 422


def test_empty_other_and_rate_limit_and_pagination(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    assert ask(actors, session, category='OTHER', text=' ').status_code == 422
    for index in range(20):
        assert ask(actors, session, text=f'问题 {index}').status_code == 201
    assert ask(actors, session).status_code == 429
    client = actors['teacher']['client']
    page1 = client.get(path(session), params={'limit': 12}).json()['data']
    page2 = client.get(path(session), params={'limit': 12, 'offset': 12}).json()['data']
    assert page1['total'] == 20 and len(page1['items']) == 12 and len(page2['items']) == 8
    assert not {i['id'] for i in page1['items']} & {i['id'] for i in page2['items']}
    answer(actors, session, page1['items'][0])
    filtered = client.get(path(session), params={'status': 'RESOLVED'}).json()['data']
    assert filtered['total'] == 1 and filtered['summary']['total'] == 20
    assert client.get(path(session), params={'limit': 2001}).status_code == 422
    assert client.get(path(session), params={'status': "' OR 1=1"}).status_code == 422


def test_recap_period_boundaries_and_actual_counts(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    start, end = datetime.fromisoformat(session['starts_at']), datetime.fromisoformat(session['ends_at'])
    midpoint = start + (end - start) / 2
    with connect() as connection:
        for stamp, emotion in [(start - timedelta(milliseconds=1), 'SAD'), (start, 'HAPPY'), (midpoint - timedelta(milliseconds=1), 'HAPPY'), (midpoint, 'NEUTRAL'), (end - timedelta(milliseconds=1), 'NEUTRAL'), (end, 'SAD')]:
            connection.execute("INSERT INTO emoji_records(session_id,user_id,emotion,source,recorded_at) VALUES (?,?,?,'MANUAL',?)", (session['id'], actors['student']['user']['id'], emotion, utc_text(stamp)))
    question = ask(actors, session, category='REPEAT').json()['data']
    answer(actors, session, question)
    data = actors['teacher']['client'].get(path(session, 'recap')).json()['data']
    assert data['summary'] == {'total': 6, 'responding_students': 1, 'manual_count': 6, 'ai_count': 0, 'demo_count': 0}
    assert data['outside_period_count'] == 2
    assert [item['total'] for item in data['periods']] == [2, 2]
    assert next(i for i in data['periods'][0]['emotions'] if i['emotion'] == 'HAPPY')['count'] == 2
    assert next(i for i in data['periods'][1]['emotions'] if i['emotion'] == 'NEUTRAL')['count'] == 2
    assert data['questions']['resolved'] == 1 and data['reflection']['version'] == 0


def test_reflection_export_privacy_and_spreadsheet_safety(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    item = ask(actors, session, text='=HYPERLINK("bad")').json()['data']
    answer(actors, session, item, reply='@危险公式')
    client = actors['teacher']['client']
    payload = {'reflection': '+公式\n第二行', 'version': 0}
    saved = client.put(path(session, 'recap'), json=payload, headers=HEADERS)
    assert saved.status_code == 200 and saved.json()['data']['version'] == 1
    assert client.put(path(session, 'recap'), json=payload, headers=HEADERS).status_code == 409
    export = client.get(path(session, 'recap/export'))
    assert export.status_code == 200 and 'attachment' in export.headers['Content-Disposition']
    content = export.content.decode('utf-8-sig')
    rows = list(csv.reader(io.StringIO(content)))
    assert any("'=HYPERLINK" in cell for row in rows for cell in row)
    assert any(cell == "'@危险公式" for row in rows for cell in row)
    assert any(cell == "'+公式\n第二行" for row in rows for cell in row)
    assert 'student' not in content and 'author_id' not in content and 'request_id' not in content
    for actor in ('student', 'other_teacher'):
        for suffix in ('recap', 'recap/export'):
            assert actors[actor]['client'].get(path(session, suffix)).status_code == 403
        assert actors[actor]['client'].put(path(session, 'recap'), json=payload, headers=HEADERS).status_code == 403
    assert client.put(path(session, 'recap'), json={'reflection': 'x' * 2001, 'version': 1}, headers=HEADERS).status_code == 422


def test_reinitialize_preserves_existing_data_and_new_features(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    submit(actors['student'], session)
    with connect() as connection:
        # Simulate the existing 0.8 schema with accounts and classroom records.
        connection.execute('DROP TABLE classroom_questions')
        connection.execute('DROP TABLE classroom_reflections')
    initialize_database()
    ask(actors, session)
    initialize_database()
    initialize_database()
    data = actors['teacher']['client'].get(path(session, 'recap')).json()['data']
    assert data['summary']['total'] == 1 and data['questions']['total'] == 1
