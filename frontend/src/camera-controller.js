// One frame at a time. A failed frame keeps its ID so a retry cannot double count.
export function createCameraController({ getMedia, attach, capture, send, onState, onResult, onError, getInterval = () => 3000, newId = () => crypto.randomUUID(), schedule = setTimeout, cancel = clearTimeout }) {
  let generation = 0, stream = null, timer = null, abort = null, pending = null, failures = 0;
  function stop() {
    generation += 1;
    if (timer !== null) cancel(timer);
    timer = null; abort?.abort(); abort = null;
    stream?.getTracks().forEach(track => track.stop()); stream = null;
    pending = null; failures = 0; onState('stopped');
  }
  async function tick(token) {
    if (token !== generation) return;
    abort = new AbortController();
    try {
      if (!pending) {
        const blob = await capture();
        if (token !== generation) return;
        pending = { blob, id: newId() };
      }
      const result = await send(pending.blob, pending.id, abort.signal);
      if (token !== generation) return;
      pending = null; failures = 0; onResult(result);
    } catch (error) {
      if (token !== generation) return;
      failures += 1; onError(error);
      if (![0, 429, 503].includes(error.status) || failures >= 3) { stop(); return; }
    }
    const interval = Math.max(3000, Math.min(60000, Number(getInterval()) || 3000));
    if (token === generation) timer = schedule(() => tick(token), Math.min(60000, interval * 2 ** failures));
  }
  async function start() {
    stop();
    const token = generation;
    onState('starting');
    try {
      const acquired = await getMedia();
      if (token !== generation) { acquired.getTracks().forEach(track => track.stop()); return; }
      stream = acquired;
      stream.getTracks().forEach(track => track.addEventListener?.('ended', () => { if (token === generation) stop(); }));
      await attach(stream);
      if (token !== generation) return;
      onState('running');
      await tick(token);
    } catch (error) {
      if (token === generation) { stop(); onError(error); }
    }
  }
  return { start, stop };
}
