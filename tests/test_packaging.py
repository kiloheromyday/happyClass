from pathlib import Path

from scripts.package_project import included


def test_handin_excludes_local_data_and_credentials():
    for name in ('data/classroom.db', 'data/ai-ingest.token', '.env', 'frontend/.env.local', 'frontend/node_modules/example/index.js', '.venv/bin/python', 'ai_service/models/emotion-ferplus-8.onnx', 'backend/__pycache__/main.pyc', 'logs/backend.log'):
        assert not included(Path(name)), name
    for name in ('.env.example', 'frontend/package-lock.json', 'frontend/dist/index.html', 'database/schema.sql', 'ai_service/models/LICENSE.txt', 'backend/app/main.py', 'docs/REQUIREMENTS.md'):
        assert included(Path(name)), name
