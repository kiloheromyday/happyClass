from datetime import datetime, timedelta
import hashlib
import math

from backend.app.emotion.lab import repository as repo
from backend.app.emotion.lab.access import authorize_sessions
from backend.app.emotion.lab.alignment import build_alignment
from backend.app.emotion.lab.metrics import (
    SOURCES,
    changes_over_time,
    counts_for,
    distribution,
    group_comparison,
    rank_sessions,
    session_pairs,
    source_summaries,
    summarize_sessions,
)
from backend.app.emotion.lab.quality import inspect_session, summarize_quality
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.database import connect

ENGINE_VERSION = 'happyclass-lab-1.0'
MAX_BUCKETS = 180


def time_window(session, settings, cutoff):
    start = datetime.fromisoformat(session['starts_at'])
    end = datetime.fromisoformat(session['ends_at'])
    finish = end + timedelta(minutes=30 if settings['include_after_class'] else 0)
    upper = max(start, min(cutoff, finish))
    duration = (finish - start).total_seconds()
    if settings['alignment'] == 'RELATIVE':
        seconds = max(1, math.ceil(duration / settings['relative_bins']))
    else:
        seconds = max(settings['bucket_minutes'] * 60, math.ceil(duration / MAX_BUCKETS / 60) * 60)
    return start, end, finish, upper, seconds


def analyze_session(connection, session, settings, cutoff):
    start, end, finish, upper, seconds = time_window(session, settings, cutoff)
    grouped = repo.grouped_records(
        connection, session['id'], utc_text(start), utc_text(upper), settings, seconds,
    )
    by_bucket = {}
    for row in grouped:
        by_bucket.setdefault(row['bucket'], []).append(row)
    frames = []
    amount = max(1, math.ceil((upper - start).total_seconds() / seconds))
    for index in range(amount):
        lower = start + timedelta(seconds=index * seconds)
        planned_end = min(finish, lower + timedelta(seconds=seconds))
        observed_end = min(upper, planned_end)
        selected = by_bucket.get(index, [])
        frames.append({
            'index': index,
            'from_time': utc_text(lower),
            'to_time': utc_text(observed_end),
            'planned_to_time': utc_text(planned_end),
            'start_second': index * seconds,
            'planned_end_second': int((planned_end - start).total_seconds()),
            'complete': observed_end == planned_end and observed_end > lower,
            'sources': source_summaries(selected, settings['min_records']),
            'total': sum(row['count'] for row in selected),
        })
    phase_rows = repo.phase_records(
        connection, session['id'], utc_text(start), utc_text(upper), settings,
    )
    phase_groups = {}
    for row in phase_rows:
        target = phase_groups.setdefault(row['phase_id'], {
            'title': row['title'],
            'start_minute': row['start_minute'],
            'end_minute': row['end_minute'],
            'rows': [],
        })
        target['rows'].append({
            'source': row['source'],
            'emotion': row['emotion'],
            'count': row['count'],
            'demo_count': row['demo_count'],
        })
    fields = ('id', 'course_id', 'course_name', 'class_name', 'classroom', 'starts_at', 'ends_at', 'privacy_mode')
    result = {
        'session': {key: session[key] for key in fields},
        'window': {
            'from_time': utc_text(start),
            'to_time': utc_text(upper),
            'planned_to_time': utc_text(finish),
            'bucket_seconds': seconds,
        },
        'has_started': cutoff >= start,
        'has_finished': cutoff >= finish,
        'sources': source_summaries(grouped, settings['min_records']),
        'distribution': distribution(counts_for(grouped), settings['min_records']),
        'demo_count': sum(row['demo_count'] for row in grouped),
        'frames': frames,
        'phases': repo.phase_definitions(connection, session['id']),
        'phase_summary': list(phase_groups.values()),
        'confidence_histogram': repo.confidence_histogram(
            connection, session['id'], utc_text(start), utc_text(upper), settings,
        ),
        'integrity': repo.integrity_counts(
            connection, session['id'], utc_text(start), utc_text(finish), utc_text(cutoff), settings,
        ),
    }
    result['quality'] = inspect_session(result, settings)
    return result


