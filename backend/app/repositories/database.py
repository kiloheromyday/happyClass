import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_FILE = PROJECT_ROOT / "database" / "schema.sql"


def database_path() -> Path:
    return Path(os.getenv("EMOJI_DATABASE_PATH", str(PROJECT_ROOT / "data" / "classroom.db")))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(database_path(), timeout=5)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    database_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as connection:
        had_enrollments = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='course_enrollments'").fetchone() is not None
        connection.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        # Add optional public study attributes to databases created before 0.8.0.
        connection.execute('BEGIN IMMEDIATE')
        from backend.app.catalog import DEPARTMENTS
        for table, additions in {
            'departments': {'version': 'INTEGER NOT NULL DEFAULT 1'},
            'courses': {'version': 'INTEGER NOT NULL DEFAULT 1', 'archived': 'INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1))'},
        }.items():
            present = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
            for name, definition in additions.items():
                if name not in present:
                    connection.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        removed = {row[0] for row in connection.execute('SELECT id FROM removed_departments')}
        connection.executemany('INSERT OR IGNORE INTO departments(id,name,short_name,color,background) VALUES (?,?,?,?,?)', [item for item in DEPARTMENTS if item[0] not in removed])
        course_columns = {row[1] for row in connection.execute('PRAGMA table_info(courses)')}
        if 'department_id' not in course_columns:
            connection.execute('ALTER TABLE courses ADD COLUMN department_id TEXT REFERENCES departments(id)')
        if 'is_demo' not in course_columns:
            connection.execute('ALTER TABLE courses ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1))')
        record_columns = {row[1] for row in connection.execute('PRAGMA table_info(emoji_records)')}
        if 'is_demo' not in record_columns:
            connection.execute('ALTER TABLE emoji_records ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1))')
        if not had_enrollments:
            connection.execute('''INSERT OR IGNORE INTO course_enrollments(course_id,user_id,joined_at)
                SELECT DISTINCT s.course_id,r.user_id,strftime('%Y-%m-%dT%H:%M:%fZ','now')
                FROM schedule_users r JOIN class_sessions s ON s.id=r.session_id''')
        columns = {row[1] for row in connection.execute('PRAGMA table_info(user_profiles)')}
        additions = {
            'major': "TEXT NOT NULL DEFAULT '' CHECK (length(major) <= 60)",
            'grade': "TEXT NOT NULL DEFAULT '' CHECK (length(grade) <= 20)",
            'study_goal': "TEXT NOT NULL DEFAULT '' CHECK (length(study_goal) <= 100)",
            'learning_style': "TEXT NOT NULL DEFAULT '' CHECK (learning_style IN ('','pair','questions','project','focus'))",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f'ALTER TABLE user_profiles ADD COLUMN {name} {definition}')


def check_database() -> None:
    # Check the actual connection and required schema, not only file existence.
    required = {"users", "courses", "class_sessions", "schedule_users", "emoji_records", "audit_logs", "auth_sessions", "auth_rate_limits", "emoji_submission_keys", "ai_frame_keys", "ai_batch_keys", "user_profiles", "buddy_connections"}
    with connect() as connection:
        connection.execute("SELECT 1").fetchone()
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required.update({'classroom_questions', 'classroom_reflections', 'personal_notes', 'personal_note_keys', 'buddy_wall_messages', 'buddy_wall_keys', 'session_join_codes', 'course_enrollments', 'user_avatars', 'classroom_guides', 'teaching_session_keys', 'demo_access_sessions'})
    required.update({'departments', 'demo_seed_items', 'leave_requests', 'course_evaluations', 'evaluation_keys', 'notifications', 'removed_departments', 'course_creation_keys'})
    if not required.issubset(tables):
        raise sqlite3.DatabaseError("Database schema is incomplete")
