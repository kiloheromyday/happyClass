"""Redis Streams carries signed LABELS only, never camera frames or credentials."""
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta

from ai_service.config import ingest_token
from backend.app.errors import AppError
from backend.app.models.ai import AiBatchRequest
from backend.app.models.classroom import now_utc, utc_text
from backend.app.repositories.database import connect
from backend.app.services.ai import ingest_results, validate_batch

STREAM = 'happyclass:ai:results'
DEAD = 'happyclass:ai:failed'
GROUP = 'happyclass-ai-writers'
TTL = 7 * 86400


def signing_key():
    token = ingest_token()
    if not token:
        raise AppError(503, 'AI_INGEST_NOT_CONFIGURED', '请先准备 AI 独立服务密钥')
    return token.encode()


def signature(envelope):
    return hmac.new(signing_key(), envelope.encode(), hashlib.sha256).hexdigest()


def get_queue():
    url = os.getenv('EMOJI_REDIS_URL')
    if not url:
        raise AppError(503, 'QUEUE_DISABLED', '异步队列未配置，请设置 EMOJI_REDIS_URL')
    from redis import Redis
    return ResultQueue(Redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=5))


class ResultQueue:
    def __init__(self, client):
        self.client = client
        self.claim_cursor = '0-0'

    @staticmethod
    def job_key(identifier):
        return 'happyclass:ai:job:' + identifier

    def enqueue(self, payload):
        from redis.exceptions import WatchError
        raw = payload.model_dump_json()
        digest = hashlib.sha256(raw.encode()).hexdigest()
        identifier = hashlib.sha256(f'{payload.device_id}:{payload.batch_id}'.encode()).hexdigest()
        key = self.job_key(identifier)
        for _ in range(4):
            with self.client.pipeline() as transaction:
                try:
                    transaction.watch(key, STREAM)
                    previous = transaction.hgetall(key)
                    if previous:
                        if previous['digest'] != digest:
                            raise AppError(409, 'REQUEST_ID_REUSED', '该批次已使用，重试内容必须相同')
                        return {'job_id': identifier, 'state': previous['state'], 'duplicate': True}
                    accepted = now_utc()
                    with connect() as connection:
                        validate_batch(connection, payload, accepted)
                    if transaction.xlen(STREAM) >= int(os.getenv('EMOJI_QUEUE_CAPACITY', '10000')):
                        raise AppError(503, 'QUEUE_FULL', '异步队列已满，请稍后重试')
                    envelope = json.dumps({'accepted_at': utc_text(accepted), 'payload': json.loads(raw)}, sort_keys=True, separators=(',', ':'))
                    signed = signature(envelope)
                    transaction.multi()
                    transaction.hset(key, mapping={'digest': digest, 'state': 'QUEUED', 'attempts': '0', 'queued_at': utc_text(accepted), 'envelope': envelope, 'signature': signed})
                    transaction.expire(key, TTL)
                    transaction.xadd(STREAM, {'job_id': identifier, 'envelope': envelope, 'signature': signed})
                    transaction.execute()
                    return {'job_id': identifier, 'state': 'QUEUED', 'duplicate': False}
                except WatchError:
                    continue
        raise AppError(503, 'QUEUE_BUSY', '队列忙，请稍后使用相同批次重试')

    def ensure_group(self):
        from redis.exceptions import ResponseError
        try:
            self.client.xgroup_create(STREAM, GROUP, id='0-0', mkstream=True)
        except ResponseError as error:
            if 'BUSYGROUP' not in str(error):
                raise

    def acknowledge(self, entry_id):
        with self.client.pipeline() as transaction:
            transaction.xack(STREAM, GROUP, entry_id)
            transaction.xdel(STREAM, entry_id)
            transaction.execute()

    def process(self, entry_id, fields):
        identifier = fields.get('job_id', '')
        if len(identifier) != 64 or any(char not in '0123456789abcdef' for char in identifier):
            self.acknowledge(entry_id)
            return 'INVALID'
        key = self.job_key(identifier)
        state = self.client.hget(key, 'state')
        if state is None:
            # Retention may expire while a consumer is offline; do not resurrect an incomplete job hash.
            self.client.xadd(DEAD, {'job_id': identifier, 'error_code': 'JOB_EXPIRED'}, maxlen=1000, approximate=False)
            self.acknowledge(entry_id)
            return 'EXPIRED'
        if state == 'COMPLETED':
            self.acknowledge(entry_id)
            return 'COMPLETED'
        attempts = self.client.hincrby(key, 'attempts', 1)
        try:
            envelope = fields['envelope']
            if not hmac.compare_digest(signature(envelope), fields['signature']):
                raise ValueError('Invalid signed message')
            content = json.loads(envelope)
            accepted = datetime.fromisoformat(content['accepted_at'])
            if not now_utc() - timedelta(days=7) <= accepted <= now_utc() + timedelta(seconds=30):
                raise ValueError('Expired message')
            payload = AiBatchRequest.model_validate(content['payload'])
            expected = hashlib.sha256(f'{payload.device_id}:{payload.batch_id}'.encode()).hexdigest()
            if identifier != expected:
                raise ValueError('Wrong job identifier')
            result = ingest_results(payload, received_at=accepted)['data']
        except Exception as error:
            permanent = isinstance(error, (ValueError, KeyError, TypeError)) or isinstance(error, AppError) and error.status < 500
            if permanent or attempts >= 3:
                with self.client.pipeline() as transaction:
                    transaction.hset(key, mapping={'state': 'FAILED', 'error_code': getattr(error, 'code', type(error).__name__)})
                    transaction.expire(key, TTL)
                    transaction.xadd(DEAD, {'job_id': identifier, 'error_code': getattr(error, 'code', type(error).__name__)}, maxlen=1000, approximate=False)
                    transaction.xack(STREAM, GROUP, entry_id)
                    transaction.xdel(STREAM, entry_id)
                    transaction.execute()
                return 'FAILED'
            self.client.hset(key, mapping={'state': 'RETRYING', 'error_code': type(error).__name__})
            return 'RETRYING'
        self.client.hset(key, mapping={'state': 'COMPLETED', 'result': json.dumps(result), 'completed_at': utc_text(now_utc())})
        self.client.expire(key, TTL)
        self.acknowledge(entry_id)
        return 'COMPLETED'

    def run_once(self, consumer, *, block_ms=1000, idle_ms=30000):
        self.ensure_group()
        reclaimed = self.client.xautoclaim(STREAM, GROUP, consumer, idle_ms, start_id=self.claim_cursor, count=10)
        self.claim_cursor = reclaimed[0]
        entries = reclaimed[1]
        if not entries:
            batches = self.client.xreadgroup(GROUP, consumer, {STREAM: '>'}, count=10, block=block_ms)
            entries = [entry for _, batch in batches for entry in batch]
        for entry_id, fields in entries:
            self.process(entry_id, fields)
        self.client.set('happyclass:ai:worker-heartbeat', utc_text(now_utc()), ex=60)
        return len(entries)

    def overview(self):
        self.client.ping()
        failed = self.client.xrevrange(DEAD, count=20)
        current_failed = {}
        for _, row in failed:
            if self.client.hget(self.job_key(row['job_id']), 'state') == 'FAILED':
                current_failed.setdefault(row['job_id'], {'job_id': row['job_id'], 'error_code': row['error_code']})
        return {'enabled': True, 'ready': True, 'queued_or_pending': self.client.xlen(STREAM),
                'worker_heartbeat': self.client.get('happyclass:ai:worker-heartbeat'),
                'failed': list(current_failed.values())}

    def retry(self, identifier):
        from redis.exceptions import WatchError
        key = self.job_key(identifier)
        for _ in range(4):
            with self.client.pipeline() as transaction:
                try:
                    transaction.watch(key, STREAM)
                    item = transaction.hgetall(key)
                    if not item:
                        raise AppError(404, 'JOB_NOT_FOUND', '任务已过保留期或不存在')
                    if item['state'] != 'FAILED':
                        raise AppError(409, 'JOB_NOT_FAILED', '仅可重试失败任务')
                    if transaction.xlen(STREAM) >= int(os.getenv('EMOJI_QUEUE_CAPACITY', '10000')):
                        raise AppError(503, 'QUEUE_FULL', '队列已满，请稍后重试')
                    if not hmac.compare_digest(signature(item['envelope']), item['signature']):
                        raise AppError(409, 'INVALID_ENVELOPE', '任务签名无效，不能重试')
                    transaction.multi()
                    transaction.hset(key, mapping={'state': 'QUEUED', 'attempts': '0', 'error_code': ''})
                    transaction.xadd(STREAM, {'job_id': identifier, 'envelope': item['envelope'], 'signature': item['signature']})
                    transaction.execute()
                    return {'job_id': identifier, 'state': 'QUEUED'}
                except WatchError:
                    continue
        raise AppError(503, 'QUEUE_BUSY', '任务状态正在变化，请刷新后重试')
