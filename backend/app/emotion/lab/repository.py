import json

from backend.app.repositories.classroom import one, rows


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def study_view(item):
    result = dict(item)
    result['tags'] = json.loads(result['tags'])
    result['definition'] = json.loads(result['definition'])
    result['archived'] = bool(result['archived'])
    result.pop('payload_hash', None)
    result.pop('request_id', None)
    result.pop('owner_id', None)
    return result


def job_view(item):
    fields = (
        'id', 'study_id', 'title', 'study_version', 'state', 'progress',
        'attempts', 'cancel_requested', 'error_code', 'report_id',
        'created_at', 'updated_at',
    )
    result = {key: item[key] for key in fields}
    result['cancel_requested'] = bool(result['cancel_requested'])
    return result


def report_view(item, detailed=False):
    fields = (
        'id', 'job_id', 'study_id', 'title', 'fingerprint', 'status',
        'bookmarked', 'conclusion', 'version', 'created_at', 'updated_at',
    )
    result = {key: item[key] for key in fields}
    result['bookmarked'] = bool(result['bookmarked'])
    if detailed:
        result['definition'] = json.loads(item['definition'])
        result['result'] = json.loads(item['result'])
    return result


def dashboard(connection, owner_id):
    studies = connection.execute(
        'SELECT count(*),coalesce(sum(archived=0),0) FROM lab_studies WHERE owner_id=?',
        (owner_id,),
    ).fetchone()
    report_counts = dict(connection.execute(
        'SELECT status,count(*) FROM lab_reports WHERE owner_id=? GROUP BY status',
        (owner_id,),
    ).fetchall())
    job_counts = dict(connection.execute(
        'SELECT state,count(*) FROM lab_jobs WHERE owner_id=? GROUP BY state',
        (owner_id,),
    ).fetchall())
    return {
        'studies': studies[0],
        'active_studies': studies[1],
        'reports': sum(report_counts.values()),
        'reviewed_reports': report_counts.get('REVIEWED', 0),
        'active_jobs': job_counts.get('QUEUED', 0) + job_counts.get('RUNNING', 0),
        'failed_jobs': job_counts.get('FAILED', 0),
        'job_states': job_counts,
        'report_states': report_counts,
    }


def catalog(connection, user, search, course_id, offset, limit):
    conditions = ['1=1']
    values = []
    if user['role'] == 'TEACHER':
        conditions.append('c.teacher_id=?')
        values.append(user['id'])
    if search:
        conditions.append("(instr(lower(c.name),lower(?))>0 OR instr(lower(s.class_name),lower(?))>0)")
        values.extend([search, search])
    if course_id is not None:
        conditions.append('c.id=?')
        values.append(course_id)
    suffix = ' FROM class_sessions s JOIN courses c ON c.id=s.course_id WHERE ' + ' AND '.join(conditions)
    total = connection.execute('SELECT count(*)' + suffix, values).fetchone()[0]
    items = rows(connection.execute(
        '''SELECT s.id,s.course_id,s.starts_at,s.ends_at,s.classroom,s.class_name,
        c.name AS course_name,c.is_demo,
        (SELECT count(*) FROM emoji_records r WHERE r.session_id=s.id) AS record_count,
        (SELECT count(*) FROM emotion_insight_entries p WHERE p.session_id=s.id AND p.kind='PHASE') AS phase_count'''
        + suffix + ' ORDER BY s.starts_at DESC,s.id DESC LIMIT ? OFFSET ?',
        (*values, limit, offset),
    ))
    return {'items': items, 'total': total, 'offset': offset, 'limit': limit}


