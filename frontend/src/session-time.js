// Availability flags from a response age while the page stays open.
export function feedbackAvailable(item, now = Date.now()) {
  if (!item) return false;
  const start = Date.parse(item.starts_at), close = Date.parse(item.feedback_closes_at);
  if (Number.isFinite(start) && Number.isFinite(close)) return start <= now && now < close;
  return item.can_feedback === true && (!item.feedback_closes_at || now < close);
}
export function sessionAt(item, now = Date.now()) {
  const start = Date.parse(item.starts_at), end = Date.parse(item.ends_at);
  return Number.isFinite(start) && Number.isFinite(end)
    ? { ...item, status: now < start ? 'UPCOMING' : now >= end ? 'ENDED' : 'ONGOING' }
    : item;
}
