import hashlib
import json

from backend.app.errors import AppError
from backend.app.emotion.lab import access
from backend.app.emotion.lab import repository as repo
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import audit, one
from backend.app.repositories.database import connect

MAX_STUDIES = 100
MAX_REPORTS = 200
MAX_ACTIVE_JOBS = 3


def fingerprint(value):
    return hashlib.sha256(repo.encode(value).encode()).hexdigest()


def definition(payload):
    return {
        'session_ids': payload.session_ids,
        'baseline_ids': payload.baseline_ids,
        'settings': payload.settings.model_dump(),
        'question': payload.question,
    }


def dashboard(user):
    from backend.app.emotion.lab.runtime import status
    access.staff(user)
    with connect() as db:
        result = repo.dashboard(db, user['id'])
        result['worker'] = status()
        return result


def catalog(user, search='', course_id=None, offset=0, limit=20):
    access.staff(user)
    with connect() as db:
        return repo.catalog(db, user, search.strip(), course_id, offset, limit)


def list_studies(user, archived=None, search='', offset=0, limit=20):
    access.staff(user)
    with connect() as db:
        return repo.studies(db, user['id'], archived, search.strip(), offset, limit)


def get_study(identifier, user):
    with connect() as db:
        return repo.study_view(access.study(db, identifier, user))


def save_study(payload, user, identifier=None):
    access.staff(user)
    snapshot = definition(payload)
    digest = fingerprint(payload.model_dump(mode='json', exclude={'request_id', 'version'}))
    timestamp = utc_text(now_utc())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        access.authorize_sessions(db, snapshot['session_ids'], user)
        if identifier is None:
            previous = repo.previous_study(db, user['id'], str(payload.request_id))
            if previous:
                if previous['payload_hash'] != digest:
                    raise AppError(409, 'REQUEST_ID_REUSED', '方案请求已使用，重试内容必须相同')
                return repo.study_view(previous)
            count = db.execute(
                'SELECT count(*) FROM lab_studies WHERE owner_id=?',
                (user['id'],),
            ).fetchone()[0]
            if count >= MAX_STUDIES:
                raise AppError(422, 'LAB_STUDY_LIMIT', '每个账号最多保存 100 个分析方案')
            if payload.version != 0:
                raise AppError(409, 'VERSION_CONFLICT', '新方案版本应为零')
            identifier = repo.insert_study(db, user['id'], payload, snapshot, digest, timestamp)
        else:
            current = access.study(db, identifier, user)
            if current['archived']:
                raise AppError(409, 'STUDY_ARCHIVED', '请先恢复归档方案，再修改内容')
            if current['version'] != payload.version:
                raise AppError(409, 'VERSION_CONFLICT', '方案已在其他窗口更新，请刷新后再编辑')
            repo.update_study(db, identifier, payload, snapshot, timestamp)
        audit(db, user['id'], 'LAB_STUDY_SAVED', {'study_id': identifier})
        return repo.study_view(access.study(db, identifier, user))


def archive_study(identifier, payload, user):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = access.study(db, identifier, user)
        if item['version'] != payload.version:
            raise AppError(409, 'VERSION_CONFLICT', '方案版本已变化，请刷新')
        db.execute(
            'UPDATE lab_studies SET archived=?,version=version+1,updated_at=? WHERE id=?',
            (int(payload.archived), utc_text(now_utc()), identifier),
        )
        audit(db, user['id'], 'LAB_STUDY_ARCHIVED', {
            'study_id': identifier,
            'archived': payload.archived,
        })
        return repo.study_view(access.study(db, identifier, user))


def preview(payload, user):
    access.staff(user)
    snapshot = definition(payload)
    with connect() as db:
        db.execute('BEGIN')
        items = access.authorize_sessions(db, snapshot['session_ids'], user)
        return {
            'session_count': len(items),
            'baseline_count': len(snapshot['baseline_ids']),
            'comparison_count': len(items) - len(snapshot['baseline_ids']),
            'demo_courses': sum(item['is_demo'] for item in items),
            'stored_record_count': sum(item['record_count'] for item in items),
            'settings': snapshot['settings'],
            'note': '存储条数是筛选前数量；正式报告将按来源、演示范围和课堂时间过滤。',
            'sessions': [{
                'id': item['id'],
                'course_name': item['course_name'],
                'class_name': item['class_name'],
                'starts_at': item['starts_at'],
                'group': 'BASELINE' if item['id'] in snapshot['baseline_ids'] else 'COMPARISON',
            } for item in items],
        }


