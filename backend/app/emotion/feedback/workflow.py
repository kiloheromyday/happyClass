from datetime import datetime, timedelta

from backend.app.errors import AppError
from backend.app.models.classroom import now_utc, utc_text

STATES = (
    'NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'WAITING_STUDENT',
    'WAITING_REVIEW', 'RESOLVED', 'WITHDRAWN',
)
STATE_NAMES = {
    'NEW': '待查看',
    'ACKNOWLEDGED': '已收到',
    'IN_PROGRESS': '处理中',
    'WAITING_STUDENT': '待学生补充',
    'WAITING_REVIEW': '待回访',
    'RESOLVED': '已结案',
    'WITHDRAWN': '学生已撤回',
}
REASONS = {
    'PACE_FAST': '课堂节奏偏快',
    'PACE_SLOW': '希望加快进度',
    'NEED_EXAMPLE': '希望补充例子',
    'UNCLEAR': '概念还没理解',
    'EXERCISE_HARD': '练习难以完成',
    'CONTENT_DENSE': '内容较密集',
    'AUDIO_VISUAL': '听不清或看不清',
    'TIRED': '需要短暂休息',
    'GROUP_WORK': '小组协作问题',
    'POSITIVE': '学习体验不错',
    'OTHER': '其他课堂原因',
}
EVENT_NAMES = {
    'CREATED': '学生提交了反馈',
    'EDITED': '学生补充了反馈内容',
    'ACKNOWLEDGE': '老师确认收到',
    'START': '老师开始处理',
    'ASK_STUDENT': '老师请求补充说明',
    'RESOLVE': '老师说明后结案',
    'REOPEN': '学生重新发起跟进',
    'WITHDRAW': '学生撤回了反馈',
    'MESSAGE': '新增一条交流记录',
    'MESSAGE_EDITED': '交流记录已修订',
    'MESSAGE_REMOVED': '交流记录已撤回',
    'REVIEW_REQUESTED': '老师发起了回访',
    'REVIEW_ANSWERED': '学生提交了回访',
    'REVIEW_CANCELLED': '回访已取消',
    'REVIEW_REMINDER': '老师发送了回访提醒',
    'MANAGED': '处理优先级或标签已更新',
    'ADJUSTMENT_LINKED': '老师关联了教学调整',
    'ADJUSTMENT_UNLINKED': '教学调整关联已移除',
    'GROUP_REPLY': '老师回应了同类反馈',
}
STAFF_TRANSITIONS = {
    'ACKNOWLEDGE': ({'NEW'}, 'ACKNOWLEDGED'),
    'START': ({'NEW', 'ACKNOWLEDGED', 'WAITING_STUDENT'}, 'IN_PROGRESS'),
    'ASK_STUDENT': ({'NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'WAITING_STUDENT'}, 'WAITING_STUDENT'),
    'RESOLVE': ({'NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'WAITING_STUDENT', 'WAITING_REVIEW'}, 'RESOLVED'),
}
DEFAULT_POLICY = {
    'response_hours': 24,
    'review_days': 3,
    'submit_grace_hours': 72,
    'daily_case_limit': 5,
    'reopen_days': 7,
    'version': 0,
    'updated_at': None,
}


def require_version(item, value):
    if item['version'] != value:
        raise AppError(409, 'VERSION_CONFLICT', '内容已被更新，请刷新后核对；当前草稿不会自动丢弃')


def next_state(item, action, user, policy, content):
    state = item['state']
    if user['role'] == 'STUDENT':
        if action == 'WITHDRAW' and state not in ('RESOLVED', 'WITHDRAWN'):
            return 'WITHDRAWN'
        if action == 'REOPEN' and state == 'RESOLVED':
            deadline = datetime.fromisoformat(item['resolved_at']) + timedelta(days=policy['reopen_days'])
            if now_utc() > deadline:
                raise AppError(409, 'REOPEN_EXPIRED', '重新跟进时限已过，可在开放课堂提交新的反馈')
            if len(content) < 2:
                raise AppError(422, 'REASON_REQUIRED', '请说明为什么仍需要跟进')
            return 'IN_PROGRESS'
        raise AppError(409, 'INVALID_TRANSITION', '当前状态不能执行这项学生操作')
    transition = STAFF_TRANSITIONS.get(action)
    if transition is None or state not in transition[0]:
        raise AppError(409, 'INVALID_TRANSITION', '当前状态不能执行这项处理操作')
    if action in ('ASK_STUDENT', 'RESOLVE') and len(content) < 2:
        raise AppError(422, 'REASON_REQUIRED', '请填写给学生的处理说明')
    return transition[1]


def capabilities(item, user, policy, has_open_review=False):
    state = item['state']
    if user['role'] == 'STUDENT':
        reopen = False
        if state == 'RESOLVED' and item['resolved_at']:
            reopen = now_utc() <= datetime.fromisoformat(item['resolved_at']) + timedelta(days=policy['reopen_days'])
        return {
            'edit': state == 'NEW',
            'reply': state not in ('RESOLVED', 'WITHDRAWN'),
            'withdraw': state not in ('RESOLVED', 'WITHDRAWN'),
            'reopen': reopen,
            'review': has_open_review and state == 'WAITING_REVIEW',
            'staff': False,
        }
    return {
        'acknowledge': state == 'NEW',
        'start': state in ('NEW', 'ACKNOWLEDGED', 'WAITING_STUDENT'),
        'ask': state in ('NEW', 'ACKNOWLEDGED', 'IN_PROGRESS', 'WAITING_STUDENT'),
        'resolve': state not in ('RESOLVED', 'WITHDRAWN'),
        'reply': state not in ('RESOLVED', 'WITHDRAWN'),
        'request_review': state in ('ACKNOWLEDGED', 'IN_PROGRESS', 'WAITING_STUDENT') and not has_open_review,
        'manage': state != 'WITHDRAWN',
        'staff': True,
    }


def due_fields(item, policy, timestamp=None):
    timestamp = timestamp or now_utc()
    deadline = datetime.fromisoformat(item['created_at']) + timedelta(hours=policy['response_hours'])
    waiting = item['state'] == 'NEW' and not item['acknowledged_at']
    elapsed = (timestamp - datetime.fromisoformat(item['created_at'])).total_seconds()
    return {
        'acknowledgement_due_at': utc_text(deadline),
        'acknowledgement_overdue': waiting and timestamp > deadline,
        'age_hours': round(max(0, elapsed / 3600), 2),
        'waiting_for': 'STUDENT' if item['state'] in ('WAITING_STUDENT', 'WAITING_REVIEW') else 'NONE' if item['state'] in ('RESOLVED', 'WITHDRAWN') else 'STAFF',
    }
