from backend.app.repositories.database import connect, initialize_database
from tests.test_classroom import actors, classroom_for, schedule, submit, HEADERS


def set_mode(actors, session, mode, version=0, actor='teacher'):
    return actors[actor]['client'].put(f"/api/privacy/sessions/{session['id']}", json={'mode': mode, 'version': version}, headers=HEADERS)


def test_anonymous_mode_covers_history_dashboard_and_csv_without_hiding_personal_history(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    record = submit(actors['student'], session).json()['data']
    assert set_mode(actors, session, 'ANONYMOUS').status_code == 200
    for role in ('teacher', 'admin'):
        client = actors[role]['client']
        history = client.get('/api/emoji/history').json()['data']
        assert history['total'] == 1
        item = history['items'][0]
        assert item['username'] is None and item['user_id'] is None and item['device_id'] is None
        dashboard = client.get(f"/api/dashboard/realtime?session_id={session['id']}").json()['data']
        assert dashboard['latest'][0]['username'] is None
        exported = client.get(f"/api/reports/export?session_id={session['id']}")
        assert exported.status_code == 200
        assert actors['student']['user']['username'] not in exported.text
    own = actors['student']['client'].get('/api/emoji/history').json()['data']['items'][0]
    assert own['id'] == record['id'] and own['user_id'] == actors['student']['user']['id']
    with connect() as connection:
        assert connection.execute('SELECT user_id FROM emoji_records').fetchone()[0] == own['user_id']


def test_aggregate_mode_removes_details_counts_pagination_and_blocks_mixed_exports(actors):
    first = classroom_for(actors)
    second = classroom_for(actors)
    for session in (first, second):
        schedule(actors, session)
        submit(actors['student'], session)
    assert set_mode(actors, first, 'AGGREGATE').status_code == 200
    client = actors['teacher']['client']
    history = client.get('/api/emoji/history?limit=1').json()['data']
    assert history['total'] == 1 and history['items'][0]['session_id'] == second['id']
    assert client.get(f"/api/emoji/history?session_id={first['id']}").json()['data']['items'] == []
    dashboard = client.get(f"/api/dashboard/realtime?session_id={first['id']}").json()['data']
    assert dashboard['latest'] == [] and dashboard['summary']['total'] == 1
    assert client.get('/api/reports/export').status_code == 409
    exported = client.get(f"/api/privacy/sessions/{first['id']}/export")
    assert exported.status_code == 200 and 'HAPPY,MANUAL,1' in exported.text
    assert actors['student']['user']['username'] not in exported.text
    assert actors['student']['client'].get('/api/emoji/history').json()['data']['total'] == 2


def test_policy_permissions_concurrency_and_no_privacy_downgrade(actors):
    session = classroom_for(actors)
    schedule(actors, session)
    for actor in ('student', 'other_teacher'):
        assert set_mode(actors, session, 'ANONYMOUS', actor=actor).status_code == 403
    assert actors['other_student']['client'].get(f"/api/privacy/sessions/{session['id']}").status_code == 403
    assert set_mode(actors, session, 'ANONYMOUS').json()['data']['version'] == 1
    assert set_mode(actors, session, 'STANDARD', version=0).status_code == 409
    # Empty classrooms can change configuration; recorded classrooms cannot reveal old identities.
    assert set_mode(actors, session, 'STANDARD', version=1).status_code == 200
    submit(actors['student'], session)
    assert set_mode(actors, session, 'AGGREGATE', version=2).status_code == 200
    assert set_mode(actors, session, 'STANDARD', version=3).json()['code'] == 'PRIVACY_DOWNGRADE'
    assert actors['student']['client'].get(f"/api/privacy/sessions/{session['id']}/export").status_code == 403
    initialize_database()
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 1
        assert connection.execute('SELECT mode FROM session_privacy').fetchone()[0] == 'AGGREGATE'
