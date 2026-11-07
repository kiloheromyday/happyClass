"""Explicit, repeatable campus demo seeding. Does not run on application startup."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.catalog import DEPARTMENTS, DEMO_COURSES
from backend.app.models.classroom import utc_text
from backend.app.repositories.database import connect, initialize_database
from backend.app.security import hash_password

CHINA = timezone(timedelta(hours=8))
SLOTS = ((8, 0, 9, 35), (9, 55, 11, 30), (13, 0, 14, 35),
         (14, 55, 16, 30), (18, 30, 20, 5), (20, 15, 21, 50))


def seed(now=None):
    initialize_database()
    now = (now or datetime.now(CHINA)).astimezone(CHINA)
    first = now.date() - timedelta(days=now.weekday() + 7)
    rng = random.Random(20261103)
    digest = hash_password(secrets.token_urlsafe(48) + 'A1')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')

        def existing(kind, key):
            row = c.execute('SELECT entity_id FROM demo_seed_items WHERE kind=? AND seed_key=?', (kind, key)).fetchone()
            return row[0] if row else None

        def remember(kind, key, entity):
            c.execute('INSERT INTO demo_seed_items VALUES (?,?,?)', (kind, key, entity))
            return entity

        def account(username, role, nickname):
            identifier = existing('user', username)
            if identifier:
                return identifier
            if c.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
                raise RuntimeError('Reserved demo username already exists: ' + username)
            identifier = c.execute('INSERT INTO users(username,password_hash,role) VALUES (?,?,?)', (username, digest, role)).lastrowid
            c.execute('INSERT INTO user_profiles(user_id,nickname,bio,avatar_color) VALUES (?,?,?,?)',
                      (identifier, nickname, '合成演示成员，用于课程展示。', ('sage', 'sand', 'sky', 'lilac', 'rose')[identifier % 5]))
            return remember('user', username, identifier)

        teachers = {}
        for index, (key, _, short, _, _) in enumerate(DEPARTMENTS):
            primary = c.execute("SELECT id FROM users WHERE username='demo_teacher' AND role='TEACHER' AND status='ACTIVE'").fetchone() if key == 'computer' else None
            teachers[key] = primary[0] if primary else account('campus_t_' + key, 'TEACHER', f'{short}教师（演示）')
        students = [account(f'campus_s_{i:02}', 'STUDENT', f'同学{i:02}（演示）') for i in range(1, 37)]
        for name in ('demo_student', 'demo_buddy'):
            row = c.execute("SELECT id FROM users WHERE username=? AND role='STUDENT' AND status='ACTIVE'", (name,)).fetchone()
            if row:
                students.insert(0, row[0])
        courses = []
        for index, (department, name) in enumerate(DEMO_COURSES):
            key = f'ustc-inspired-{index:02}'
            identifier = existing('course', key)
            if not identifier:
                identifier = c.execute('INSERT INTO courses(name,teacher_id,department_id,is_demo) VALUES (?,?,?,1)', (name, teachers[department], department)).lastrowid
                remember('course', key, identifier)
            courses.append(identifier)
            c.executemany('INSERT OR IGNORE INTO course_enrollments(course_id,user_id,joined_at) VALUES (?,?,?)', [(identifier, user, utc_text(now)) for user in students])
        created_sessions = created_feedback = 0
        for day_index in range(28):
            day = first + timedelta(days=day_index)
            for slot, (h1, m1, h2, m2) in enumerate(SLOTS):
                key = f'{day.isoformat()}-{slot}'
                start = datetime(day.year, day.month, day.day, h1, m1, tzinfo=CHINA)
                end = datetime(day.year, day.month, day.day, h2, m2, tzinfo=CHINA)
                session = existing('session', key)
                if not session:
                    course_index = (day.weekday() * 6 + slot) % len(courses)
                    session = c.execute('INSERT INTO class_sessions(course_id,starts_at,ends_at,classroom,class_name) VALUES (?,?,?,?,?)',
                        (courses[course_index], utc_text(start), utc_text(end), f'{"东区" if slot % 2 == 0 else "西区"}教学楼 {100 + course_index * 2 + 1}', '跨院选修班 · 演示')).lastrowid
                    remember('session', key, session)
                    c.executemany('INSERT INTO schedule_users(session_id,user_id) VALUES (?,?)', [(session, user) for user in students])
                    created_sessions += 1
                # Never fabricate feedback for a class which has not started.
                if end <= now and not existing('feedback', key):
                    selected = students[:2] + rng.sample(students[2:], rng.randint(20, 30))
                    for user in selected:
                        emotion = rng.choices(('HAPPY', 'NEUTRAL', 'SURPRISED', 'SAD', 'FEAR'), (48, 30, 10, 7, 5))[0]
                        stamp = start + timedelta(minutes=rng.randint(15, 90))
                        c.execute("INSERT INTO emoji_records(user_id,session_id,emotion,source,recorded_at,is_demo) VALUES (?,?,?,'MANUAL',?,1)", (user, session, emotion, utc_text(stamp)))
                        created_feedback += 1
                    remember('feedback', key, session)
        result = {'first_date': first.isoformat(), 'last_date': (first + timedelta(days=27)).isoformat(),
                  'courses': len(courses), 'departments': len(DEPARTMENTS), 'students': len(students),
                  'created_sessions': created_sessions, 'created_feedback': created_feedback}
        import json
        c.execute("INSERT INTO audit_logs(action,detail) VALUES ('CAMPUS_DEMO_SEEDED',?)", (json.dumps(result),))
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-demo-data', action='store_true', required=True)
    parser.parse_args()
    import json
    print(json.dumps(seed(), ensure_ascii=False))
