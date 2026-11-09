import hashlib
import os
from datetime import timedelta, datetime

import httpx
from pydantic import ValidationError

from ai_service.config import confidence_threshold, service_token
from ai_service.contracts import FaceResult, InferenceResult
from backend.app.errors import AppError, success
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.database import connect
from backend.app.repositories.ai import previous_frame, add_predictions, remember_frame, previous_batch, remember_batch
from backend.app.repositories.classroom import audit, get_session
from backend.app.services.auth import limit_attempt
from backend.app.services.classroom import accessible_session, session_status



def ai_url():
    return os.getenv('EMOJI_AI_URL', 'http://127.0.0.1:18081').rstrip('/')


def ongoing(connection, session_id, user):
    item = accessible_session(connection, session_id, user)
    if session_status(item) != 'ONGOING':
        raise AppError(409, 'SESSION_NOT_ONGOING', '只能在正在进行的课堂开启识别')


async def run_inference(data):
    token = service_token()
    if not token:
        raise AppError(503, 'AI_NOT_CONFIGURED', 'AI 服务尚未配置，请先运行识别环境准备脚本')
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.post(ai_url() + '/infer', content=data, headers={'Authorization': f'Bearer {token}', 'Content-Type': 'image/jpeg'})
        if response.status_code in (413, 415, 422):
            raise AppError(response.status_code, 'INVALID_FRAME', '图片无效，请使用不超过 1 MB、最大 1920×1080 的 JPEG 图片')
        if response.status_code != 200:
            raise AppError(503, 'AI_UNAVAILABLE', 'AI 服务尚未就绪，请检查模型与服务配置')
        result = InferenceResult.model_validate(response.json())
        if result.processed != len(result.faces) or result.detected < result.processed:
            raise ValueError('Inconsistent face counts')
        return result
    except (httpx.HTTPError, ValidationError, ValueError) as error:
        raise AppError(503, 'AI_UNAVAILABLE', '无法完成识别，请检查独立 AI 服务后重试') from error


async def status():
    ready = False
    if service_token():
        try:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                response = await client.get(ai_url() + '/health')
            ready = response.status_code == 200 and response.json().get('data', {}).get('ready') is True
        except (httpx.HTTPError, ValueError):
            pass
    return success({'ready': ready, 'min_confidence': confidence_threshold(), 'stores_raw_media': False})


async def process_frame(session_id, user, request_id, data):
    with connect() as connection:
        ongoing(connection, session_id, user)
    digest = hashlib.sha256(data).hexdigest()
    with connect() as connection:
        previous = previous_frame(connection, session_id, user['id'], request_id, digest)
    if previous is not None:
        return success(previous)
    limit_attempt(f'ai-frame:{user["id"]}', 100, 300)
    prediction = await run_inference(bytes(data))
    threshold = confidence_threshold()
    kept = [face for face in prediction.faces if face.confidence >= threshold and face.emotion != 'CONTEMPT']
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        ongoing(connection, session_id, user)
        previous = previous_frame(connection, session_id, user['id'], request_id, digest)
        if previous is not None:
            return success(previous)
        # Store only anonymous labels and probabilities; no image bytes or identity matching.
        add_predictions(connection, session_id, user['id'], kept, utc_text(now_utc()))
        result = {'detected': prediction.detected, 'processed': prediction.processed, 'saved': len(kept), 'filtered': prediction.processed - len(kept), 'min_confidence': threshold}
        remember_frame(connection, session_id, user['id'], request_id, digest, result)
        audit(connection, user['id'], 'AI_FRAME_PROCESSED', {'session_id': session_id, **result})
    return success(result, '识别完成')


def validate_batch(connection, payload, received_at=None):
    item = get_session(connection, payload.session_id)
    if item is None:
        raise AppError(404, 'SESSION_NOT_FOUND', '课堂不存在')
    now = received_at or now_utc()
    if not datetime.fromisoformat(item['starts_at']) <= now < datetime.fromisoformat(item['ends_at']):
        raise AppError(409, 'SESSION_NOT_ONGOING', '只能向正在进行的课堂提交识别结果')
    if not now - timedelta(minutes=5) <= payload.captured_at <= now + timedelta(seconds=30):
        raise AppError(422, 'INVALID_CAPTURE_TIME', '采集时间需在接收前 5 分钟内，且不能超前超过 30 秒')
    if not datetime.fromisoformat(item['starts_at']) <= payload.captured_at < datetime.fromisoformat(item['ends_at']):
        raise AppError(422, 'CAPTURE_OUTSIDE_SESSION', '采集时间不在课堂时间范围内')


def ingest_results(payload, *, received_at=None):
    # received_at is supplied ONLY by the verified internal queue worker, never HTTP input.
    digest = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
    with connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        previous = previous_batch(connection, payload.device_id, payload.batch_id, digest)
        if previous is not None:
            return success(previous, '该批结果已接收')
        validate_batch(connection, payload, received_at)
        # Ingest has a dedicated credential, and cannot supply user identity or source.
        threshold = confidence_threshold()
        kept = [face for face in payload.faces if face.confidence >= threshold and face.emotion != 'CONTEMPT']
        add_predictions(connection, payload.session_id, None, kept, utc_text(payload.captured_at), device_id='worker:' + payload.device_id)
        result = {'session_id': payload.session_id, 'received': len(payload.faces), 'saved': len(kept), 'filtered': len(payload.faces) - len(kept), 'min_confidence': threshold, 'captured_at': utc_text(payload.captured_at)}
        remember_batch(connection, payload, digest, result)
        audit(connection, None, 'AI_BATCH_RECEIVED', {'device_id': payload.device_id, **result})
    return success(result, '识别结果已接收')
