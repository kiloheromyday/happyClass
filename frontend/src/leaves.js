import { h, ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api } from './api.js';
import { icon } from './ui.js';
import { departmentStyle, chinaDay } from './timetable.js';

const states = { PENDING: '待审批', APPROVED: '已同意', REJECTED: '已驳回', CANCELLED: '已撤回' };
const types = { SICK: '病假', PERSONAL: '事假', OTHER: '其他' };
const date = value => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
const emptySummary = () => ({ PENDING: 0, APPROVED: 0, REJECTED: 0, CANCELLED: 0 });

export const LeavesPanel = {
  props: ['user', 'initialSessionId'], emits: ['expired', 'dirty-change', 'navigate'],
  setup(props, { emit }) {
    const student = props.user.role === 'STUDENT', teacher = props.user.role === 'TEACHER';
    const courses = ref([]), sessions = ref([]), items = ref([]), summary = ref(emptySummary()), total = ref(0), offset = ref(0);
    const loading = ref(false), saving = ref(false), opened = ref(false), error = ref(''), message = ref('');
    const status = ref('ALL'), courseFilter = ref(''), reviewing = ref(null), decision = ref('APPROVED'), reply = ref(''), confirming = ref(null);
    const form = reactive({ session_id: '', course_id: '', day: '', category: 'PERSONAL', reason: '' }), baseline = ref('');
    const dirty = computed(() => (opened.value && JSON.stringify(form) !== baseline.value) || reviewing.value !== null);
    const locked = computed(() => loading.value || saving.value);
    const leaving = computed(() => dirty.value || saving.value);
    const clock = ref(Date.now());
    const eligible = computed(() => sessions.value.filter(item => Date.parse(item.ends_at) > clock.value).sort((a, b) => a.starts_at.localeCompare(b.starts_at)));
    const choices = computed(() => eligible.value.filter(item => (!form.course_id || String(item.course_id) === form.course_id) && (!form.day || chinaDay(item.starts_at) === form.day)));
    let alive = true, readAbort, writeAbort, retry, timer;
    watch(leaving, value => emit('dirty-change', value), { flush: 'sync' });
    function fail(failure) { if (failure.status === 401) emit('expired'); else error.value = failure.message; }
    async function load(nextOffset = 0) {
      if (saving.value || dirty.value) return;
      readAbort?.abort(); const controller = new AbortController(); readAbort = controller;
      loading.value = true; error.value = '';
      try {
        const query = new URLSearchParams({ status: status.value, limit: '10', offset: String(nextOffset) });
        if (courseFilter.value) query.set('course_id', courseFilter.value);
        let response = await api(`/api/leaves?${query}`, { signal: controller.signal });
        const last = Math.max(0, Math.floor((response.data.total - 1) / 10) * 10);
        if (nextOffset > last) { nextOffset = last; query.set('offset', String(last)); response = await api(`/api/leaves?${query}`, { signal: controller.signal }); }
        if (alive && !controller.signal.aborted) { items.value = response.data.items; total.value = response.data.total; summary.value = response.data.summary; offset.value = nextOffset; }
      } catch (failure) { if (alive && !controller.signal.aborted) fail(failure); }
      finally { if (alive && readAbort === controller) loading.value = false; }
    }
    function open() {
      if (locked.value || dirty.value) return;
      const initial = eligible.value.find(item => item.id === Number(props.initialSessionId)) || eligible.value[0];
      Object.assign(form, { session_id: initial ? String(initial.id) : '', course_id: initial ? String(initial.course_id) : '', day: initial ? chinaDay(initial.starts_at) : chinaDay(new Date()), category: 'PERSONAL', reason: '' });
      baseline.value = JSON.stringify(form); opened.value = true; retry = null; error.value = message.value = ''; confirming.value = null;
    }
    function close() { if (saving.value) return; opened.value = false; form.reason = ''; error.value = ''; retry = null; }
    function chooseScope(key, value) { form[key] = value; form.session_id = ''; }
    async function mutate(operation, notice, onSaved = () => {}) {
      if (locked.value) return;
      saving.value = true; error.value = message.value = ''; const controller = new AbortController(); writeAbort = controller;
      try { await operation(controller.signal); if (alive) { onSaved(); message.value = notice; confirming.value = null; } }
      catch (failure) { if (alive && !controller.signal.aborted) fail(failure); }
      finally { if (alive) saving.value = false; }
      if (alive && !error.value) await load(offset.value);
    }
    async function submit(event) {
      event.preventDefault(); if (locked.value) return;
      if (!form.session_id || !choices.value.some(item => item.id === Number(form.session_id))) { error.value = '请选择尚未结束的课堂。'; return; }
      if (form.reason.trim().length < 2) { error.value = '请填写 2～500 字的请假原因。'; return; }
      const body = { session_id: Number(form.session_id), category: form.category, reason: form.reason.trim() }, signature = JSON.stringify(body);
      if (retry?.signature !== signature) retry = { signature, request_id: crypto.randomUUID() };
      await mutate(signal => api('/api/leaves', { method: 'POST', signal, body: { ...body, request_id: retry.request_id } }), '申请已提交，等待任课教师审批。', () => { opened.value = false; form.reason = ''; retry = null; });
    }
    function cancel(item) {
      if (locked.value || dirty.value) return;
      if (confirming.value !== item.id) { confirming.value = item.id; return; }
      mutate(signal => api(`/api/leaves/${item.id}/cancel`, { method: 'PUT', signal, body: { version: item.version } }), '申请已撤回。');
    }
    function review(item) { if (locked.value || dirty.value) return; reviewing.value = item.id; decision.value = 'APPROVED'; reply.value = ''; error.value = message.value = ''; confirming.value = null; }
    async function decide(event, item) {
      event.preventDefault();
      if (decision.value === 'REJECTED' && !reply.value.trim()) { error.value = '驳回申请时，请填写原因，方便学生了解。'; return; }
      await mutate(signal => api(`/api/leaves/${item.id}/decision`, { method: 'PUT', signal, body: { version: item.version, decision: decision.value, reply: reply.value.trim() } }), '审批结果已保存，学生可以查看。', () => { reviewing.value = null; reply.value = ''; });
    }
    function editor() {
      return h('section', { class: 'leave-editor', 'aria-label': '请假申请窗口' }, [h('div', { class: 'section-title' }, [h('h3', '新建请假申请'), h('span', { class: 'leave-private' }, '仅本人、任课教师与管理员可见')]), h('form', { class: 'leave-request-form', onSubmit: submit }, [
        h('div', { class: 'form-pair' }, [h('label', { class: 'field' }, [h('span', '所属课程'), h('select', { name: 'leave_course', value: form.course_id, disabled: saving.value, onChange: event => chooseScope('course_id', event.target.value) }, [h('option', { value: '' }, '全部已加入课程'), ...courses.value.map(item => h('option', { value: String(item.id) }, item.name))])]), h('label', { class: 'field' }, [h('span', '上课日期（北京时间）'), h('input', { name: 'leave_date', type: 'date', value: form.day, disabled: saving.value, onInput: event => chooseScope('day', event.target.value) })])]),
        h('label', { class: 'field' }, [h('span', '请假课堂'), h('select', { name: 'leave_session', required: true, value: form.session_id, disabled: saving.value, onChange: event => form.session_id = event.target.value }, [h('option', { value: '' }, choices.value.length ? '选择一节课堂' : '此日期暂无可请假的课堂'), ...choices.value.map(item => h('option', { value: String(item.id) }, `${item.course_name} · ${date(item.starts_at)} · ${item.classroom}`))])]),
        h('label', { class: 'field' }, [h('span', '请假类型'), h('select', { name: 'leave_category', value: form.category, disabled: saving.value, onChange: event => form.category = event.target.value }, Object.entries(types).map(([value, label]) => h('option', { value }, label)))]),
        h('label', { class: 'field' }, [h('span', '请假原因'), h('textarea', { name: 'leave_reason', required: true, minlength: 2, maxlength: 500, rows: 4, value: form.reason, disabled: saving.value, placeholder: '简要说明本节课无法到课的原因', onInput: event => form.reason = event.target.value })]),
        h('div', { class: 'leave-editor-bottom' }, [h('span', `${form.reason.length}/500`), h('div', { class: 'guide-actions' }, [h('button', { type: 'button', class: 'quiet-button', disabled: saving.value, onClick: close }, dirty.value ? '放弃请假草稿' : '取消申请'), h('button', { class: 'primary-button', disabled: saving.value || !form.session_id }, saving.value ? '正在提交…' : '提交请假申请')])]),
      ])]);
    }
    function card(item) {
      return h('article', { class: 'leave-card', style: departmentStyle(item), key: item.id }, [h('div', { class: 'leave-card-heading' }, [h('div', [h('span', { class: 'department-badge' }, item.department_name || '综合课程'), h('h3', item.course_name)]), h('span', { class: ['leave-status', item.status.toLowerCase()] }, states[item.status])]),
        h('p', { class: 'leave-class-info' }, `${date(item.starts_at)} — ${date(item.ends_at)} · ${item.classroom}`),
        h('p', { class: 'leave-class-info' }, student ? `任课教师 · ${item.teacher_name}` : `${item.student_name} · ${item.student_username} · ${item.class_name}`),
        h('div', { class: 'leave-reason' }, [h('span', types[item.category]), h('p', item.reason)]),
        item.reply ? h('div', { class: 'leave-reply' }, [h('span', `${item.reviewer_name || '任课教师'}的回复`), h('p', item.reply)]) : null,
        h('div', { class: 'leave-card-footer' }, [h('span', `提交于 ${date(item.created_at)}${item.reviewed_at ? ` · 处理于 ${date(item.reviewed_at)}` : ''}`), h('div', { class: 'guide-actions' }, [h('button', { class: 'quiet-button', disabled: locked.value || dirty.value, onClick: () => emit('navigate', { tab: 'courses', courseId: item.course_id }) }, '课程详情'), student && item.status === 'PENDING' ? h('button', { class: 'quiet-button', disabled: locked.value || dirty.value, onClick: () => cancel(item) }, confirming.value === item.id ? '确认撤回申请' : '撤回申请') : null, confirming.value === item.id ? h('button', { class: 'quiet-button', onClick: () => confirming.value = null }, '保留申请') : null, teacher && item.status === 'PENDING' ? h('button', { class: 'secondary-button', disabled: locked.value || dirty.value, onClick: () => review(item) }, '处理申请') : null])]),
        reviewing.value === item.id ? h('form', { class: 'leave-review-form', onSubmit: event => decide(event, item) }, [h('h4', '审批请假'), h('label', { class: 'field' }, [h('span', '审批结果'), h('select', { name: 'leave_decision', value: decision.value, disabled: saving.value, onChange: event => decision.value = event.target.value }, [h('option', { value: 'APPROVED' }, '同意请假'), h('option', { value: 'REJECTED' }, '驳回申请')])]), h('label', { class: 'field' }, [h('span', decision.value === 'REJECTED' ? '驳回原因' : '回复（选填）'), h('textarea', { name: 'leave_reply', rows: 3, maxlength: 500, required: decision.value === 'REJECTED', value: reply.value, disabled: saving.value, onInput: event => reply.value = event.target.value })]), h('div', { class: 'guide-actions' }, [h('button', { type: 'button', class: 'quiet-button', disabled: saving.value, onClick: () => { reviewing.value = null; reply.value = ''; error.value = ''; } }, '放弃审批草稿'), h('button', { class: 'primary-button', disabled: saving.value }, saving.value ? '正在保存…' : '确认审批')])]) : null,
      ]);
    }
    async function refresh(initial = false) {
      if (locked.value || dirty.value) return;
      const controller = new AbortController(); readAbort = controller; loading.value = true;
      error.value = '';
      try { const results = await Promise.all([api('/api/courses', { signal: controller.signal }), api('/api/sessions', { signal: controller.signal })]); if (alive && !controller.signal.aborted) { courses.value = results[0].data.items; sessions.value = results[1].data.items; } }
      catch (failure) { if (alive && !controller.signal.aborted) fail(failure); }
      finally { if (alive) loading.value = false; }
      if (alive && !error.value) { await load(offset.value); if (initial && student && props.initialSessionId && !error.value) open(); }
    }
    const beforeUnload = event => { if (leaving.value) { event.preventDefault(); event.returnValue = ''; } };
    onMounted(() => {
      if (typeof window !== 'undefined') window.addEventListener('beforeunload', beforeUnload);
      timer = setInterval(() => clock.value = Date.now(), 1000); refresh(true);
    });
    onBeforeUnmount(() => { alive = false; readAbort?.abort(); writeAbort?.abort(); clearInterval(timer); emit('dirty-change', false); if (typeof window !== 'undefined') window.removeEventListener('beforeunload', beforeUnload); });
    return () => h('section', { class: 'leaves-panel', 'aria-busy': locked.value }, [
      h('div', { class: 'section-title' }, [h('h2', student ? '请假申请' : teacher ? '请假审批' : '全校请假记录'), h('div', { class: 'guide-actions' }, [h('button', { class: 'quiet-button', disabled: locked.value || dirty.value, onClick: () => refresh() }, [icon('refresh', 15), '刷新']), student && !opened.value ? h('button', { class: 'secondary-button', disabled: locked.value || dirty.value, onClick: open }, '申请请假') : null])]),
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null,
      message.value ? h('p', { class: 'form-notice success', role: 'status' }, message.value) : null,
      opened.value && student ? editor() : null,
      h('div', { class: 'leave-summary' }, Object.entries(states).map(([key, label]) => h('div', [h('strong', String(summary.value[key] || 0)), h('span', label)]))),
      h('div', { class: 'leave-filters' }, [h('select', { name: 'leave_filter_course', 'aria-label': '请假课程筛选', value: courseFilter.value, disabled: locked.value || dirty.value, onChange: event => { courseFilter.value = event.target.value; confirming.value = null; load(); } }, [h('option', { value: '' }, student ? '全部已加入课程' : '全部课程'), ...courses.value.map(item => h('option', { value: String(item.id) }, item.name))]), h('select', { name: 'leave_filter_status', 'aria-label': '请假状态筛选', value: status.value, disabled: locked.value || dirty.value, onChange: event => { status.value = event.target.value; confirming.value = null; load(); } }, [['ALL', '全部状态'], ...Object.entries(states)].map(([value, label]) => h('option', { value }, label)))]),
      loading.value ? h('p', { class: 'empty-note', role: 'status' }, '正在读取请假记录…') : null,
      h('div', { class: 'leave-list' }, items.value.map(card)),
      !loading.value && !items.value.length ? h('div', { class: 'empty-state' }, [icon('book', 28), h('h3', student ? '还没有请假记录' : '暂时没有符合条件的申请'), h('p', student ? '需要请假时，选择一节尚未结束的课堂填写申请。' : teacher ? '所授课堂的申请会出现在这里。' : '全校学生的申请与处理结果会显示在这里。')]) : null,
      total.value > 10 || offset.value ? h('div', { class: 'pagination' }, [h('button', { disabled: locked.value || dirty.value || offset.value === 0, onClick: () => load(offset.value - 10) }, '上一页申请'), h('span', `共 ${total.value} 条 · 第 ${Math.floor(offset.value / 10) + 1} 页`), h('button', { disabled: locked.value || dirty.value || offset.value + 10 >= total.value, onClick: () => load(offset.value + 10) }, '下一页申请')]) : null,
    ]);
  },
};
