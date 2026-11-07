import csv
import io
from datetime import datetime, timedelta

from backend.app.errors import AppError
from backend.app.models.classroom import Emotion, now_utc, utc_text
from backend.app.repositories import engagement as repo
from backend.app.repositories.classroom import audit, statistics
from backend.app.repositories.database import connect
from backend.app.services.classroom import accessible_session, session_status, session_view
from backend.app.services.reports import safe_csv_cell
from backend.app.services.inbox import notify

CATEGORIES = {'PACE': '讲得太快', 'EXAMPLE': '希望举例', 'REPEAT': '需要再讲一次', 'OTHER': '其他问题'}
EMOTIONS = dict(zip([emotion.value for emotion in Emotion], ['开心', '平静', '低落', '生气', '惊讶', '担忧', '反感']))


def question_view(item, user):
    # Explicit whitelist: identity and idempotency keys never leave this service.
    result = {key: item[key] for key in ('id', 'category', 'text', 'reply', 'status', 'version', 'created_at', 'updated_at')}
    if user['role'] == 'STUDENT':
        result['is_mine'] = item['author_id'] == user['id']
    return result


def list_questions(session_id, user, status, limit, offset):
    with connect() as connection:
        connection.execute('BEGIN')
        accessible_session(connection, session_id, user)
        items, total = repo.list_questions(connection, session_id, status, limit, offset)
        return {'items': [question_view(item, user) for item in items], 'total': total, 'summary': repo.counts(connection, session_id), 'limit': limit, 'offset': offset}


