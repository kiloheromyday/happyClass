import csv
from datetime import datetime, timedelta
import hashlib
from io import StringIO
import math

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.emotion.insights import repository as repo
from backend.app.repositories.classroom import audit
from backend.app.repositories.database import connect
from backend.app.repositories.privacy import policy
from backend.app.emotion.replay.repository import grouped_frames
from backend.app.services.classroom import accessible_session, FEEDBACK_GRACE, session_view
from backend.app.emotion.insights.analysis import compare_windows, detect_signals, distribution, SOURCES
from backend.app.services.reports import safe_csv_cell

MAX_WINDOWS = 360
MAX_ENTRIES = 100


def require_staff(user):
    if user['role'] not in ('TEACHER', 'ADMIN'):
        raise AppError(403, 'FORBIDDEN', '仅任课教师或管理员可访问课堂洞察')


def analysis(session_id, user, source='ALL', data_scope='REAL', comparison_minutes=5):
    require_staff(user)
    with connect() as db:
        db.execute('BEGIN')
        session = accessible_session(db, session_id, user)
        rules = repo.rules(db, session_id)
        start, end = (datetime.fromisoformat(session[key]) for key in ('starts_at', 'ends_at'))
        now = now_utc()
        upper = max(start, min(now, end + FEEDBACK_GRACE))
        seconds = max(rules['bucket_minutes'] * 60, math.ceil((upper-start).total_seconds()/MAX_WINDOWS/60)*60)
        frames = []
        grouped = grouped_frames(db, session_id, utc_text(start), utc_text(upper), seconds, source, data_scope)
        by_frame = {}
        for row in grouped:
            by_frame.setdefault(row['frame'], []).append(row)
        for index in range(max(1, math.ceil((upper-start).total_seconds()/seconds))):
            lower = start + timedelta(seconds=index*seconds)
            finish = min(upper, lower + timedelta(seconds=seconds))
            items = by_frame.get(index, [])
            frames.append({'index': index, 'from_time': utc_text(lower), 'to_time': utc_text(finish),
                           'start_minute': index*seconds//60, 'end_minute': (finish-start).total_seconds()/60,
                           'complete': finish-lower == timedelta(seconds=seconds),
                           'sources': {key: distribution(items, key) for key in SOURCES},
                           **distribution(items)})
        authored = repo.entries(db, session_id)
        phases = [item for item in authored if item['kind'] == 'PHASE']
        for frame in frames:
            frame['phase_titles'] = [item['title'] for item in phases
                                     if item['start_minute'] < frame['end_minute'] and item['end_minute'] > frame['start_minute']]
        signals = detect_signals(frames, rules)
        for signal in signals:
            signal['phase_titles'] = [item['title'] for item in phases
                                      if item['start_minute'] < signal['end_minute'] and item['end_minute'] > signal['start_minute']]
        for item in authored:
            if item['kind'] != 'ACTION':
                continue
            anchor = start + timedelta(minutes=item['start_minute'])
            before_start, after_end = anchor-timedelta(minutes=comparison_minutes), anchor+timedelta(minutes=comparison_minutes)
            complete = start <= before_start and after_end <= upper and item['status'] == 'DONE'
            before = repo.counts(db, session_id, utc_text(max(start,before_start)), utc_text(min(anchor,upper)), source, data_scope)
            after = repo.counts(db, session_id, utc_text(anchor), utc_text(min(after_end,upper)), source, data_scope)
            item['comparison'] = {'window_minutes': comparison_minutes, 'complete': complete,
                                  'from_time': utc_text(max(start,before_start)), 'anchor_time': utc_text(anchor),
                                  'to_time': utc_text(min(after_end,upper)),
                                  'sources': compare_windows(before, after, rules['min_records'], complete)}
        all_rows = repo.counts(db, session_id, utc_text(start), utc_text(upper), source, data_scope)
        return {'session': session_view(session), 'rules': rules, 'source': source, 'data_scope': data_scope,
                'privacy_mode': policy(db, session_id)['mode'], 'updated_at': utc_text(now),
                'window': {'from_time': utc_text(start), 'to_time': utc_text(upper), 'bucket_minutes': seconds//60,
                           'class_minutes': (end-start).total_seconds()/60},
                'summary': {**distribution(all_rows), 'populated_windows': sum(frame['total'] > 0 for frame in frames),
                            'complete_windows': sum(frame['complete'] for frame in frames),
                            'signal_count': len(signals), 'action_count': sum(item['kind'] == 'ACTION' for item in authored)},
                'sources': {key: distribution(all_rows, key) for key in SOURCES},
                'frames': frames, 'signals': signals, 'entries': authored,
                'method': {'version': 'sustained-concern-v1', 'concern_emotions': ['SAD','ANGRY','FEAR','DISGUST'],
                           'unit': 'records', 'compares_sources_separately': True, 'causal_inference': False}}


