from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
import csv
from io import StringIO

from backend.app.emotion.feedback import access, cases
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback import serialization as serial
from backend.app.emotion.feedback.reporting import ACTIVE, EXPORT_LIMIT, response_metrics, safe_cell
from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.classroom import rows
from backend.app.repositories.database import connect

DUTY_STATES = {'NEW', 'ACKNOWLEDGED', 'IN_PROGRESS'}
SERVICE_LABELS = {
    'ON_TIME': '按时确认',
    'LATE': '超时确认',
    'OVERDUE': '逾期未确认',
    'OPEN': '未到期',
    'WITHDRAWN': '确认前撤回',
}
EVENT_SETS = {
    'acknowledgements': {'ACKNOWLEDGE'},
    'starts': {'START'},
    'questions': {'ASK_STUDENT'},
    'resolutions': {'RESOLVE'},
    'reopened': {'REOPEN'},
    'reviews': {'REVIEW_REQUESTED'},
    'answers': {'REVIEW_ANSWERED'},
    'reminders': {'REVIEW_REMINDER'},
}


def bounds(end_date, days):
    stamp = now_utc()
    end = end_date or stamp.date()
    if end > stamp.date():
        raise AppError(422, 'REPORT_FUTURE_DATE', '统计截止日期不能晚于今天')
    if end < stamp.date() - timedelta(days=730):
        raise AppError(422, 'REPORT_DATE_TOO_OLD', '请选择近两年内的截止日期')
    upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    middle = upper - timedelta(days=days)
    lower = middle - timedelta(days=days)
    return lower, middle, upper, stamp


def scope_cases(connection, filters, user, start, stop):
    where, parameters = repo.filtered(user, filters)
    # Fixed cohorts: a case is included by its original submission date.
    where += ' AND f.created_at>=? AND f.created_at<?'
    items = rows(connection.execute(
        repo.SELECT + where + ' ORDER BY f.created_at,f.id LIMIT ?',
        (*parameters, utc_text(start), utc_text(stop), EXPORT_LIMIT + 1),
    ))
    if len(items) > EXPORT_LIMIT:
        raise AppError(422, 'REPORT_TOO_LARGE', '统计范围内反馈过多，请选择课程或缩短日期范围')
    return items


def target_state(item, target_hours, timestamp):
    received = datetime.fromisoformat(item['created_at'])
    deadline = received + timedelta(hours=target_hours)
    acknowledged = item['acknowledged_at']
    if acknowledged:
        value = 'ON_TIME' if datetime.fromisoformat(acknowledged) <= deadline else 'LATE'
    elif item['state'] == 'WITHDRAWN':
        value = 'WITHDRAWN'
    elif timestamp > deadline:
        value = 'OVERDUE'
    else:
        value = 'OPEN'
    return value, utc_text(deadline)


def measure(items, policies, timestamp):
    service = Counter()
    for item in items:
        state, _ = target_state(item, policies[item['course_id']]['response_hours'], timestamp)
        service[state] += 1
    decided = service['ON_TIME'] + service['LATE'] + service['OVERDUE']
    return {
        'total': len(items),
        'closed': sum(item['state'] == 'RESOLVED' for item in items),
        'active': sum(item['state'] in ACTIVE for item in items),
        'waiting_staff': sum(item['state'] in DUTY_STATES for item in items),
        'waiting_student': sum(item['state'] in ('WAITING_REVIEW', 'WAITING_STUDENT') for item in items),
        'confirmed': sum(item['resolution'] == 'STUDENT_CONFIRMED' for item in items),
        'staff_closed': sum(item['resolution'] == 'STAFF_CLOSED' for item in items),
        'demo': sum(bool(item['is_demo']) for item in items),
        'service_counts': {key: service[key] for key in SERVICE_LABELS},
        'service_decided': decided,
        'on_time_rate': round(100 * service['ON_TIME'] / decided, 1) if decided else None,
        'response': response_metrics(items),
    }


