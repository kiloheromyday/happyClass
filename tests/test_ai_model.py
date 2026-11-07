import struct

import pytest

cv2 = pytest.importorskip('cv2')
np = pytest.importorskip('numpy')
pytest.importorskip('onnxruntime')

from ai_service.config import ROOT
from ai_service.inference import EmotionEngine, jpeg_dimensions


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
