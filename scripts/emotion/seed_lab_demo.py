"""Create an isolated, explicitly synthetic multi-class laboratory example."""
import argparse
from datetime import timedelta
from pathlib import Path
import secrets
import sys
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.emotion.lab.models import AnalysisSettings, RunRequest, StudyRequest
from backend.app.emotion.lab.service import enqueue, save_study
from backend.app.models.classroom import now_utc, utc_text
from backend.app.emotion.insights.models import InsightEntry
from backend.app.repositories.database import connect, initialize_database
from backend.app.security import hash_password
from backend.app.emotion.insights.service import save_entry


def seed(username):
    initialize_database()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        teacher = db.execute(
            "SELECT id FROM users WHERE username=? AND role='TEACHER' AND status='ACTIVE'", (username,),
        ).fetchone()
        if teacher is None:
            raise ValueError('请指定已有的有效教师账号')
        owner = {'id': teacher[0], 'role': 'TEACHER'}
        key = f'lab-v1:{teacher[0]}'
        existing = db.execute(
            "SELECT entity_id FROM demo_seed_items WHERE kind='lab-course' AND seed_key=?", (key,),
        ).fetchone()
        if existing:
            identifiers = [row[0] for row in db.execute('SELECT id FROM class_sessions WHERE course_id=? ORDER BY id', (existing[0],))]
            return {'created': False, 'session_ids': identifiers}
        student = db.execute("SELECT id FROM users WHERE username='lab_synthetic_student'").fetchone()
        student_id = student[0] if student else db.execute(
            "INSERT INTO users(username,password_hash,role,status) VALUES (?,?,'STUDENT','DISABLED')",
            ('lab_synthetic_student', hash_password(secrets.token_urlsafe(32))),
        ).lastrowid
        course_id = db.execute(
            'INSERT INTO courses(name,teacher_id,is_demo) VALUES (?,?,1)',
            ('课堂情绪分析实验室演示（合成）', teacher[0]),
        ).lastrowid
        identifiers = []
        total = 0
        for index in range(4):
            start = now_utc().replace(second=0, microsecond=0) - timedelta(days=4-index, hours=1)
            end = start + timedelta(minutes=45)
            identifier = db.execute(
                'INSERT INTO class_sessions(course_id,starts_at,ends_at,classroom,class_name) VALUES (?,?,?,?,?)',
                (course_id, utc_text(start), utc_text(end), 'Lab Demo', f'合成样例 {"ABCD"[index]}'),
            ).lastrowid
            identifiers.append(identifier)
            values = []
            for minute in range(1, 45, 2):
                for source, amount in (('MANUAL', 3), ('AI', 6)):
                    if index == 2 and 15 <= minute < 35:
                        continue
                    if index == 3 and source == 'MANUAL' and minute > 3:
                        continue
                    high = 10 <= minute < (20 if index < 2 else 30)
                    if source == 'MANUAL':
                        emotion = 'SAD' if high else 'HAPPY' if minute >= 20 else 'NEUTRAL'
                    else:
                        emotion = 'FEAR' if high and index != 1 else 'NEUTRAL'
                    for offset in range(amount):
                        values.append((identifier, student_id if source == 'MANUAL' else None, emotion, source,
                                       .62 if source == 'AI' and index == 3 else .92 if source == 'AI' else None,
                                       'lab-synthetic-demo', utc_text(start+timedelta(minutes=minute, seconds=offset)), 1))
            db.executemany(
                '''INSERT INTO emoji_records(session_id,user_id,emotion,source,confidence,device_id,recorded_at,is_demo)
                VALUES (?,?,?,?,?,?,?,?)''', values,
            )
            total += len(values)
        db.execute("INSERT INTO demo_seed_items(kind,seed_key,entity_id) VALUES ('lab-course',?,?)", (key, course_id))
    for identifier in identifiers:
        for position, (lower, upper, title) in enumerate(((0,10,'导入'),(10,20,'概念讲解'),(20,45,'例题与练习'))):
            save_entry(identifier, InsightEntry(
                kind='PHASE', title=title, content='实验室合成教学环节', start_minute=lower,
                end_minute=upper, request_id=uuid5(NAMESPACE_URL,f'{key}:{identifier}:phase:{position}'),
            ), owner)
    jobs = []
    for mode, title in (('RELATIVE','多课堂进度复盘（合成演示）'),('PHASE','教学环节对比（合成演示）')):
        study = save_study(StudyRequest(
            title=title,
            question='在合成课堂中验证来源差异、时间覆盖与跨课堂对齐流程。',
            tags=['合成演示'],
            session_ids=identifiers,
            baseline_ids=identifiers[:2],
            settings=AnalysisSettings(data_scope='DEMO', alignment=mode),
            request_id=uuid5(NAMESPACE_URL,f'{key}:study:{mode}'),
        ), owner)
        job = enqueue(study['id'], RunRequest(
            version=study['version'], request_id=uuid5(NAMESPACE_URL,f'{key}:run:{mode}'),
        ), owner)
        jobs.append(job['id'])
    return {'created': True, 'session_ids': identifiers, 'synthetic_records': total, 'job_ids': jobs}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--teacher', required=True)
    parser.add_argument('--confirm-demo-data', action='store_true')
    args = parser.parse_args()
    if not args.confirm_demo_data:
        parser.error('请显式添加 --confirm-demo-data，命令会新增独立合成演示数据')
    print(seed(args.teacher))