def action_activity(connection, filters, user, start, end):
    where, params = repo.filtered(user, filters)
    where += " AND ev.created_at>=? AND ev.created_at<? AND ev.visibility='SHARED'"
    action_counts = Counter()
    for item in rows(connection.execute(
        'SELECT ev.code,count(*) AS total' + repo.JOIN +
        ' JOIN feedback_events ev ON ev.case_id=f.id' + where + ' GROUP BY ev.code',
        (*params, utc_text(start), utc_text(end)),
    )):
        action_counts[item['code']] = item['total']
    return {
        key: sum(action_counts[code] for code in codes)
        for key, codes in EVENT_SETS.items()
    }


def make_period(start, end, items, policies, timestamp, activity):
    return {
        'start_date': start.date().isoformat(),
        'end_date': (end.date() - timedelta(days=1)).isoformat(),
        'summary': measure(items, policies, timestamp),
        'activity': activity,
    }


def course_breakdown(current, previous, policies, timestamp):
    current_by_course = defaultdict(list)
    previous_by_course = defaultdict(list)
    for item in current:
        current_by_course[item['course_id']].append(item)
    for item in previous:
        previous_by_course[item['course_id']].append(item)
    identifiers = current_by_course.keys() | previous_by_course.keys()
    result = []
    for identifier in identifiers:
        cohort = current_by_course[identifier]
        earlier = previous_by_course[identifier]
        result.append({
            'course_id': identifier,
            'course_name': (cohort or earlier)[0]['course_name'],
            'target_hours': policies[identifier]['response_hours'],
            'current': measure(cohort, policies, timestamp),
            'previous': measure(earlier, policies, timestamp),
        })
    return sorted(result, key=lambda item: (-item['current']['total'], item['course_id']))


def overdue_list(connection, current, policies, timestamp, user):
    late = []
    for item in current:
        state, deadline = target_state(item, policies[item['course_id']]['response_hours'], timestamp)
        if state == 'OVERDUE':
            late.append((deadline, item))
    late.sort(key=lambda pair: (pair[0], pair[1]['id']))
    return {
        'total': len(late),
        'items': [
            {
                **serial.case(connection, item, user),
                'target_at': deadline,
            }
            for deadline, item in late[:15]
        ],
    }


def assemble(connection, filters, user, days, end_date):
    start, middle, end, stamp = bounds(end_date, days)
    cases.validate_filters(connection, filters, user)
    previous = scope_cases(connection, filters, user, start, middle)
    current = scope_cases(connection, filters, user, middle, end)
    identifiers = {item['course_id'] for item in current + previous}
    policies = {identifier: repo.policy(connection, identifier) for identifier in identifiers}
    return {
        'generated_at': utc_text(stamp),
        'days': days,
        'current': make_period(
            middle, end, current, policies, stamp,
            action_activity(connection, filters, user, middle, end),
        ),
        'previous': make_period(
            start, middle, previous, policies, stamp,
            action_activity(connection, filters, user, start, middle),
        ),
        'courses': course_breakdown(current, previous, policies, stamp),
        'overdue': overdue_list(connection, current, policies, stamp, user),
        'service_labels': SERVICE_LABELS,
    }


def report(filters, user, days, end_date):
    access.staff(user)
    with connect() as connection:
        connection.execute('BEGIN')
        return assemble(connection, filters, user, days, end_date)


def export(filters, user, days, end_date):
    data = report(filters, user, days, end_date)
    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow([
        '课程', '统计区间', '开始日期 UTC', '结束日期 UTC', '确认时限小时',
        '提交反馈', '目前已结案', '目前进行中', '学生确认改善',
        '按时确认', '超时确认', '逾期未确认', '未到期', '确认前撤回', '按时率',
    ])
    for course in data['courses']:
        for period, name in (('current', '本期'), ('previous', '上期')):
            row = course[period]
            start = data[period]['start_date']
            end = data[period]['end_date']
            writer.writerow([safe_cell(value) for value in [
                course['course_name'], name, start, end, course['target_hours'],
                row['total'], row['closed'], row['active'], row['confirmed'],
                *[row['service_counts'][key] for key in SERVICE_LABELS],
                str(row['on_time_rate']) + '%' if row['on_time_rate'] is not None else '',
            ]])
    return '\ufeff' + output.getvalue(), len(data['courses']) * 2
