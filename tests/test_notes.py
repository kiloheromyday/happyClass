import csv
import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.models.classroom import utc_text
from backend.app.repositories.database import connect, initialize_database
from test_classroom import HEADERS, actors, classroom_for, schedule, submit

BASE = '/api/personal/notes'


def create(actors, actor='student', **changes):
    payload = {'title': '课堂笔记', 'content': '今天理解了信息层级。', 'request_id': str(uuid4()), **changes}
    return actors[actor]['client'].post(BASE, json=payload, headers=HEADERS)


def edit_body(item, **changes):
    return {key: changes.get(key, item[key]) for key in ('session_id', 'title', 'content', 'takeaway', 'next_step', 'reviewed', 'version')}


def test_note_lifecycle_and_review_status(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    response = create(actors, session_id=session['id'], title=' 笔记标题 ', content=' 正文\n第二行 ')
    assert response.status_code == 201
    item = response.json()['data']
    assert item['title'] == '笔记标题' and item['content'] == '正文\n第二行'
    assert item['course_name'] == '软件工程' and not item['reviewed'] and item['reviewed_at'] is None
    client = actors['student']['client']
    updated = client.put(f"{BASE}/{item['id']}", json=edit_body(item, reviewed=True, takeaway='学会分层', next_step='再练一个例子'), headers=HEADERS).json()['data']
    assert updated['version'] == 2 and updated['reviewed_at'] and updated['reviewed'] is True
    changed = client.put(f"{BASE}/{item['id']}", json=edit_body(updated, content='补充内容'), headers=HEADERS).json()['data']
    assert changed['reviewed_at'] == updated['reviewed_at']
    reopened = client.put(f"{BASE}/{item['id']}", json=edit_body(changed, reviewed=False), headers=HEADERS).json()['data']
    assert reopened['reviewed_at'] is None and not reopened['reviewed']
    assert client.get(f"{BASE}/{item['id']}").json()['data'] == reopened
    assert client.delete(f"{BASE}/{item['id']}?version={reopened['version']}", headers=HEADERS).status_code == 200
    assert client.get(f"{BASE}/{item['id']}").status_code == 404


def test_notes_private_from_peers_staff_and_buddies(actors):
    item = create(actors).json()['data']
    for actor in ('teacher', 'admin', 'other_teacher'):
        client = actors[actor]['client']
        for path in (BASE, f"{BASE}/{item['id']}", BASE + '/sessions', BASE + '/export', '/api/personal/review'):
            assert client.get(path).status_code == 403
        assert client.put(f"{BASE}/{item['id']}", json=edit_body(item), headers=HEADERS).status_code == 403
        assert client.delete(f"{BASE}/{item['id']}?version=1", headers=HEADERS).status_code == 403
    peer = actors['other_student']['client']
    low, high = sorted([actors['student']['user']['id'], actors['other_student']['user']['id']])
    with connect() as connection:
        connection.execute("INSERT INTO buddy_connections(low_user_id,high_user_id,requester_id,status,accepted_at) VALUES (?,?,?,'ACCEPTED',?)", (low, high, low, utc_text(datetime.now(UTC))))
    assert peer.get(BASE).json()['data']['total'] == 0
    assert peer.get(f"{BASE}/{item['id']}").status_code == 404
    assert peer.put(f"{BASE}/{item['id']}", json=edit_body(item), headers=HEADERS).status_code == 404
    assert peer.delete(f"{BASE}/{item['id']}?version=1", headers=HEADERS).status_code == 404
    assert item['title'] not in peer.get(BASE + '/export').content.decode('utf-8-sig')
    assert peer.get('/api/personal/review').json()['data']['summary']['note_count'] == 0
    assert not {'user_id', 'request_id', 'payload_hash'} & item.keys()


def test_class_link_and_history_after_roster_removal(actors):
    session = classroom_for(actors)
    assert create(actors, session_id=session['id']).status_code == 403
    schedule(actors, session)
    submit(actors['student'], session)
    item = create(actors, session_id=session['id']).json()['data']
    create(actors, title='不关联课堂')
    filtered = actors['student']['client'].get(BASE, params={'session_id': session['id']}).json()['data']
    assert filtered['total'] == 1 and filtered['items'][0]['id'] == item['id']
    schedule(actors, session, ())
    client = actors['student']['client']
    assert session['id'] in [row['id'] for row in client.get(BASE + '/sessions').json()['data']['items']]
    assert client.put(f"{BASE}/{item['id']}", json=edit_body(item, content='课后补充'), headers=HEADERS).status_code == 200
    assert create(actors, session_id=session['id']).status_code == 201
    assert actors['other_student']['client'].get(BASE + '/sessions').json()['data']['items'] == []
    assert create(actors, session_id=99999).status_code == 403


def test_existing_note_retained_after_removal_without_feedback(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    item = create(actors, session_id=session['id']).json()['data']
    schedule(actors, session, ())
    client = actors['student']['client']
    assert client.get(f"{BASE}/{item['id']}").status_code == 200
    assert client.put(f"{BASE}/{item['id']}", json=edit_body(item, takeaway='课后回顾'), headers=HEADERS).status_code == 200


def test_create_retry_conflicts_and_deleted_tombstone(actors):
    key = str(uuid4())
    first = create(actors, request_id=key).json()['data']
    client = actors['student']['client']
    assert create(actors, request_id=key).status_code == 200
    assert create(actors, request_id=key, title='不同').status_code == 409
    changed = client.put(f"{BASE}/{first['id']}", json=edit_body(first, title='已编辑'), headers=HEADERS).json()['data']
    assert create(actors, request_id=key).json()['data']['title'] == '已编辑'
    assert client.delete(f"{BASE}/{first['id']}?version={changed['version']}", headers=HEADERS).status_code == 200
    assert create(actors, request_id=key).status_code == 410
    assert client.get(BASE).json()['data']['total'] == 0


def test_edit_and_delete_version_conflict(actors):
    item = create(actors).json()['data']
    client = actors['student']['client']
    assert client.put(f"{BASE}/{item['id']}", json=edit_body(item, title='更新后'), headers=HEADERS).status_code == 200
    assert client.put(f"{BASE}/{item['id']}", json=edit_body(item, title='旧版本覆盖'), headers=HEADERS).status_code == 409
    assert client.delete(f"{BASE}/{item['id']}?version=1", headers=HEADERS).status_code == 409
    assert client.get(f"{BASE}/{item['id']}").json()['data']['title'] == '更新后'


@pytest.mark.parametrize('changes', [dict(title=' '), dict(content=' '), dict(title='x' * 81), dict(content='x' * 5001), dict(takeaway='x' * 301), dict(next_step='x' * 301), dict(content='\x00'), dict(title='两\n行'), dict(user_id=999), dict(created_at='2020-01-01'), dict(reviewed='true'), dict(session_id=True), dict(request_id='bad')])
def test_note_input_validation(actors, changes):
    assert create(actors, **changes).status_code == 422


def test_csrf_and_unknown_query_filters(actors):
    client = actors['student']['client']
    assert client.post(BASE, json={'title': '标题', 'content': '正文', 'request_id': str(uuid4())}).status_code == 403
    item = create(actors).json()['data']
    assert client.put(f"{BASE}/{item['id']}", json=edit_body(item)).status_code == 403
    assert client.delete(f"{BASE}/{item['id']}?version=1").status_code == 403
    for query in ('limit=1000', 'offset=-1', 'review=INVALID', 'session_id=-1', 'q=' + 'x' * 81):
        assert client.get(BASE + '?' + query).status_code == 422


def test_search_and_export_match_filters_and_escape_formulas(actors):
    a = create(actors, title='设计 100%_\\', content='=HYPERLINK("bad")', takeaway='构图', next_step='@练习', reviewed=True).json()['data']
    create(actors, title='普通笔记', content='后续计划')
    create(actors, actor='other_student', title='设计 100%_\\')
    client = actors['student']['client']
    for query in ('100%_\\', '构图', '@练习', 'HYPERLINK'):
        data = client.get(BASE, params={'q': query}).json()['data']
        assert data['total'] == 1 and data['items'][0]['id'] == a['id']
    assert client.get(BASE, params={'q': "' OR 1=1 --"}).json()['data']['total'] == 0
    assert client.get(BASE, params={'review': 'PENDING'}).json()['data']['total'] == 1
    response = client.get(BASE + '/export', params={'review': 'DONE'})
    assert response.status_code == 200 and response.headers['X-Export-Count'] == '1'
    rows = list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))
    assert len(rows) == 2 and rows[1][0] == a['title'] and rows[1][3].startswith("'=HYPERLINK") and rows[1][5] == "'@练习"
    assert client.get(BASE, params={'limit': 1, 'offset': 1}).json()['data']['total'] == 2
    assert len(client.get(BASE, params={'limit': 1, 'offset': 1}).json()['data']['items']) == 1


