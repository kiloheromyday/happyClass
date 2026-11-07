from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture
def tmp_path():
    # Use ordinary directory permissions in restricted Windows execution sessions.
    path = Path(__file__).resolve().parents[1] / "data" / "test-runs" / uuid4().hex
    path.mkdir(parents=True)
    yield path
    for item in path.iterdir():
        item.unlink()
    path.rmdir()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EMOJI_DATABASE_PATH", str(tmp_path / "test.db"))
    with TestClient(app) as test_client:
        yield test_client
