import json
import os
import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest

fakeredis = pytest.importorskip('fakeredis')
from ai_service import result_queue as module
from backend.app.models.ai import AiBatchRequest
from backend.app.models.classroom import now_utc
from backend.app.repositories.database import connect
from tests.test_classroom import actors, classroom_for, HEADERS
from tests.test_ai_ingest import batch, TOKEN, AUTH


@pytest.fixture(autouse=True)
def credential(monkeypatch):
    monkeypatch.setenv('EMOJI_AI_INGEST_TOKEN', TOKEN)
    monkeypatch.setenv('EMOJI_AI_MIN_CONFIDENCE', '.70')


@pytest.fixture
def queue(monkeypatch):
    value = module.ResultQueue(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr('backend.app.controllers.ai_queue.get_queue', lambda: value)
    return value


def entries(queue):
    queue.ensure_group()
    return queue.client.xreadgroup(module.GROUP, 'test', {module.STREAM: '>'}, count=10)[0][1]


def test_async_accept_then_store_once_and_keep_event_time_after_class_ends(actors, queue, monkeypatch):
    payload = batch(classroom_for(actors))
    client = actors['admin']['client']
    assert client.post('/api/ai/queued-results', json=payload).status_code == 401
    first = client.post('/api/ai/queued-results', json=payload, headers=AUTH)
    assert first.status_code == 202
    identifier = first.json()['data']['job_id']
    assert client.post('/api/ai/queued-results', json=payload, headers=AUTH).status_code == 200
    assert client.post('/api/ai/queued-results', json={**payload, 'faces': []}, headers=AUTH).status_code == 409
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 0
    # Processing may occur after the classroom closes; accepted event time remains authoritative.
    later = now_utc() + timedelta(hours=3)
    monkeypatch.setattr('backend.app.services.ai.now_utc', lambda: later)
    assert queue.run_once('worker-a', block_ms=1, idle_ms=0) == 1
    assert queue.client.hget(queue.job_key(identifier), 'state') == 'COMPLETED'
    assert queue.client.xlen(module.STREAM) == 0
    with connect() as connection:
        assert connection.execute('SELECT count(*),min(user_id),min(source) FROM emoji_records').fetchone() == (1, None, 'AI')
    assert actors['teacher']['client'].get('/api/ai/queue/status').status_code == 403


def test_worker_crash_after_commit_before_ack_does_not_duplicate(actors, queue, monkeypatch):
    payload = AiBatchRequest.model_validate(batch(classroom_for(actors)))
    identifier = queue.enqueue(payload)['job_id']
    entry_id, fields = entries(queue)[0]
    original = queue.acknowledge
    monkeypatch.setattr(queue, 'acknowledge', lambda _: (_ for _ in ()).throw(ConnectionError()))
    with pytest.raises(ConnectionError):
        queue.process(entry_id, fields)
    monkeypatch.setattr(queue, 'acknowledge', original)
    queue.run_once('replacement-worker', block_ms=1, idle_ms=0)
    assert queue.client.hget(queue.job_key(identifier), 'state') == 'COMPLETED'
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 1


def test_retry_limit_dead_letter_manual_retry_and_signed_message_validation(actors, queue, monkeypatch):
    payload = AiBatchRequest.model_validate(batch(classroom_for(actors)))
    identifier = queue.enqueue(payload)['job_id']
    entry_id, fields = entries(queue)[0]
    original = module.ingest_results
    monkeypatch.setattr(module, 'ingest_results', lambda *_, **__: (_ for _ in ()).throw(sqlite3.OperationalError()))
    assert [queue.process(entry_id, fields) for _ in range(3)] == ['RETRYING', 'RETRYING', 'FAILED']
    assert queue.client.xlen(module.DEAD) == 1
    admin = actors['admin']['client']
    assert admin.get('/api/ai/queue/status').json()['data']['failed'][0]['job_id'] == identifier
    assert actors['student']['client'].post(f'/api/ai/queue/jobs/{identifier}/retry', headers=HEADERS).status_code == 403
    assert admin.post(f'/api/ai/queue/jobs/{identifier}/retry', headers=HEADERS).status_code == 200
    monkeypatch.setattr(module, 'ingest_results', original)
    queue.run_once('recovered-worker', block_ms=1, idle_ms=0)
    assert queue.client.hget(queue.job_key(identifier), 'state') == 'COMPLETED'
    other = queue.enqueue(AiBatchRequest.model_validate({**payload.model_dump(mode='json'), 'batch_id': str(uuid4())}))['job_id']
    entry_id, fields = entries(queue)[0]
    fields['envelope'] = fields['envelope'].replace('HAPPY', 'ANGRY')
    assert queue.process(entry_id, fields) == 'FAILED'
    assert queue.client.hget(queue.job_key(other), 'error_code') == 'ValueError'
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 1


def test_queue_limits_reject_raw_images_and_secrets_are_not_in_broker(actors, queue, monkeypatch):
    payload = batch(classroom_for(actors))
    client = actors['admin']['client']
    assert client.post('/api/ai/queued-results', json={**payload, 'image': 'private pixels'}, headers=AUTH).status_code == 422
    queue.enqueue(AiBatchRequest.model_validate(payload))
    broker = json.dumps(queue.client.xrange(module.STREAM))
    assert TOKEN not in broker and 'private pixels' not in broker
    monkeypatch.setenv('EMOJI_QUEUE_CAPACITY', '1')
    second = {**payload, 'batch_id': str(uuid4())}
    assert client.post('/api/ai/queued-results', json=second, headers=AUTH).status_code == 503


def test_expired_job_metadata_cannot_be_resurrected_by_an_old_delivery(actors, queue):
    identifier = queue.enqueue(AiBatchRequest.model_validate(batch(classroom_for(actors))))['job_id']
    entry_id, fields = entries(queue)[0]
    queue.client.delete(queue.job_key(identifier))  # Simulate the documented seven-day expiration.
    assert queue.process(entry_id, fields) == 'EXPIRED'
    assert not queue.client.exists(queue.job_key(identifier))
    assert queue.client.xlen(module.STREAM) == 0
    with connect() as connection:
        assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 0


@pytest.mark.skipif(not os.getenv('EMOJI_TEST_REDIS_URL'), reason='Dedicated real Redis integration server not configured')
def test_real_redis_consumer_recovery(actors, monkeypatch):
    from redis import Redis
    prefix = 'happyclass:test:' + uuid4().hex
    monkeypatch.setattr(module, 'STREAM', prefix + ':stream')
    monkeypatch.setattr(module, 'DEAD', prefix + ':dead')
    monkeypatch.setattr(module, 'GROUP', prefix + ':group')
    client = Redis.from_url(os.environ['EMOJI_TEST_REDIS_URL'], decode_responses=True)
    queue = module.ResultQueue(client)
    queue.job_key = lambda identifier: prefix + ':job:' + identifier
    payload = AiBatchRequest.model_validate(batch(classroom_for(actors)))
    result = queue.enqueue(payload)
    try:
        entries(queue)  # Simulate delivery to a worker which dies before committing.
        assert queue.run_once('replacement', block_ms=1, idle_ms=0) == 1
        assert client.hget(queue.job_key(result['job_id']), 'state') == 'COMPLETED'
        with connect() as connection:
            assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 1
        # A process can also die after DB commit but before acknowledging Redis.
        second = queue.enqueue(AiBatchRequest.model_validate({**payload.model_dump(mode='json'), 'batch_id': str(uuid4())}))
        acknowledge = queue.acknowledge
        monkeypatch.setattr(queue, 'acknowledge', lambda _: (_ for _ in ()).throw(ConnectionError('simulated loss after commit')))
        with pytest.raises(ConnectionError):
            queue.run_once('dies-after-commit', block_ms=1, idle_ms=0)
        monkeypatch.setattr(queue, 'acknowledge', acknowledge)
        assert queue.run_once('recovers-after-commit', block_ms=1, idle_ms=0) == 1
        assert client.hget(queue.job_key(second['job_id']), 'state') == 'COMPLETED'
        with connect() as connection:
            assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 2
        # Exercise retry/dead-letter/replay against actual Redis commands too.
        third = queue.enqueue(AiBatchRequest.model_validate({**payload.model_dump(mode='json'), 'batch_id': str(uuid4())}))
        ingest = module.ingest_results
        monkeypatch.setattr(module, 'ingest_results', lambda *_, **__: (_ for _ in ()).throw(sqlite3.OperationalError('simulated outage')))
        for _ in range(3):
            assert queue.run_once('failed-writer', block_ms=1, idle_ms=0) == 1
        assert client.hget(queue.job_key(third['job_id']), 'state') == 'FAILED'
        assert client.xlen(module.DEAD) == 1
        monkeypatch.setattr(module, 'ingest_results', ingest)
        queue.retry(third['job_id'])
        assert queue.run_once('replay-writer', block_ms=1, idle_ms=0) == 1
        assert client.hget(queue.job_key(third['job_id']), 'state') == 'COMPLETED'
        with connect() as connection:
            assert connection.execute('SELECT count(*) FROM emoji_records').fetchone()[0] == 3
        assert client.xlen(module.STREAM) == 0
    finally:
        for key in client.scan_iter(prefix + ':*'):
            client.delete(key)