def test_creation_limit_survives_deletion(actors):
    client = actors['student']['client']
    for index in range(30):
        response = create(actors, title=f'笔记 {index}')
        assert response.status_code == 201
        item = response.json()['data']
        client.delete(f"{BASE}/{item['id']}?version=1", headers=HEADERS)
    assert create(actors).status_code == 429


def test_note_storage_limit(actors):
    timestamp = utc_text(datetime.now(UTC))
    with connect() as connection:
        connection.executemany('INSERT INTO personal_notes(user_id,title,content,created_at,updated_at) VALUES (?,?,?,?,?)', [(actors['student']['user']['id'], f'笔记 {index}', '正文', timestamp, timestamp) for index in range(1000)])
    assert create(actors).status_code == 409
    assert create(actors, actor='other_student').status_code == 201


def test_personal_review_uses_own_feedback_and_selected_window(actors, monkeypatch):
    session = classroom_for(actors)
    schedule(actors, session, ('student', 'other_student'))
    now = datetime(2026, 11, 3, 12, tzinfo=UTC)
    monkeypatch.setattr('backend.app.services.notes.now_utc', lambda: now)
    with connect() as connection:
        for user, stamp, emotion in [('student', now - timedelta(days=7), 'HAPPY'), ('student', now - timedelta(days=1), 'NEUTRAL'), ('student', now, 'SAD'), ('student', now - timedelta(days=8), 'SAD'), ('other_student', now - timedelta(days=1), 'ANGRY')]:
            connection.execute("INSERT INTO emoji_records(session_id,user_id,emotion,source,recorded_at) VALUES (?,?,?,'MANUAL',?)", (session['id'], actors[user]['user']['id'], emotion, utc_text(stamp)))
        connection.execute("INSERT INTO emoji_records(session_id,emotion,source,confidence,recorded_at) VALUES (?,'FEAR','AI',.9,?)", (session['id'], utc_text(now - timedelta(days=1))))
    item = create(actors, session_id=session['id'], reviewed=True).json()['data']
    with connect() as connection:
        connection.execute('UPDATE personal_notes SET created_at=? WHERE id=?', (utc_text(now - timedelta(days=2)), item['id']))
    create(actors)
    data_response = actors['student']['client'].get('/api/personal/review?days=7')
    assert data_response.status_code == 200, data_response.text
    data = data_response.json()['data']
    assert data['summary'] == {'feedback_count': 2, 'active_days': 2, 'note_count': 1, 'reviewed_count': 1, 'pending_count': 1}
    assert sum(item['count'] for item in data['emotions']) == 2 and sum(item['total'] for item in data['trend']) == 2
    assert data['sessions'][0]['feedback_count'] == 2 and data['sessions'][0]['note_count'] == 1
    assert actors['student']['client'].get('/api/personal/review?days=30').status_code == 200
    assert actors['student']['client'].get('/api/personal/review?days=5').status_code == 422


