const assert = require('node:assert/strict');

(async () => {
  const { createCameraController } = await import('../frontend/src/camera-controller.js');
  const deferred = () => { let resolve; const promise = new Promise(done => resolve = done); return { promise, resolve }; };
  function harness(extra = {}) {
    const events = { stopped: 0, results: [], errors: [], timers: [], states: [], sends: [] };
    const stream = { getTracks: () => [{ stop: () => events.stopped++ }] };
    const camera = createCameraController({
      getMedia: async () => stream, attach: async () => {}, capture: async () => new Blob(['jpeg']),
      send: async (blob, id) => { events.sends.push({ blob, id }); return { saved: 1 }; },
      onState: state => events.states.push(state), onResult: result => events.results.push(result), onError: error => events.errors.push(error),
      schedule: (fn, delay) => { events.timers.push({ fn, delay }); return events.timers.length; }, cancel: () => {}, newId: () => 'frame-id', ...extra,
    });
    return { camera, events, stream };
  }
  {
    const media = deferred();
    const h = harness({ getMedia: () => media.promise });
    const starting = h.camera.start(); h.camera.stop(); media.resolve(h.stream); await starting;
    assert.equal(h.events.stopped, 1, 'permission granted after stop must release the stream');
    assert.equal(h.events.sends.length, 0);
  }
  {
    const attempts = []; let captureCount = 0;
    const h = harness({ capture: async () => { captureCount++; return new Blob(['same-frame']); }, send: async (blob, id) => { attempts.push({ blob, id }); if (attempts.length === 1) throw Object.assign(new Error('offline'), { status: 503 }); return { saved: 1 }; } });
    await h.camera.start();
    assert.equal(h.events.timers[0].delay, 6000);
    await h.events.timers[0].fn();
    assert.equal(captureCount, 1, 'retry must preserve the frame');
    assert.equal(attempts[0].blob, attempts[1].blob);
    assert.equal(attempts[0].id, attempts[1].id);
    assert.equal(h.events.results.length, 1);
    h.camera.stop();
  }
  {
    const response = deferred(); let signal;
    const h = harness({ send: (blob, id, nextSignal) => { signal = nextSignal; return response.promise; } });
    const starting = h.camera.start();
    await new Promise(setImmediate);
    assert.equal(h.events.timers.length, 0, 'no second frame while the first request is pending');
    h.camera.stop(); assert(signal.aborted); response.resolve({ saved: 1 }); await starting;
    assert.equal(h.events.results.length, 0, 'ignore results after leaving the classroom');
    assert.equal(h.events.timers.length, 0);
    assert.equal(h.events.stopped, 1);
  }
  {
    const h = harness({ getInterval: () => 10000 });
    await h.camera.start();
    assert.equal(h.events.timers[0].delay, 10000, 'sampling frequency must use the selected interval');
    h.camera.stop();
  }
  {
    const h = harness({ send: async () => { throw Object.assign(new Error('class ended'), { status: 409 }); } });
    await h.camera.start();
    assert.equal(h.events.stopped, 1);
    assert.equal(h.events.states.at(-1), 'stopped');
    assert.equal(h.events.timers.length, 0);
  }
  {
    const denied = Object.assign(new Error('camera permission denied'), { name: 'NotAllowedError' });
    const h = harness({ getMedia: async () => { throw denied; } });
    await h.camera.start();
    assert.equal(h.events.errors[0], denied);
    assert.equal(h.events.states.at(-1), 'stopped');
    assert.equal(h.events.sends.length, 0);
    assert.equal(h.events.timers.length, 0);
  }
  {
    let ended, released = 0, cancelled = 0;
    const h = harness({ getMedia: async () => ({ getTracks: () => [{ stop: () => released++, addEventListener: (name, callback) => { assert.equal(name, 'ended'); ended = callback; } }] }), cancel: () => cancelled++ });
    await h.camera.start();
    assert.equal(h.events.results.length, 1);
    ended(); ended();
    assert.equal(released, 1, 'device removal releases this stream only once');
    assert.equal(cancelled, 1, 'device removal cancels scheduled capture');
    assert.equal(h.events.states.at(-1), 'stopped');
  }
  {
    const h = harness({ capture: async () => { throw new Error('no readable camera frame'); } });
    await h.camera.start();
    assert.equal(h.events.stopped, 1);
    assert.equal(h.events.states.at(-1), 'stopped');
    assert.equal(h.events.sends.length, 0);
    assert.equal(h.events.timers.length, 0);
  }
  console.log('Camera lifecycle checks passed: permission cancellation/denial, idempotent retry, no overlap, abort, device removal, unreadable frames and stop.');
})().catch(error => { console.error(error); process.exitCode = 1; });
