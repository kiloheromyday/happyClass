"""Report lifecycle and verifiable aggregate snapshots."""
import hashlib
import json

from backend.app.errors import AppError
from backend.app.emotion.lab import access
from backend.app.emotion.lab import repository as repo
from backend.app.emotion.lab.metrics import EMOTIONS, SOURCES
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import audit, rows
from backend.app.repositories.database import connect


def storage(user):
    access.staff(user)
    with connect() as db:
        reports = db.execute(
            '''SELECT count(*),coalesce(sum(length(CAST(result AS BLOB))),0),
            coalesce(sum(status='ARCHIVED'),0),coalesce(sum(status='REVIEWED'),0),
            min(created_at),max(created_at) FROM lab_reports WHERE owner_id=?''',
            (user['id'],),
        ).fetchone()
        notes = db.execute(
            '''SELECT count(*),coalesce(sum(length(CAST(a.content AS BLOB))),0)
            FROM lab_annotations a JOIN lab_reports r ON r.id=a.report_id WHERE r.owner_id=?''',
            (user['id'],),
        ).fetchone()
        studies = db.execute(
            'SELECT count(*),coalesce(sum(archived=1),0) FROM lab_studies WHERE owner_id=?',
            (user['id'],),
        ).fetchone()
        jobs = dict(db.execute(
            'SELECT state,count(*) FROM lab_jobs WHERE owner_id=? GROUP BY state',
            (user['id'],),
        ).fetchall())
    return {
        'reports': reports[0],
        'report_limit': 200,
        'aggregate_payload_bytes': reports[1],
        'archived_reports': reports[2],
        'reviewed_reports': reports[3],
        'oldest_report_at': reports[4],
        'newest_report_at': reports[5],
        'annotations': notes[0],
        'annotation_text_bytes': notes[1],
        'studies': studies[0],
        'archived_studies': studies[1],
        'study_limit': 100,
        'job_states': jobs,
        'note': '字节数仅统计当前账号的聚合结果和批注正文，不代表整个数据库文件大小。',
    }


def check_snapshot(identifier, user):
    with connect() as db:
        db.execute('BEGIN')
        report = access.report(db, identifier, user)
        data = json.loads(report['result'])
        frozen = {key: value for key, value in data.items() if key != 'fingerprint'}
        computed = hashlib.sha256(repo.encode(frozen).encode()).hexdigest()
        checks = []

        def check(code, label, passed, detail):
            checks.append({
                'code': code,
                'label': label,
                'passed': bool(passed),
                'detail': detail,
            })

        check(
            'CONTENT_HASH',
            '聚合内容与存储指纹一致',
            computed == report['fingerprint'],
            '对固定分析结果重新计算 SHA-256，不包括可编辑的教师结论和批注。',
        )
        check(
            'EMBEDDED_HASH',
            '结果内嵌指纹一致',
            data.get('fingerprint') == report['fingerprint'],
            '核对报告元信息与结果内嵌指纹。',
        )
        check(
            'SESSION_SCOPE',
            '课堂范围一致',
            [item['session']['id'] for item in data['sessions']] == json.loads(report['definition'])['session_ids'],
            '核对方案快照与实际分析课堂顺序。',
        )
        count = sum(item['distribution']['total'] for item in data['sessions'])
        check(
            'RECORD_TOTAL',
            '课堂总记录与摘要一致',
            count == data['summary']['total_records'],
            f'逐节汇总得到 {count} 条反馈记录。',
        )
        for source in SOURCES:
            selected = [item['sources'][source] for item in data['sessions']]
            source_total = sum(item['total'] for item in selected)
            pooled = data['sources'][source]['pooled']
            check(
                f'SOURCE_TOTAL_{source}',
                f'{source} 来源总数一致',
                source_total == pooled['total'] == data['summary']['source_totals'][source],
                '核对课堂、来源汇总与总摘要三个层次。',
            )
            count_match = all(
                sum(item['counts'][emotion] for item in selected) == pooled['counts'][emotion]
                for emotion in EMOTIONS
            )
            check(
                f'EMOTION_TOTAL_{source}',
                f'{source} 七类情绪计数一致',
                count_match,
                '核对七个分类的逐节总和，不涉及任何学生身份。',
            )
        check(
            'DEMO_COUNT',
            '演示标记总数一致',
            sum(item['demo_count'] for item in data['sessions']) == data['summary']['demo_records'],
            '核对被纳入分析的合成演示记录数量。',
        )
        check(
            'SETTINGS',
            '方案参数一致',
            data['settings'] == json.loads(report['definition'])['settings'],
            '核对任务创建时保存的方案参数。',
        )
        return {
            'report_id': identifier,
            'checked_at': utc_text(now_utc()),
            'passed': all(item['passed'] for item in checks),
            'stored_fingerprint': report['fingerprint'],
            'computed_fingerprint': computed,
            'checks': checks,
            'note': '内部一致性校验不代表情绪分类本身正确，也不是第三方数字签名。',
        }


def delete_report(identifier, version, user):
    timestamp = utc_text(now_utc())
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = access.report(db, identifier, user)
        if item['version'] != version:
            raise AppError(409, 'VERSION_CONFLICT', '报告版本已经变化，请刷新后再清理')
        if item['status'] != 'ARCHIVED':
            raise AppError(409, 'REPORT_NOT_ARCHIVED', '仅允许永久清理已归档报告，请先核对并归档')
        annotation_count = db.execute(
            'SELECT count(*) FROM lab_annotations WHERE report_id=?',
            (identifier,),
        ).fetchone()[0]
        db.execute('DELETE FROM lab_annotations WHERE report_id=?', (identifier,))
        db.execute('UPDATE lab_jobs SET report_id=NULL WHERE report_id=?', (identifier,))
        db.execute('DELETE FROM lab_reports WHERE id=? AND owner_id=?', (identifier, user['id']))
        repo.event(
            db, item['job_id'], 'REPORT_REMOVED',
            '创建者已永久清理归档报告，任务处理记录保留', 100, timestamp,
        )
        audit(db, user['id'], 'LAB_REPORT_REMOVED', {
            'report_id': identifier,
            'annotation_count': annotation_count,
        })
    return {'deleted': True, 'report_id': identifier, 'removed_annotations': annotation_count}


def history(study_id, user):
    with connect() as db:
        db.execute('BEGIN')
        access.study(db, study_id, user)
        items = rows(db.execute(
            'SELECT * FROM lab_jobs WHERE study_id=? AND owner_id=? ORDER BY id DESC LIMIT 100',
            (study_id, user['id']),
        ))
        visible = []
        restricted = 0
        for item in items:
            try:
                access.authorize_snapshot(db, item['definition'], user)
            except AppError as error:
                if error.status not in (403, 404):
                    raise
                restricted += 1
                continue
            definition = json.loads(item['definition'])
            visible.append({
                **repo.job_view(item),
                'session_count': len(definition['session_ids']),
                'settings': definition['settings'],
            })
    return {
        'items': visible,
        'restricted_count': restricted,
        'limit': 100,
        'note': '最多显示最近 100 次运行；失去课堂权限的历史快照不会展示内容。',
    }
