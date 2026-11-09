from fastapi import APIRouter, Depends, Path, Response

from ai_service.result_queue import get_queue
from backend.app.controllers.ai import require_ingest
from backend.app.dependencies import require_roles, require_same_origin
from backend.app.errors import AppError, success
from backend.app.models.ai import AiBatchRequest
from backend.app.services.auth import limit_attempt

router = APIRouter(prefix='/api/ai', tags=['AI 异步结果队列'])


@router.post('/queued-results', status_code=202, dependencies=[Depends(require_ingest)])
def enqueue(payload: AiBatchRequest, response: Response):
    limit_attempt(f'ai-queue:{payload.device_id}', 120, 300)
    try:
        item = get_queue().enqueue(payload)
    except AppError:
        raise
    except Exception as error:
        raise AppError(503, 'QUEUE_UNAVAILABLE', '队列暂不可用，请使用相同批次稍后重试') from error
    response.status_code = 200 if item['duplicate'] else 202
    return success(item, '已接收，正在等待异步入库')


@router.get('/queue/status')
def status(user=Depends(require_roles('ADMIN'))):
    try:
        return success(get_queue().overview())
    except AppError as error:
        if error.code == 'QUEUE_DISABLED':
            return success({'enabled': False, 'ready': False, 'queued_or_pending': 0, 'failed': [], 'worker_heartbeat': None})
        raise
    except Exception:
        return success({'enabled': True, 'ready': False, 'queued_or_pending': None, 'failed': [], 'worker_heartbeat': None})


@router.post('/queue/jobs/{job_id}/retry', dependencies=[Depends(require_same_origin)])
def retry(job_id: str = Path(pattern=r'^[a-f0-9]{64}$'), user=Depends(require_roles('ADMIN'))):
    try:
        return success(get_queue().retry(job_id), '失败任务已重新排队')
    except AppError:
        raise
    except Exception as error:
        raise AppError(503, 'QUEUE_UNAVAILABLE', '队列暂不可用，请稍后重试') from error
