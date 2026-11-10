"""Bounded grouped counts only: no student, device, image or individual record IDs."""
from backend.app.repositories.classroom import rows


def grouped_frames(connection, session_id, start, end, seconds, source, data_scope):
    conditions = ['session_id=?', 'recorded_at>=?', 'recorded_at<?']
    values = [start, seconds * 1000, session_id, start, end]
    if source != 'ALL':
        conditions.append('source=?')
        values.append(source)
    if data_scope != 'ALL':
        conditions.append('is_demo=?')
        values.append(int(data_scope == 'DEMO'))
    # Round Julian-day arithmetic to the stored millisecond precision before binning.
    # This avoids a minute-boundary value falling into the preceding bin due to FP error.
    return rows(connection.execute('''SELECT
        CAST(ROUND((julianday(recorded_at)-julianday(?))*86400000)/? AS INTEGER) AS frame,
        emotion,source,count(*) AS count,sum(is_demo) AS demo_count FROM emoji_records WHERE ''' + ' AND '.join(conditions) +
        ' GROUP BY frame,emotion,source ORDER BY frame,emotion,source', values))