def save_rules(session_id, payload, user):
    require_staff(user)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        accessible_session(db, session_id, user)
        old = repo.rules(db, session_id)
        if old['version'] != payload.version:
            raise AppError(409, 'VERSION_CONFLICT', '规则已被其他窗口更新，请刷新后再保存')
        db.execute('''INSERT INTO emotion_insight_rules VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET bucket_minutes=excluded.bucket_minutes,
            min_records=excluded.min_records,concern_ratio=excluded.concern_ratio,
            consecutive_windows=excluded.consecutive_windows,version=excluded.version,updated_at=excluded.updated_at''',
            (session_id,payload.bucket_minutes,payload.min_records,payload.concern_ratio,payload.consecutive_windows,
             payload.version+1,utc_text(now_utc())))
        audit(db, user['id'], 'INSIGHT_RULES_UPDATED', {'session_id':session_id,'version':payload.version+1})
        return repo.rules(db, session_id)


def save_entry(session_id, payload, user, entry_id=None):
    require_staff(user)
    digest = hashlib.sha256(payload.model_dump_json(exclude={'version','request_id'}).encode()).hexdigest()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        session = accessible_session(db, session_id, user)
        old = next((item for item in repo.entries(db,session_id) if item['id'] == entry_id), None)
        if entry_id is not None and old is None:
            raise AppError(404, 'ENTRY_NOT_FOUND', '这节课没有该条记录')
        previous = db.execute('SELECT id,payload_hash FROM emotion_insight_entries WHERE session_id=? AND request_id=?',
                              (session_id,str(payload.request_id))).fetchone()
        if entry_id is None and previous:
            if previous[1] != digest:
                raise AppError(409, 'REQUEST_ID_REUSED', '重试内容与原记录不一致')
            return next(item for item in repo.entries(db,session_id) if item['id'] == previous[0])
        if payload.version != (old['version'] if old else 0):
            raise AppError(409, 'VERSION_CONFLICT', '记录已变化，请刷新后再编辑')
        if old and old['kind'] != payload.kind:
            raise AppError(422, 'ENTRY_KIND_FIXED', '不能改变记录类型，请另建一条记录')
        start, end = (datetime.fromisoformat(session[key]) for key in ('starts_at','ends_at'))
        limit = (end-start).total_seconds()/60 + (30 if payload.kind == 'ACTION' else 0)
        if payload.end_minute > limit:
            raise AppError(422, 'OUTSIDE_SESSION', '记录时间超出课堂范围')
        if payload.kind == 'ACTION' and payload.status == 'DONE' and start+timedelta(minutes=payload.start_minute) > now_utc():
            raise AppError(422, 'ACTION_IN_FUTURE', '未来的教学调整请先保存为计划')
        if payload.kind == 'PHASE' and db.execute('''SELECT 1 FROM emotion_insight_entries WHERE session_id=?
            AND kind='PHASE' AND id<>? AND start_minute<? AND end_minute>? LIMIT 1''',
            (session_id,entry_id or -1,payload.end_minute,payload.start_minute)).fetchone():
            raise AppError(409, 'PHASE_OVERLAP', '教学环节时间重叠，请调整起止分钟')
        if old is None and db.execute('SELECT count(*) FROM emotion_insight_entries WHERE session_id=?',(session_id,)).fetchone()[0] >= MAX_ENTRIES:
            raise AppError(422, 'ENTRY_LIMIT', '每节课最多保存 100 条教学记录')
        stamp = utc_text(now_utc())
        values = (payload.title,payload.content,payload.start_minute,payload.end_minute,payload.status,payload.outcome,payload.version+1,stamp)
        if old:
            db.execute('''UPDATE emotion_insight_entries SET title=?,content=?,start_minute=?,end_minute=?,status=?,outcome=?,
                version=?,updated_at=? WHERE id=? AND session_id=?''',(*values,entry_id,session_id))
        else:
            cursor = db.execute('''INSERT INTO emotion_insight_entries(title,content,start_minute,end_minute,status,outcome,version,
                updated_at,session_id,kind,created_by,created_at,request_id,payload_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (*values,session_id,payload.kind,user['id'],stamp,str(payload.request_id),digest))
            entry_id = cursor.lastrowid
        audit(db,user['id'],'INSIGHT_ENTRY_SAVED',{'session_id':session_id,'entry_id':entry_id,'kind':payload.kind})
        return next(item for item in repo.entries(db,session_id) if item['id'] == entry_id)


def delete_entry(session_id, entry_id, version, user):
    require_staff(user)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        accessible_session(db,session_id,user)
        item = next((item for item in repo.entries(db,session_id) if item['id'] == entry_id),None)
        if item is None:
            raise AppError(404,'ENTRY_NOT_FOUND','记录不存在或已删除')
        if item['version'] != version:
            raise AppError(409,'VERSION_CONFLICT','记录已更新，请刷新后再删除')
        db.execute('DELETE FROM emotion_insight_entries WHERE id=? AND session_id=?',(entry_id,session_id))
        audit(db,user['id'],'INSIGHT_ENTRY_DELETED',{'session_id':session_id,'entry_id':entry_id})
    return {'deleted':True}


def export_report(session_id, user, source, data_scope, comparison_minutes):
    data = analysis(session_id,user,source,data_scope,comparison_minutes)
    buffer = StringIO(newline='')
    writer = csv.writer(buffer)
    def row(*cells):
        writer.writerow([safe_csv_cell(cell) for cell in cells])
    row('课堂情绪洞察报告',data['session']['course_name'],data['session']['class_name'])
    row('快照时间',data['updated_at'],'来源',source,'数据范围',data_scope)
    row('统计单位','反馈记录次数；不代表人数。前后变化为描述性对比，不证明教学措施导致变化。')
    row('关注类别','低落、生气、担忧、反感；AI 与主动反馈分开分析')
    row('规则',f"每段 {data['window']['bucket_minutes']} 分钟",f"至少 {data['rules']['min_records']} 条",f"关注占比 {data['rules']['concern_ratio']:.0%}",f"连续 {data['rules']['consecutive_windows']} 段")
    row('记录总数',data['summary']['total'],'合成演示记录',data['summary']['demo_count'])
    row('时段开始','时段结束','来源','记录数','关注类别记录数','关注类别占比','完整时段','教学环节')
    for frame in data['frames']:
        for origin in SOURCES:
            metric = frame['sources'][origin]
            row(frame['from_time'],frame['to_time'],origin,metric['total'],metric['concern_count'],metric['concern_ratio'],'是' if frame['complete'] else '否',' / '.join(frame['phase_titles']))
    row('关注时段来源','开始时间','结束时间','连续时段数','记录数','关注类别占比','关联环节')
    for signal in data['signals']:
        row(signal['source'],signal['from_time'],signal['to_time'],signal['windows'],signal['total'],signal['concern_ratio'],' / '.join(signal['phase_titles']))
    row('教学记录类型','标题','内容','开始分钟','结束分钟','状态','教师复盘')
    for item in data['entries']:
        row(item['kind'],item['title'],item['content'],item['start_minute'],item['end_minute'],item['status'],item['outcome'])
        if item['kind'] == 'ACTION':
            for comparison in item['comparison']['sources']:
                row('前后对比',comparison['source'],comparison['status'],'前',comparison['before']['total'],'后',comparison['after']['total'],'变化百分点',comparison['change_percentage_points'])
    return ('\ufeff'+buffer.getvalue()).encode('utf-8'),len(data['frames'])