def studies(connection, owner_id, archived, search, offset, limit):
    conditions = ['owner_id=?']
    values = [owner_id]
    if archived is not None:
        conditions.append('archived=?')
        values.append(int(archived))
    if search:
        conditions.append('(instr(lower(title),lower(?))>0 OR instr(lower(question),lower(?))>0)')
        values.extend([search, search])
    where = ' WHERE ' + ' AND '.join(conditions)
    total = connection.execute('SELECT count(*) FROM lab_studies' + where, values).fetchone()[0]
    items = rows(connection.execute(
        'SELECT * FROM lab_studies' + where + ' ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?',
        (*values, limit, offset),
    ))
    return {
        'items': [study_view(item) for item in items],
        'total': total,
        'offset': offset,
        'limit': limit,
    }


def previous_study(connection, owner_id, request_id):
    return one(connection.execute(
        'SELECT * FROM lab_studies WHERE owner_id=? AND request_id=?',
        (owner_id, request_id),
    ))


def insert_study(connection, user_id, payload, definition, digest, timestamp):
    cursor = connection.execute(
        '''INSERT INTO lab_studies(owner_id,title,question,tags,definition,
        request_id,payload_hash,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)''',
        (
            user_id,
            payload.title,
            payload.question,
            encode(payload.tags),
            encode(definition),
            str(payload.request_id),
            digest,
            timestamp,
            timestamp,
        ),
    )
    return cursor.lastrowid


def update_study(connection, study_id, payload, definition, timestamp):
    connection.execute(
        '''UPDATE lab_studies SET title=?,question=?,tags=?,definition=?,
        version=version+1,updated_at=? WHERE id=?''',
        (
            payload.title,
            payload.question,
            encode(payload.tags),
            encode(definition),
            timestamp,
            study_id,
        ),
    )


def list_jobs(connection, owner_id, state, offset, limit):
    where = ' WHERE owner_id=?'
    values = [owner_id]
    if state:
        where += ' AND state=?'
        values.append(state)
    count = connection.execute('SELECT count(*) FROM lab_jobs' + where, values).fetchone()[0]
    items = rows(connection.execute(
        'SELECT * FROM lab_jobs' + where + ' ORDER BY id DESC LIMIT ? OFFSET ?',
        (*values, limit, offset),
    ))
    return {
        'items': [job_view(item) for item in items],
        'total': count,
        'offset': offset,
        'limit': limit,
    }


def job_events(connection, job_id, after_id=0):
    return rows(connection.execute(
        '''SELECT id,code,message,progress,created_at FROM lab_job_events
        WHERE job_id=? AND id>? ORDER BY id LIMIT 200''',
        (job_id, after_id),
    ))


def event(connection, job_id, code, message, progress, timestamp):
    connection.execute(
        'INSERT INTO lab_job_events(job_id,code,message,progress,created_at) VALUES (?,?,?,?,?)',
        (job_id, code, message, progress, timestamp),
    )


def list_reports(connection, owner_id, status, bookmarked, search, offset, limit):
    conditions = ['owner_id=?']
    values = [owner_id]
    if status:
        conditions.append('status=?')
        values.append(status)
    if bookmarked:
        conditions.append('bookmarked=1')
    if search:
        conditions.append('instr(lower(title),lower(?))>0')
        values.append(search)
    where = ' WHERE ' + ' AND '.join(conditions)
    count = connection.execute('SELECT count(*) FROM lab_reports' + where, values).fetchone()[0]
    items = rows(connection.execute(
        'SELECT * FROM lab_reports' + where + ' ORDER BY id DESC LIMIT ? OFFSET ?',
        (*values, limit, offset),
    ))
    return {
        'items': [report_view(item) for item in items],
        'total': count,
        'offset': offset,
        'limit': limit,
    }


def annotations(connection, report_id):
    return rows(connection.execute(
        '''SELECT id,section,content,version,created_at,updated_at
        FROM lab_annotations WHERE report_id=? ORDER BY id''',
        (report_id,),
    ))


def filtered_where(session_id, lower, upper, settings):
    conditions = ['session_id=?', 'recorded_at>=?', 'recorded_at<?']
    values = [session_id, lower, upper]
    if settings['source'] != 'ALL':
        conditions.append('source=?')
        values.append(settings['source'])
    if settings['data_scope'] != 'ALL':
        conditions.append('is_demo=?')
        values.append(int(settings['data_scope'] == 'DEMO'))
    return ' AND '.join(conditions), values


