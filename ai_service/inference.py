import hashlib
import struct
from threading import Lock

import cv2
import numpy as np
import onnxruntime as ort

from ai_service.config import ROOT, MODEL_SHA256, MAX_FRAME_BYTES

LABELS = ('NEUTRAL', 'HAPPY', 'SURPRISED', 'SAD', 'ANGRY', 'DISGUST', 'FEAR', 'CONTEMPT')


def jpeg_dimensions(data):
    """Read JPEG dimensions before decoding to bound decompression memory."""
    if not data.startswith(b'\xff\xd8'):
        raise ValueError('请提交 JPEG 图片')
    offset = 2
    while offset < len(data):
        if data[offset] != 0xff:
            raise ValueError('JPEG 图片结构无效')
        while offset < len(data) and data[offset] == 0xff:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in (0xd9, 0xda):
            break
        if marker == 0x01 or 0xd0 <= marker <= 0xd8:
            continue
        if offset + 2 > len(data):
            break
        size = struct.unpack_from('>H', data, offset)[0]
        if size < 2 or offset + size > len(data):
            break
        if marker in (0xc0, 0xc1, 0xc2):
            if size < 8:
                break
            height, width = struct.unpack_from('>HH', data, offset + 3)
            if not (32 <= width <= 1920 and 32 <= height <= 1080):
                raise ValueError('图片尺寸需在 32×32 至 1920×1080 之间')
            return width, height
        offset += size
    raise ValueError('无法读取 JPEG 图片尺寸')


class EmotionEngine:
    def __init__(self):
        path = ROOT / 'ai_service' / 'models' / 'emotion-ferplus-8.onnx'
        if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError('Model checksum mismatch')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        if self.detector.empty():
            raise ValueError('Face detector unavailable')
        self.lock = Lock()

    def infer(self, data):
        if len(data) > MAX_FRAME_BYTES:
            raise ValueError('图片不能超过 1 MB')
        width, height = jpeg_dimensions(data)
        gray = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
        if gray is None or gray.shape != (height, width):
            raise ValueError('图片损坏或尺寸不一致')
        # Haar and inference share a lock; bound both face count and CPU use.
        with self.lock:
            scale = min(1.0, 640 / width)
            preview = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
            boxes = self.detector.detectMultiScale(preview, scaleFactor=1.15, minNeighbors=5, minSize=(40, 40))
            faces = []
            for x, y, w, h in sorted(boxes, key=lambda box: int(box[2]) * int(box[3]), reverse=True)[:12]:
                x, y, w, h = (int(round(value / scale)) for value in (x, y, w, h))
                crop = gray[y:min(height, y + h), x:min(width, x + w)]
                tensor = cv2.resize(crop, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)[None, None, :, :]
                scores = self.session.run(None, {self.input_name: tensor})[0].reshape(8).astype(np.float64)
                probabilities = np.exp(scores - scores.max())
                probabilities /= probabilities.sum()
                index = int(probabilities.argmax())
                faces.append({'emotion': LABELS[index], 'confidence': float(probabilities[index])})
        return {'detected': len(boxes), 'processed': len(faces), 'faces': faces}
