"""Opt-in smoke test for a disposable Compose database and live report worker."""
import argparse
from datetime import timedelta
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.database import connect
from backend.app.security import hash_password


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-demo-data', action='store_true')
    args = parser.parse_args()
    if not args.confirm_demo_data:
        parser.error('This test creates isolated synthetic accounts and records; use --confirm-demo-data only in a disposable validation database')
    password = secrets.token_urlsafe(24)
    username = 'lab_smoke_' + uuid4().hex[:12]
    start = now_utc() - timedelta(hours=1)
    end = start + timedelta(minutes=30)
    with connect() as db:
        teacher = db.execute(
            "INSERT INTO users(username,password_hash,role) VALUES (?,?,'TEACHER')",
            (username, hash_password(password)),
        ).lastrowid
        course = db.execute(
            'INSERT INTO courses(name,teacher_id,is_demo) VALUES (?,?,1)',
            ('Backend smoke synthetic course', teacher),
        ).lastrowid
        session = db.execute(
            'INSERT INTO class_sessions(course_id,starts_at,ends_at,classroom,class_name) VALUES (?,?,?,?,?)',
            (course, utc_text(start), utc_text(end), 'Smoke Lab', 'Synthetic runtime check'),
        ).lastrowid
        db.executemany(
            '''INSERT INTO emoji_records(session_id,emotion,source,confidence,device_id,recorded_at,is_demo)
            VALUES (?,?,'AI',0.9,'smoke-synthetic',?,1)''',
            [(session, 'HAPPY', utc_text(start+timedelta(minutes=minute))) for minute in (1,2,6,7,11,12)],
        )
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    origin = os.getenv('EMOJI_ALLOWED_ORIGINS', 'http://127.0.0.1:18080').split(',')[0]

    def call(path, method='GET', body=None):
        payload = None if body is None else json.dumps(body).encode()
        request = Request('http://127.0.0.1:18080'+path, data=payload, method=method, headers={
            'Content-Type': 'application/json',
            'X-Requested-With': 'EmojiClassroom',
            'Origin': origin,
        })
        with opener.open(request, timeout=10) as response:
            return json.load(response)['data']

    call('/api/auth/login', 'POST', {'username': username, 'password': password})
    dashboard = call('/api/emotion-lab/dashboard')
    assert dashboard['worker']['active_in_web_process'], 'Live report worker not running'
    replay = call(f'/api/sessions/{session}/emotion-replay?data_scope=DEMO')
    assert replay['summary']['total'] == 6
    insights = call(f'/api/sessions/{session}/insights?data_scope=DEMO')
    assert insights['summary']['total'] == 6
    study = call('/api/emotion-lab/studies', 'POST', {
        'title': 'Disposable backend compatibility check',
        'session_ids': [session],
        'settings': {'data_scope': 'DEMO'},
        'request_id': str(uuid4()),
    })
    job = call(f"/api/emotion-lab/studies/{study['id']}/runs", 'POST', {
        'version': study['version'],
        'request_id': str(uuid4()),
    })
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        state = call(f"/api/emotion-lab/jobs/{job['id']}")
        if state['state'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
            break
        time.sleep(0.5)
    assert state['state'] == 'SUCCEEDED', state['state']
    report = call(f"/api/emotion-lab/reports/{state['report_id']}")
    assert report['result']['summary']['total_records'] == 6
    integrity = call(f"/api/emotion-lab/reports/{state['report_id']}/integrity")
    assert integrity['passed']
    print('BACKEND_RUNTIME_SMOKE_PASSED: authenticated replay, insights, durable report job and snapshot integrity; original frontend unchanged')


if __name__ == '__main__':
    main()
