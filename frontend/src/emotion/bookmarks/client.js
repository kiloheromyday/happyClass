import { api, downloadCsv } from '../../api.js';
import { useCommand, useResource } from '../feedback/client.js';

const base = '/api/classroom-bookmarks';

export function bookmarkUrl(path, filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return base + path + (query ? '?' + query : '');
}

export async function readBookmarks(path, filters, signal) {
  const result = await api(bookmarkUrl(path, filters), { signal });
  return result.data;
}

export function useBookmarkResource(path, expired) {
  return useResource((signal, filters = {}) => readBookmarks(
    typeof path === 'function' ? path() : path, filters, signal,
  ), expired);
}

export function useBookmarkWrite(expired) {
  return useCommand(expired, bookmarkUrl);
}

export function sessionPath(sessionId, tail) {
  return '/sessions/' + sessionId + '/' + tail;
}

export function exportTimeline(sessionId, bucket, signal) {
  return downloadCsv(bookmarkUrl(sessionPath(sessionId, 'timeline.csv'), { bucket }), signal);
}

export function minuteText(minute) {
  return '开课后 ' + minute + ' 分钟';
}

export function rangeText(start, end) {
  return start + '–' + end + ' 分钟';
}

export function within(item, minute) {
  return item.start_minute <= minute && minute < item.end_minute;
}
