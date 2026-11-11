import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue';
import { api, downloadCsv } from '../../api.js';

const base = '/api/emotion-feedback';

export function url(path, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') {
      query.set(key, String(value));
    }
  }
  const suffix = query.toString();
  return base + path + (suffix ? '?' + suffix : '');
}

export async function read(path, params, signal) {
  return (await api(url(path, params), { signal })).data;
}

export function csv(filters, signal) {
  return downloadCsv(url('/export.csv', filters), signal);
}

export function useResource(loader, expired) {
  const value = ref(null);
  const loading = ref(false);
  const error = ref('');
  let request;
  async function load(...args) {
    request?.abort();
    const current = new AbortController();
    request = current;
    loading.value = true;
    error.value = '';
    try {
      const next = await loader(current.signal, ...args);
      if (current.signal.aborted) return null;
      value.value = next;
      return next;
    } catch (failure) {
      if (!current.signal.aborted) {
        if (failure.status === 401) expired?.();
        else error.value = failure.message;
      }
      return null;
    } finally {
      if (request === current) {
        request = undefined;
        loading.value = false;
      }
    }
  }
  function clear() {
    request?.abort();
    request = undefined;
    loading.value = false;
    value.value = null;
    error.value = '';
  }
  function replace(next) {
    clear();
    value.value = next;
  }
  onBeforeUnmount(clear);
  return { value, loading, error, load, clear, replace };
}

export function useCommand(expired, resolveUrl = url) {
  const busy = ref(false);
  const error = ref('');
  const conflict = ref(false);
  let last;
  let disposed = false;

  onBeforeUnmount(() => { disposed = true; });

  async function run(path, payload, settings = {}) {
    if (busy.value) return null;
    const { method = 'POST', params, idempotent = true } = settings;
    const endpoint = resolveUrl(path, params);
    const fingerprint = JSON.stringify([endpoint, method, payload]);
    const requestId = last?.fingerprint === fingerprint
      ? last.requestId
      : crypto.randomUUID();
    last = { fingerprint, requestId };
    busy.value = true;
    error.value = '';
    conflict.value = false;
    try {
      const body = idempotent ? { ...payload, request_id: requestId } : payload;
      const result = await api(endpoint, { method, body });
      last = undefined;
      return disposed ? null : result.data;
    } catch (failure) {
      if (disposed) return null;
      if (failure.status === 401) expired?.();
      else error.value = failure.message;
      conflict.value = failure.status === 409;
      return null;
    } finally {
      busy.value = false;
    }
  }

  function reset() {
    error.value = '';
    conflict.value = false;
    // A retry with the same payload retains its request key.
  }

  return { busy, error, conflict, run, reset };
}

export function useDraft(initial, notify, busy) {
  const copy = value => JSON.parse(JSON.stringify(value));
  const values = reactive(copy(initial));
  const baseline = ref(JSON.stringify(initial));
  const dirty = computed(() => JSON.stringify(values) !== baseline.value);

  function restore(next = JSON.parse(baseline.value)) {
    const snapshot = copy(next);
    for (const key of Object.keys(values)) {
      if (!(key in snapshot)) delete values[key];
    }
    Object.assign(values, snapshot);
    baseline.value = JSON.stringify(values);
  }

  watch(() => dirty.value || Boolean(busy?.value), value => notify?.(value), {
    flush: 'sync',
  });
  onBeforeUnmount(() => notify?.(false));

  return { values, dirty, restore };
}

export function defaultFilters() {
  return {
    course_id: null,
    session_id: null,
    state: 'ALL',
    reason: 'ALL',
    emotion: 'ALL',
    priority: 'ALL',
    search: '',
    watched: false,
    overdue: false,
    review_overdue: false,
    active_only: false,
    data_scope: 'ALL',
    sort: 'UPDATED',
  };
}

export function scoped(filters) {
  return {
    course_id: filters.course_id,
    session_id: filters.session_id,
    data_scope: filters.data_scope,
  };
}

export function normalizeFilters(values) {
  return { ...defaultFilters(), ...values, search: (values.search || '').trim() };
}
