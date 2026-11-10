"""Explicit, idempotent synthetic demo for the classroom insight workflow."""
import argparse
from datetime import timedelta
import secrets
import sys
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

from backend.app.models.classroom import now_utc, utc_text
from backend.app.emotion.insights.models import InsightEntry
from backend.app.repositories.database import connect, initialize_database
from backend.app.security import hash_password
from backend.app.emotion.insights.service import save_entry


def seed(teacher_username):
    initialize_database()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        teacher=db.execute("SELECT id FROM users WHERE username=? AND role='TEACHER' AND status='ACTIVE'",(teacher_username,)).fetchone()
        if teacher is None:
            raise ValueError('请先创建指定的有效教师账号')
        teacher_id=teacher[0]
        key=f'insights-v1:{teacher_id}'
        existing=db.execute("SELECT entity_id FROM demo_seed_items WHERE kind='insights-session' AND seed_key=?",(key,)).fetchone()
        if existing:
            return {'session_id':existing[0],'created':False}
        student=db.execute("SELECT id FROM users WHERE username='insights_synthetic_student'").fetchone()
        if student is None:
            student_id=db.execute("INSERT INTO users(username,password_hash,role,status) VALUES (?,?, 'STUDENT','DISABLED')",
                                  ('insights_synthetic_student',hash_password(secrets.token_urlsafe(32)))).lastrowid
        else:
            student_id=student[0]
        course_id=db.execute("INSERT INTO courses(name,teacher_id,is_demo) VALUES (?,?,1)",
                             ('课堂情绪洞察演示（合成）',teacher_id)).lastrowid
        start=now_utc().replace(second=0,microsecond=0)-timedelta(minutes=60)
        end=start+timedelta(minutes=45)
        session_id=db.execute('INSERT INTO class_sessions(course_id,starts_at,ends_at,classroom,class_name) VALUES (?,?,?,?,?)',
                              (course_id,utc_text(start),utc_text(end),'Insights Demo Lab','教学跟进演示 · 合成数据')).lastrowid
        samples=[]
        for minute in range(1,45):
            if minute%5 not in (1,3):
                continue
            for source,amount in (('MANUAL',5),('AI',10)):
                for index in range(amount):
                    emotion=('SAD' if source=='MANUAL' else 'FEAR') if 10<=minute<20 else ('HAPPY' if minute>=20 else 'NEUTRAL')
                    samples.append((session_id,student_id if source=='MANUAL' else None,emotion,source,.91 if source=='AI' else None,
                                    'insights-synthetic-demo',utc_text(start+timedelta(minutes=minute,seconds=index)),1))
        db.executemany('''INSERT INTO emoji_records(session_id,user_id,emotion,source,confidence,device_id,recorded_at,is_demo)
            VALUES (?,?,?,?,?,?,?,?)''',samples)
        db.execute("INSERT INTO demo_seed_items(kind,seed_key,entity_id) VALUES ('insights-session',?,?)",(key,session_id))
        actor={'id':teacher_id,'role':'TEACHER'}
    # Saved through the same validation and audit path used by the UI.
    for index,(lower,upper,title) in enumerate(((0,10,'导入与课堂提问'),(10,20,'新概念讲解'),(20,45,'图示例题与互动练习'))):
        save_entry(session_id,InsightEntry(kind='PHASE',title=title,content='合成演示教学环节',start_minute=lower,end_minute=upper,
                    status='DONE',request_id=uuid5(NAMESPACE_URL,f'{key}:phase:{index}')),actor)
    save_entry(session_id,InsightEntry(kind='ACTION',title='补充图示并放慢讲解',content='合成教学调整示例：结合图示重新讲解，并用课堂提问核实理解情况。',
                start_minute=20,end_minute=20,status='DONE',outcome='此处的前后分布由合成数据构造，只用于验证对比流程。',
                request_id=uuid5(NAMESPACE_URL,f'{key}:action')),actor)
    return {'session_id':session_id,'created':True,'synthetic_records':len(samples)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--teacher',required=True,help='Existing active teacher username')
    parser.add_argument('--confirm-demo-data',action='store_true',help='Explicitly create synthetic records in this database')
    args=parser.parse_args()
    if not args.confirm_demo_data:
        parser.error('请显式添加 --confirm-demo-data；本命令会新增独立的合成演示课程和反馈')
    print(seed(args.teacher))
