from datetime import datetime, timedelta
import math

from backend.app.models.classroom import Emotion, now_utc, utc_text
from backend.app.repositories.database import connect
from backend.app.emotion.replay.repository import grouped_frames
from backend.app.repositories.privacy import policy
from backend.app.services.classroom import accessible_session, session_view, FEEDBACK_GRACE

MAX_FRAMES = 360


def get_replay(session_id, user, bucket_minutes=1, source='ALL', data_scope='ALL'):
    with connect() as connection:
        connection.execute('BEGIN')
        session = accessible_session(connection, session_id, user)
        start = datetime.fromisoformat(session['starts_at'])
        finish = datetime.fromisoformat(session['ends_at'])
        now = now_utc()
        upper = max(start, min(now, finish + FEEDBACK_GRACE))
        duration = max(0, (upper - start).total_seconds())
        seconds = max(bucket_minutes * 60, math.ceil(duration / MAX_FRAMES / 60) * 60)
        count = max(1, math.ceil(duration / seconds))
        codes = [emotion.value for emotion in Emotion]
        frames = []
        for index in range(count):
            lower = start + timedelta(seconds=index * seconds)
            frames.append({'index': index, 'from_time': utc_text(lower),
                           'to_time': utc_text(min(upper, lower + timedelta(seconds=seconds))),
                           'total': 0, 'manual_count': 0, 'ai_count': 0,
                           'emotions': [{'emotion': code, 'count': 0} for code in codes]})
        demo_count = 0
        for row in grouped_frames(connection, session_id, utc_text(start), utc_text(upper), seconds, source, data_scope):
            if not 0 <= row['frame'] < count or row['emotion'] not in codes:
                continue
            frame = frames[row['frame']]
            frame['emotions'][codes.index(row['emotion'])]['count'] += row['count']
            frame['total'] += row['count']
            frame['manual_count' if row['source'] == 'MANUAL' else 'ai_count'] += row['count']
            demo_count += row['demo_count']
        for frame in frames:
            maximum = max(item['count'] for item in frame['emotions'])
            frame['dominant_emotions'] = [item['emotion'] for item in frame['emotions'] if maximum > 0 and item['count'] == maximum]
        return {'session': session_view(session), 'privacy_mode': policy(connection, session_id)['mode'],
                'updated_at': utc_text(now), 'source': source, 'data_scope': data_scope,
                'bucket_minutes': seconds // 60, 'requested_bucket_minutes': bucket_minutes,
                'window': {'from_time': utc_text(start), 'to_time': utc_text(upper),
                           'class_ends_at': utc_text(finish), 'feedback_closes_at': utc_text(finish + FEEDBACK_GRACE)},
                'has_started': now >= start, 'includes_after_class': upper > finish, 'demo_record_count': demo_count,
                'summary': {key: sum(frame[key] for frame in frames) for key in ('total', 'manual_count', 'ai_count')},
                'frames': frames}
