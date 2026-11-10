"""Download the MIT-licensed official FER+ model and create a local credential."""
import hashlib
import secrets
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_service.config import MODEL_SHA256


def ensure_model():
    model = ROOT / 'ai_service/models/emotion-ferplus-8.onnx'
    model.parent.mkdir(parents=True, exist_ok=True)
    if not model.exists() or hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_SHA256:
        url = 'https://media.githubusercontent.com/media/onnx/models/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx'
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read(36_000_000)
        if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
            raise RuntimeError('Downloaded model checksum mismatch')
        model.write_bytes(data)
    return model


def main():
    ensure_model()
    for filename in ('ai-service.token', 'ai-ingest.token'):
        credential = ROOT / 'data' / filename
        credential.parent.mkdir(parents=True, exist_ok=True)
        try:
            with credential.open('x', encoding='utf-8') as output:
                output.write(secrets.token_urlsafe(48))
        except FileExistsError:
            pass
    print('FER+ model verified. Local service and ingest credentials ready (not displayed).')


if __name__ == '__main__':
    main()