def grouped_records(connection, session_id, lower, upper, settings, seconds):
    where, values = filtered_where(session_id, lower, upper, settings)
    return rows(connection.execute(
        '''SELECT CAST(ROUND((julianday(recorded_at)-julianday(?))*86400000)/? AS INTEGER) AS bucket,
        source,emotion,count(*) AS count,sum(is_demo) AS demo_count,
        sum(CASE WHEN source='AI' THEN confidence ELSE 0 END) AS confidence_sum,
        sum(CASE WHEN source='AI' AND confidence<0.7 THEN 1 ELSE 0 END) AS lower_confidence_count
        FROM emoji_records WHERE ''' + where + ' GROUP BY bucket,source,emotion ORDER BY bucket,source,emotion',
        (lower, seconds * 1000, *values),
    ))


def confidence_histogram(connection, session_id, lower, upper, settings):
    where, values = filtered_where(session_id, lower, upper, settings)
    return rows(connection.execute(
        '''SELECT CASE WHEN confidence<0.5 THEN 'UNDER_50'
        WHEN confidence<0.7 THEN '50_TO_70'
        WHEN confidence<0.9 THEN '70_TO_90' ELSE '90_TO_100' END AS band,
        count(*) AS count FROM emoji_records WHERE ''' + where + " AND source='AI' GROUP BY band",
        values,
    ))


def phase_records(connection, session_id, lower, upper, settings):
    where, values = filtered_where(session_id, lower, upper, settings)
    # R is a bounded per-class selection; P cannot overlap within one classroom.
    # The SQL returns only aggregate labels, never a row or student identifier.
    return rows(connection.execute(
        '''WITH selected AS (SELECT emotion,source,is_demo,recorded_at FROM emoji_records WHERE ''' + where + ''')
        SELECT p.id AS phase_id,p.title,p.start_minute,p.end_minute,r.source,r.emotion,
        count(*) AS count,sum(r.is_demo) AS demo_count
        FROM selected r JOIN emotion_insight_entries p ON p.session_id=? AND p.kind='PHASE'
        JOIN class_sessions s ON s.id=p.session_id
        WHERE ROUND((julianday(r.recorded_at)-julianday(s.starts_at))*86400000)>=p.start_minute*60000
        AND ROUND((julianday(r.recorded_at)-julianday(s.starts_at))*86400000)<p.end_minute*60000
        GROUP BY p.id,r.source,r.emotion ORDER BY p.start_minute,p.id,r.source,r.emotion''',
        (*values, session_id),
    ))


def phase_definitions(connection, session_id):
    return rows(connection.execute(
        '''SELECT title,start_minute,end_minute FROM emotion_insight_entries
        WHERE session_id=? AND kind='PHASE' ORDER BY start_minute,id LIMIT 100''',
        (session_id,),
    ))


def integrity_counts(connection, session_id, start, finish, cutoff, settings):
    conditions = ['session_id=?']
    values = [session_id]
    if settings['source'] != 'ALL':
        conditions.append('source=?')
        values.append(settings['source'])
    if settings['data_scope'] != 'ALL':
        conditions.append('is_demo=?')
        values.append(int(settings['data_scope'] == 'DEMO'))
    return one(connection.execute(
        '''SELECT count(*) AS stored_total,
        coalesce(sum(recorded_at<?),0) AS before_start,
        coalesce(sum(recorded_at>=?),0) AS after_window,
        coalesce(sum(recorded_at>=?),0) AS at_or_after_cutoff,
        coalesce(sum(source='AI' AND confidence IS NULL),0) AS missing_confidence
        FROM emoji_records WHERE ''' + ' AND '.join(conditions),
        (start, finish, cutoff, *values),
    ))
