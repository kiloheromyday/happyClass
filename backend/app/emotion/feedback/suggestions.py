from collections import Counter, defaultdict
from itertools import groupby
import json

from backend.app.emotion.feedback import access, cases
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback import serialization as serial
from backend.app.emotion.feedback.catalog import EMOTIONS
from backend.app.emotion.feedback.workflow import REASONS, STATES, STATE_NAMES
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import rows
from backend.app.repositories.database import connect

MAX_SUGGESTIONS = 30
MAX_CANDIDATES = 10000
TERMINAL = {'RESOLVED', 'WITHDRAWN'}


def pool(connection, user, filters, include_grouped):
    cases.validate_filters(connection, filters, user)
    where, parameters = repo.filtered(user, filters)
    where += " AND f.state NOT IN ('RESOLVED','WITHDRAWN')"
    if not include_grouped:
        where += ''' AND NOT EXISTS (
            SELECT 1 FROM feedback_group_members gm
            JOIN feedback_groups g ON g.id=gm.group_id
            WHERE gm.case_id=f.id AND g.archived=0
        )'''
    total = connection.execute(
        'SELECT count(*)' + repo.JOIN + where,
        parameters,
    ).fetchone()[0]
    items = rows(connection.execute(
        repo.SELECT + where + ' ORDER BY f.created_at DESC,f.id DESC LIMIT ?',
        (*parameters, MAX_CANDIDATES),
    ))
    return items, total


def partition(items, topic_window):
    if topic_window is None:
        return [(None, items)]
    known = sorted(
        (item for item in items if item['topic_minute'] is not None),
        key=lambda item: item['topic_minute'],
    )
    buckets = [
        (minute, list(values))
        for minute, values in groupby(
            known,
            key=lambda item: item['topic_minute'] // topic_window * topic_window,
        )
    ]
    unknown = [item for item in items if item['topic_minute'] is None]
    if unknown:
        buckets.append((None, unknown))
    return buckets


def shared_reasons(items, topic_window):
    by_reason = defaultdict(list)
    for item in items:
        for reason in json.loads(item['reasons']):
            if reason != 'OTHER':
                key = (item['session_id'], bool(item['is_demo']), reason)
                by_reason[key].append(item)
    for (session_id, demo, reason), candidates in by_reason.items():
        for minute, selected in partition(candidates, topic_window):
            yield {
                'session_id': session_id,
                'demo': demo,
                'reason': reason,
                'minute': minute,
                'items': selected,
            }


def score(candidate):
    items = candidate['items']
    return (
        -len(items),
        -sum(item['priority'] == 'HIGH' for item in items),
        -max(item['id'] for item in items),
        candidate['reason'],
    )


def choose(candidates, threshold):
    accepted = []
    seen_members = set()
    for candidate in sorted(candidates, key=score):
        identifiers = frozenset(item['id'] for item in candidate['items'])
        if len(identifiers) < threshold or identifiers in seen_members:
            continue
        seen_members.add(identifiers)
        accepted.append(candidate)
    return accepted


def view(connection, user, candidate, topic_window):
    items = candidate['items']
    first = items[0]
    reason = candidate['reason']
    minute = candidate['minute']
    ordered = sorted(items, key=lambda item: (item['created_at'], item['id']))
    states = Counter(item['state'] for item in items)
    emotions = Counter(item['emotion'] for item in items)
    visible = ordered[:50]
    return {
        'key': ':'.join(map(str, (first['session_id'], candidate['demo'], reason, minute))),
        'session_id': first['session_id'],
        'course_id': first['course_id'],
        'course_name': first['course_name'],
        'class_name': first['class_name'],
        'starts_at': first['starts_at'],
        'is_demo': candidate['demo'],
        'reason': reason,
        'reason_label': REASONS[reason],
        'minute_from': minute,
        'minute_to': minute + topic_window if minute is not None else None,
        'without_minute': minute is None and topic_window is not None,
        'count': len(items),
        'included_count': len(visible),
        'high_priority': sum(item['priority'] == 'HIGH' for item in items),
        'states': [{
            'value': key,
            'label': STATE_NAMES[key],
            'count': states[key],
        } for key in STATES if states[key]],
        'emotions': [{
            'value': key,
            'label': EMOTIONS[key][0],
            'count': count,
        } for key, count in sorted(emotions.items(), key=lambda pair: (-pair[1], pair[0]))],
        'members': [serial.case(connection, item, user) for item in visible],
    }


def suggest(filters, user, threshold=2, topic_window=None, include_grouped=False):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN')
        items, total = pool(connection, user, filters, include_grouped)
        candidates = choose(shared_reasons(items, topic_window), threshold)
        return {
            'generated_at': utc_text(now_utc()),
            'candidate_count': total,
            'scanned_count': len(items),
            'suggestion_count': len(candidates),
            'items': [
                view(connection, user, item, topic_window)
                for item in candidates[:MAX_SUGGESTIONS]
            ],
            'settings': {
                'threshold': threshold,
                'topic_window': topic_window,
                'include_grouped': include_grouped,
            },
        }
