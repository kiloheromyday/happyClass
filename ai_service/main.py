import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ai_service.config import MAX_FRAME_BYTES, service_token
from ai_service.contracts import InferenceResult


def load_engine():
    from ai_service.inference import EmotionEngine
    return EmotionEngine()


@asynccontextmanager
async def lifespan(app):
    app.state.engine = None
    try:
        app.state.engine = load_engine()
    except Exception:
        logging.exception('Emotion model could not be loaded')
    yield


app = FastAPI(title="课堂情绪 AI 服务", version="0.6.0", lifespan=lifespan)


@app.get("/health")
def health():
    loaded = getattr(app.state, 'engine', None) is not None
    ready = loaded and service_token() is not None
    return {'code': 'OK' if ready else 'NOT_READY', 'data': {'model_loaded': loaded, 'authentication_configured': service_token() is not None, 'stores_raw_media': False, 'ready': ready}}


@app.post('/infer', response_model=InferenceResult)
async def infer(request: Request, authorization: str = Header(default='')):
    token = service_token()
    if not token:
        raise HTTPException(503, 'AI 服务密钥尚未配置')
    if not secrets.compare_digest(authorization.encode(), f'Bearer {token}'.encode()):
        raise HTTPException(401, 'AI 服务认证失败')
    engine = getattr(app.state, 'engine', None)
    if engine is None:
        raise HTTPException(503, '识别模型未加载，请检查 AI 服务')
    if request.headers.get('content-type', '').split(';')[0] != 'image/jpeg':
        raise HTTPException(415, '请提交 JPEG 图片')
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_FRAME_BYTES:
            raise HTTPException(413, '图片不能超过 1 MB')
    try:
        return await run_in_threadpool(engine.infer, bytes(data))
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
