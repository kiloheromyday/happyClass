"""Insight data access: aggregated labels and teacher-authored entries only."""
from backend.app.repositories.classroom import rows

DEFAULT_RULES = {'bucket_minutes': 5, 'min_records': 5, 'concern_ratio': 0.6,
                 'consecutive_windows': 2, 'version': 0, 'updated_at': None}


def rules(connection, session_id):
    items = rows(connection.execute('SELECT bucket_minutes,min_records,concern_ratio,consecutive_windows,version,updated_at '
                                    'FROM emotion_insight_rules WHERE session_id=?', (session_id,)))
    return items[0] if items else dict(DEFAULT_RULES)


def entries(connection, session_id):
    return rows(connection.execute('''SELECT id,kind,title,content,start_minute,end_minute,status,outcome,
        version,created_at,updated_at FROM emotion_insight_entries WHERE session_id=? ORDER BY start_minute,id''', (session_id,)))


def counts(connection, session_id, lower, upper, source, data_scope):
    conditions = ['session_id=?', 'recorded_at>=?', 'recorded_at<?']
    values = [session_id, lower, upper]
    if source != 'ALL':
        conditions.append('source=?')
        values.append(source)
    if data_scope != 'ALL':
        conditions.append('is_demo=?')
        values.append(int(data_scope == 'DEMO'))
    return rows(connection.execute('SELECT source,emotion,count(*) AS count,sum(is_demo) AS demo_count '
                                    'FROM emoji_records WHERE ' + ' AND '.join(conditions) + ' GROUP BY source,emotion', values))
