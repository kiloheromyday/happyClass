from backend.app.errors import AppError
from backend.app.repositories.classroom import get_session, one
from backend.app.services.classroom import accessible_session


def staff(user):
    if user['role'] not in ('TEACHER', 'ADMIN'):
        raise AppError(403, 'FORBIDDEN', '此操作仅供任课教师和管理员使用')


def student(user):
    if user['role'] != 'STUDENT':
        raise AppError(403, 'FORBIDDEN', '请使用学生账号提交情绪反馈')


def case(connection, identifier, user):
    item = one(connection.execute('SELECT * FROM feedback_cases WHERE id=?', (identifier,)))
    if item is None:
        raise AppError(404, 'FEEDBACK_NOT_FOUND', '反馈单不存在或无法访问')
    if user['role'] == 'STUDENT':
        if item['author_id'] != user['id']:
            raise AppError(404, 'FEEDBACK_NOT_FOUND', '反馈单不存在或无法访问')
    else:
        staff(user)
        accessible_session(connection, item['session_id'], user)
    return item


def course(connection, identifier, user):
    cursor = connection.execute('SELECT * FROM courses WHERE id=?', (identifier,))
    values = cursor.fetchone()
    if values is None:
        raise AppError(404, 'COURSE_NOT_FOUND', '课程不存在')
    item = dict(zip((column[0] for column in cursor.description), values))
    if user['role'] == 'TEACHER' and item['teacher_id'] != user['id']:
        raise AppError(403, 'FORBIDDEN', '只能管理自己所授课程')
    if user['role'] == 'STUDENT':
        enrolled = connection.execute(
            'SELECT 1 FROM course_enrollments WHERE course_id=? AND user_id=?',
            (identifier, user['id']),
        ).fetchone()
        historical = connection.execute(
            '''SELECT 1 FROM feedback_cases f JOIN class_sessions s ON s.id=f.session_id
            WHERE s.course_id=? AND f.author_id=?''',
            (identifier, user['id']),
        ).fetchone()
        if not enrolled and not historical:
            raise AppError(404, 'COURSE_NOT_FOUND', '课程不存在或尚未加入')
    return item


def group(connection, identifier, user):
    staff(user)
    item = one(connection.execute('SELECT * FROM feedback_groups WHERE id=?', (identifier,)))
    if item is None:
        raise AppError(404, 'GROUP_NOT_FOUND', '集中处理组不存在')
    accessible_session(connection, item['session_id'], user)
    return item


def review(connection, identifier, user):
    item = one(connection.execute('SELECT * FROM feedback_reviews WHERE id=?', (identifier,)))
    if item is None:
        raise AppError(404, 'REVIEW_NOT_FOUND', '回访不存在')
    parent = case(connection, item['case_id'], user)
    return item, parent


def owned(connection, table, identifier, user):
    if table not in ('feedback_templates', 'feedback_saved_views'):
        raise ValueError('Unknown feedback resource')
    item = one(connection.execute(
        f'SELECT * FROM {table} WHERE id=? AND owner_id=?',
        (identifier, user['id']),
    ))
    if item is None:
        raise AppError(404, 'RESOURCE_NOT_FOUND', '记录不存在或不属于当前账号')
    return item


def session_for_case(connection, item):
    session = get_session(connection, item['session_id'])
    if session is None:
        raise AppError(404, 'SESSION_NOT_FOUND', '关联课堂不存在')
    return session
