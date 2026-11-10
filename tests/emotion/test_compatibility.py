from datetime import UTC, datetime, timedelta
from contextlib import closing
from pathlib import Path
import sqlite3

from backend.app.models.classroom import utc_text
from backend.app.repositories.database import connect, initialize_database
from scripts.package_project import collect, included


def test_existing_database_is_upgraded_without_changing_business_rows(tmp_path, monkeypatch):
    # Frozen from main c2d284a; independent of the new schema and checkout depth.
    original = (Path(__file__).parent / 'fixtures' / 'schema-v022.sql').read_text(encoding='utf-8')
    path = tmp_path / 'pre-extension.db'
    monkeypatch.setenv('EMOJI_DATABASE_PATH', str(path))
    timestamp = utc_text(datetime.now(UTC))
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(original)
        db.execute("INSERT INTO users(id,username,password_hash,role) VALUES (1,'existing_teacher','unchanged-hash','TEACHER')")
        db.execute("INSERT INTO courses(id,name,teacher_id) VALUES (1,'Existing course',1)")
        db.execute('INSERT INTO class_sessions(id,course_id,starts_at,ends_at,classroom,class_name) VALUES (1,1,?,?,?,?)',
                   (timestamp,utc_text(datetime.now(UTC)+timedelta(hours=1)),'Existing room','Existing class'))
        db.execute("INSERT INTO emoji_records(session_id,emotion,source,confidence,device_id,recorded_at) VALUES (1,'HAPPY','AI',0.9,'existing-device',?)",(timestamp,))
    initialize_database()
    initialize_database()
    with connect() as db:
        assert db.execute('SELECT username,password_hash FROM users WHERE id=1').fetchone()==('existing_teacher','unchanged-hash')
        assert db.execute('SELECT name,teacher_id FROM courses WHERE id=1').fetchone()==('Existing course',1)
        assert db.execute('SELECT emotion,source,device_id FROM emoji_records').fetchall()==[('HAPPY','AI','existing-device')]
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'emotion_insight_rules','emotion_insight_entries','lab_studies','lab_jobs','lab_job_events','lab_reports','lab_annotations'}.issubset(tables)


def test_grouped_delivery_is_packaged_and_local_runtime_data_is_excluded():
    root = Path(__file__).resolve().parents[2]
    paths={path.relative_to(root).as_posix() for path in collect()}
    assert {
        'backend/app/emotion/replay/controller.py',
        'backend/app/emotion/insights/service.py',
        'backend/app/emotion/lab/worker.py',
        'scripts/emotion/seed_lab_demo.py',
        'scripts/emotion/smoke_runtime.py',
        'docs/emotion/README.md',
        'tests/emotion/test_compatibility.py',
    }.issubset(paths)
    assert not included(Path('data/classroom.db'))
    assert not included(Path('.docker/secrets/ai-service.token'))