def enqueue(study_id, payload, user):
    timestamp = utc_text(now_utc())
    digest = fingerprint({'study_id': study_id, 'version': payload.version})
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        study = access.study(db, study_id, user)
        previous = one(db.execute(
            'SELECT * FROM lab_jobs WHERE owner_id=? AND request_id=?',
            (user['id'], str(payload.request_id)),
        ))
        if previous:
            if previous['payload_hash'] != digest:
                raise AppError(409, 'REQUEST_ID_REUSED', '该运行请求已用于其他方案或版本')
            access.authorize_snapshot(db, previous['definition'], user)
            return repo.job_view(previous)
        if study['archived']:
            raise AppError(409, 'STUDY_ARCHIVED', '归档方案不能运行，请先恢复')
        if study['version'] != payload.version:
            raise AppError(409, 'VERSION_CONFLICT', '方案已更新，请刷新后运行')
        active = db.execute(
            "SELECT count(*) FROM lab_jobs WHERE owner_id=? AND state IN ('QUEUED','RUNNING')",
            (user['id'],),
        ).fetchone()[0]
        if active >= MAX_ACTIVE_JOBS:
            raise AppError(429, 'LAB_QUEUE_LIMIT', '已有三个进行中任务，请等待或取消后再运行')
        reports = db.execute(
            'SELECT count(*) FROM lab_reports WHERE owner_id=?',
            (user['id'],),
        ).fetchone()[0]
        if reports >= MAX_REPORTS:
            raise AppError(422, 'LAB_REPORT_LIMIT', '报告已达到 200 份上限，请先整理报告')
        cursor = db.execute(
            '''INSERT INTO lab_jobs(study_id,owner_id,title,definition,study_version,state,
            request_id,payload_hash,created_at,updated_at) VALUES (?,?,?,?,?,'QUEUED',?,?,?,?)''',
            (
                study_id,
                user['id'],
                study['title'],
                study['definition'],
                study['version'],
                str(payload.request_id),
                digest,
                timestamp,
                timestamp,
            ),
        )
        identifier = cursor.lastrowid
        repo.event(db, identifier, 'QUEUED', '方案快照已保存，等待后台分析', 0, timestamp)
        audit(db, user['id'], 'LAB_JOB_CREATED', {'job_id': identifier, 'study_id': study_id})
        return repo.job_view(access.job(db, identifier, user))


def list_jobs(user, state=None, offset=0, limit=20):
    access.staff(user)
    with connect() as db:
        return repo.list_jobs(db, user['id'], state, offset, limit)


def get_job(identifier, user, after_id=0):
    with connect() as db:
        db.execute('BEGIN')
        item = repo.job_view(access.job(db, identifier, user))
        item['events'] = repo.job_events(db, identifier, after_id)
        return item