def build_result(definition, user, cutoff, checkpoint=lambda progress, message: None):
    settings = definition['settings']
    results = []
    with connect() as db:
        db.execute('BEGIN')
        selected = authorize_sessions(db, definition['session_ids'], user)
    for index, session in enumerate(selected):
        checkpoint(5 + int(index / len(selected) * 65), f'正在聚合第 {index + 1}/{len(selected)} 节课堂')
        with connect() as db:
            db.execute('BEGIN')
            session = authorize_sessions(db, [session['id']], user)[0]
            results.append(analyze_session(db, session, settings, cutoff))
    checkpoint(75, '正在对齐课堂时段与教学环节')
    alignment = build_alignment(results, settings)
    checkpoint(82, '正在汇总组间比较与数据质量')
    result = {
        'engine_version': ENGINE_VERSION,
        'captured_at': utc_text(now_utc()),
        'recorded_before': utc_text(cutoff),
        'settings': settings,
        'sessions': results,
        'summary': {
            'session_count': len(results),
            'total_records': sum(item['distribution']['total'] for item in results),
            'demo_records': sum(item['demo_count'] for item in results),
            'source_totals': {
                source: sum(item['sources'][source]['total'] for item in results)
                for source in SOURCES
            },
        },
        'sources': {
            source: summarize_sessions(results, source, settings['min_records'])
            for source in SOURCES
        },
        'alignment': alignment,
        'groups': group_comparison(results, definition['baseline_ids'], settings['min_records']),
        'pairs': session_pairs(results, settings['min_records']),
        'quality': summarize_quality(results),
        'chronology': {
            source: changes_over_time(results, source, settings['min_records'])
            for source in SOURCES
        },
        'attention_order': {
            source: rank_sessions(results, source, settings['min_records'])
            for source in SOURCES
        },
        'methodology': methodology(),
    }
    result['findings'] = findings(result)
    checkpoint(94, '正在冻结报告快照')
    result['fingerprint'] = hashlib.sha256(repo.encode(result).encode()).hexdigest()
    return result


def methodology():
    return {
        'unit': '反馈记录次数，不代表学生人数',
        'sources': '学生主动反馈与 AI 分类分别分析，采样对象和频率可能不同',
        'concern_classes': ['SAD', 'ANGRY', 'FEAR', 'DISGUST'],
        'equal_weight': '仅纳入达到最小样本的课堂，各课堂关注占比按相同权重求均值',
        'pooled_weight': '将记录相加后计算占比，采样量大的课堂权重更高',
        'distribution_distance': '总变差和 Jensen–Shannon 分歧描述分布差异，不是模型准确率',
        'temporal_window': '时间区间左闭右开，结束边界上的记录不属于前一个区间',
        'uncertainty': '没有对学生去重或随机抽样，不输出显著性检验、因果结论或心理诊断',
        'reproducibility': '冻结聚合查询结果、方案版本、引擎版本与快照指纹；不修改原始反馈',
    }


def findings(result):
    notes = []
    summary = result['summary']
    notes.append({
        'code': 'SAMPLE_OVERVIEW',
        'title': '分析范围',
        'text': f"本次共选择 {summary['session_count']} 节课堂，纳入 {summary['total_records']} 条反馈记录。",
    })
    if summary['demo_records']:
        notes.append({
            'code': 'DEMO_BOUNDARY',
            'title': '包含合成演示记录',
            'text': f"其中 {summary['demo_records']} 条标记为演示，不能作为实际课堂效果证据。",
        })
    patterns = result['alignment']['patterns']
    notes.append({
        'code': 'REPEATED_PATTERNS',
        'title': '重复出现的时段线索',
        'text': f"识别到 {len(patterns)} 个满足样本量、完整性和阈值条件的跨课堂时段线索。",
    })
    for group in result['groups']:
        if group['status'] == 'INSUFFICIENT_DATA':
            continue
        notes.append({
            'code': 'GROUP_DIFFERENCE',
            'source': group['source'],
            'title': '两组课堂的描述性差异',
            'text': f"比较组相对基准组的课堂等权关注占比变化为 {group['equal_weight_change_pp']:+g} 个百分点。",
        })
    if result['quality']['warning_count']:
        notes.append({
            'code': 'QUALITY_FIRST',
            'title': '先核对数据质量',
            'text': f"存在 {result['quality']['warning_count']} 项质量提示，解读差异前请先核对对应课堂。",
        })
    return notes
