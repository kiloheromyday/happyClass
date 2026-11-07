from backend.app.models.classroom import utc_text
from backend.app.repositories.classroom import RECORD_SELECT, one, rows

JOINS = ' FROM emoji_records e JOIN class_sessions s ON s.id=e.session_id JOIN courses c ON c.id=s.course_id'


def conditions(user, filters):
    parts = ['e.recorded_at >= ?', 'e.recorded_at < ?']
    values = [utc_text(filters.from_time), utc_text(filters.to_time)]
    if filters.data_scope != 'ALL':
        parts.append('e.is_demo=?')
        values.append(int(filters.data_scope == 'DEMO'))
    if user['role'] == 'TEACHER':
        parts.append('c.teacher_id=?')
        values.append(user['id'])
    for field, expression in [('course_id', 'c.id'), ('class_name', 's.class_name'), ('source', 'e.source'), ('session_id', 's.id')]:
        value = getattr(filters, field)
        if value is not None:
            parts.append(expression + '=?')
            values.append(value)
    return ' WHERE ' + ' AND '.join(parts), values


def summary(connection, user, filters):
    where, values = conditions(user, filters)
    return one(connection.execute("SELECT count(*) AS total,count(DISTINCT CASE WHEN e.source='MANUAL' THEN e.user_id END) AS responding_students,count(DISTINCT s.id) AS session_count,count(DISTINCT c.id) AS course_count,coalesce(sum(e.source='MANUAL'),0) AS manual_count,coalesce(sum(e.source='AI'),0) AS ai_count" + JOINS + where, values))


def emotions(connection, user, filters):
    where, values = conditions(user, filters)
    return rows(connection.execute('SELECT e.emotion,count(*) AS count' + JOINS + where + ' GROUP BY e.emotion', values))


def dimensions(connection, user, filters, dimension):
    where, values = conditions(user, filters)
    if dimension == 'course':
        fields, group = 'c.id AS course_id,c.name AS course_name,', 'c.id,c.name'
    else:
        fields, group = 's.class_name,', 's.class_name'
    return rows(connection.execute('SELECT ' + fields + "count(*) AS total,count(DISTINCT CASE WHEN e.source='MANUAL' THEN e.user_id END) AS responding_students,count(DISTINCT s.id) AS session_count" + JOINS + where + ' GROUP BY ' + group + ' ORDER BY total DESC,' + group, values))


def trend(connection, user, filters, bucket=None):
    formats = {'day': '%Y-%m-%dT00:00:00.000Z', 'hour': '%Y-%m-%dT%H:00:00.000Z', 'minute': '%Y-%m-%dT%H:%M:00.000Z'}
    format_text = formats[bucket or filters.bucket]
    where, values = conditions(user, filters)
    return rows(connection.execute("SELECT strftime(?,e.recorded_at) AS timestamp,count(*) AS total,coalesce(sum(e.source='MANUAL'),0) AS manual_count,coalesce(sum(e.source='AI'),0) AS ai_count" + JOINS + where + ' GROUP BY timestamp ORDER BY timestamp', [format_text, *values]))


def export_records(connection, user, filters):
    where, values = conditions(user, filters)
    return rows(connection.execute(RECORD_SELECT.replace('SELECT e.*,', 'SELECT e.*,c.id AS course_id,') + where + ' ORDER BY e.recorded_at,e.id', values))
