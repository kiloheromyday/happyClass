import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.repositories.database import connect
from ai_service.main import app as ai_app


def test_database_survives_application_restart(client):
    assert client.get('/api/health').json()['data']['database'] == 'ready'
    with connect() as connection:
        connection.execute("INSERT INTO users (username,password_hash,role) VALUES (?,?,?)", ('test', 'not-a-real-password-hash', 'STUDENT'))
    with TestClient(app) as restarted:
        assert restarted.get('/api/health').status_code == 200
        with connect() as connection:
            assert connection.execute('SELECT count(*) FROM users').fetchone()[0] == 1


def test_database_failure_is_not_reported_as_ready(client, monkeypatch, tmp_path):
    monkeypatch.setenv('EMOJI_DATABASE_PATH', str(tmp_path / 'missing' / 'unavailable.db'))
    response = client.get('/api/health')
    assert response.status_code == 503
    assert response.json()['data']['database'] == 'unavailable'


def test_schema_rejects_invalid_records(client):
    with connect() as connection:
        connection.execute("INSERT INTO users (id,username,password_hash,role) VALUES (1,'teacher','test-hash','TEACHER')")
        connection.execute("INSERT INTO courses (id,name,teacher_id) VALUES (1,'Test',1)")
        connection.execute("INSERT INTO class_sessions (id,course_id,starts_at,ends_at,classroom,class_name) VALUES (1,1,'2026-11-02T10:00:00Z','2026-11-02T11:00:00Z','101','A')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO emoji_records (session_id,emotion,source) VALUES (1,'HAPPY','AI')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO emoji_records (session_id,emotion,source,confidence) VALUES (999,'HAPPY','AI',0.9)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO emoji_records (session_id,emotion,source,confidence) VALUES (1,'UNKNOWN','AI',0.9)")


def test_unknown_api_does_not_return_frontend(client):
    assert client.get('/api/does-not-exist').status_code == 404


def test_ai_health_does_not_claim_inference_is_ready(monkeypatch):
    def unavailable():
        raise RuntimeError('Model intentionally unavailable in this test')
    monkeypatch.setattr('ai_service.main.load_engine', unavailable)
    with TestClient(ai_app) as client:
        data = client.get('/health').json()['data']
        assert data['model_loaded'] is False
        assert data['ready'] is False
        assert data['stores_raw_media'] is False
