import { h, ref, onMounted, onBeforeUnmount } from 'vue';
import { api } from './api.js';
const kinds = [['ALL', '全部消息'], ['LEAVE', '课堂请假'], ['QUESTION', '问题回复'], ['GUIDE', '学习指引'], ['BUDDY', '好友学伴']];
const stamp = value => new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));

export const MessagesPanel = {
  emits: ['expired', 'navigate', 'unread-change'],
  setup(_, { emit }) {
    const items = ref([]), unread = ref(false), kind = ref('ALL'), unreadCount = ref(0), total = ref(0), offset = ref(0), busy = ref(false), error = ref('');
    let alive = true, readAbort, writeAbort;
    function fail(e) { if (e.status === 401) emit('expired'); else error.value = e.message; }
    async function load(page = 0) {
      readAbort?.abort(); const controller = new AbortController(); readAbort = controller; busy.value = true; error.value = '';
      try {
        const query = new URLSearchParams({ unread: String(unread.value), kind: kind.value, limit: '10', offset: String(page) });
        let r = await api('/api/messages?' + query, { signal: controller.signal });
        if (!alive || controller.signal.aborted) return;
        const last = Math.max(0, Math.floor((r.data.total - 1) / 10) * 10);
        if (page > last) { page = last; query.set('offset', String(page)); r = await api('/api/messages?' + query, { signal: controller.signal }); }
        if (!alive || controller.signal.aborted) return;
        items.value = r.data.items; total.value = r.data.total; offset.value = page; unreadCount.value = r.data.unread_count; emit('unread-change', unreadCount.value);
      } catch (e) { if (alive && !controller.signal.aborted) fail(e); }
      finally { if (alive && readAbort === controller) busy.value = false; }
    }
    async function mark(item, open = false) {
      if (busy.value) return;
      busy.value = true; error.value = ''; writeAbort = new AbortController();
      try {
        const r = await api(item ? `/api/messages/${item.id}/read` : '/api/messages/read-all', { method: 'PUT', signal: writeAbort.signal });
        if (!alive) return;
        unreadCount.value = r.data.unread_count; emit('unread-change', unreadCount.value);
        if (open) emit('navigate', { tab: item.target_tab, sessionId: item.session_id, courseId: item.course_id, view: item.kind === 'GUIDE' ? 'guide' : item.kind === 'QUESTION' ? 'questions' : undefined });
      } catch (e) { if (alive && !writeAbort.signal.aborted) fail(e); }
      finally { if (alive) busy.value = false; }
      if (alive && !error.value && !open) await load(offset.value);
    }
    onMounted(load); onBeforeUnmount(() => { alive = false; readAbort?.abort(); writeAbort?.abort(); });
    return () => h('section', { class: 'messages-panel', 'aria-busy': busy.value }, [
      h('div', { class: 'section-title' }, [h('div', [h('p', { class: 'campus-eyebrow' }, 'INBOX / 与课堂保持连接'), h('h2', '消息中心')]), h('div', { class: 'guide-actions' }, [h('button', { class: 'quiet-button', disabled: busy.value, onClick: () => load(offset.value) }, '刷新消息'), h('button', { class: 'secondary-button', disabled: busy.value || !unreadCount.value, onClick: () => mark(null) }, '全部标为已读')])]),
      h('div', { class: 'extension-filters' }, [h('select', { name: 'message_kind', 'aria-label': '消息类型', value: kind.value, disabled: busy.value, onChange: e => { kind.value = e.target.value; load(); } }, kinds.map(([value, text]) => h('option', { value }, text))), h('label', { class: 'message-unread-toggle' }, [h('input', { type: 'checkbox', checked: unread.value, disabled: busy.value, onChange: e => { unread.value = e.target.checked; load(); } }), `只看未读（${unreadCount.value}）`])]),
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null,
      busy.value ? h('p', { class: 'data-note', role: 'status' }, '正在更新消息…') : null,
      h('div', { class: 'message-list' }, items.value.map(item => h('article', { key: item.id, class: ['message-card', { unread: !item.read_at }] }, [h('div', { class: 'message-dot', 'aria-label': item.read_at ? '已读' : '未读' }), h('div', { class: 'message-body' }, [h('div', { class: 'section-title' }, [h('h3', item.title), h('time', { datetime: item.created_at }, stamp(item.created_at))]), h('p', item.body), h('div', { class: 'guide-actions' }, [h('button', { class: 'quiet-button', disabled: busy.value, onClick: () => mark(item, true) }, '查看详情'), !item.read_at ? h('button', { class: 'quiet-button', disabled: busy.value, onClick: () => mark(item) }, '标为已读') : null])])]))),
      !busy.value && !items.value.length ? h('div', { class: 'empty-state' }, [h('h3', unread.value ? '未读消息已处理完' : '暂时没有消息'), h('p', '请假进展、课堂回复、学习指引和学伴动态会在这里通知你。')]) : null,
      total.value > 10 || offset.value ? h('div', { class: 'pagination' }, [h('button', { disabled: busy.value || !offset.value, onClick: () => load(offset.value - 10) }, '上一页消息'), h('span', `共 ${total.value} 条 · 第 ${offset.value / 10 + 1} 页`), h('button', { disabled: busy.value || offset.value + 10 >= total.value, onClick: () => load(offset.value + 10) }, '下一页消息')]) : null,
    ]);
  },
};
