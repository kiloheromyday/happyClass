from datetime import datetime, UTC, timedelta
import json

from backend.app.models.classroom import utc_text
from backend.app.repositories.database import connect
from tests.test_classroom import actors, classroom_for


def endpoint(session):
    return f"/api/sessions/{session['id']}/emotion-replay"


def add(session, when, emotion='HAPPY', source='AI', demo=0, user_id=None):
    with connect() as db:
        db.execute('INSERT INTO emoji_records(session_id,user_id,emotion,source,confidence,device_id,recorded_at,is_demo) VALUES (?,?,?,?,?,?,?,?)',
                   (session['id'], user_id, emotion, source, .9 if source == 'AI' else None, 'private-device', utc_text(when), demo))


def times(session, start, end):
    with connect() as db:
        db.execute('UPDATE class_sessions SET starts_at=?,ends_at=? WHERE id=?', (utc_text(start), utc_text(end), session['id']))


def test_replay_exact_minute_boundaries_empty_gaps_and_filters(actors, monkeypatch):
    session = classroom_for(actors)
    start = datetime(2026, 11, 9, 2, 0, 0, 123000, tzinfo=UTC)
    times(session, start, start + timedelta(minutes=10))
    monkeypatch.setattr('backend.app.emotion.replay.service.now_utc', lambda: start + timedelta(minutes=7))
    add(session, start-timedelta(seconds=1), 'ANGRY')
    add(session, start, 'HAPPY', 'MANUAL', user_id=actors['student']['user']['id'])
    add(session, start+timedelta(seconds=59, milliseconds=999), 'NEUTRAL')
    add(session, start+timedelta(minutes=1), 'SAD', 'MANUAL', 1, actors['student']['user']['id'])
    add(session, start+timedelta(seconds=61), 'HAPPY')
    add(session, start+timedelta(minutes=7), 'ANGRY')  # snapshot upper edge is exclusive
    client = actors['teacher']['client']
    response = client.get(endpoint(session), params={'bucket_minutes':1})
    assert response.status_code == 200
    data = response.json()['data']
    assert len(data['frames']) == 7 and data['summary'] == {'total':4,'manual_count':2,'ai_count':2}
    assert data['demo_record_count'] == 1
    assert [frame['total'] for frame in data['frames']] == [2,2,0,0,0,0,0]
    assert data['frames'][0]['dominant_emotions'] == ['HAPPY','NEUTRAL']
    assert all(frame['dominant_emotions'] == [] for frame in data['frames'][2:])
    assert len(data['frames'][0]['emotions']) == 7
    assert client.get(endpoint(session), params={'source':'AI'}).json()['data']['summary']['total'] == 2
    assert client.get(endpoint(session), params={'data_scope':'REAL'}).json()['data']['summary']['total'] == 3
    assert client.get(endpoint(session), params={'data_scope':'DEMO'}).json()['data']['summary']['total'] == 1
    assert client.get(endpoint(session), params={'bucket_minutes':5}).json()['data']['frames'][0]['total'] == 4


def test_replay_roles_ownership_and_aggregate_privacy(actors):
    session = classroom_for(actors)
    add(session, datetime.now(UTC)-timedelta(seconds=1), user_id=None)
    assert actors['student']['client'].get(endpoint(session)).status_code == 403
    assert actors['other_teacher']['client'].get(endpoint(session)).status_code == 403
    assert actors['teacher']['client'].get('/api/sessions/999999/emotion-replay').status_code == 404
    for mode in ('ANONYMOUS','AGGREGATE'):
        with connect() as db:
            db.execute('INSERT OR REPLACE INTO session_privacy(session_id,mode,version,updated_at,updated_by) VALUES (?,?,1,?,?)', (session['id'], mode, utc_text(datetime.now(UTC)), actors['admin']['user']['id']))
        result = actors['admin']['client'].get(endpoint(session)).json()['data']
        assert result['privacy_mode'] == mode and result['summary']['total'] == 1
        text = json.dumps(result)
        assert not any(key in text for key in ('"user_id"','"username"','"device_id"','private-device','"confidence"','"record_id"'))


def test_replay_after_class_grace_upper_edge_and_upcoming(actors, monkeypatch):
    session = classroom_for(actors)
    start = datetime(2026,11,9,2,tzinfo=UTC); end = start+timedelta(minutes=10)
    times(session,start,end)
    monkeypatch.setattr('backend.app.emotion.replay.service.now_utc',lambda:end+timedelta(hours=1))
    add(session,end+timedelta(minutes=29,seconds=59))
    add(session,end+timedelta(minutes=30))
    data = actors['teacher']['client'].get(endpoint(session)).json()['data']
    assert data['includes_after_class'] and data['summary']['total'] == 1
    assert data['frames'][-1]['to_time'] == utc_text(end+timedelta(minutes=30))
    future = classroom_for(actors,upcoming=True)
    monkeypatch.setattr('backend.app.emotion.replay.service.now_utc',lambda:datetime.now(UTC))
    data = actors['teacher']['client'].get(endpoint(future)).json()['data']
    assert not data['has_started'] and data['summary']['total'] == 0
    assert len(data['frames']) == 1 and data['frames'][0]['dominant_emotions'] == []


def test_replay_bounded_frames_and_invalid_options(actors, monkeypatch):
    session = classroom_for(actors); now = datetime.now(UTC)
    times(session,now-timedelta(days=40),now+timedelta(hours=1))
    monkeypatch.setattr('backend.app.emotion.replay.service.now_utc',lambda:now)
    client = actors['teacher']['client']
    data = client.get(endpoint(session)).json()['data']
    assert len(data['frames']) <= 360 and data['bucket_minutes'] > 1
    for params in ({'bucket_minutes':0},{'bucket_minutes':2},{'bucket_minutes':11},{'source':'VIDEO'},{'data_scope':'SECRET'}):
        assert client.get(endpoint(session),params=params).status_code == 422
