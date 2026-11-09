from pathlib import Path

import pytest

yaml = pytest.importorskip('yaml')

from scripts.package_project import collect, included


def test_extension_delivery_includes_deployment_and_excludes_generated_secrets():
    files = {path.relative_to(Path(__file__).resolve().parents[1]).as_posix() for path in collect()}
    assert {'Dockerfile', 'compose.yaml', '.dockerignore', '.github/workflows/ci.yml',
            'requirements-extensions.txt', 'ai_service/mcp_server.py', 'ai_service/result_queue.py',
            'ai_service/worker.py', 'scripts/start-extensions.ps1'}.issubset(files)
    for path in ('.docker/secrets/ai-service.token', '.env', 'data/classroom.db', 'ai_service/models/emotion-ferplus-8.onnx', 'frontend/node_modules/vue/index.js'):
        assert not included(Path(path))


def test_compose_service_boundaries_and_nonpublishing_ci_permissions():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / 'compose.yaml').read_text())
    services = compose['services']
    assert set(services) == {'web', 'redis', 'worker', 'ai', 'mcp'}
    assert services['web']['ports'][0].startswith('127.0.0.1:')
    assert all('ports' not in services[name] for name in ('redis', 'worker', 'ai', 'mcp'))
    assert 'volumes' not in services['ai'] and 'volumes' not in services['mcp']
    assert services['web']['depends_on']['redis']['condition'] == 'service_healthy'
    workflow = yaml.safe_load((root / '.github/workflows/ci.yml').read_text())
    assert workflow['permissions'] == {'contents': 'read'}
    assert {'tests', 'containers'} == set(workflow['jobs'])
