import json

import httpx
import pytest

from ai_service.capture import parser, post_with_retry, submit_image, trusted_url


def test_capture_retry_preserves_batch_id_after_ambiguous_write():
    submitted, sleeps = [], []
    def handle(request):
        if request.url.path == '/infer':
            assert request.headers['Authorization'] == 'Bearer inference-secret'
            return httpx.Response(200, json={'detected': 1, 'processed': 1, 'faces': [{'emotion': 'HAPPY', 'confidence': .9}]})
        assert request.headers['Authorization'] == 'Bearer ingestion-secret'
        submitted.append(json.loads(request.content))
        if len(submitted) == 1:
            raise httpx.ReadTimeout('Ambiguous acknowledgement', request=request)
        return httpx.Response(200, json={'data': {'received': 1, 'saved': 1, 'filtered': 0}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = submit_image(client, b'jpeg', backend_url='http://localhost', ai_url='http://localhost', session_id=2, device_id='test-camera', inference_token='inference-secret', intake_token='ingestion-secret', sleep=sleeps.append)
    assert submitted[0] == submitted[1]
    assert 'user_id' not in submitted[0] and 'source' not in submitted[0]
    assert result['saved'] == 1 and sleeps == [1]


def test_capture_does_not_retry_permanent_errors():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(409, json={'message': 'Class ended'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            post_with_retry(client, 'http://localhost/result', json={}, sleep=lambda _: pytest.fail('No retry for 409'))
    assert len(calls) == 1


def test_capture_temporary_failures_have_bounded_retries():
    sleeps, calls = [], []
    def handle(request):
        calls.append(request)
        return httpx.Response(503)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            post_with_retry(client, 'http://localhost/result', json={}, sleep=sleeps.append)
    assert len(calls) == 3 and sleeps == [1, 2]


def test_capture_requires_an_explicit_source_and_safe_url():
    with pytest.raises(SystemExit):
        parser().parse_args(['--session-id', '1', '--device-id', 'camera'])
    for address in ('http://example.com', 'https://user:password@example.com', 'https://example.com/?token=secret'):
        with pytest.raises(Exception):
            trusted_url(address)
    assert trusted_url('http://127.0.0.1:18080/') == 'http://127.0.0.1:18080'
    assert trusted_url('https://example.com') == 'https://example.com'


def test_local_video_sampling_without_camera(tmp_path):
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from ai_service.capture import frames
    path = tmp_path / 'synthetic.avi'
    output = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 2, (320, 240))
    assert output.isOpened()
    try:
        for _ in range(7):
            output.write(np.zeros((240, 320, 3), dtype=np.uint8))
    finally:
        output.release()
    args = parser().parse_args(['--video', str(path), '--session-id', '1', '--device-id', 'video-test', '--interval', '3'])
    samples = list(frames(args))
    assert len(samples) == 2 and all(data.startswith(b'\xff\xd8') for data in samples)
