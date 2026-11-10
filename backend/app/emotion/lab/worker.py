"""Durable SQLite report queue with leases, cancellation and idempotent reports."""
from datetime import datetime, timedelta
import json
import logging
import threading
from uuid import uuid4

from backend.app.errors import AppError
from backend.app.emotion.lab import access
from backend.app.emotion.lab import repository as repo
from backend.app.emotion.lab.analysis import build_result
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import get_user, one
from backend.app.repositories.database import connect

LEASE_SECONDS = 120
MAX_ATTEMPTS = 3
MAX_RESULT_BYTES = 8_000_000
logger = logging.getLogger(__name__)


class LeaseLost(Exception):
    pass


class JobCancelled(Exception):
    pass


class WorkerStopped(Exception):
    pass


def claim():
    now = now_utc()
    timestamp = utc_text(now)
    lease = utc_text(now + timedelta(seconds=LEASE_SECONDS))
    token = uuid4().hex
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        expired = db.execute(
            "SELECT id,attempts,cancel_requested FROM lab_jobs WHERE state='RUNNING' AND lease_until<?",
            (timestamp,),
        ).fetchall()
        for identifier, attempts, cancelled in expired:
            state = 'CANCELLED' if cancelled else 'FAILED' if attempts >= MAX_ATTEMPTS else 'QUEUED'
            code = 'CANCELLED' if cancelled else 'LEASE_EXPIRED'
            db.execute(
                'UPDATE lab_jobs SET state=?,error_code=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?',
                (state, code, timestamp, identifier),
            )
            repo.event(db, identifier, code, '中断任务的租约已过期，状态已恢复', 0, timestamp)
        item = one(db.execute(
            "SELECT * FROM lab_jobs WHERE state='QUEUED' AND cancel_requested=0 ORDER BY created_at,id LIMIT 1",
        ))
        if item is None:
            return None
        db.execute(
            '''UPDATE lab_jobs SET state='RUNNING',attempts=attempts+1,progress=1,
            lease_token=?,lease_until=?,error_code=NULL,updated_at=? WHERE id=?''',
            (token, lease, timestamp, item['id']),
        )
        repo.event(db, item['id'], 'STARTED', '后台分析已开始', 1, timestamp)
        item['lease_token'] = token
        item['attempts'] += 1
        return item


def checkpoint(identifier, token, progress, message, stop):
    if stop.is_set():
        raise WorkerStopped()
    now = now_utc()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = one(db.execute('SELECT * FROM lab_jobs WHERE id=?', (identifier,)))
        if item is None or item['state'] != 'RUNNING' or item['lease_token'] != token:
            raise LeaseLost()
        if item['cancel_requested']:
            raise JobCancelled()
        owner = get_user(db, item['owner_id'])
        if owner is None or owner['status'] != 'ACTIVE':
            raise AppError(403, 'LAB_OWNER_INACTIVE', '分析账号已停用')
        access.authorize_snapshot(db, item['definition'], owner)
        db.execute(
            'UPDATE lab_jobs SET progress=?,lease_until=?,updated_at=? WHERE id=? AND lease_token=?',
            (
                progress,
                utc_text(now + timedelta(seconds=LEASE_SECONDS)),
                utc_text(now),
                identifier,
                token,
            ),
        )
        repo.event(db, identifier, 'PROGRESS', message, progress, utc_text(now))


def finish(item, result):
    text = repo.encode(result)
    if len(text.encode('utf-8')) > MAX_RESULT_BYTES:
        raise AppError(422, 'LAB_RESULT_LIMIT', '结果过大，请减少课堂或增加时间粒度')
    timestamp = utc_text(now_utc())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = one(db.execute('SELECT * FROM lab_jobs WHERE id=?', (item['id'],)))
        if current['state'] != 'RUNNING' or current['lease_token'] != item['lease_token']:
            raise LeaseLost()
        if current['cancel_requested']:
            raise JobCancelled()
        owner = get_user(db, current['owner_id'])
        if owner is None or owner['status'] != 'ACTIVE':
            raise AppError(403, 'LAB_OWNER_INACTIVE', '分析账号已停用')
        access.authorize_snapshot(db, current['definition'], owner)
        cursor = db.execute(
            '''INSERT INTO lab_reports(job_id,study_id,owner_id,title,definition,result,
            fingerprint,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)''',
            (
                item['id'],
                item['study_id'],
                item['owner_id'],
                item['title'],
                item['definition'],
                text,
                result['fingerprint'],
                timestamp,
                timestamp,
            ),
        )
        report_id = cursor.lastrowid
        db.execute(
            '''UPDATE lab_jobs SET state='SUCCEEDED',progress=100,report_id=?,
            lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?''',
            (report_id, timestamp, item['id']),
        )
        repo.event(db, item['id'], 'SUCCEEDED', '聚合报告已生成并归档为草稿', 100, timestamp)
    return report_id


def end_without_report(item, state, code, message):
    timestamp = utc_text(now_utc())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = one(db.execute('SELECT * FROM lab_jobs WHERE id=?', (item['id'],)))
        if current is None or current['lease_token'] != item['lease_token'] or current['state'] != 'RUNNING':
            return
        db.execute(
            '''UPDATE lab_jobs SET state=?,error_code=?,lease_token=NULL,
            lease_until=NULL,updated_at=? WHERE id=?''',
            (state, code, timestamp, item['id']),
        )
        repo.event(db, item['id'], code, message, current['progress'], timestamp)


def run_once(stop=None):
    stop = stop or threading.Event()
    if stop.is_set():
        return False
    item = claim()
    if item is None:
        return False
    try:
        with connect() as db:
            owner = get_user(db, item['owner_id'])
        if owner is None or owner['status'] != 'ACTIVE':
            raise AppError(403, 'LAB_OWNER_INACTIVE', '分析账号已停用')
        definition = json.loads(item['definition'])
        result = build_result(
            definition,
            owner,
            datetime.fromisoformat(item['created_at']),
            lambda progress, message: checkpoint(item['id'], item['lease_token'], progress, message, stop),
        )
        checkpoint(item['id'], item['lease_token'], 98, '正在保存聚合报告', stop)
        finish(item, result)
    except LeaseLost:
        logger.info('Laboratory job %s lease changed', item['id'])
    except JobCancelled:
        end_without_report(item, 'CANCELLED', 'CANCELLED', '任务已取消，没有创建报告')
    except WorkerStopped:
        end_without_report(item, 'QUEUED', 'WORKER_STOPPED', '服务停止，任务保留在队列等待恢复')
    except Exception as error:
        code = error.code if isinstance(error, AppError) else 'LAB_ANALYSIS_FAILED'
        end_without_report(item, 'FAILED', code, '分析失败，可核对权限、数据和参数后重试')
        logger.warning('Laboratory job %s failed: %s', item['id'], type(error).__name__)
    return True


def loop(stop):
    while not stop.is_set():
        try:
            processed = run_once(stop)
        except Exception as error:
            logger.warning('Laboratory worker unavailable: %s', type(error).__name__)
            processed = False
        if not processed:
            stop.wait(1)
