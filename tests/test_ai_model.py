import struct

import pytest

cv2 = pytest.importorskip('cv2')
np = pytest.importorskip('numpy')
pytest.importorskip('onnxruntime')

from ai_service.config import ROOT
from ai_service.inference import EmotionEngine, jpeg_dimensions


def test_inference_candidates_preserve_actual_scores_and_label_order():
    # Isolate postprocessing from model accuracy: each class must be able to win.
    from threading import Lock
    from ai_service.inference import LABELS
    class Detector:
        def detectMultiScale(self, *args, **kwargs):
            return [(0, 0, 64, 64)]
    class Session:
        def run(self, outputs, inputs):
            return [scores]
    engine = EmotionEngine.__new__(EmotionEngine)
    engine.lock, engine.detector, engine.session, engine.input_name = Lock(), Detector(), Session(), 'input'
    ok, encoded = cv2.imencode('.jpg', np.full((64, 64, 3), 127, np.uint8))
    assert ok
    for index, emotion in enumerate(LABELS):
        scores = np.full((1, 8), -2, np.float32)
        scores[0, index] = 2
        face = engine.infer(encoded.tobytes())['faces'][0]
        assert face['emotion'] == emotion
        assert face['candidates'][0] == {'emotion': emotion, 'confidence': face['confidence']}
        assert len(face['candidates']) == 3
        assert face['candidates'][0]['confidence'] > face['candidates'][1]['confidence']


def test_jpeg_dimensions_reject_bombs_and_bad_headers():
    for data in (b'bad', b'\xff\xd8', b'\xff\xd8\xff\xc0\x00\x01'):
        with pytest.raises(ValueError):
            jpeg_dimensions(data)
    oversized = b'\xff\xd8\xff\xc0' + struct.pack('>HBHHB', 8, 8, 10000, 10000, 1)
    with pytest.raises(ValueError):
        jpeg_dimensions(oversized)


@pytest.mark.skipif(not (ROOT / 'ai_service/models/emotion-ferplus-8.onnx').exists(), reason='Optional model is not installed')
def test_real_model_load_and_no_face_input():
    engine = EmotionEngine()
    ok, encoded = cv2.imencode('.jpg', np.zeros((480, 640, 3), np.uint8))
    assert ok
    assert engine.infer(encoded.tobytes()) == {'detected': 0, 'processed': 0, 'faces': []}
    # Exercise the actual ONNX path independently of face detection.
    scores = engine.session.run(None, {engine.input_name: np.full((1, 1, 64, 64), 127, np.float32)})[0]
    assert scores.shape == (1, 8) and np.isfinite(scores).all()
