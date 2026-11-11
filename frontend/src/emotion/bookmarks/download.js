import { onBeforeUnmount, ref } from 'vue';
import { downloadCsv } from '../../api.js';
import { bookmarkUrl } from './client.js';

export function useBookmarkDownload(expired) {
  const busy = ref(false);
  const status = ref('');
  let request;

  function abort() {
    request?.abort();
  }

  onBeforeUnmount(abort);

  async function download(path, params, success) {
    if (busy.value) {
      abort();
      return;
    }
    const active = new AbortController();
    request = active;
    busy.value = true;
    status.value = '';
    try {
      await downloadCsv(bookmarkUrl(path, params), active.signal);
      status.value = success;
    } catch (failure) {
      if (!active.signal.aborted) {
        if (failure.status === 401) expired?.();
        else status.value = failure.message;
      }
    } finally {
      if (request === active) {
        request = undefined;
        busy.value = false;
      }
    }
  }

  return { busy, status, download };
}