def submit_question(session_id, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        session = accessible_session(connection, session_id, user)
        previous = repo.previous(connection, user['id'], str(payload.request_id))
        if previous:
            if (previous['session_id'], previous['category'], previous['text']) != (session_id, payload.category, payload.text):
                raise AppError(409, 'REQUEST_ID_REUSED', '重复请求的内容不一致，请重新提交')
            return question_view(previous, user), False
        if session_status(session) != 'ONGOING':
            raise AppError(409, 'SESSION_NOT_ONGOING', '请在课堂进行时提交问题')
        if payload.category == 'OTHER' and not payload.text:
            raise AppError(422, 'QUESTION_EMPTY', '请写下你想问的问题')
        now = now_utc()
        count = connection.execute('SELECT count(*) FROM classroom_questions WHERE author_id=? AND created_at>=?', (user['id'], utc_text(now - timedelta(hours=1)))).fetchone()[0]
        if count >= 20:
            raise AppError(429, 'QUESTION_LIMIT', '这一小时已提交 20 个问题，请稍后再试')
        if repo.counts(connection, session_id)['total'] >= 2000:
            raise AppError(409, 'SESSION_QUESTION_LIMIT', '本节课堂的问题卡已达上限')
        item = repo.add_question(connection, session_id, user['id'], payload, utc_text(now))
        return question_view(item, user), True


def answer(session_id, question_id, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        accessible_session(connection, session_id, user)
        item = repo.question(connection, question_id)
        if not item or item['session_id'] != session_id:
            raise AppError(404, 'QUESTION_NOT_FOUND', '问题卡不存在')
        if item['version'] != payload.version:
            raise AppError(409, 'VERSION_CONFLICT', '问题卡已被更新，请刷新后再保存')
        connection.execute('UPDATE classroom_questions SET reply=?,status=?,version=version+1,updated_at=? WHERE id=?', (payload.reply, payload.status, utc_text(now_utc()), question_id))
        audit(connection, user['id'], 'QUESTION_ANSWERED', {'session_id': session_id, 'question_id': question_id, 'status': payload.status})
        notify(connection, item['author_id'], f"question:{question_id}:{payload.version + 1}", 'QUESTION', '课堂问题有了新回复', '老师更新了你的问题卡，进入课堂查看。', 'classroom', session_id)
        return question_view(repo.question(connection, question_id), user)


def distribution(grouped):
    counts = {item['emotion']: item['count'] for item in grouped}
    return [{'emotion': emotion.value, 'count': counts.get(emotion.value, 0)} for emotion in Emotion]


def recap_snapshot(connection, session_id, user):
    item = accessible_session(connection, session_id, user)
    start, end = datetime.fromisoformat(item['starts_at']), datetime.fromisoformat(item['ends_at'])
    middle = start + (end - start) / 2
    periods = []
    for label, left, right in [('前半节', start, middle), ('后半节', middle, end)]:
        emotions = distribution(repo.emotion_counts(connection, session_id, utc_text(left), utc_text(right)))
        periods.append({'label': label, 'starts_at': utc_text(left), 'ends_at': utc_text(right), 'total': sum(row['count'] for row in emotions), 'emotions': emotions})
    _, summary = statistics(connection, session_id)
    return {'session': session_view(item), 'summary': summary, 'emotions': distribution(repo.emotion_counts(connection, session_id)),
            'periods': periods, 'outside_period_count': summary['total'] - sum(period['total'] for period in periods),
            'questions': repo.counts(connection, session_id), 'reflection': repo.reflection(connection, session_id), 'generated_at': utc_text(now_utc())}


def get_recap(session_id, user):
    with connect() as connection:
        connection.execute('BEGIN')
        return recap_snapshot(connection, session_id, user)


def save_reflection(session_id, payload, user):
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        accessible_session(connection, session_id, user)
        previous = repo.reflection(connection, session_id)
        if previous['version'] != payload.version:
            raise AppError(409, 'VERSION_CONFLICT', '小结已被更新，请刷新后再保存')
        timestamp = utc_text(now_utc())
        connection.execute('''INSERT INTO classroom_reflections(session_id,reflection,version,updated_at) VALUES (?,?,1,?)
            ON CONFLICT(session_id) DO UPDATE SET reflection=excluded.reflection,version=classroom_reflections.version+1,updated_at=excluded.updated_at''', (session_id, payload.reflection, timestamp))
        audit(connection, user['id'], 'REFLECTION_SAVED', {'session_id': session_id})
        return repo.reflection(connection, session_id)


def export_recap(session_id, user):
    with connect() as connection:
        connection.execute('BEGIN')
        data = recap_snapshot(connection, session_id, user)
        questions, _ = repo.list_questions(connection, session_id, limit=2000)
        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer)
        def row(*values):
            writer.writerow([safe_csv_cell(value) for value in values])
        session = data['session']
        row('课堂小结', session['course_name'], session['class_name'])
        row('课堂状态', {'ONGOING': '进行中（阶段小结）', 'UPCOMING': '未开始', 'ENDED': '已结束'}[session['status']])
        row('开始时间（UTC）', session['starts_at'], '结束时间（UTC）', session['ends_at'])
        row('生成时间（UTC）', data['generated_at'])
        row('反馈记录', data['summary']['total'], '手动', data['summary']['manual_count'], 'AI', data['summary']['ai_count'])
        row('反馈学生', data['summary']['responding_students'], '名单人数', session['scheduled_count'])
        row('分布按反馈次数统计；时间分段不代表教学效果或心理诊断')
        row('时段', *EMOTIONS.values(), '合计')
        for period in [{'label': '全节', 'emotions': data['emotions'], 'total': data['summary']['total']}, *data['periods']]:
            row(period['label'], *(item['count'] for item in period['emotions']), period['total'])
        row('课堂时段以外的记录', data['outside_period_count'])
        row('问题卡', data['questions']['total'], '待回应', data['questions']['open'], '已解决', data['questions']['resolved'])
        for category in data['questions']['categories']:
            row(CATEGORIES[category['category']], category['count'])
        row('类型', '问题内容', '教师回应', '状态', '提问时间（UTC）')
        for item in questions:
            row(CATEGORIES[item['category']], item['text'], item['reply'], '已解决' if item['status'] == 'RESOLVED' else '待回应', item['created_at'])
        row('教学反思', data['reflection']['reflection'])
        return ('\ufeff' + buffer.getvalue()).encode('utf-8')
