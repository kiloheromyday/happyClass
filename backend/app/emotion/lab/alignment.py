from backend.app.emotion.lab.metrics import (
    SOURCES,
    counts_for,
    distribution,
    sum_counts,
)


def source_cells(rows, minimum):
    return {
        source: distribution(counts_for(rows, source), minimum)
        for source in SOURCES
    }


def relative_alignment(sessions, settings):
    columns = []
    amount = settings['relative_bins']
    for index in range(amount):
        columns.append({
            'key': str(index),
            'label': f'{index * 100 / amount:.0f}%–{(index + 1) * 100 / amount:.0f}%',
            'index': index,
        })
    matrix = []
    for item in sessions:
        cells = []
        mapping = {frame['index']: frame for frame in item['frames']}
        for column in columns:
            frame = mapping.get(column['index'])
            if frame is None:
                cell = {
                    'key': column['key'],
                    'observed': False,
                    'complete': False,
                    'sources': source_cells([], settings['min_records']),
                }
            else:
                cell = {
                    'key': column['key'],
                    'observed': True,
                    'complete': frame['complete'],
                    'from_time': frame['from_time'],
                    'to_time': frame['to_time'],
                    'sources': frame['sources'],
                }
            cells.append(cell)
        matrix.append({
            'session_id': item['session']['id'],
            'label': item['session']['class_name'],
            'course_name': item['session']['course_name'],
            'cells': cells,
        })
    return {
        'mode': 'RELATIVE',
        'description': '按方案完整时间窗口的进度对齐；未到达时段和已到达但无数据分开表示。',
        'columns': columns,
        'rows': matrix,
    }


def minute_alignment(sessions, settings):
    # Sessions can have different effective bucket sizes to respect the 180-bin cap.
    # Interval labels remain literal; unequal sizes are never silently treated as equal.
    intervals = {}
    for item in sessions:
        for frame in item['frames']:
            key = f"{frame['start_second']}:{frame['planned_end_second']}"
            intervals[key] = {
                'key': key,
                'label': f"{frame['start_second']/60:g}–{frame['planned_end_second']/60:g} 分钟",
                'start_second': frame['start_second'],
                'end_second': frame['planned_end_second'],
            }
    columns = sorted(intervals.values(), key=lambda item: (item['start_second'], item['end_second']))
    if len(columns) > 360:
        return {
            'mode': 'MINUTE',
            'description': '课堂时长差异产生过多不同分钟区间，请改用相对进度或较粗粒度。',
            'columns': [],
            'rows': [],
            'limited': True,
        }
    matrix = []
    for item in sessions:
        mapping = {
            f"{frame['start_second']}:{frame['planned_end_second']}": frame
            for frame in item['frames']
        }
        cells = []
        for column in columns:
            frame = mapping.get(column['key'])
            cells.append({
                'key': column['key'],
                'observed': frame is not None,
                'complete': bool(frame and frame['complete']),
                'sources': frame['sources'] if frame else source_cells([], settings['min_records']),
            })
        matrix.append({
            'session_id': item['session']['id'],
            'label': item['session']['class_name'],
            'course_name': item['session']['course_name'],
            'cells': cells,
        })
    return {
        'mode': 'MINUTE',
        'description': '从开课开始按实际分钟区间对齐；时长不同的区间分别保留。',
        'columns': columns,
        'rows': matrix,
        'limited': False,
    }


def phase_alignment(sessions, settings):
    names = {}
    by_session = {}
    for item in sessions:
        mapped = {}
        for phase in item['phase_summary']:
            key = phase['title'].strip().casefold()
            names.setdefault(key, phase['title'])
            target = mapped.setdefault(key, [])
            target.extend(phase['rows'])
        by_session[item['session']['id']] = mapped
    columns = [
        {'key': key, 'label': title}
        for key, title in sorted(names.items(), key=lambda pair: pair[1])
    ]
    matrix = []
    for item in sessions:
        mapping = by_session[item['session']['id']]
        defined = {phase['title'].strip().casefold() for phase in item['phases']}
        cells = []
        for column in columns:
            key = column['key']
            cells.append({
                'key': key,
                'observed': key in defined,
                'complete': bool(item['has_finished'] and key in defined),
                'sources': source_cells(mapping.get(key, []), settings['min_records']),
            })
        matrix.append({
            'session_id': item['session']['id'],
            'label': item['session']['class_name'],
            'course_name': item['session']['course_name'],
            'cells': cells,
        })
    return {
        'mode': 'PHASE',
        'description': '按环节名称对齐。首尾空格和英文字母大小写可以不同。',
        'columns': columns,
        'rows': matrix,
    }


def build_alignment(sessions, settings):
    builders = {
        'RELATIVE': relative_alignment,
        'MINUTE': minute_alignment,
        'PHASE': phase_alignment,
    }
    result = builders[settings['alignment']](sessions, settings)
    result['patterns'] = repeated_patterns(result, settings)
    return result


def repeated_patterns(alignment, settings):
    result = []
    for index, column in enumerate(alignment['columns']):
        for source in SOURCES:
            eligible = []
            matching = []
            for row in alignment['rows']:
                cell = row['cells'][index]
                metric = cell['sources'][source]
                if not cell['complete'] or not metric['sample_sufficient']:
                    continue
                eligible.append(row['session_id'])
                if metric['concern_count'] >= metric['total'] * settings['concern_threshold']:
                    matching.append(row['session_id'])
            if len(matching) >= 2:
                result.append({
                    'key': column['key'],
                    'label': column['label'],
                    'source': source,
                    'eligible_sessions': eligible,
                    'matching_sessions': matching,
                    'threshold': settings['concern_threshold'],
                    'description': '至少两节有足够样本的完整时段达到关注占比阈值，仅作为进一步核实的线索。',
                })
    return result


def pooled_column(alignment, column_index, source, minimum):
    counts = []
    included = []
    for row in alignment['rows']:
        cell = row['cells'][column_index]
        if cell['observed']:
            counts.append(cell['sources'][source]['counts'])
            included.append(row['session_id'])
    return {
        'session_ids': included,
        'distribution': distribution(sum_counts(counts), minimum),
    }
