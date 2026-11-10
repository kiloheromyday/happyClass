from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ai_service import main as ai_main
from backend.app.repositories.database import connect
from backend.app.services import ai
from tests.test_classroom import actors, classroom_for, end_session, HEADERS


def frame(actor, session, content=b'jpeg-test-placeholder', request_id=None, **headers):
    return actor['client'].post(f"/api/sessions/{session['id']}/ai-frame", content=content, headers={**HEADERS, 'Content-Type': 'image/jpeg', 'X-Frame-ID': request_id or str(uuid4()), **headers})


@pytest.fixture
def inference(monkeypatch):
    calls = []
    async def predict(data):
        calls.append(data)
        return ai.InferenceResult(detected=4, processed=4, faces=[
            {'emotion': 'HAPPY', 'confidence': .95}, {'emotion': 'SAD', 'confidence': .69, 'candidates': [{'emotion': 'SAD', 'confidence': .69}, {'emotion': 'ANGRY', 'confidence': .2}, {'emotion': 'NEUTRAL', 'confidence': .1}]},
            {'emotion': 'NEUTRAL', 'confidence': .70}, {'emotion': 'CONTEMPT', 'confidence': .99},
        ])
    monkeypatch.setattr(ai, 'run_inference', predict)
    monkeypatch.setenv('EMOJI_AI_MIN_CONFIDENCE', '0.70')
    return calls


def test_ai_filter_idempotence_anonymity_and_statistics(actors, inference):
    session = classroom_for(actors)
    identifier = str(uuid4())
    first = frame(actors['teacher'], session, request_id=identifier)
    assert first.status_code == 200
    result = first.json()['data']
    assert {key: result[key] for key in ('detected', 'processed', 'saved', 'filtered', 'min_confidence')} == {'detected': 4, 'processed': 4, 'saved': 2, 'filtered': 2, 'min_confidence': .7}
    assert [(item['emotion'], item['reason']) for item in result['predictions']] == [
        ('HAPPY', 'SAVED'), ('SAD', 'LOW_CONFIDENCE'), ('NEUTRAL', 'SAVED'), ('CONTEMPT', 'UNSUPPORTED_CLASS')]
    assert result['predictions'][1]['candidates'][1] == {'emotion': 'ANGRY', 'confidence': .2}
    assert frame(actors['teacher'], session, request_id=identifier).json()['data'] == first.json()['data']
    assert len(inference) == 1
    assert frame(actors['teacher'], session, content=b'different', request_id=identifier).status_code == 409
    with connect() as connection:
        rows = connection.execute('SELECT user_id,source,emotion,confidence FROM emoji_records').fetchall()
        assert rows == [(None, 'AI', 'HAPPY', .95), (None, 'AI', 'NEUTRAL', .7)]
        assert connection.execute('SELECT count(*) FROM ai_frame_keys').fetchone()[0] == 1
    stats = actors['teacher']['client'].get(f"/api/sessions/{session['id']}/statistics").json()['data']
    assert stats['ai_count'] == 2 and stats['responding_students'] == 0
    assert actors['student']['client'].get('/api/emoji/history').json()['data']['total'] == 0


def test_ai_access_time_limits_and_bounded_input(actors, inference):
    session = classroom_for(actors)
    assert frame(actors['other_teacher'], session).status_code == 403
    assert frame(actors['student'], session).status_code == 403
    assert frame(actors['teacher'], session, **{'Content-Type': 'image/png'}).status_code == 415
    assert frame(actors['teacher'], session, request_id='bad').status_code == 422
    assert frame(actors['teacher'], session, content=b'x' * 1_000_001).status_code == 413
    assert actors['student']['client'].get('/api/ai/status').status_code == 403
    upcoming = classroom_for(actors, upcoming=True)
    assert frame(actors['teacher'], upcoming).status_code == 409
    end_session(session)
    assert frame(actors['teacher'], session).status_code == 409
    assert not inference


def test_ai_csrf_required(actors, inference):
    session = classroom_for(actors)
    assert frame(actors['teacher'], session, **{'X-Requested-With': ''}).status_code == 403
    assert not inference


def test_ai_class_ending_during_inference_never_saves(actors, monkeypatch):
    session = classroom_for(actors)
    async def predict(data):
        end_session(session)
        return ai.InferenceResult(detected=1, processed=1, faces=[{'emotion': 'HAPPY', 'confidence': .9}])
    monkeypatch.setattr(ai, 'run_inference', predict)
    assert frame(actors['teacher'], session).status_code == 409
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 0


def test_service_auth_and_input_contract(monkeypatch):
    class Engine:
        def infer(self, data):
            if data != b'valid':
                raise ValueError('Invalid JPEG')
            return {'detected': 0, 'processed': 0, 'faces': []}
    monkeypatch.setenv('EMOJI_AI_TOKEN', 't' * 48)
    monkeypatch.setattr(ai_main, 'load_engine', Engine)
    with TestClient(ai_main.app) as client:
        assert client.get('/health').json()['data']['ready'] is True
        assert client.post('/infer', content=b'valid').status_code == 401
        headers = {'Authorization': 'Bearer ' + 't' * 48, 'Content-Type': 'image/jpeg'}
        assert client.post('/infer', content=b'valid', headers=headers).status_code == 200
        assert client.post('/infer', content=b'bad', headers=headers).status_code == 422
        assert client.post('/infer', content=b'x' * 1_000_001, headers=headers).status_code == 413
        assert client.post('/infer', content=b'valid', headers={**headers, 'Content-Type': 'image/png'}).status_code == 415


def test_admin_creates_teacher_and_preserves_own_session(actors):
    admin = actors['admin']['client']
    payload = {'username': 'teacher.new@example.edu', 'password': 'TeacherPass123!', 'role': 'TEACHER'}
    for role in ('teacher', 'student'):
        assert actors[role]['client'].post('/api/admin/users', json=payload, headers=HEADERS).status_code == 403
    assert admin.post('/api/admin/users', json=payload).status_code == 403
    created = admin.post('/api/admin/users', json=payload, headers=HEADERS)
    assert created.status_code == 201
    assert 'password' not in str(created.json())
    assert admin.get('/api/users/me').json()['data']['role'] == 'ADMIN'
    assert admin.post('/api/admin/users', json=payload, headers=HEADERS).status_code == 409
    assert admin.post('/api/admin/users', json={**payload, 'role': 'ADMIN'}, headers=HEADERS).status_code == 422
    with connect() as connection:
        assert connection.execute("SELECT actor_id FROM audit_logs WHERE action='USER_CREATED' ORDER BY id DESC LIMIT 1").fetchone()[0] == actors['admin']['user']['id']
    login = actors['other_student']['client'].post('/api/auth/login', json={key: payload[key] for key in ('username', 'password')}, headers=HEADERS)
    assert login.status_code == 200 and login.json()['data']['role'] == 'TEACHER'
