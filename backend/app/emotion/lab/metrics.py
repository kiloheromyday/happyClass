"""Descriptive metrics over aggregate emotion counts."""
import math
from statistics import median, pstdev

EMOTIONS = ('HAPPY', 'NEUTRAL', 'SAD', 'ANGRY', 'SURPRISED', 'FEAR', 'DISGUST')
SOURCES = ('MANUAL', 'AI')
CONCERN = frozenset(('SAD', 'ANGRY', 'FEAR', 'DISGUST'))
NAMES = {
    'HAPPY': '开心',
    'NEUTRAL': '平静',
    'SAD': '低落',
    'ANGRY': '生气',
    'SURPRISED': '惊讶',
    'FEAR': '担忧',
    'DISGUST': '反感',
}


def ratio(numerator, denominator, places=5):
    if denominator <= 0:
        return None
    return round(numerator / denominator, places)


def empty_counts():
    return {emotion: 0 for emotion in EMOTIONS}


def counts_for(rows, source=None):
    result = empty_counts()
    for row in rows:
        if source is not None and row['source'] != source:
            continue
        if row['emotion'] in result:
            result[row['emotion']] += row['count']
    return result


def sum_counts(items):
    result = empty_counts()
    for item in items:
        for emotion in EMOTIONS:
            result[emotion] += item.get(emotion, 0)
    return result


def distribution(counts, minimum=5):
    total = sum(counts.values())
    concern = sum(counts.get(emotion, 0) for emotion in CONCERN)
    maximum = max(counts.values(), default=0)
    dominant = [emotion for emotion in EMOTIONS if maximum > 0 and counts[emotion] == maximum]
    return {
        'total': total,
        'counts': {emotion: counts.get(emotion, 0) for emotion in EMOTIONS},
        'shares': {emotion: ratio(counts.get(emotion, 0), total) for emotion in EMOTIONS},
        'concern_count': concern,
        'concern_ratio': ratio(concern, total),
        'happy_ratio': ratio(counts.get('HAPPY', 0), total),
        'neutral_ratio': ratio(counts.get('NEUTRAL', 0), total),
        'dominant_emotions': dominant,
        'sample_sufficient': total >= minimum,
        'entropy_bits': entropy(counts),
    }


def entropy(counts):
    total = sum(counts.values())
    if total == 0:
        return None
    value = 0
    for count in counts.values():
        if count:
            probability = count / total
            value -= probability * math.log2(probability)
    return round(value, 4)


def source_summaries(rows, minimum):
    result = {}
    for source in SOURCES:
        selected = [item for item in rows if item['source'] == source]
        item = distribution(counts_for(selected), minimum)
        item['demo_count'] = sum(row['demo_count'] for row in selected)
        item['average_confidence'] = (
            ratio(sum(row.get('confidence_sum', 0) for row in selected), item['total'])
            if source == 'AI' else None
        )
        item['lower_confidence_count'] = sum(row.get('lower_confidence_count', 0) for row in selected)
        result[source] = item
    return result


def distance(left, right, minimum):
    left_total = sum(left.values())
    right_total = sum(right.values())
    if min(left_total, right_total) < minimum:
        return {
            'status': 'INSUFFICIENT_DATA',
            'total_variation': None,
            'jensen_shannon_bits': None,
        }
    p = [left.get(emotion, 0) / left_total for emotion in EMOTIONS]
    q = [right.get(emotion, 0) / right_total for emotion in EMOTIONS]
    average = [(a + b) / 2 for a, b in zip(p, q)]
    divergence = 0
    for values in (p, q):
        for value, midpoint in zip(values, average):
            if value:
                divergence += 0.5 * value * math.log2(value / midpoint)
    return {
        'status': 'DESCRIPTIVE_ONLY',
        'total_variation': round(sum(abs(a - b) for a, b in zip(p, q)) / 2, 5),
        'jensen_shannon_bits': round(max(0, divergence), 5),
    }


def concentration(values):
    if not values or sum(values) == 0:
        return {'peak_share': None, 'coefficient_of_variation': None, 'peak': 0}
    total = sum(values)
    average = total / len(values)
    return {
        'peak_share': round(max(values) / total, 5),
        'coefficient_of_variation': round(pstdev(values) / average, 4),
        'peak': max(values),
    }


def longest_empty_run(frames, source):
    longest = 0
    current = 0
    first = None
    longest_start = None
    longest_end = None
    for frame in frames:
        if frame['sources'][source]['total'] == 0:
            if current == 0:
                first = frame['from_time']
            current += 1
            if current > longest:
                longest = current
                longest_start = first
                longest_end = frame['to_time']
        else:
            current = 0
    return {
        'windows': longest,
        'from_time': longest_start,
        'to_time': longest_end,
    }


