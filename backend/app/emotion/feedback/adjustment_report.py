from collections import Counter, defaultdict
import csv
from io import StringIO

from backend.app.emotion.feedback import access, cases
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback import serialization as serial
from backend.app.emotion.feedback.reporting import ACTIVE, safe_cell
from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import one, rows
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session

ADJUSTMENT_JOIN = ''' FROM feedback_adjustments l
JOIN emotion_insight_entries e ON e.id=l.adjustment_id
JOIN feedback_cases f ON f.id=l.case_id
JOIN class_sessions s ON s.id=f.session_id
JOIN courses c ON c.id=s.course_id'''
MAX_LINKS = 10000
OUTCOMES = {
    'HELPED': '已改善',
    'PARTLY': '部分改善',
    'UNCHANGED': '仍未改善',
}
FOLLOWUP_STATES = {
    'ANSWERED': '已收到调整后答复',
    'WAITING': '等待调整后答复',
    'UNREQUESTED': '尚无调整后的有效回访',
}


def load_links(connection, filters, user, identifier=None):
    cases.validate_filters(connection, filters, user)
    where, params = repo.filtered(user, filters)
    if identifier is not None:
        where += ' AND e.id=?'
        params.append(identifier)
    links = rows(connection.execute(
        '''SELECT l.case_id,l.created_at AS linked_at,l.public_summary,
        e.id AS adjustment_id,e.title,e.start_minute,e.end_minute,e.status,
        s.id AS session_id,s.class_name,s.starts_at,c.id AS course_id,c.name AS course_name,
        f.state,f.resolution,f.emotion,f.is_demo''' + ADJUSTMENT_JOIN + where +
        ' ORDER BY l.created_at DESC,l.case_id DESC LIMIT ?',
        (*params, MAX_LINKS + 1),
    ))
    if len(links) > MAX_LINKS:
        raise AppError(422, 'REPORT_TOO_LARGE', '教学调整关联较多，请缩小课程或课堂范围')
    return links


def related_reviews(connection, links):
    ids = sorted({item['case_id'] for item in links})
    result = defaultdict(list)
    for index in range(0, len(ids), 400):
        batch = ids[index:index + 400]
        markers = ','.join('?' for _ in batch)
        for item in rows(connection.execute(
            '''SELECT r.id,r.case_id,r.created_at,r.state,r.due_at,
            a.outcome,a.emotion,a.created_at AS answered_at
            FROM feedback_reviews r
            LEFT JOIN feedback_review_answers a ON a.review_id=r.id
            WHERE r.case_id IN (''' + markers + ') ORDER BY r.created_at DESC,r.id DESC',
            batch,
        )):
            result[item['case_id']].append(item)
    return result


def latest_review(link, reviews):
    return next(
        (item for item in reviews if item['created_at'] >= link['linked_at'] and item['state'] != 'CANCELLED'),
        None,
    )


def evidence(link, reviews):
    review = latest_review(link, reviews)
    state = 'UNREQUESTED'
    if review:
        state = 'ANSWERED' if review['outcome'] else 'WAITING'
    return {
        'linked_at': link['linked_at'],
        'public_summary': link['public_summary'],
        'status': state,
        'label': FOLLOWUP_STATES[state],
        'review_id': review['id'] if review else None,
        'due_at': review['due_at'] if review else None,
        'outcome': review['outcome'] if review else None,
        'answered_at': review['answered_at'] if review else None,
        'original_emotion': link['emotion'],
        'review_emotion': review['emotion'] if review else None,
    }


def summarize(links, reviews):
    first = links[0]
    followup = Counter()
    outcomes = Counter()
    for link in links:
        item = evidence(link, reviews[link['case_id']])
        followup[item['status']] += 1
        if item['outcome']:
            outcomes[item['outcome']] += 1
    answered = followup['ANSWERED']
    return {
        'id': first['adjustment_id'],
        'title': first['title'],
        'adjustment_status': first['status'],
        'start_minute': first['start_minute'],
        'end_minute': first['end_minute'],
        'session_id': first['session_id'],
        'course_id': first['course_id'],
        'course_name': first['course_name'],
        'class_name': first['class_name'],
        'starts_at': first['starts_at'],
        'latest_linked_at': first['linked_at'],
        'linked_count': len(links),
        'active_count': sum(item['state'] in ACTIVE for item in links),
        'student_confirmed_count': sum(item['resolution'] == 'STUDENT_CONFIRMED' for item in links),
        'demo_count': sum(bool(item['is_demo']) for item in links),
        'answered': answered,
        'waiting': followup['WAITING'],
        'unrequested': followup['UNREQUESTED'],
        'helped': outcomes['HELPED'],
        'partly': outcomes['PARTLY'],
        'unchanged': outcomes['UNCHANGED'],
        'helped_rate': round(100 * outcomes['HELPED'] / answered, 1) if answered else None,
    }


