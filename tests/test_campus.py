from datetime import datetime, timedelta
import sqlite3

import pytest

from backend.app.repositories.database import connect, initialize_database
from scripts.seed_campus import seed, CHINA, SLOTS
from test_classroom import actors, classroom_for, schedule, submit, HEADERS


def test_campus_is_admin_only_and_counts_all_courses(actors):
    first = classroom_for(actors)
    second = classroom_for(actors, owner='other_teacher')
    schedule(actors, first)
    schedule(actors, second)
    submit(actors['student'], first)
    submit(actors['student'], second, 'NEUTRAL')
    for role in ('teacher', 'other_teacher', 'student'):
        assert actors[role]['client'].get('/api/admin/campus').status_code == 403
    data = actors['admin']['client'].get('/api/admin/campus').json()['data']
    assert data['summary']['courses'] == 2 and data['summary']['feedback_count'] == 2
    assert {item['id'] for item in data['sessions']} == {first['id'], second['id']}
    assert all(item['summary']['responding_students'] == 1 for item in data['courses'])
    assert 'password' not in str(data) and 'author_id' not in str(data)


def test_department_creation_validation_and_same_color_across_views(actors):
    admin = actors['admin']['client']
    departments = admin.get('/api/departments').json()['data']['items']
    assert len(departments) == 10
    body = {'name': '数学分析', 'teacher_id': actors['teacher']['user']['id'], 'department_id': 'math'}
    assert admin.post('/api/admin/courses', headers=HEADERS, json={**body, 'department_id': 'unknown'}).status_code == 422
    assert actors['student']['client'].post('/api/admin/courses', headers=HEADERS, json=body).status_code == 403
    course = admin.post('/api/admin/courses', headers=HEADERS, json=body).json()['data']
    session = classroom_for(actors)
    with connect() as c:
        c.execute('UPDATE class_sessions SET course_id=? WHERE id=?', (course['id'], session['id']))
    schedule(actors, session)
    detail = actors['student']['client'].get(f"/api/courses/{course['id']}").json()['data']
    assert detail['course']['department_name'] == '数学科学学院'
    assert detail['course']['department_color'] == detail['sessions'][0]['department_color']
    assert 'record_count' not in detail['sessions'][0]


def test_old_database_department_migration_is_repeatable(client):
    with connect() as c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES ('t','original-hash','TEACHER')")
        c.execute('ALTER TABLE courses RENAME TO previous_courses')
        c.execute('CREATE TABLE courses(id INTEGER PRIMARY KEY,name TEXT NOT NULL,teacher_id INTEGER NOT NULL REFERENCES users(id))')
        c.execute("INSERT INTO courses VALUES (1,'旧课程',1)")
    initialize_database(); initialize_database()
    with connect() as c:
        assert c.execute('SELECT name,department_id,is_demo FROM courses').fetchone() == ('旧课程', None, 0)
        assert c.execute('SELECT count(*) FROM departments').fetchone()[0] == 10
        assert c.execute('SELECT password_hash FROM users').fetchone()[0] == 'original-hash'


def test_seed_covers_every_day_and_evenings_without_duplicates_or_future_feedback(client):
    now = datetime(2026, 11, 4, 12, 0, tzinfo=CHINA)
    result = seed(now)
    assert result['created_sessions'] == 168 and result['created_feedback'] > 1000
    with connect() as c:
        rows = c.execute('SELECT s.id,s.starts_at,s.ends_at,c.department_id FROM class_sessions s JOIN courses c ON c.id=s.course_id').fetchall()
        by_day = {}
        for _, start, end, _ in rows:
            start = datetime.fromisoformat(start).astimezone(CHINA)
            by_day.setdefault(start.date(), []).append(start)
        assert len(by_day) == 28 and all(len(items) == 6 for items in by_day.values())
        assert all(sorted(item.hour for item in items) == [8, 9, 13, 14, 18, 20] for items in by_day.values())
        assert c.execute('SELECT count(DISTINCT department_id) FROM courses').fetchone()[0] == 10
        assert not c.execute('SELECT 1 FROM emoji_records e JOIN class_sessions s ON s.id=e.session_id WHERE e.recorded_at<s.starts_at OR e.recorded_at>=s.ends_at').fetchone()
        counts = {table: c.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in ('users', 'courses', 'class_sessions', 'emoji_records', 'schedule_users', 'course_enrollments')}
    again = seed(now)
    assert again['created_sessions'] == again['created_feedback'] == 0
    with connect() as c:
        assert counts == {table: c.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in counts}
        assert not c.execute('PRAGMA foreign_key_check').fetchall()


def test_seed_does_not_repurpose_existing_account(client):
    with connect() as c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES ('campus_t_math','keep-this','STUDENT')")
    with pytest.raises(RuntimeError):
        seed(datetime(2026, 11, 4, 12, tzinfo=CHINA))
    with connect() as c:
        assert c.execute('SELECT role,password_hash FROM users').fetchone() == ('STUDENT', 'keep-this')
        assert c.execute('SELECT count(*) FROM courses').fetchone()[0] == 0
