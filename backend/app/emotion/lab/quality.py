from backend.app.emotion.lab.metrics import SOURCES, distance, source_coverage


def issue(code, severity, title, detail, source=None):
    return {
        'code': code,
        'severity': severity,
        'title': title,
        'detail': detail,
        'source': source,
    }


def inspect_session(item, settings):
    issues = []
    minimum = settings['min_records']
    enabled = SOURCES if settings['source'] == 'ALL' else (settings['source'],)
    coverage = {}
    for source in SOURCES:
        summary = item['sources'][source]
        record = source_coverage(item['frames'], source, minimum)
        coverage[source] = record
        if source not in enabled:
            continue
        if summary['total'] == 0:
            issues.append(issue(
                'NO_RECORDS', 'INFO', '没有该来源记录',
                '当前范围没有记录；不能将空白解释为学生情绪平静。', source,
            ))
            continue
        if summary['total'] < minimum:
            issues.append(issue(
                'SMALL_SAMPLE', 'WARNING', '总样本量不足',
                f"仅有 {summary['total']} 条记录，未达到方案要求的 {minimum} 条。", source,
            ))
        if record['complete_windows'] == 0:
            issues.append(issue(
                'NO_COMPLETE_WINDOW', 'INFO', '没有完整分析时段',
                '课堂尚未形成一个完整分析时段，请等待或调整粒度。', source,
            ))
        elif record['coverage_ratio'] < 0.5:
            issues.append(issue(
                'LOW_TIME_COVERAGE', 'WARNING', '时间覆盖较少',
                f"{record['complete_windows']} 个完整时段中，仅 {record['populated_windows']} 个有记录。", source,
            ))
        if record['longest_empty_run']['windows'] >= 3:
            issues.append(issue(
                'CONTINUOUS_GAP', 'WARNING', '存在连续空白时段',
                f"最长连续 {record['longest_empty_run']['windows']} 个完整时段没有记录。", source,
            ))
        if (record['concentration']['peak_share'] or 0) > 0.5 and record['populated_windows'] >= 3:
            issues.append(issue(
                'BURST_CONCENTRATION', 'INFO', '记录集中在少数时段',
                '超过一半记录来自单一时段，汇总占比可能更受该时段影响。', source,
            ))
    ai = item['sources']['AI']
    manual = item['sources']['MANUAL']
    if ai['total'] and ai['lower_confidence_count']:
        issues.append(issue(
            'LOWER_MODEL_CONFIDENCE', 'INFO', '存在低于 70% 置信度的模型记录',
            f"{ai['lower_confidence_count']} 条历史模型记录低于 70%；置信度不是识别准确率。", 'AI',
        ))
    if ai['total'] >= minimum and manual['total'] >= minimum:
        source_distance = distance(manual['counts'], ai['counts'], minimum)
        if source_distance['total_variation'] >= 0.4:
            issues.append(issue(
                'SOURCE_DISTRIBUTION_GAP', 'INFO', '两种来源的分布差异较大',
                '两种来源可能覆盖不同对象与采样频率，差异不能直接解释为模型错误率。',
            ))
    else:
        source_distance = distance(manual['counts'], ai['counts'], minimum)
    if ai['total'] > max(1, manual['total']) * 10 and manual['total']:
        issues.append(issue(
            'SOURCE_IMBALANCE', 'INFO', 'AI 采样量明显更多',
            'AI 记录超过主动反馈的十倍，应分开阅读，避免汇总数量掩盖主动反馈。',
        ))
    if item['demo_count']:
        issues.append(issue(
            'SYNTHETIC_DATA', 'INFO', '当前分析包含合成演示记录',
            f"包含 {item['demo_count']} 条演示记录，只适合验证产品流程。",
        ))
    if item['integrity']['before_start']:
        issues.append(issue(
            'BEFORE_SESSION', 'WARNING', '存储中有早于开课的记录',
            '这些记录在所选时段之外。',
        ))
    if item['integrity']['after_window']:
        issues.append(issue(
            'OUTSIDE_CLASS_WINDOW', 'INFO', '存在所选窗口以外的记录',
            '要算课后记录，可在方案里调整时间范围。',
        ))
    if item['integrity']['missing_confidence']:
        issues.append(issue(
            'MISSING_AI_CONFIDENCE', 'WARNING', '历史 AI 数据缺少置信度',
            '请核对数据来源与版本；缺失值不能当作零置信度。', 'AI',
        ))
    if not item['phases']:
        issues.append(issue(
            'NO_PHASE_LABELS', 'INFO', '尚未标注教学环节',
            '可在情绪洞察中标注环节；本次仍可按课堂进度或分钟分析。',
        ))
    return {
        'issues': issues,
        'warning_count': sum(item['severity'] == 'WARNING' for item in issues),
        'info_count': sum(item['severity'] == 'INFO' for item in issues),
        'coverage': coverage,
        'source_distance': source_distance,
        'confidence_histogram': item['confidence_histogram'],
    }


def summarize_quality(sessions):
    categories = {}
    for item in sessions:
        for warning in item['quality']['issues']:
            target = categories.setdefault(warning['code'], {
                'code': warning['code'],
                'title': warning['title'],
                'severity': warning['severity'],
                'session_ids': [],
            })
            if item['session']['id'] not in target['session_ids']:
                target['session_ids'].append(item['session']['id'])
    checks = sorted(categories.values(), key=lambda item: (item['severity'] != 'WARNING', item['code']))
    return {
        'sessions_with_warnings': sum(item['quality']['warning_count'] > 0 for item in sessions),
        'warning_count': sum(item['quality']['warning_count'] for item in sessions),
        'info_count': sum(item['quality']['info_count'] for item in sessions),
        'categories': checks,
        'unit': 'aggregated_feedback_records',
        'automatic_exclusion': '仅依据方案时间和来源范围过滤；质量提示不会自动删除原记录',
    }
