import { h, ref, onMounted, onBeforeUnmount } from 'vue';
import { api } from './api.js';
import { icon } from './ui.js';

const names = { NONE: '尚未开放', ACTIVE: '开放中', EXPIRED: '已过期', DISABLED: '已停用', CLOSED: '课堂已结束' };
const dateText = value => new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value));

export const JoinClassPanel = {
  emits: ['expired', 'joined'],
  setup(_, { emit }) {
    const code = ref(''), busy = ref(false), error = ref('');
    const abort = new AbortController(); let alive = true;
    onBeforeUnmount(() => { alive = false; abort.abort(); });
    async function join(event) {
      event.preventDefault(); if (busy.value || !code.value.trim()) return;
      busy.value = true; error.value = '';
      try {
        const result = await api('/api/sessions/join', { method: 'POST', body: { code: code.value }, signal: abort.signal });
        if (alive) { code.value = ''; emit('joined', result.data.session, result.message); }
      } catch (failure) { if (alive && !abort.signal.aborted) { if (failure.status === 401) emit('expired'); else error.value = failure.message; } }
      finally { if (alive) busy.value = false; }
    }
    return () => h('section', { class: 'join-class-panel' }, [
      h('form', { class: 'join-class-form', onSubmit: join }, [h('label', { class: 'field' }, [h('span', '课程加入码'), h('input', { name: 'class_join_code', value: code.value, required: true, maxlength: 20, autocomplete: 'off', autocapitalize: 'characters', spellcheck: false, placeholder: '输入老师提供的 8 位加入码', disabled: busy.value, onInput: event => code.value = event.target.value.toUpperCase() })]), h('button', { class: 'secondary-button', disabled: busy.value || !code.value.trim() }, busy.value ? '正在添加…' : '确认添加课程')]),
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null,
    ]);
  },
};

export const JoinCodePanel = {
  props: ['sessionId', 'ended'], emits: ['expired'],
  setup(props, { emit }) {
    const data = ref(null), ttl = ref('60'), busy = ref(false), error = ref(''), message = ref(''), confirm = ref(false);
    const abort = new AbortController(); let alive = true, retry;
    const fail = failure => { if (failure.status === 401) emit('expired'); else error.value = failure.message; };
    onBeforeUnmount(() => { alive = false; abort.abort(); });
    async function load() {
      if (busy.value) return;
      busy.value = true; error.value = ''; message.value = ''; confirm.value = false;
      try { const result = await api(`/api/sessions/${props.sessionId}/join-code`, { signal: abort.signal }); if (alive) data.value = result.data; }
      catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) busy.value = false; }
    }
    async function generate() {
      if (busy.value || !data.value || props.ended) return;
      if (data.value.status === 'ACTIVE' && !confirm.value) { confirm.value = true; return; }
      busy.value = true; error.value = ''; message.value = '';
      const body = { version: data.value.version, ttl_minutes: Number(ttl.value) }, signature = JSON.stringify(body);
      if (retry?.signature !== signature) retry = { signature, request_id: crypto.randomUUID() };
      try {
        const result = await api(`/api/sessions/${props.sessionId}/join-code`, { method: 'POST', body: { ...body, request_id: retry.request_id }, signal: abort.signal });
        if (alive) { data.value = result.data; retry = null; confirm.value = false; message.value = result.message; }
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) busy.value = false; }
    }
    async function revoke() {
      if (busy.value || !data.value) return;
      busy.value = true; error.value = ''; message.value = '';
      try {
        const result = await api(`/api/sessions/${props.sessionId}/join-code?version=${data.value.version}`, { method: 'DELETE', signal: abort.signal });
        if (alive) { data.value = result.data; confirm.value = false; message.value = result.message; }
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) busy.value = false; }
    }
    async function copy() {
      if (!data.value?.code) return;
      try { await navigator.clipboard.writeText(data.value.code); if (alive) message.value = '加入码已复制'; }
      catch { if (alive) message.value = '可选中加入码文字后手动复制'; }
    }
    onMounted(load);
    return () => h('details', { class: 'join-code-panel' }, [
      h('summary', '课程加入码'), h('div', { class: 'join-code-body' }, [
        error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null,
        message.value ? h('p', { class: 'form-notice success', role: 'status' }, message.value) : null,
        data.value ? h('div', [
          h('div', { class: 'join-code-display' }, [h('div', [h('span', { class: 'join-code-status' }, names[data.value.status]), h('strong', { class: { inactive: data.value.status !== 'ACTIVE' }, 'aria-label': '当前课堂加入码' }, data.value.code ? `${data.value.code.slice(0, 4)} ${data.value.code.slice(4)}` : '— — — —')]), data.value.status === 'ACTIVE' ? h('button', { class: 'quiet-button', onClick: copy }, '复制加入码') : null]),
          h('p', { class: 'data-note' }, data.value.expires_at ? `有效期至 ${dateText(data.value.expires_at)}。学生在“我的课程”中添加一次，后续课堂自动安排。` : '生成后分享给学生，用于添加这门课程。'),
          h('div', { class: 'join-code-actions' }, [h('label', { class: 'field' }, [h('span', '有效时长'), h('select', { name: 'join_code_ttl', value: ttl.value, disabled: busy.value || props.ended, onChange: event => { ttl.value = event.target.value; confirm.value = false; } }, [['15', '15 分钟'], ['60', '1 小时'], ['240', '4 小时'], ['1440', '24 小时']].map(([value, label]) => h('option', { value }, label)))]), h('button', { class: 'secondary-button', disabled: busy.value || props.ended, onClick: generate }, confirm.value ? '确认更换加入码' : data.value.code ? '重新生成' : '生成加入码'), data.value.status === 'ACTIVE' ? h('button', { class: 'quiet-button', disabled: busy.value, onClick: revoke }, '停用加入码') : null, h('button', { class: 'quiet-button', disabled: busy.value, onClick: load }, [icon('refresh', 14), '刷新加入码'])]),
          confirm.value ? h('p', { class: 'data-note', role: 'status' }, '更换后旧码立即失效，已加入的学生不受影响。再次点击确认。') : null,
        ]) : h('p', { class: 'data-note', role: 'status' }, busy.value ? '正在读取加入码…' : '暂未读取到加入码设置。'),
      ]),
    ]);
  },
};
