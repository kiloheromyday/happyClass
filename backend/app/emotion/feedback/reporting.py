from collections import Counter, defaultdict
from datetime import datetime, timedelta
from html import escape
from io import StringIO
import csv
import json
from statistics import median

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import rows
from backend.app.repositories.database import connect
from backend.app.emotion.feedback import cases
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback import serialization as serial
from backend.app.emotion.feedback.catalog import EMOTIONS
from backend.app.emotion.feedback.workflow import REASONS, STATES, STATE_NAMES, due_fields

EXPORT_LIMIT = 10000
ACTIVE = {'NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'WAITING_STUDENT', 'WAITING_REVIEW'}


def collect(connection, user, filters, limit=EXPORT_LIMIT):
    cases.validate_filters(connection, filters, user)
    items, total = repo.listing(connection, user, filters, 0, limit)
    if total > limit:
        raise AppError(422, 'REPORT_TOO_LARGE', f'筛选结果超过 {limit} 条，请缩小课程或课堂范围')
    return items


def duration_hours(start, end):
    if not start or not end:
        return None
    return round(max(0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 3600), 2)


def distribution(items, field, labels):
    counts = Counter(item[field] for item in items)
    total = len(items)
    return [{
        'value': key,
        'label': label,
        'count': counts[key],
        'percent': round(counts[key] * 100 / total, 1) if total else 0,
    } for key, label in labels.items()]


def round_data(connection, items):
    identifiers = {item['id'] for item in items}
    if not identifiers:
        return []
    result = []
    for start in range(0, len(items), 400):
        batch = [item['id'] for item in items[start:start + 400]]
        placeholders = ','.join('?' for _ in batch)
        result.extend(rows(connection.execute(
            '''SELECT r.*,a.outcome,a.emotion AS answer_emotion,a.created_at AS answered_at
            FROM feedback_reviews r LEFT JOIN feedback_review_answers a ON a.review_id=r.id
            WHERE r.case_id IN (''' + placeholders + ')',
            batch,
        )))
    return result


def response_metrics(items):
    acknowledgements = []
    responses = []
    resolutions = []
    for item in items:
        for key, values in (
            ('acknowledged_at', acknowledgements),
            ('first_response_at', responses),
            ('resolved_at', resolutions),
        ):
            value = duration_hours(item['created_at'], item[key])
            if value is not None:
                values.append(value)
    return {
        'acknowledgement_median_hours': median(acknowledgements) if acknowledgements else None,
        'response_median_hours': median(responses) if responses else None,
        'resolution_median_hours': median(resolutions) if resolutions else None,
        'acknowledgement_samples': len(acknowledgements),
        'response_samples': len(responses),
        'resolution_samples': len(resolutions),
    }


def review_metrics(rounds):
    counts = Counter(item['outcome'] for item in rounds if item['outcome'])
    answered = sum(counts.values())
    cancelled = sum(item['state'] == 'CANCELLED' for item in rounds)
    opened = sum(item['state'] == 'OPEN' for item in rounds)
    now = utc_text(now_utc())
    overdue = sum(item['state'] == 'OPEN' and item['due_at'] < now for item in rounds)
    denominator = len(rounds) - cancelled
    return {
        'total': len(rounds),
        'answered': answered,
        'open': opened,
        'overdue': overdue,
        'cancelled': cancelled,
        'helped': counts['HELPED'],
        'partly': counts['PARTLY'],
        'unchanged': counts['UNCHANGED'],
        'answer_rate': round(answered * 100 / denominator, 1) if denominator else None,
        'helped_rate': round(counts['HELPED'] * 100 / answered, 1) if answered else None,
        'denominator': denominator,
    }


def daily_timeline(items, days):
    today = now_utc().date()
    created = Counter(item['created_at'][:10] for item in items)
    resolved = Counter(item['resolved_at'][:10] for item in items if item['resolved_at'])
    result = []
    for offset in range(days - 1, -1, -1):
        date = (today - timedelta(days=offset)).isoformat()
        result.append({
            'date': date,
            'created': created[date],
            'resolved': resolved[date],
        })
    return result


def reason_summary(items, rounds):
    by_case = defaultdict(list)
    for item in rounds:
        by_case[item['case_id']].append(item)
    result = []
    for key, label in REASONS.items():
        selected = [item for item in items if key in json.loads(item['reasons'])]
        selected_rounds = [value for item in selected for value in by_case[item['id']]]
        result.append({
            'reason': key,
            'label': label,
            'count': len(selected),
            'active': sum(item['state'] in ACTIVE for item in selected),
            'resolved': sum(item['state'] == 'RESOLVED' for item in selected),
            'confirmed': sum(item['resolution'] == 'STUDENT_CONFIRMED' for item in selected),
            'reviews': review_metrics(selected_rounds),
        })
    return sorted(result, key=lambda item: (-item['count'], item['reason']))


def session_summary(items, rounds):
    grouped = defaultdict(list)
    for item in items:
        grouped[item['session_id']].append(item)
    by_case = defaultdict(list)
    for item in rounds:
        by_case[item['case_id']].append(item)
    result = []
    for identifier, selected in grouped.items():
        first = selected[0]
        result.append({
            'session_id': identifier,
            'course_id': first['course_id'],
            'course_name': first['course_name'],
            'class_name': first['class_name'],
            'starts_at': first['starts_at'],
            'total': len(selected),
            'active': sum(item['state'] in ACTIVE for item in selected),
            'resolved': sum(item['state'] == 'RESOLVED' for item in selected),
            'confirmed': sum(item['resolution'] == 'STUDENT_CONFIRMED' for item in selected),
            'reviews': review_metrics([value for item in selected for value in by_case[item['id']]]),
            **response_metrics(selected),
        })
    return sorted(result, key=lambda item: item['starts_at'], reverse=True)


def dashboard(filters, user, days=14):
    with connect() as connection:
        connection.execute('BEGIN')
        items = collect(connection, user, filters)
        rounds = round_data(connection, items)
        states = Counter(item['state'] for item in items)
        overdue = []
        student_waiting = []
        active_items = []
        for item in items:
            policy = repo.policy(connection, item['course_id'])
            due = due_fields(item, policy)
            if due['acknowledgement_overdue']:
                overdue.append(item)
            if due['waiting_for'] == 'STUDENT':
                student_waiting.append(item)
            if item['state'] in ACTIVE:
                active_items.append(item)
        oldest = sorted(active_items, key=lambda item: item['created_at'])[:6]
        return {
            'generated_at': utc_text(now_utc()),
            'total': len(items),
            'active': len(active_items),
            'new': states['NEW'],
            'resolved': states['RESOLVED'],
            'withdrawn': states['WITHDRAWN'],
            'waiting_student': len(student_waiting),
            'acknowledgement_overdue': len(overdue),
            'confirmed_improved': sum(item['resolution'] == 'STUDENT_CONFIRMED' for item in items),
            'staff_closed': sum(item['resolution'] == 'STAFF_CLOSED' for item in items),
            'real_count': sum(not item['is_demo'] for item in items),
            'demo_count': sum(bool(item['is_demo']) for item in items),
            'states': distribution(items, 'state', STATE_NAMES),
            'emotions': distribution(items, 'emotion', {key: value[0] for key, value in EMOTIONS.items()}),
            'impacts': distribution(items, 'impact', {'LOW': '轻微影响', 'MEDIUM': '影响学习', 'HIGH': '明显影响'}),
            'reviews': review_metrics(rounds),
            'response': response_metrics(items),
            'timeline': daily_timeline(items, days),
            'reasons': reason_summary(items, rounds),
            'sessions': session_summary(items, rounds),
            'oldest_active': [serial.case(connection, item, user) for item in oldest],
            'method': {
                'unit': '反馈单',
                'reason_multiple': True,
                'review_unit': '回访轮次',
                'helped_rate': '已答复回访中选择已改善的比例',
                'closed_cases': '老师说明后关闭与学生确认改善分别统计',
                'time_zone': 'UTC',
                'timeline_days': days,
            },
        }


def todos(filters, user):
    with connect() as connection:
        items = collect(connection, user, filters)
        buckets = {
            'new': [],
            'overdue': [],
            'reply': [],
            'review': [],
            'high_priority': [],
        }
        for item in items:
            policy = repo.policy(connection, item['course_id'])
            due = due_fields(item, policy)
            if user['role'] == 'STUDENT':
                if item['state'] == 'WAITING_STUDENT':
                    buckets['reply'].append(item)
                if item['state'] == 'WAITING_REVIEW':
                    buckets['review'].append(item)
            else:
                if item['state'] == 'NEW':
                    buckets['new'].append(item)
                if due['acknowledgement_overdue']:
                    buckets['overdue'].append(item)
                if item['state'] == 'IN_PROGRESS':
                    buckets['reply'].append(item)
                if item['priority'] == 'HIGH' and item['state'] in ACTIVE:
                    buckets['high_priority'].append(item)
                review = repo.open_review(connection, item['id'])
                if review and review['due_at'] < utc_text(now_utc()):
                    buckets['review'].append(item)
        return {
            'generated_at': utc_text(now_utc()),
            'buckets': {key: {
                'count': len(values),
                'items': [serial.case(connection, item, user) for item in sorted(values, key=lambda value: value['created_at'])[:10]],
            } for key, values in buckets.items()},
        }


def safe_cell(value):
    text = '' if value is None else str(value)
    if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
        return "'" + text
    return text


def csv_report(filters, user):
    with connect() as connection:
        connection.execute('BEGIN')
        items = collect(connection, user, filters)
        buffer = StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow([
            '反馈编号', '课程', '班级', '课堂开始时间 UTC', '情绪',
            '课堂原因', '标题', '学生说明', '影响程度', '状态',
            '提交时间 UTC', '首次确认 UTC', '首次回应 UTC', '结案时间 UTC',
            '结案依据', '回访轮数', '已改善轮数', '部分改善轮数', '未改善轮数', '数据类型',
        ])
        for item in items:
            rounds = repo.reviews(connection, item['id'])
            metrics = review_metrics(rounds)
            row = [
                f'EF-{item["id"]:06d}',
                item['course_name'],
                item['class_name'],
                item['starts_at'],
                EMOTIONS[item['emotion']][0],
                '、'.join(REASONS[value] for value in json.loads(item['reasons'])),
                item['title'],
                item['content'],
                {'LOW': '轻微', 'MEDIUM': '中等', 'HIGH': '明显'}[item['impact']],
                STATE_NAMES[item['state']],
                item['created_at'],
                item['acknowledged_at'],
                item['first_response_at'],
                item['resolved_at'],
                {'STUDENT_CONFIRMED': '学生确认改善', 'STAFF_CLOSED': '老师说明后关闭'}.get(item['resolution'], ''),
                len(rounds),
                metrics['helped'],
                metrics['partly'],
                metrics['unchanged'],
                '演示' if item['is_demo'] else '真实',
            ]
            writer.writerow([safe_cell(value) for value in row])
        return '\ufeff' + buffer.getvalue(), len(items)


def case_report(identifier, user):
    with connect() as connection:
        connection.execute('BEGIN')
        from backend.app.emotion.feedback import access
        access.case(connection, identifier, user)
        item = serial.case(connection, repo.case(connection, identifier), user, True)
        messages = repo.messages(connection, identifier, user, limit=1001)
        if len(messages) > 1000:
            raise AppError(422, 'CONVERSATION_TOO_LONG', '单次打印最多包含 1000 条交流记录')
        fields = [
            ('反馈编号', item['number']),
            ('课堂', item['course_name'] + ' · ' + item['class_name']),
            ('状态', item['state_label']),
            ('情绪', EMOTIONS[item['emotion']][0]),
            ('课堂原因', '、'.join(item['reason_labels'])),
            ('提交时间 UTC', item['created_at']),
        ]
        summary = ''.join(
            '<dt>' + escape(label) + '</dt><dd>' + escape(str(value)) + '</dd>'
            for label, value in fields
        )
        conversation = []
        for value in reversed(messages):
            public = serial.message(value, user)
            badge = ' · 教师内部备注' if public['visibility'] == 'STAFF' else ''
            body = '此消息已撤回' if public['deleted'] else public['content']
            conversation.append(
                '<article><h3>' + escape(public['actor'] + badge) + '</h3><small>' +
                escape(public['created_at']) + '</small><p>' + escape(body) + '</p></article>'
            )
        review_parts = []
        for value in item['reviews']:
            answer = value['answer']
            outcome = {'HELPED': '已改善', 'PARTLY': '部分改善', 'UNCHANGED': '仍未改善'}
            body = outcome[answer['outcome']] + '：' + answer['content'] if answer else {'OPEN': '待学生答复', 'CANCELLED': '已取消'}.get(value['state'], '已结束')
            review_parts.append(
                '<article><h3>' + escape(value['prompt']) + '</h3><p>' + escape(body) + '</p></article>'
            )
        adjustments = ''.join(
            '<li>' + escape(value['public_summary']) + '</li>'
            for value in item['adjustments']
        )
        html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>课堂情绪反馈记录</title><style>
        body{font:16px/1.8 system-ui,sans-serif;color:#2c3c33;max-width:850px;margin:40px auto;padding:24px}
        h1{font-size:28px}small{color:#667365}dl{display:grid;grid-template-columns:150px 1fr}
        dt,dd{margin:0;padding:8px;border-bottom:1px solid #dfe4d8}article{border:1px solid #dfe4d8;padding:18px;margin:16px 0}
        p{white-space:pre-wrap;overflow-wrap:anywhere}@media print{body{margin:0;padding:0}article{break-inside:avoid}}
        </style><h1>''' + escape(item['title']) + '</h1><dl>' + summary + '</dl><h2>学生说明</h2><p>' + escape(item['content']) + '</p><h2>交流记录</h2>' + ''.join(conversation) + '<h2>教学调整</h2><ul>' + adjustments + '</ul><h2>回访记录</h2>' + ''.join(review_parts) + '<small>导出时间 UTC：' + escape(utc_text(now_utc())) + '</small></html>'
        return html
