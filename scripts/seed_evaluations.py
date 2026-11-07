"""Add explicitly labeled synthetic evaluations for existing campus demo classes only."""
from datetime import datetime, timedelta
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.database import connect, initialize_database


def seed(now=None):
    initialize_database()
    now = now or now_utc()
    created = 0
    comments = ['演示：板书结构清楚，希望再补充一道应用例题。', '演示：讨论环节很有帮助，期待更多动手练习。', '演示：本节内容较多，希望关键推导稍慢一些。', '演示：对知识之间的联系有了更清晰的认识。', '演示：如果课后有简短复习提纲，会更方便回顾。']
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        sessions = c.execute('''SELECT s.id,s.ends_at FROM class_sessions s JOIN courses c ON c.id=s.course_id
            WHERE c.is_demo=1 AND s.ends_at<=? ORDER BY s.id''', (utc_text(now),)).fetchall()
        for session_id, ends_at in sessions:
            candidates = c.execute('''SELECT r.user_id FROM schedule_users r JOIN users u ON u.id=r.user_id
                WHERE r.session_id=? AND u.role='STUDENT' AND u.status='ACTIVE'
                AND EXISTS(SELECT 1 FROM demo_seed_items d WHERE d.kind='user' AND d.entity_id=u.id)
                ORDER BY u.id''', (session_id,)).fetchall()
            if not candidates:
                continue
            shift = session_id % len(candidates)
            selected = (candidates[shift:] + candidates[:shift])[:6]
            for (student_id,) in selected:
                key = f'evaluation-v1:{session_id}:{student_id}'
                if c.execute("SELECT 1 FROM demo_seed_items WHERE kind='evaluation' AND seed_key=?", (key,)).fetchone():
                    continue
                rng = random.Random(f'{session_id}:{student_id}:v1')
                scores = [rng.choices([2, 3, 4, 5], weights=[1, 2, 5, 4])[0] for _ in range(4)]
                timestamp = utc_text(min(now, datetime.fromisoformat(ends_at) + timedelta(minutes=5)))
                cursor = c.execute('''INSERT OR IGNORE INTO course_evaluations
                    (session_id,student_id,clarity,pace,engagement,gain,comment,version,is_demo,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,1,1,?,?)''', (session_id, student_id, *scores, rng.choice(comments), timestamp, timestamp))
                if cursor.rowcount:
                    c.execute("INSERT INTO demo_seed_items(kind,seed_key,entity_id) VALUES ('evaluation',?,?)", (key, cursor.lastrowid))
                    created += 1
    return {'created_evaluations': created, 'demo_only': True}


if __name__ == '__main__':
    import json
    print(json.dumps(seed(), ensure_ascii=False))