def test_old_database_initialization_and_data_preservation(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    submit(actors['student'], session)
    with connect() as connection:
        connection.execute('DROP TABLE personal_note_keys')
        connection.execute('DROP TABLE personal_notes')
    initialize_database()
    item = create(actors).json()['data']
    initialize_database()
    assert actors['student']['client'].get(f"{BASE}/{item['id']}").status_code == 200
    assert actors['student']['client'].get('/api/emoji/history').json()['data']['total'] == 1


def test_review_class_filter_recent_notes_and_export_privacy(actors, monkeypatch):
    session, other = classroom_for(actors), classroom_for(actors)
    schedule(actors, session, ('student', 'other_student'))
    schedule(actors, other)
    now = datetime.now(UTC) + timedelta(minutes=1)
    monkeypatch.setattr('backend.app.services.notes.now_utc', lambda: now)
    submit(actors['student'], session)
    submit(actors['student'], other, emotion='SAD')
    first = create(actors, session_id=session['id'], title='=个人收获', takeaway='@例子', next_step='+练习').json()['data']
    create(actors, session_id=other['id'], title='另一课堂笔记')
    create(actors, actor='other_student', session_id=session['id'], title='别人的私密笔记')
    with connect() as connection:
        connection.execute('UPDATE personal_notes SET created_at=?', (utc_text(now - timedelta(minutes=1)),))
    client = actors['student']['client']
    data = client.get('/api/personal/review', params={'days': 90, 'session_id': session['id']}).json()['data']
    assert data['summary']['feedback_count'] == 1 and data['summary']['note_count'] == 1 and data['summary']['pending_count'] == 1
    assert len(data['trend']) >= 90
    assert len(data['recent_notes']) == 1 and data['recent_notes'][0]['id'] == first['id']
    content = client.get('/api/personal/review/export', params={'days': 90, 'session_id': session['id']}).content.decode('utf-8-sig')
    assert "'=个人收获" in content and "'@例子" in content and "'+练习" in content
    assert '别人的私密笔记' not in content and '另一课堂笔记' not in content
    foreign = actors['other_student']['client'].get('/api/personal/review', params={'session_id': other['id']}).json()['data']
    assert foreign['summary']['feedback_count'] == 0 and not foreign['recent_notes']
    for actor in ('teacher', 'admin'):
        assert actors[actor]['client'].get('/api/personal/review/export').status_code == 403


DAY_QUERY = {'day': '2026-11-03', 'starts_at': '2026-10-27T12:00:00Z', 'ends_at': '2026-11-03T12:00:00Z'}


def test_review_day_matches_window_scope_and_ownership(actors):
    session, other = classroom_for(actors), classroom_for(actors)
    schedule(actors, session, ('student', 'other_student'))
    schedule(actors, other)
    a = create(actors, session_id=session['id'], title='当天自己的笔记').json()['data']
    b = create(actors, session_id=other['id'], title='另一课堂笔记').json()['data']
    create(actors, actor='other_student', session_id=session['id'], title='别人的笔记')
    with connect() as connection:
        connection.execute("UPDATE personal_notes SET created_at='2026-11-03T09:00:00.000Z'")
        for owner, classroom, stamp in [('student', session, '2026-11-03T00:00:00.000Z'), ('student', session, '2026-11-03T11:59:59.999Z'), ('student', session, '2026-11-03T12:00:00.000Z'), ('student', other, '2026-11-03T09:00:00.000Z'), ('other_student', session, '2026-11-03T09:00:00.000Z')]:
            connection.execute("INSERT INTO emoji_records(user_id,session_id,emotion,source,recorded_at) VALUES (?,?,'HAPPY','MANUAL',?)", (actors[owner]['user']['id'], classroom['id'], stamp))
        connection.execute("INSERT INTO emoji_records(session_id,emotion,source,confidence,recorded_at) VALUES (?,'FEAR','AI',.9,'2026-11-03T09:00:00.000Z')", (session['id'],))
    client = actors['student']['client']
    response = client.get('/api/personal/review/day', params={**DAY_QUERY, 'session_id': session['id']})
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['feedback']['total'] == 2 and sum(item['count'] for item in data['emotions']) == 2
    assert len(data['feedback']['items']) == 2 and all('user_id' not in row for row in data['feedback']['items'])
    assert [row['id'] for row in data['notes']['items']] == [a['id']]
    assert data['notes']['total'] == 1 and '别人的笔记' not in response.text
    all_classes = client.get('/api/personal/review/day', params=DAY_QUERY).json()['data']
    assert all_classes['feedback']['total'] == 3 and {row['id'] for row in all_classes['notes']['items']} == {a['id'], b['id']}
    empty = client.get('/api/personal/review/day', params={**DAY_QUERY, 'day': '2026-11-02'}).json()['data']
    assert empty['feedback']['total'] == empty['notes']['total'] == 0
    for actor in ('teacher', 'admin'):
        assert actors[actor]['client'].get('/api/personal/review/day', params=DAY_QUERY).status_code == 403


def test_review_day_paginates_feedback_and_notes_independently(actors):
    session = classroom_for(actors)
    with connect() as connection:
        for _ in range(15):
            connection.execute("INSERT INTO emoji_records(user_id,session_id,emotion,source,recorded_at) VALUES (?,?,'HAPPY','MANUAL','2026-11-03T09:00:00.000Z')", (actors['student']['user']['id'], session['id']))
        for index in range(13):
            connection.execute("INSERT INTO personal_notes(user_id,title,content,created_at,updated_at) VALUES (?,?,?,'2026-11-03T09:00:00.000Z','2026-11-03T09:00:00.000Z')", (actors['student']['user']['id'], str(index), '正文'))
    client = actors['student']['client']
    first = client.get('/api/personal/review/day', params=DAY_QUERY).json()['data']
    second = client.get('/api/personal/review/day', params={**DAY_QUERY, 'feedback_offset': 12, 'notes_offset': 12}).json()['data']
    assert first['feedback']['total'] == 15 and len(first['feedback']['items']) == 12 and len(second['feedback']['items']) == 3
    assert first['notes']['total'] == 13 and len(first['notes']['items']) == 12 and len(second['notes']['items']) == 1
    assert not {row['id'] for row in first['feedback']['items']} & {row['id'] for row in second['feedback']['items']}
    assert not {row['id'] for row in first['notes']['items']} & {row['id'] for row in second['notes']['items']}
    clipped = client.get('/api/personal/review/day', params={**DAY_QUERY, 'starts_at': '2026-11-03T10:00:00Z'}).json()['data']
    assert clipped['feedback']['total'] == clipped['notes']['total'] == 0


@pytest.mark.parametrize('changes', [dict(day='2026-02-30'), dict(day='2026-11-04'), dict(starts_at='2026-10-27T12:00:00'), dict(ends_at='2026-10-27T12:00:00Z'), dict(starts_at='2025-11-03T00:00:00Z'), dict(feedback_offset=-1), dict(notes_offset=1001), dict(session_id=-1)])
def test_review_day_rejects_invalid_dates_windows_and_pagination(actors, changes):
    assert actors['student']['client'].get('/api/personal/review/day', params={**DAY_QUERY, **changes}).status_code == 422


def test_review_at_midnight_does_not_offer_empty_end_date(actors, monkeypatch):
    monkeypatch.setattr('backend.app.services.notes.now_utc', lambda: datetime(2026, 11, 3, tzinfo=UTC))
    data = actors['student']['client'].get('/api/personal/review?days=7').json()['data']
    assert len(data['trend']) == 7 and data['trend'][-1]['timestamp'].startswith('2026-11-02')