def aggregate(connection, filters, user):
    links = load_links(connection, filters, user)
    reviews = related_reviews(connection, links)
    buckets = defaultdict(list)
    for item in links:
        buckets[item['adjustment_id']].append(item)
    return [summarize(value, reviews) for value in buckets.values()]


def order_groups(items, sort):
    if sort == 'WAITING':
        return sorted(items, key=lambda item: (-item['waiting'], -item['unrequested'], -item['id']))
    if sort == 'LINKS':
        return sorted(items, key=lambda item: (-item['linked_count'], -item['id']))
    return sorted(items, key=lambda item: (item['latest_linked_at'], item['id']), reverse=True)


def listing(filters, user, offset, limit, sort):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN')
        groups = order_groups(aggregate(connection, filters, user), sort)
        return {
            'items': groups[offset:offset + limit],
            'total': len(groups),
            'offset': offset,
            'limit': limit,
            'has_more': offset + limit < len(groups),
            'generated_at': utc_text(now_utc()),
            'totals': {
                'adjustments': len(groups),
                'links': sum(item['linked_count'] for item in groups),
                'answered_links': sum(item['answered'] for item in groups),
                'waiting_links': sum(item['waiting'] for item in groups),
                'unrequested_links': sum(item['unrequested'] for item in groups),
            },
        }


def detail(identifier, filters, user, state, offset, limit):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN')
        entry = one(connection.execute(
            "SELECT id,session_id FROM emotion_insight_entries WHERE id=? AND kind='ACTION'",
            (identifier,),
        ))
        if not entry:
            raise AppError(404, 'ADJUSTMENT_NOT_FOUND', '教学调整不存在')
        accessible_session(connection, entry['session_id'], user)
        links = load_links(connection, filters, user, identifier)
        if not links:
            raise AppError(404, 'ADJUSTMENT_LINKS_NOT_FOUND', '所选范围内没有相关反馈')
        reviews = related_reviews(connection, links)
        entries = [
            (item, evidence(item, reviews[item['case_id']]))
            for item in links
        ]
        if state != 'ALL':
            entries = [(item, followup) for item, followup in entries if followup['status'] == state]
        selected = entries[offset:offset + limit]
        return {
            'adjustment': summarize(links, reviews),
            'items': [{
                'case': serial.case(connection, repo.case(connection, item['case_id']), user),
                'followup': followup,
            } for item, followup in selected],
            'total': len(entries),
            'offset': offset,
            'limit': limit,
            'has_more': offset + len(selected) < len(entries),
        }


def export(filters, user, sort):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN')
        items = order_groups(aggregate(connection, filters, user), sort)
        output = StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow([
            '课程', '班级', '课堂开始时间 UTC', '教学调整', '调整状态',
            '课堂起始分钟', '课堂结束分钟', '关联反馈', '收到调整后答复',
            '等待调整后答复', '尚无有效回访', '已改善', '部分改善', '仍未改善',
            '其中演示关联',
        ])
        for item in items:
            writer.writerow([safe_cell(value) for value in (
                item['course_name'], item['class_name'], item['starts_at'], item['title'],
                {'PLANNED': '计划中', 'DONE': '已完成', 'CANCELLED': '已取消'}.get(item['adjustment_status'], ''),
                item['start_minute'], item['end_minute'], item['linked_count'],
                item['answered'], item['waiting'], item['unrequested'],
                item['helped'], item['partly'], item['unchanged'], item['demo_count'],
            )])
        return '\ufeff' + output.getvalue(), len(items)
