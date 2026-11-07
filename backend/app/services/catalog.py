from backend.app.errors import AppError
from backend.app.repositories import classroom as repo
from backend.app.repositories.database import connect


def background(color):
    return '#' + ''.join(f'{round(int(color[i:i+2], 16)*.1+255*.9):02x}' for i in (1, 3, 5))


def department_save(payload, user, identifier=None):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        item = repo.one(c.execute('SELECT * FROM departments WHERE id=?', (identifier or payload.id,)))
        if identifier is None and item:
            raise AppError(409, 'DEPARTMENT_EXISTS', '院系编号已存在')
        if identifier is not None and (not item or identifier != payload.id):
            raise AppError(404, 'DEPARTMENT_NOT_FOUND', '院系不存在，编号不能修改')
        if payload.version != (item['version'] if item else 0):
            raise AppError(409, 'VERSION_CONFLICT', '院系信息已更新，请刷新后编辑')
        duplicate = c.execute('SELECT id FROM departments WHERE name=? AND id<>?', (payload.name, payload.id)).fetchone()
        if duplicate:
            raise AppError(409, 'DEPARTMENT_EXISTS', '院系名称已存在')
        c.execute('''INSERT INTO departments(id,name,short_name,color,background,version) VALUES (?,?,?,?,?,1)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name,short_name=excluded.short_name,color=excluded.color,
            background=excluded.background,version=departments.version+1''', (payload.id, payload.name, payload.short_name, payload.color.lower(), background(payload.color)))
        repo.audit(c, user['id'], 'DEPARTMENT_SAVED', {'department_id': payload.id})
        return repo.one(c.execute('SELECT * FROM departments WHERE id=?', (payload.id,)))


def department_delete(identifier, version, user):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        item = c.execute('SELECT version FROM departments WHERE id=?', (identifier,)).fetchone()
        if not item:
            raise AppError(404, 'DEPARTMENT_NOT_FOUND', '院系不存在')
        if item[0] != version:
            raise AppError(409, 'VERSION_CONFLICT', '院系信息已更新，请刷新')
        if c.execute('SELECT 1 FROM courses WHERE department_id=?', (identifier,)).fetchone():
            raise AppError(409, 'DEPARTMENT_IN_USE', '请先将该院系的课程转移到其他院系')
        c.execute('DELETE FROM departments WHERE id=?', (identifier,))
        # Tombstone prevents the built-in catalog from recreating an explicitly removed unit.
        c.execute('INSERT OR IGNORE INTO removed_departments(id) VALUES (?)', (identifier,))
        repo.audit(c, user['id'], 'DEPARTMENT_REMOVED', {'department_id': identifier})
        return {'removed': True}


def course_update(identifier, payload, user):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        item = repo.get_course(c, identifier)
        if not item:
            raise AppError(404, 'COURSE_NOT_FOUND', '课程不存在')
        if item['version'] != payload.version:
            raise AppError(409, 'VERSION_CONFLICT', '课程信息已更新，请刷新后编辑')
        teacher = repo.get_user(c, payload.teacher_id)
        if not teacher or teacher['role'] != 'TEACHER' or teacher['status'] != 'ACTIVE':
            raise AppError(422, 'INVALID_TEACHER', '请选择有效教师')
        if payload.department_id and not c.execute('SELECT 1 FROM departments WHERE id=?', (payload.department_id,)).fetchone():
            raise AppError(422, 'INVALID_DEPARTMENT', '请选择有效院系')
        c.execute('UPDATE courses SET name=?,teacher_id=?,department_id=?,archived=?,version=version+1 WHERE id=?', (payload.name, payload.teacher_id, payload.department_id, int(payload.archived), identifier))
        repo.audit(c, user['id'], 'COURSE_UPDATED', {'course_id': identifier, 'archived': payload.archived})
        return repo.get_course(c, identifier)
