export function createPoller({ load, onData, onError, interval = 5000, isVisible = () => typeof document === 'undefined' || document.visibilityState !== 'hidden', setTimer = setTimeout, clearTimer = clearTimeout }) {
  let generation = 0, active = false, timer = null, controller = null, key, repeat = true;
  function stop() {
    active = false;
    generation += 1;
    if (timer !== null) clearTimer(timer);
    timer = null;
    controller?.abort();
    controller = null;
  }
  function schedule(current) {
    if (active && current === generation && repeat) timer = setTimer(() => { timer = null; run(current); }, interval);
    else if (current === generation) active = false;
  }
  async function run(current) {
    if (!active || current !== generation) return;
    if (!isVisible()) { schedule(current); return; }
    const request = new AbortController();
    controller = request;
    try {
      const result = await load(key, request.signal);
      if (active && current === generation && !request.signal.aborted) onData(result);
    } catch (error) {
      if (active && current === generation && !request.signal.aborted) onError(error);
    } finally {
      if (current === generation) { controller = null; schedule(current); }
    }
  }
  return { stop, start(value, options = {}) { stop(); key = value; repeat = options.repeat ?? true; active = true; run(generation); } };
}
