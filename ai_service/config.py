"""Shared local configuration; the service credential never reaches the browser."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_SHA256 = 'a2a2ba6a335a3b29c21acb6272f962bd3d47f84952aaffa03b60986e04efa61c'
MAX_FRAME_BYTES = 1_000_000


def local_token(environment_name, filename):
    token = os.getenv(environment_name, '').strip()
    if not token:
        try:
            token = (ROOT / 'data' / filename).read_text(encoding='utf-8').strip()
        except FileNotFoundError:
            return None
    return token if len(token) >= 32 else None


def service_token():
    return local_token('EMOJI_AI_TOKEN', 'ai-service.token')


def ingest_token():
    return local_token('EMOJI_AI_INGEST_TOKEN', 'ai-ingest.token')


def confidence_threshold():
    value = float(os.getenv('EMOJI_AI_MIN_CONFIDENCE', '0.70'))
    if not 0.5 <= value <= 1:
        raise ValueError('EMOJI_AI_MIN_CONFIDENCE must be between 0.5 and 1')
    return value