def source_coverage(frames, source, minimum):
    complete = [frame for frame in frames if frame['complete']]
    populated = sum(frame['sources'][source]['total'] > 0 for frame in complete)
    sufficient = sum(frame['sources'][source]['total'] >= minimum for frame in complete)
    counts = [frame['sources'][source]['total'] for frame in complete]
    return {
        'complete_windows': len(complete),
        'populated_windows': populated,
        'sufficient_windows': sufficient,
        'coverage_ratio': ratio(populated, len(complete)),
        'sufficient_ratio': ratio(sufficient, len(complete)),
        'longest_empty_run': longest_empty_run(complete, source),
        'concentration': concentration(counts),
    }


def summarize_sessions(sessions, source, minimum):
    values = [item['sources'][source] for item in sessions]
    pooled = distribution(sum_counts(item['counts'] for item in values), minimum)
    eligible = [item for item in values if item['sample_sufficient']]
    fractions = [item['concern_count'] / item['total'] for item in eligible]
    return {
        'sessions': len(sessions),
        'eligible_sessions': len(eligible),
        'empty_sessions': sum(item['total'] == 0 for item in values),
        'pooled': pooled,
        'equal_weight_concern_ratio': round(sum(fractions) / len(fractions), 5) if fractions else None,
        'median_concern_ratio': round(median(fractions), 5) if fractions else None,
        'min_concern_ratio': round(min(fractions), 5) if fractions else None,
        'max_concern_ratio': round(max(fractions), 5) if fractions else None,
    }


def group_comparison(sessions, baseline_ids, minimum):
    baseline = [item for item in sessions if item['session']['id'] in baseline_ids]
    other = [item for item in sessions if item['session']['id'] not in baseline_ids]
    result = []
    for source in SOURCES:
        left = summarize_sessions(baseline, source, minimum)
        right = summarize_sessions(other, source, minimum)
        enough = left['eligible_sessions'] > 0 and right['eligible_sessions'] > 0
        delta = None
        if enough:
            delta = round((right['equal_weight_concern_ratio'] - left['equal_weight_concern_ratio']) * 100, 3)
        result.append({
            'source': source,
            'baseline': left,
            'comparison': right,
            'status': 'DESCRIPTIVE_ONLY' if enough else 'INSUFFICIENT_DATA',
            'equal_weight_change_pp': delta,
            'distribution_distance': distance(left['pooled']['counts'], right['pooled']['counts'], minimum),
        })
    return result


def session_pairs(sessions, minimum):
    pairs = []
    for index, left in enumerate(sessions):
        for right in sessions[index + 1:]:
            item = {
                'left_session_id': left['session']['id'],
                'right_session_id': right['session']['id'],
                'sources': {},
            }
            for source in SOURCES:
                a = left['sources'][source]
                b = right['sources'][source]
                metric = distance(a['counts'], b['counts'], minimum)
                metric['concern_change_pp'] = None
                if a['sample_sufficient'] and b['sample_sufficient']:
                    metric['concern_change_pp'] = round(
                        (b['concern_count'] / b['total'] - a['concern_count'] / a['total']) * 100,
                        3,
                    )
                item['sources'][source] = metric
            pairs.append(item)
    return pairs


def rank_sessions(sessions, source, minimum):
    eligible = []
    excluded = []
    for item in sessions:
        value = item['sources'][source]
        target = eligible if value['total'] >= minimum else excluded
        target.append({
            'session_id': item['session']['id'],
            'course_name': item['session']['course_name'],
            'class_name': item['session']['class_name'],
            'starts_at': item['session']['starts_at'],
            'total': value['total'],
            'concern_ratio': value['concern_ratio'],
        })
    eligible.sort(key=lambda item: (-item['concern_ratio'], item['starts_at'], item['session_id']))
    return {
        'source': source,
        'eligible': eligible,
        'excluded': excluded,
        'meaning': '按关注类别占比排列课堂线索，不是教学质量或教师排名',
    }


def changes_over_time(sessions, source, minimum):
    ordered = sorted(sessions, key=lambda item: (item['session']['starts_at'], item['session']['id']))
    result = []
    previous = None
    for item in ordered:
        value = item['sources'][source]
        change = None
        if previous is not None and value['total'] >= minimum:
            change = round((value['concern_count'] / value['total'] - previous) * 100, 3)
        result.append({
            'session_id': item['session']['id'],
            'starts_at': item['session']['starts_at'],
            'total': value['total'],
            'concern_ratio': value['concern_ratio'],
            'change_from_previous_eligible_pp': change,
        })
        if value['total'] >= minimum:
            previous = value['concern_count'] / value['total']
    return result
