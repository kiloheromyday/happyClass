from collections import Counter
import csv
from datetime import datetime
from io import StringIO
import math

from backend.app.emotion.bookmarks import repository as repo, service
from backend.app.emotion.bookmarks.models import REASONS
from backend.app.models.classroom import now_utc
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session

MAX_SEGMENTS = 360


def covers(item, start, end):
    return item['start_minute'] < end and item['end_minute'] > start


def bin_counts(connection, session_id, width, visible):
    reason_bins = {}
    for row in repo.grouped_counts(connection, session_id, width, end=visible):
        reason_bins.setdefault(row['bucket'], {})[row['reason']] = row['count']
    student_bins = repo.grouped_students(connection, session_id, width, end=visible)
    return reason_bins, student_bins


def material_interval(item):
    return {
        'id': item['id'],
        'title': item['title'],
        'start_minute': item['start_minute'],
        'end_minute': item['end_minute'],
    }


def timeline(connection, session, width=5, now=None):
    now = now or now_utc()
    bounds = service.window(session, now)
    total_minutes = bounds['duration_minutes']
    effective = max(width, math.ceil(total_minutes / MAX_SEGMENTS))
    reason_bins, student_bins = bin_counts(connection, session['id'], effective, total_minutes)
    materials = repo.materials(connection, session['id'])
    published = [item for item in materials if item['state'] == 'PUBLISHED']
    drafts = [item for item in materials if item['state'] == 'DRAFT']
    segments = []
    aggregate_reasons = Counter()
    for index, start in enumerate(range(0, total_minutes, effective)):
        end = min(total_minutes, start + effective)
        reason_counts = reason_bins.get(index, {})
        aggregate_reasons.update(reason_counts)
        count = sum(reason_counts.values())
        resources = [material_interval(item) for item in published if covers(item, start, end)]
        segments.append({
            'start_minute': start,
            'end_minute': end,
            'count': count,
            'student_count': student_bins.get(index, 0),
            'reasons': [
                {'value': reason, 'label': REASONS[reason], 'count': amount}
                for reason, amount in sorted(reason_counts.items(), key=lambda entry: (-entry[1], entry[0]))
            ],
            'materials': resources,
            'draft_count': sum(covers(item, start, end) for item in drafts),
            'started': start < bounds['elapsed_minutes'],
        })
    students = connection.execute(
        'SELECT count(DISTINCT student_id) FROM classroom_bookmarks WHERE session_id=? AND minute<?',
        (session['id'], total_minutes),
    ).fetchone()[0]
    bookmarked = [item for item in segments if item['count']]
    return {
        'session': service.session_public(session, now),
        'segments': segments,
        'bucket_minutes': effective,
        'requested_bucket_minutes': width,
        'summary': {
            'bookmarks': sum(item['count'] for item in segments),
            'students': students,
            'with_materials': sum(bool(item['materials']) for item in bookmarked),
            'with_bookmarks': len(bookmarked),
            'published': len(published),
            'drafts': len(drafts),
            'reasons': [{'value': key, 'label': REASONS[key], 'count': count}
                        for key, count in aggregate_reasons.most_common()],
        },
    }


def get_timeline(session_id, width, user):
    service.require_teacher(user)
    with connect() as connection:
        connection.execute('BEGIN')
        session = accessible_session(connection, session_id, user)
        return timeline(connection, session, width)


def export_timeline(session_id, width, user):
    data = get_timeline(session_id, width, user)
    buffer = StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow(['开课后开始分钟', '结束分钟（不含）', '书签条数', '学生人数', '已发布资料数', *REASONS.values()])
    for item in data['segments']:
        if not item['count'] and not item['materials']:
            continue
        counts = {reason['value']: reason['count'] for reason in item['reasons']}
        writer.writerow([
            item['start_minute'], item['end_minute'], item['count'], item['student_count'],
            len(item['materials']), *[counts.get(key, 0) for key in REASONS],
        ])
    return '\ufeff' + buffer.getvalue()


def replay_overlay(connection, session, frames, width, data_scope):
    demo = bool(session.get('is_demo'))
    if (data_scope == 'REAL' and demo) or (data_scope == 'DEMO' and not demo):
        return
    start = datetime.fromisoformat(session['starts_at'])
    bounds = service.window(session)
    visible = bounds['duration_minutes']
    reason_bins, _ = bin_counts(connection, session['id'], width, visible)
    resources = repo.materials(connection, session['id'], state='PUBLISHED')
    for frame in frames:
        start_minute = frame['index'] * width
        end_minute = math.ceil((datetime.fromisoformat(frame['to_time']) - start).total_seconds() / 60)
        if end_minute <= start_minute:
            continue
        frame['bookmark_count'] = sum(reason_bins.get(frame['index'], {}).values())
        frame['study_materials'] = [
            material_interval(item) for item in resources if covers(item, start_minute, end_minute)
        ]
