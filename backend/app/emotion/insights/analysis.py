"""Deterministic, explainable classroom signals; never individual diagnoses."""
import hashlib

CONCERN = frozenset({'SAD', 'ANGRY', 'FEAR', 'DISGUST'})
SOURCES = ('MANUAL', 'AI')


def distribution(rows, source=None):
    selected = [row for row in rows if source is None or row['source'] == source]
    total = sum(row['count'] for row in selected)
    concern = sum(row['count'] for row in selected if row['emotion'] in CONCERN)
    return {'total': total, 'concern_count': concern,
            'concern_ratio': round(concern / total, 4) if total else None,
            'demo_count': sum(row['demo_count'] for row in selected)}


def detect_signals(frames, rules):
    """Consecutive *completed* windows, independently per source; gaps break a run."""
    signals = []
    for source in SOURCES:
        run = []

        def finish():
            if len(run) < rules['consecutive_windows']:
                return
            total = sum(frame['sources'][source]['total'] for frame in run)
            concern = sum(frame['sources'][source]['concern_count'] for frame in run)
            identity = f"{source}:{run[0]['from_time']}:{run[-1]['to_time']}"
            signals.append({'id': hashlib.sha256(identity.encode()).hexdigest()[:20],
                            'rule': 'SUSTAINED_CONCERN', 'source': source,
                            'from_time': run[0]['from_time'], 'to_time': run[-1]['to_time'],
                            'start_minute': run[0]['start_minute'], 'end_minute': run[-1]['end_minute'],
                            'windows': len(run), 'total': total, 'concern_count': concern,
                            'concern_ratio': round(concern / total, 4),
                            'explanation': f"连续 {len(run)} 个完整时段，每段至少 {rules['min_records']} 条记录，关注类别占比均达到 {rules['concern_ratio']:.0%}"})

        for frame in frames:
            metric = frame['sources'][source]
            # Compare raw integers rather than rounded displayed ratios at the threshold.
            qualifies = (frame['complete'] and metric['total'] >= rules['min_records']
                         and metric['concern_count'] >= metric['total'] * rules['concern_ratio'])
            if qualifies:
                run.append(frame)
            else:
                finish()
                run = []
        finish()
    return sorted(signals, key=lambda item: (item['from_time'], item['source']))


def compare_windows(before, after, minimum, complete):
    comparisons = []
    for source in SOURCES:
        left, right = distribution(before, source), distribution(after, source)
        ready = complete and left['total'] >= minimum and right['total'] >= minimum
        comparisons.append({'source': source, 'before': left, 'after': right,
                            'status': 'COMPARABLE' if ready else 'INSUFFICIENT_DATA',
                            'change_percentage_points': round((right['concern_ratio'] - left['concern_ratio']) * 100, 2) if ready else None})
    return comparisons
