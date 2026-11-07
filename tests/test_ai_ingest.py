from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.app.repositories.database import connect
from tests.test_classroom import actors, classroom_for, end_session

TOKEN = 'ingest-test-' + 'i' * 48
AUTH = {'Authorization': 'Bearer ' + TOKEN}


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv('EMOJI_AI_INGEST_TOKEN', TOKEN)
    monkeypatch.setenv('EMOJI_AI_TOKEN', 'inference-' + 's' * 48)
    monkeypatch.setenv('EMOJI_AI_MIN_CONFIDENCE', '.70')


def batch(session, **extra):
    return {'batch_id': str(uuid4()), 'session_id': session['id'], 'device_id': 'classroom-a', 'captured_at': datetime.now(UTC).isoformat(), 'faces': [{'emotion': 'HAPPY', 'confidence': .9}, {'emotion': 'SAD', 'confidence': .69}, {'emotion': 'CONTEMPT', 'confidence': .99}], **extra}


def test_ingest_independent_auth_and_no_cookie_substitution(actors):
    payload = batch(classroom_for(actors))
    for actor in actors.values():
        assert actor['client'].post('/api/ai/emoji-results', json=payload).status_code == 401
    admin = actors['admin']['client']
    for value in ('wrong', 'inference-' + 's' * 48):
        assert admin.post('/api/ai/emoji-results', json=payload, headers={'Authorization': 'Bearer ' + value}).status_code == 401
    response = admin.post('/api/ai/emoji-results', json=payload, headers=AUTH)
    assert response.status_code == 200
    assert response.json()['data']['saved'] == 1 and response.json()['data']['filtered'] == 2
    with connect() as connection:
        assert connection.execute('SELECT user_id,source,device_id,recorded_at FROM emoji_records').fetchone() == (None, 'AI', 'worker:classroom-a', response.json()['data']['captured_at'])


def test_ingest_idempotence_time_normalization_conflicts_and_late_retry(actors):
    session = classroom_for(actors)
    payload = batch(session)
    client = actors['admin']['client']
    first = client.post('/api/ai/emoji-results', json=payload, headers=AUTH)
    assert first.status_code == 200
    equivalent = {**payload, 'captured_at': datetime.fromisoformat(payload['captured_at']).astimezone(timezone(timedelta(hours=8))).isoformat()}
    assert client.post('/api/ai/emoji-results', json=equivalent, headers=AUTH).json()['data'] == first.json()['data']
    assert client.post('/api/ai/emoji-results', json={**payload, 'faces': []}, headers=AUTH).status_code == 409
    end_session(session)
    assert client.post('/api/ai/emoji-results', json=payload, headers=AUTH).status_code == 200
    assert client.post('/api/ai/emoji-results', json={**payload, 'batch_id': str(uuid4())}, headers=AUTH).status_code == 409
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM ai_batch_keys').fetchone()[0] == 1


@pytest.mark.parametrize('changes', [
    {'source': 'MANUAL'}, {'user_id': 1}, {'batch_id': 'bad'}, {'device_id': '../camera'},
    {'captured_at': '2026-11-02T12:00:00'}, {'faces': [{'emotion': 'FAKE', 'confidence': .9}]},
    {'faces': [{'emotion': 'HAPPY', 'confidence': -.1}]}, {'faces': [{'emotion': 'HAPPY', 'confidence': 1.01}]},
    {'faces': [{'emotion': 'HAPPY', 'confidence': .9, 'user_id': 1}]},
    {'faces': [{'emotion': 'HAPPY', 'confidence': .9}] * 13},
])
def test_ingest_strict_schema(actors, changes):
    payload = batch(classroom_for(actors), **changes)
    assert actors['admin']['client'].post('/api/ai/emoji-results', json=payload, headers=AUTH).status_code == 422
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 0


@pytest.mark.parametrize('seconds', [-301, 31])
def test_ingest_rejects_stale_or_future_capture(actors, seconds):
    payload = batch(classroom_for(actors), captured_at=(datetime.now(UTC) + timedelta(seconds=seconds)).isoformat())
    assert actors['admin']['client'].post('/api/ai/emoji-results', json=payload, headers=AUTH).status_code == 422


def test_ingest_capture_must_belong_to_session_and_session_must_exist(actors):
    session = classroom_for(actors)
    with connect() as connection:
        connection.execute('UPDATE class_sessions SET starts_at=? WHERE id=?', ((datetime.now(UTC) - timedelta(seconds=20)).isoformat(), session['id']))
    payload = batch(session, captured_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
    assert actors['admin']['client'].post('/api/ai/emoji-results', json=payload, headers=AUTH).status_code == 422
    assert actors['admin']['client'].post('/api/ai/emoji-results', json={**payload, 'session_id': 999999}, headers=AUTH).status_code == 404
    upcoming = batch(classroom_for(actors, upcoming=True))
    assert actors['admin']['client'].post('/api/ai/emoji-results', json=upcoming, headers=AUTH).status_code == 409


def test_ingest_concurrent_retries_insert_once(actors):
    payload = batch(classroom_for(actors))
    client = actors['admin']['client']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post('/api/ai/emoji-results', json=payload, headers=AUTH), range(2)))
    assert [response.status_code for response in results] == [200, 200]
    assert results[0].json()['data'] == results[1].json()['data']
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 1


def test_ingest_missing_configuration_returns_unavailable(client, monkeypatch):
    monkeypatch.setattr('backend.app.controllers.ai.ingest_token', lambda: None)
    assert client.post('/api/ai/emoji-results', json=batch({'id': 1}), headers=AUTH).status_code == 503
