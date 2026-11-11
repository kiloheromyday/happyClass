from datetime import datetime, timedelta
import json

from backend.app.models.classroom import now_utc
from backend.app.repositories.classroom import one
from backend.app.emotion.feedback import repository as repo
from backend.app.emotion.feedback.workflow import (
    capabilities,
    due_fields,
    EVENT_NAMES,
    REASONS,
    STATE_NAMES,
)


def message(item, user):
    own = item['actor_id'] == user['id']
    deleted = bool(item['deleted'])
    recent = now_utc() <= datetime.fromisoformat(item['created_at']) + timedelta(minutes=10)
    return {
        'id': item['id'],
        'case_id': item['case_id'],
        'actor': '我' if own else '学生' if item['actor_role'] == 'STUDENT' else '老师',
        'actor_role': item['actor_role'],
        'own': own,
        'visibility': item['visibility'],
        'content': '' if deleted else item['content'],
        'deleted': deleted,
        'version': item['version'],
        'created_at': item['created_at'],
        'updated_at': item['updated_at'],
        'can_edit': own and recent and not deleted,
    }


def event(item, user):
    return {
        'id': item['id'],
        'code': item['code'],
        'title': EVENT_NAMES.get(item['code'], '反馈处理记录'),
        'actor': '我' if item['actor_id'] == user['id'] else '学生' if item['actor_role'] == 'STUDENT' else '老师',
        'from_state': item['from_state'],
        'to_state': item['to_state'],
        'detail': item['detail'],
        'visibility': item['visibility'],
        'created_at': item['created_at'],
    }


def review(item, user):
    answered = item.get('outcome') is not None
    overdue = item['state'] == 'OPEN' and now_utc() > datetime.fromisoformat(item['due_at'])
    return {
        'id': item['id'],
        'case_id': item['case_id'],
        'prompt': item['prompt'],
        'state': item['state'],
        'version': item['version'],
        'due_at': item['due_at'],
        'created_at': item['created_at'],
        'closed_at': item['closed_at'],
        'overdue': overdue,
        'can_answer': user['role'] == 'STUDENT' and item['state'] == 'OPEN',
        'can_cancel': user['role'] != 'STUDENT' and item['state'] == 'OPEN',
        'answer': {
            'outcome': item['outcome'],
            'emotion': item['answer_emotion'],
            'content': item['answer_content'],
            'created_at': item['answered_at'],
        } if answered else None,
    }


def case(connection, item, user, detailed=False):
    policy = repo.policy(connection, item['course_id'])
    rounds = repo.reviews(connection, item['id'])
    open_round = next((value for value in rounds if value['state'] == 'OPEN'), None)
    reasons = json.loads(item['reasons'])
    result = {
        'id': item['id'],
        'number': f'EF-{item["id"]:06d}',
        'session_id': item['session_id'],
        'course_id': item['course_id'],
        'course_name': item['course_name'],
        'class_name': item['class_name'],
        'classroom': item['classroom'],
        'starts_at': item['starts_at'],
        'ends_at': item['ends_at'],
        'title': item['title'],
        'content': item['content'],
        'emotion': item['emotion'],
        'reasons': reasons,
        'reason_labels': [REASONS[key] for key in reasons],
        'impact': item['impact'],
        'topic_minute': item['topic_minute'],
        'state': item['state'],
        'state_label': STATE_NAMES[item['state']],
        'version': item['version'],
        'is_demo': bool(item['is_demo']),
        'created_at': item['created_at'],
        'updated_at': item['updated_at'],
        'acknowledged_at': item['acknowledged_at'],
        'first_response_at': item['first_response_at'],
        'resolved_at': item['resolved_at'],
        'resolution': item['resolution'],
        'review_count': len(rounds),
        'open_review': review(open_round, user) if open_round else None,
        'capabilities': capabilities(item, user, policy, bool(open_round)),
        **due_fields(item, policy),
    }
    if user['role'] != 'STUDENT':
        result.update({
            'priority': item['priority'],
            'tags': json.loads(item['tags']),
            'watched': bool(connection.execute(
                'SELECT 1 FROM feedback_watches WHERE user_id=? AND case_id=?',
                (user['id'], item['id']),
            ).fetchone()),
        })
    if detailed:
        result['policy'] = policy
        result['reviews'] = [review(value, user) for value in rounds]
        result['adjustments'] = []
        for value in repo.visible_adjustments(connection, item['id']):
            public = {
                'adjustment_id': value['adjustment_id'],
                'public_summary': value['public_summary'],
                'created_at': value['created_at'],
            }
            if user['role'] != 'STUDENT':
                public.update({
                    'title': value['title'],
                    'start_minute': value['start_minute'],
                    'status': value['status'],
                })
            result['adjustments'].append(public)
        result['groups'] = []
        if user['role'] == 'STUDENT':
            result['linked_emotion_record'] = linked_emotion_record(connection, item, user)
        if user['role'] != 'STUDENT':
            for value in connection.execute(
                '''SELECT g.id,g.title,g.archived FROM feedback_groups g
                JOIN feedback_group_members m ON m.group_id=g.id WHERE m.case_id=?''',
                (item['id'],),
            ):
                result['groups'].append({
                    'id': value[0],
                    'title': value[1],
                    'archived': bool(value[2]),
                })
    return result


def linked_emotion_record(connection, item, user):
    identifier = item['linked_record_id']
    if identifier is None:
        return None
    return one(connection.execute(
        '''SELECT id,emotion,recorded_at
        FROM emoji_records
        WHERE id=? AND user_id=? AND session_id=?''',
        (identifier, user['id'], item['session_id']),
    ))


def group(connection, item, user, detailed=False):
    result = {
        key: item[key]
        for key in (
            'id', 'session_id', 'title', 'description',
            'version', 'created_at', 'updated_at',
        )
    }
    result['archived'] = bool(item['archived'])
    if 'course_name' in item:
        result['course_name'] = item['course_name']
        result['class_name'] = item['class_name']
    members = repo.group_members(connection, item['id'])
    result['member_count'] = len(members)
    result['active_count'] = sum(value['state'] not in ('RESOLVED', 'WITHDRAWN') for value in members)
    if detailed:
        result['members'] = [case(connection, value, user) for value in members]
    return result


def template(item):
    return {
        'id': item['id'],
        'title': item['title'],
        'content': item['content'],
        'reason': item['reason'],
        'version': item['version'],
        'archived': bool(item['archived']),
        'uses': item['uses'],
        'created_at': item['created_at'],
        'updated_at': item['updated_at'],
    }


def saved_view(item):
    return {
        'id': item['id'],
        'title': item['title'],
        'filters': json.loads(item['filters']),
        'version': item['version'],
        'created_at': item['created_at'],
        'updated_at': item['updated_at'],
    }