def cancel_job(identifier, user):
    timestamp = utc_text(now_utc())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = access.job(db, identifier, user)
        if item['state'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
            return repo.job_view(item)
        state = 'CANCELLED' if item['state'] == 'QUEUED' else 'RUNNING'
        db.execute(
            'UPDATE lab_jobs SET cancel_requested=1,state=?,updated_at=? WHERE id=?',
            (state, timestamp, identifier),
        )
        repo.event(db, identifier, 'CANCEL_REQUESTED', '已请求取消，后台将在安全检查点停止', item['progress'], timestamp)
        audit(db, user['id'], 'LAB_JOB_CANCELLED', {'job_id': identifier})
        return repo.job_view(access.job(db, identifier, user))


def retry_job(identifier, user):
    timestamp = utc_text(now_utc())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = access.job(db, identifier, user)
        if item['state'] != 'FAILED':
            raise AppError(409, 'LAB_JOB_NOT_FAILED', '只有失败任务可以重试')
        if item['attempts'] >= 3:
            raise AppError(409, 'LAB_RETRY_LIMIT', '已达到三次尝试，请核对问题后重新创建任务')
        active = db.execute(
            "SELECT count(*) FROM lab_jobs WHERE owner_id=? AND state IN ('QUEUED','RUNNING')",
            (user['id'],),
        ).fetchone()[0]
        if active >= MAX_ACTIVE_JOBS:
            raise AppError(429, 'LAB_QUEUE_LIMIT', '进行中任务已达上限')
        db.execute(
            '''UPDATE lab_jobs SET state='QUEUED',progress=0,cancel_requested=0,
            lease_token=NULL,lease_until=NULL,error_code=NULL,updated_at=? WHERE id=?''',
            (timestamp, identifier),
        )
        repo.event(db, identifier, 'REQUEUED', '使用原方案快照重新排队', 0, timestamp)
        audit(db, user['id'], 'LAB_JOB_RETRIED', {'job_id': identifier})
        return repo.job_view(access.job(db, identifier, user))


def list_reports(user, status=None, bookmarked=False, search='', offset=0, limit=20):
    access.staff(user)
    with connect() as db:
        return repo.list_reports(db, user['id'], status, bookmarked, search.strip(), offset, limit)


def get_report(identifier, user):
    with connect() as db:
        db.execute('BEGIN')
        item = repo.report_view(access.report(db, identifier, user), detailed=True)
        item['annotations'] = repo.annotations(db, identifier)
        return item


def update_report(identifier, payload, user):
    timestamp = utc_text(now_utc())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = access.report(db, identifier, user)
        if item['version'] != payload.version:
            raise AppError(409, 'VERSION_CONFLICT', '报告已被更新，请刷新后再编辑')
        db.execute(
            '''UPDATE lab_reports SET title=?,status=?,bookmarked=?,conclusion=?,
            version=version+1,updated_at=? WHERE id=?''',
            (
                payload.title,
                payload.status,
                int(payload.bookmarked),
                payload.conclusion,
                timestamp,
                identifier,
            ),
        )
        audit(db, user['id'], 'LAB_REPORT_UPDATED', {'report_id': identifier, 'status': payload.status})
        return repo.report_view(access.report(db, identifier, user))


def save_annotation(report_id, payload, user, identifier=None):
    timestamp = utc_text(now_utc())
    digest = fingerprint({'section': payload.section, 'content': payload.content})
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        report = access.report(db, report_id, user)
        if report['status'] == 'ARCHIVED':
            raise AppError(409, 'REPORT_ARCHIVED', '请先将报告恢复为草稿，再编辑批注')
        if identifier is None:
            previous = one(db.execute(
                'SELECT * FROM lab_annotations WHERE report_id=? AND request_id=?',
                (report_id, str(payload.request_id)),
            ))
            if previous:
                if previous['payload_hash'] != digest:
                    raise AppError(409, 'REQUEST_ID_REUSED', '批注请求已使用，重试内容必须相同')
                return next(item for item in repo.annotations(db, report_id) if item['id'] == previous['id'])
            count = db.execute('SELECT count(*) FROM lab_annotations WHERE report_id=?', (report_id,)).fetchone()[0]
            if count >= 50:
                raise AppError(422, 'ANNOTATION_LIMIT', '每份报告最多保存 50 条批注')
            if payload.version != 0:
                raise AppError(409, 'VERSION_CONFLICT', '新批注版本应为零')
            cursor = db.execute(
                '''INSERT INTO lab_annotations(report_id,section,content,request_id,payload_hash,
                created_at,updated_at) VALUES (?,?,?,?,?,?,?)''',
                (report_id, payload.section, payload.content, str(payload.request_id), digest, timestamp, timestamp),
            )
            identifier = cursor.lastrowid
        else:
            item = one(db.execute(
                'SELECT * FROM lab_annotations WHERE id=? AND report_id=?',
                (identifier, report_id),
            ))
            if item is None:
                raise AppError(404, 'ANNOTATION_NOT_FOUND', '批注不存在或不属于这份报告')
            if item['version'] != payload.version:
                raise AppError(409, 'VERSION_CONFLICT', '批注已更新，请刷新')
            db.execute(
                'UPDATE lab_annotations SET section=?,content=?,version=version+1,updated_at=? WHERE id=?',
                (payload.section, payload.content, timestamp, identifier),
            )
        audit(db, user['id'], 'LAB_ANNOTATION_SAVED', {'report_id': report_id, 'annotation_id': identifier})
        return next(item for item in repo.annotations(db, report_id) if item['id'] == identifier)


def delete_annotation(report_id, identifier, version, user):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        report = access.report(db, report_id, user)
        if report['status'] == 'ARCHIVED':
            raise AppError(409, 'REPORT_ARCHIVED', '归档报告的批注不能直接删除')
        item = one(db.execute(
            'SELECT * FROM lab_annotations WHERE id=? AND report_id=?',
            (identifier, report_id),
        ))
        if item is None:
            raise AppError(404, 'ANNOTATION_NOT_FOUND', '批注不存在')
        if item['version'] != version:
            raise AppError(409, 'VERSION_CONFLICT', '批注版本已更新')
        db.execute('DELETE FROM lab_annotations WHERE id=? AND report_id=?', (identifier, report_id))
        audit(db, user['id'], 'LAB_ANNOTATION_DELETED', {'report_id': report_id, 'annotation_id': identifier})
    return {'deleted': True}


def compare_reports(left_id, right_id, user):
    from backend.app.emotion.lab.metrics import SOURCES, distance
    left = get_report(left_id, user)
    right = get_report(right_id, user)
    a = left['definition']['settings']
    b = right['definition']['settings']
    fields = ('source', 'data_scope', 'include_after_class', 'min_records')
    differences = [field for field in fields if a[field] != b[field]]
    compatible = not differences
    changes = []
    for source in SOURCES:
        before = left['result']['sources'][source]
        after = right['result']['sources'][source]
        ready = compatible and before['eligible_sessions'] and after['eligible_sessions']
        delta = None
        if ready:
            delta = round((after['equal_weight_concern_ratio'] - before['equal_weight_concern_ratio']) * 100, 3)
        changes.append({
            'source': source,
            'before': before,
            'after': after,
            'equal_weight_change_pp': delta,
            'distance': distance(before['pooled']['counts'], after['pooled']['counts'], a['min_records']) if compatible else None,
        })
    return {
        'left': {key: left[key] for key in ('id', 'title', 'created_at', 'fingerprint')},
        'right': {key: right[key] for key in ('id', 'title', 'created_at', 'fingerprint')},
        'compatible': compatible,
        'different_settings': differences,
        'sources': changes,
        'note': '报告范围与课堂组成可能不同，差异仅供描述性核对。',
    }
