"""Explicitly started capture worker. Never starts a camera on import or --help."""
import argparse
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from ai_service.config import MAX_FRAME_BYTES, ingest_token, service_token
from ai_service.contracts import InferenceResult

LOGGER = logging.getLogger('emoji.capture')


def trusted_url(value):
    url = urlsplit(value)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise argparse.ArgumentTypeError('Use an HTTP(S) base URL without credentials, query, or fragment')
    if url.scheme == 'http' and url.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise argparse.ArgumentTypeError('Remote services require HTTPS')
    return value.rstrip('/')


def post_with_retry(client, url, *, sleep=time.sleep, attempts=3, **kwargs):
    """Retries the same content and batch ID, including ambiguous write timeouts."""
    for attempt in range(attempts):
        try:
            response = client.post(url, **kwargs)
            if response.status_code not in (429, 500, 502, 503, 504):
                response.raise_for_status()
                return response
            response.raise_for_status()
        except (httpx.TransportError, httpx.HTTPStatusError) as error:
            status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else 0
            if status not in (0, 429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            LOGGER.warning('Temporary request failure (status=%s), retry %s/%s', status, attempt + 1, attempts - 1)
            sleep(2 ** attempt)


def submit_image(client, image_bytes, *, backend_url, ai_url, session_id, device_id, inference_token, intake_token, captured_at=None, sleep=time.sleep, delivery='sync'):
    captured_at = captured_at or datetime.now(UTC)
    response = post_with_retry(client, ai_url + '/infer', content=image_bytes, headers={'Authorization': f'Bearer {inference_token}', 'Content-Type': 'image/jpeg'}, sleep=sleep)
    prediction = InferenceResult.model_validate(response.json())
    payload = {'batch_id': str(uuid4()), 'session_id': session_id, 'device_id': device_id, 'captured_at': captured_at.isoformat(), 'faces': [face.model_dump() for face in prediction.faces]}
    endpoint = '/api/ai/queued-results' if delivery == 'queue' else '/api/ai/emoji-results'
    accepted = post_with_retry(client, backend_url + endpoint, json=payload, headers={'Authorization': f'Bearer {intake_token}'}, sleep=sleep)
    return accepted.json()['data']


def encode_frame(frame):
    import cv2
    height, width = frame.shape[:2]
    scale = min(1, 960 / width, 720 / height)
    if scale < 1:
        frame = cv2.resize(frame, (round(width * scale), round(height * scale)))
    ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok or len(encoded) > MAX_FRAME_BYTES:
        raise ValueError('Could not encode a JPEG within the 1 MB limit')
    return encoded.tobytes()


def frames(args):
    import cv2
    if args.image:
        # Bound file size before asking the decoder to allocate image memory.
        from ai_service.inference import jpeg_dimensions
        data = Path(args.image).read_bytes()
        if len(data) > MAX_FRAME_BYTES:
            raise ValueError('JPEG image must not exceed 1 MB')
        jpeg_dimensions(data)
        yield data
        return
    capture = cv2.VideoCapture(args.camera if args.camera is not None else str(Path(args.video)))
    try:
        if not capture.isOpened():
            raise RuntimeError('Could not open the explicitly selected camera or video')
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if args.camera is not None:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        fps = capture.get(cv2.CAP_PROP_FPS)
        skip = max(1, round(fps * args.interval)) if args.video and 0 < fps <= 240 else 1
        while True:
            ok, frame = capture.read()
            if not ok:
                if args.camera is not None:
                    raise RuntimeError('Camera stopped returning frames')
                return
            yield encode_frame(frame)
            if args.video:
                for _ in range(skip - 1):
                    if not capture.grab():
                        return
    finally:
        capture.release()


def parser():
    result = argparse.ArgumentParser(description='Sample an explicitly selected camera/video/JPEG and submit anonymous AI results.')
    source = result.add_mutually_exclusive_group(required=True)
    source.add_argument('--camera', type=int, help='Camera index; activates the camera only when explicitly selected')
    source.add_argument('--video', help='Local video file; no frames are saved')
    source.add_argument('--image', help='Single JPEG for a reproducible check; no camera access')
    result.add_argument('--session-id', required=True, type=int)
    result.add_argument('--device-id', required=True)
    result.add_argument('--delivery', choices=['sync', 'queue'], default='sync', help='queue acknowledges acceptance; the worker stores results asynchronously')
    result.add_argument('--interval', type=float, default=3, help='Sampling interval, 3 to 60 seconds')
    result.add_argument('--max-frames', type=int, default=0, help='0 for continuous capture; image mode always submits once')
    result.add_argument('--backend-url', type=trusted_url, default='http://127.0.0.1:18080')
    result.add_argument('--ai-url', type=trusted_url, default='http://127.0.0.1:18081')
    return result


def main(argv=None):
    arguments = parser()
    args = arguments.parse_args(argv)
    import re
    if args.session_id <= 0 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}', args.device_id) or not 3 <= args.interval <= 60 or args.max_frames < 0 or (args.camera is not None and args.camera < 0):
        arguments.error('Check the session ID, device ID, interval (3..60), camera index, and maximum frame count')
    inference_token, intake_token = service_token(), ingest_token()
    if not inference_token or not intake_token:
        arguments.error('Run scripts/prepare_ai.py first, or configure both service credentials')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    source = frames(args)
    try:
        with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
            for count, image in enumerate(source, start=1):
                started = time.monotonic()
                data = submit_image(client, image, backend_url=args.backend_url, ai_url=args.ai_url, session_id=args.session_id, device_id=args.device_id, inference_token=inference_token, intake_token=intake_token, delivery=args.delivery)
                if args.delivery == 'queue':
                    LOGGER.info('Queue accepted job=%s state=%s', data['job_id'], data['state'])
                else:
                    LOGGER.info('Batch acknowledged: received=%s saved=%s filtered=%s', data['received'], data['saved'], data['filtered'])
                if args.image or (args.max_frames and count >= args.max_frames):
                    break
                time.sleep(max(0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        LOGGER.info('Capture stopped by operator')
    except Exception as error:
        # Do not print headers, credentials, frame data, or request payloads.
        LOGGER.error('Capture stopped: %s', str(error))
        return 1
    finally:
        source.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
