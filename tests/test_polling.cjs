const assert = require('node:assert/strict');
const tick = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

(async () => {
  const { createPoller } = await import('../frontend/src/polling.js');
  const requests = [], values = [], errors = [], timers = new Map();
  let timerID = 0, visible = true;
  const poller = createPoller({
    load: (key, signal) => new Promise((resolve, reject) => requests.push({ key, signal, resolve, reject })),
    onData: value => values.push(value), onError: error => errors.push(error.message),
    isVisible: () => visible,
    setTimer: callback => { timers.set(++timerID, callback); return timerID; },
    clearTimer: id => timers.delete(id),
  });
  poller.start('old');
  assert.equal(timers.size, 0, 'no next poll before the current request completes');
  poller.start('new');
  assert.equal(requests[0].signal.aborted, true);
  requests[0].resolve('stale'); requests[1].resolve('fresh'); await tick();
  assert.deepEqual(values, ['fresh'], 'a switched classroom cannot be overwritten by stale data');
  assert.equal(timers.size, 1);
  const runTimer = () => { const [id, callback] = timers.entries().next().value; timers.delete(id); callback(); };
  runTimer();
  assert.equal(requests.length, 3); assert.equal(timers.size, 0);
  poller.stop();
  assert.equal(requests[2].signal.aborted, true);
  requests[2].resolve('after-stop'); await tick();
  assert.deepEqual(values, ['fresh']); assert.equal(timers.size, 0);
  visible = false; poller.start('hidden');
  assert.equal(requests.length, 3, 'hidden tabs make no requests');
  visible = true; runTimer();
  requests[3].reject(new Error('offline')); await tick();
  assert.deepEqual(errors, ['offline']); assert.equal(timers.size, 1, 'network failures schedule a retry');
  poller.start('manual', { repeat: false });
  requests[4].resolve('manual-result'); await tick();
  assert.equal(timers.size, 0, 'manual refresh stays paused after completing');
  assert.deepEqual(values, ['fresh', 'manual-result']);
  poller.stop();
  console.log('Polling checks passed: cancellation, stale response isolation, non-overlap, visibility, retry, manual refresh.');
})().catch(error => { console.error(error); process.exitCode = 1; });
