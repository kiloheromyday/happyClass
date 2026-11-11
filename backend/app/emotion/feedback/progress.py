from collections import defaultdict
from datetime import datetime

from backend.app.emotion.feedback import access
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback.reporting import duration_hours
from backend.app.emotion.feedback.workflow import STATES, STATE_NAMES, due_fields
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import rows
from backend.app.repositories.database import connect

MAX_VISITS = 500
NEXT_STEP = {
    'NEW': ('WAIT_FOR_STAFF', '等待老师确认收到'),
    'ACKNOWLEDGED': ('WAIT_FOR_STAFF', '老师已收到，等待处理'),
    'IN_PROGRESS': ('WAIT_FOR_STAFF', '老师正在处理'),
    'WAITING_STUDENT': ('REPLY', '请补充老师询问的课堂情况'),
    'WAITING_REVIEW': ('REVIEW', '请填写课堂体验回访'),
    'RESOLVED': ('DONE', '反馈已结案'),
    'WITHDRAWN': ('DONE', '反馈已撤回'),
}
STAFF_NEXT = {
    'NEW': ('WORKFLOW', '确认收到并开始处理'),
    'ACKNOWLEDGED': ('WORKFLOW', '开始处理或向学生回应'),
    'IN_PROGRESS': ('CONVERSATION', '回应学生或记录处理措施'),
    'WAITING_STUDENT': ('CONVERSATION', '等待学生补充情况'),
    'WAITING_REVIEW': ('REVIEW', '查看回访截止时间'),
    'RESOLVED': ('DONE', '反馈已结案'),
    'WITHDRAWN': ('DONE', '反馈已撤回'),
}


def visible_changes(connection, identifier):
    return rows(connection.execute(
        '''SELECT id,to_state,code,created_at
        FROM feedback_events WHERE case_id=? AND visibility='SHARED'
        AND from_state<>to_state ORDER BY id''',
        (identifier,),
    ))


def completed_visit(state, started, ended, code, generated):
    return {
        'state': state,
        'label': STATE_NAMES[state],
        'started_at': started,
        'ended_at': ended,
        'duration_hours': duration_hours(started, ended or generated),
        'entered_by': code,
        'current': ended is None,
    }


def build_visits(item, changes, stamp):
    current_state = 'NEW'
    started = item['created_at']
    entered_by = 'CREATED'
    for event in changes:
        next_state = event['to_state']
        if next_state == current_state or next_state not in STATE_NAMES:
            continue
        yield completed_visit(current_state, started, event['created_at'], entered_by, stamp)
        current_state = next_state
        started = event['created_at']
        entered_by = event['code']
    yield completed_visit(current_state, started, None, entered_by, stamp)


def totals(visits):
    counts = defaultdict(int)
    elapsed = defaultdict(float)
    for item in visits:
        state = item['state']
        counts[state] += 1
        if state not in ('RESOLVED', 'WITHDRAWN'):
            elapsed[state] += item['duration_hours']
    return [{
        'state': state,
        'label': STATE_NAMES[state],
        'visits': counts[state],
        'duration_hours': round(elapsed[state], 2),
    } for state in STATES if counts[state] and state not in ('RESOLVED', 'WITHDRAWN')]


def next_step(item, user, open_review, policy, stamp):
    mapping = NEXT_STEP if user['role'] == 'STUDENT' else STAFF_NEXT
    action, label = mapping[item['state']]
    deadline = None
    overdue = False
    if item['state'] == 'NEW':
        due = due_fields(item, policy, stamp)
        deadline = due['acknowledgement_due_at']
        overdue = due['acknowledgement_overdue']
    if open_review is not None:
        deadline = open_review['due_at']
        overdue = datetime.fromisoformat(deadline) < stamp
    return {
        'action': action,
        'label': label,
        'deadline': deadline,
        'overdue': overdue,
    }


def stamps(item, rounds, changes):
    return [
        {
            'key': 'submitted',
            'label': '学生提交反馈',
            'at': item['created_at'],
        },
        {
            'key': 'acknowledged',
            'label': '老师首次确认',
            'at': item['acknowledged_at'],
        },
        {
            'key': 'first_response',
            'label': '老师首次回应',
            'at': item['first_response_at'],
        },
        {
            'key': 'first_review',
            'label': '首次发起回访',
            'at': rounds[-1]['created_at'] if rounds else None,
        },
        {
            'key': 'last_reopen',
            'label': '最近一次重新跟进',
            'at': next((event['created_at'] for event in reversed(changes) if event['code'] == 'REOPEN'), None),
        },
        {
            'key': 'closed',
            'label': '当前结案时间',
            'at': item['resolved_at'],
        },
    ]


def read_progress(identifier, user):
    with connect() as connection:
        connection.execute('BEGIN')
        item = access.case(connection, identifier, user)
        session = access.session_for_case(connection, item)
        policy = repo.policy(connection, session['course_id'])
        rounds = repo.reviews(connection, identifier)
        pending = next((value for value in rounds if value['state'] == 'OPEN'), None)
        changes = visible_changes(connection, identifier)
        stamp = now_utc()
        generated = utc_text(stamp)
        visits = list(build_visits(item, changes, generated))
        recent = visits[-MAX_VISITS:]
        return {
            'id': identifier,
            'version': item['version'],
            'generated_at': generated,
            'current': recent[-1],
            'next': next_step(item, user, pending, policy, stamp),
            'stamps': stamps(item, rounds, changes),
            'total_visits': len(visits),
            'state_totals': totals(visits),
            'recent_visits': list(reversed(recent)),
            'review_counts': {
                'total': len(rounds),
                'open': sum(value['state'] == 'OPEN' for value in rounds),
                'answered': sum(value['state'] == 'ANSWERED' for value in rounds),
                'cancelled': sum(value['state'] == 'CANCELLED' for value in rounds),
            },
        }
