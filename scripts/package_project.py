"""Create a source hand-in without local credentials, accounts, caches or weights."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.env.example', '.gitignore', 'README.md', 'requirements.txt', 'requirements-lock.txt', 'pytest.ini'}
FOLDERS = {'backend', 'frontend', 'ai_service', 'database', 'docs', 'scripts', 'tests'}
OMIT_PARTS = {'node_modules', '.venv', '.git', '__pycache__', '.pytest_cache', 'logs', 'data'}
OMIT_SUFFIXES = {'.pyc', '.pyo', '.onnx', '.token', '.db', '.sqlite', '.sqlite3', '.log'}


def included(relative):
    if any(part in OMIT_PARTS or part.startswith('pytest-cache-') for part in relative.parts):
        return False
    if (relative.name.startswith('.env') and relative.name != '.env.example') or relative.suffix.lower() in OMIT_SUFFIXES:
        return False
    return relative.as_posix() in ROOT_FILES or (len(relative.parts) > 1 and relative.parts[0] in FOLDERS)


def collect():
    for name in sorted(ROOT_FILES):
        path = ROOT / name
        if path.is_file() and not path.is_symlink():
            yield path
    for folder in sorted(FOLDERS):
        # Prune dependency trees instead of enumerating their files.
        import os
        for current, directories, filenames in os.walk(ROOT / folder, followlinks=False):
            directories[:] = sorted(directory for directory in directories if directory not in OMIT_PARTS and not directory.startswith('pytest-cache-') and not (Path(current) / directory).is_symlink())
            for name in sorted(filenames):
                path = Path(current) / name
                if not path.is_symlink() and included(path.relative_to(ROOT)):
                    yield path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'emoji-classroom-source.zip')
    args = parser.parse_args(argv)
    destination = args.output.resolve()
    if destination.exists():
        parser.error('Output already exists; use a new filename to preserve earlier packages')
    destination.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    from backend.app.main import app
    from ai_service.main import app as ai_app
    manifest = []
    with ZipFile(destination, 'x', compression=ZIP_DEFLATED) as archive:
        for path in collect():
            relative = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            archive.writestr('emoji-classroom/' + relative, data)
            manifest.append({'path': relative, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        for name, application in [('backend', app), ('ai-service', ai_app)]:
            archive.writestr(f'emoji-classroom/docs/api/{name}-openapi.json', json.dumps(application.openapi(), ensure_ascii=False, indent=2))
        archive.writestr('emoji-classroom/PACKAGE-MANIFEST.json', json.dumps({'files': manifest, 'excluded': ['local accounts and databases', 'credentials', 'venv and node_modules', 'model weights (download with setup-ai.ps1)'], 'generated': ['docs/api/backend-openapi.json', 'docs/api/ai-service-openapi.json']}, ensure_ascii=False, indent=2))
    with ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert all(included(Path(name.removeprefix('emoji-classroom/'))) or name.endswith('PACKAGE-MANIFEST.json') for name in archive.namelist())
    print(f'Package verified: {destination} ({destination.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()
