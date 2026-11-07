import { Avatar } from './avatar.js';
import { h, ref, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api } from './api.js';
import { icon, learningStyles } from './ui.js';

const dateText = value => new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value));

export const BuddyWallPanel = {
  props: ['ownerId', 'user'], emits: ['expired', 'back', 'dirty-change'],
  setup(props, { emit }) {
    const owner = ref(null), items = ref([]), total = ref(0), offset = ref(0), mine = ref(false), mode = ref('wall');
    const content = ref(''), visibility = ref('ANONYMOUS'), editing = ref(null), editText = ref(''), deleting = ref(null);
    const loading = ref(false), busy = ref(false), error = ref(''), message = ref(''), readFailed = ref(false), canPost = ref(false);
    const sourceId = ref(null), sourceData = ref(null), sourceLoading = ref(false);
    const dirty = computed(() => !!content.value.trim() || !!(editing.value && editText.value !== editing.value.content));
    let alive = true, readAbort, writeAbort, sourceAbort, retry, timer;
    watch(dirty, value => emit('dirty-change', value), { flush: 'sync' });
    const fail = failure => { if (failure.status === 401) emit('expired'); else error.value = failure.message; };
    const beforeUnload = event => { if (dirty.value) { event.preventDefault(); event.returnValue = ''; } };
    function hideSource() { sourceAbort?.abort(); sourceId.value = null; sourceData.value = null; sourceLoading.value = false; }
    async function load(nextOffset = offset.value, quiet = false) {
      readAbort?.abort(); const abort = new AbortController(); readAbort = abort;
      const view = mode.value;
      if (!quiet) { loading.value = true; error.value = ''; hideSource(); }
      const fetchPage = async page => {
        const query = new URLSearchParams({ limit: '12', offset: String(page) });
        if (view === 'wall') query.set('mine', String(mine.value));
        return (await api(`/api/buddy-wall/${view === 'sent' ? 'sent' : props.ownerId}?${query}`, { signal: abort.signal })).data;
      };
      try {
        let data = await fetchPage(nextOffset);
        if (!alive || abort.signal.aborted) return;
        const lastOffset = Math.max(0, Math.floor((data.total - 1) / 12) * 12);
        if (nextOffset > lastOffset) { nextOffset = lastOffset; data = await fetchPage(nextOffset); }
        if (alive && !abort.signal.aborted) { items.value = data.items; total.value = data.total; offset.value = nextOffset; if (data.owner) owner.value = data.owner; readFailed.value = false; if (view === 'wall') canPost.value = true; }
      } catch (failure) {
        if (alive && !abort.signal.aborted) {
          readFailed.value = true;
          if ([403, 404].includes(failure.status)) { items.value = []; total.value = 0; canPost.value = false; hideSource(); }
          if (!quiet || [401, 403, 404].includes(failure.status)) fail(failure);
        }
      } finally { if (alive && readAbort === abort) loading.value = false; }
    }
    async function send(event) {
      event.preventDefault(); if (busy.value || !canPost.value || !content.value.trim()) return;
      const body = { content: content.value.trim(), visibility: visibility.value }, signature = JSON.stringify(body);
      if (retry?.signature !== signature) retry = { signature, request_id: crypto.randomUUID() };
      const abort = new AbortController(); writeAbort = abort; busy.value = true; error.value = ''; message.value = '';
      try {
        const result = await api(`/api/buddy-wall/${props.ownerId}`, { method: 'POST', signal: abort.signal, body: { ...body, request_id: retry.request_id } });
        if (alive) { content.value = ''; visibility.value = 'ANONYMOUS'; retry = null; mine.value = false; message.value = result.message; await load(0); }
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) busy.value = false; }
    }
    async function showSource(item) {
      if (sourceId.value === item.id) { hideSource(); return; }
      hideSource(); const abort = new AbortController(); sourceAbort = abort;
      sourceId.value = item.id; sourceLoading.value = true; error.value = '';
      try {
        const result = await api(`/api/buddy-wall/${props.ownerId}/${item.id}/source`, { signal: abort.signal });
        if (alive && !abort.signal.aborted && sourceId.value === item.id) sourceData.value = result.data;
      } catch (failure) { if (alive && !abort.signal.aborted) { hideSource(); if (failure.status === 403) { items.value = []; total.value = 0; canPost.value = false; readFailed.value = true; } fail(failure); } }
      finally { if (alive && sourceAbort === abort) sourceLoading.value = false; }
    }
    async function save(event) {
      event.preventDefault(); const item = editing.value;
      if (busy.value || !item || !editText.value.trim()) return;
      const abort = new AbortController(); writeAbort = abort; busy.value = true; error.value = ''; message.value = '';
      try {
        const result = await api(`/api/buddy-wall/${props.ownerId}/${item.id}`, { method: 'PUT', signal: abort.signal, body: { content: editText.value.trim(), version: item.version } });
        if (alive) { editing.value = null; editText.value = ''; message.value = result.message; await load(); }
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) busy.value = false; }
    }
    async function remove(item) {
      if (busy.value || deleting.value !== item.id) return;
      const abort = new AbortController(); writeAbort = abort; busy.value = true; error.value = ''; message.value = '';
      try {
        await api(`/api/buddy-wall/${mode.value === 'sent' ? item.owner_id : props.ownerId}/${item.id}?version=${item.version}`, { method: 'DELETE', signal: abort.signal });
        if (alive) { deleting.value = null; message.value = '留言已删除'; await load(); }
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) busy.value = false; }
    }
    function refresh() { editing.value = null; editText.value = ''; deleting.value = null; message.value = ''; load(); }
    function switchMode(value) { if (dirty.value || editing.value || busy.value) return; mode.value = value; message.value = ''; deleting.value = null; load(0); }
    onMounted(() => {
      load(0);
      timer = setInterval(() => { if (mode.value === 'wall' && !document.hidden && !dirty.value && !editing.value && !sourceId.value && !busy.value && !loading.value) load(offset.value, true); }, 15000);
      if (typeof window !== 'undefined') window.addEventListener('beforeunload', beforeUnload);
    });
    onBeforeUnmount(() => { alive = false; readAbort?.abort(); writeAbort?.abort(); sourceAbort?.abort(); clearInterval(timer); emit('dirty-change', false); if (typeof window !== 'undefined') window.removeEventListener('beforeunload', beforeUnload); });
    const locked = () => busy.value || loading.value;
    function sourceCard() {
      const person = sourceData.value;
      return person ? h('div', { class: 'wall-source-card' }, [
        h('div', { class: 'buddy-person' }, [h(Avatar, { person }), h('div', { class: 'buddy-name' }, [h('strong', person.nickname || person.username), h('span', `@${person.username}`)])]),
        person.bio ? h('p', person.bio) : null,
        h('div', { class: 'buddy-traits' }, [person.major, person.grade, person.interests, person.learning_style ? learningStyles[person.learning_style] : ''].filter(Boolean).map(value => h('span', value))),
        person.study_goal ? h('p', ['学习目标 · ', person.study_goal]) : null,
      ]) : h('p', { class: 'data-note', role: 'status' }, sourceLoading.value ? '正在读取公开来源…' : '');
    }
    return () => h('section', { class: 'buddy-wall-panel', 'aria-busy': locked() }, [
      h('div', { class: 'section-title' }, [h('div', [h('p', { class: 'wall-eyebrow' }, '给学习留一点温暖'), h('h2', mode.value === 'sent' ? '我发出的留言' : props.ownerId === props.user.id ? '我的留言墙' : `${owner.value?.nickname || owner.value?.username || '学伴'}的留言墙`)]), h('button', { class: 'secondary-button', disabled: busy.value, onClick: () => emit('back') }, dirty.value ? '放弃草稿并返回学伴' : '返回学伴')]),
      h('div', { class: 'wall-tabs', role: 'group', 'aria-label': '留言墙视图' }, [['wall', '学伴留言墙'], ['sent', '我发出的留言']].map(([key, label]) => h('button', { class: { active: mode.value === key }, 'aria-pressed': mode.value === key, disabled: dirty.value || !!editing.value || busy.value, onClick: () => switchMode(key) }, label))),
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null,
      message.value ? h('p', { class: 'form-notice success', role: 'status' }, message.value) : null,
      readFailed.value && !error.value ? h('p', { class: 'data-note', role: 'status' }, '更新暂未成功，当前显示上次结果。可点击刷新重试。') : null,
      mode.value === 'wall' ? h('div', [
        h('p', { class: 'wall-audience' }, '这面墙对墙主及其已确认学伴可见。匿名留言不显示账号；内容中也请勿填写姓名或联系方式。'),
        h('form', { class: 'wall-compose', onSubmit: send }, [
          h('label', { class: 'field' }, [h('span', '留一句鼓励，分享一个想法'), h('textarea', { name: 'wall_content', value: content.value, maxlength: 600, rows: 3, required: true, disabled: busy.value || !canPost.value || !!editing.value, placeholder: '今天有什么想和学伴分享的？', onInput: event => content.value = event.target.value })]),
          h('div', { class: 'wall-visibility', role: 'group', 'aria-label': '留言来源公开方式' }, [['ANONYMOUS', '匿名留言'], ['REVEALABLE', '允许点击查看来源']].map(([value, label]) => h('label', [h('input', { name: 'wall_visibility', type: 'radio', value, checked: visibility.value === value, disabled: busy.value || !canPost.value || !!editing.value, onChange: () => visibility.value = value }), label]))),
          h('p', { class: 'wall-consent-note' }, visibility.value === 'ANONYMOUS' ? '匿名发布后，墙主和学伴都不能点击查看你的身份。' : '选择此项，墙内成员可点击查看你的用户名、昵称和公开学习资料。发布后不能更改此项。'),
          h('div', { class: 'wall-compose-bottom' }, [h('span', { class: 'muted' }, `${content.value.length} / 600`), h('div', { class: 'wall-actions' }, [content.value ? h('button', { type: 'button', class: 'quiet-button', disabled: busy.value, onClick: () => { content.value = ''; retry = null; } }, '清空留言草稿') : null, h('button', { class: 'primary-button', disabled: locked() || !canPost.value || !!editing.value || !content.value.trim() }, busy.value ? '正在送达…' : '送出留言')])]),
        ]),
      ]) : h('p', { class: 'data-note' }, '这里保留自己发出的留言，解除学伴关系后仍可删除自己的内容。'),
      h('div', { class: 'wall-toolbar' }, [mode.value === 'wall' ? h('div', { class: 'wall-filters' }, [[false, '全部留言'], [true, '我在这面墙的留言']].map(([value, label]) => h('button', { class: { active: mine.value === value }, 'aria-pressed': mine.value === value, disabled: locked() || !!editing.value, onClick: () => { mine.value = value; message.value = ''; load(0); } }, label))) : h('span', { class: 'muted' }, `共 ${total.value} 条`), h('button', { class: 'quiet-button', disabled: locked(), onClick: refresh }, [icon('refresh', 15), editing.value ? '放弃修改并刷新' : '刷新留言'])]),
      loading.value ? h('p', { class: 'data-note', role: 'status' }, '正在整理留言…') : null,
      !loading.value && !readFailed.value && !items.value.length ? h('div', { class: 'empty-state wall-empty' }, [icon('leaf', 30), h('h3', '这面墙还留着空白'), h('p', mode.value === 'sent' ? '送出一句鼓励，让学习多一点陪伴。' : '第一句温暖的话，可以从你开始。')]) : null,
      h('div', { class: 'wall-message-list' }, items.value.map(item => h('article', { class: ['wall-message-card', { 'source-allowed': item.visibility === 'REVEALABLE' }], key: item.id }, [
        h('div', { class: 'wall-message-top' }, [h('span', { class: 'wall-author-label' }, item.is_mine ? '我留下的' : item.visibility === 'ANONYMOUS' ? '匿名学伴' : '学伴留言'), h('time', { datetime: item.created_at }, dateText(item.created_at))]),
        mode.value === 'sent' ? h('p', { class: 'wall-destination' }, `留在 ${item.owner_nickname || item.owner_username} 的墙上`) : null,
        h('p', { class: 'wall-message-copy' }, item.content),
        h('div', { class: 'wall-message-bottom' }, [
          mode.value === 'wall' && item.visibility === 'REVEALABLE' ? h('button', { class: 'wall-source-button', 'aria-expanded': sourceId.value === item.id, disabled: busy.value, onClick: () => showSource(item) }, [icon('profile', 14), sourceId.value === item.id ? '收起来源' : '点击查看来源']) : h('span', { class: 'wall-anonymous-note' }, item.visibility === 'ANONYMOUS' ? '来源保密' : '允许查看来源'),
          h('div', { class: 'wall-actions' }, [item.is_mine && mode.value === 'wall' ? h('button', { class: 'quiet-button', disabled: locked() || !!editing.value || !!content.value.trim(), onClick: () => { editing.value = item; editText.value = item.content; error.value = ''; message.value = ''; deleting.value = null; } }, '编辑留言') : null, item.can_delete ? h('button', { class: 'quiet-button', disabled: locked() || !!editing.value, onClick: () => deleting.value = item.id }, '删除留言') : null]),
        ]),
        sourceId.value === item.id ? sourceCard() : null,
        editing.value?.id === item.id ? h('form', { class: 'wall-edit-form', onSubmit: save }, [h('label', { class: 'field' }, [h('span', '修改留言（来源公开方式保持不变）'), h('textarea', { name: 'wall_edit_content', value: editText.value, maxlength: 600, rows: 3, required: true, disabled: busy.value, onInput: event => editText.value = event.target.value })]), h('div', { class: 'wall-actions' }, [h('button', { type: 'button', class: 'secondary-button', disabled: busy.value, onClick: () => { editing.value = null; editText.value = ''; } }, dirty.value ? '放弃留言修改' : '取消编辑'), h('button', { class: 'primary-button', disabled: busy.value || !editText.value.trim() || editText.value === item.content }, '保存留言')])]) : null,
        deleting.value === item.id ? h('div', { class: 'wall-delete-confirm' }, [h('span', '删除后无法恢复。'), h('button', { class: 'quiet-button', disabled: busy.value, onClick: () => deleting.value = null }, '保留留言'), h('button', { class: 'text-button danger', disabled: busy.value, onClick: () => remove(item) }, '确认删除留言')]) : null,
      ]))),
      total.value > 12 || offset.value > 0 ? h('div', { class: 'pagination' }, [h('button', { disabled: locked() || !!editing.value || offset.value === 0, onClick: () => load(offset.value - 12) }, '上一页'), h('span', `第 ${Math.floor(offset.value / 12) + 1} 页 · 共 ${total.value} 条`), h('button', { disabled: locked() || !!editing.value || offset.value + 12 >= total.value, onClick: () => load(offset.value + 12) }, '下一页')]) : null,
    ]);
  },
};
