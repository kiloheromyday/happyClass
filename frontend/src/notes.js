import { h, ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api, downloadCsv } from './api.js';
import { icon } from './ui.js';
import { EmotionDistribution, TrendChart } from './charts.js';

const dateText = value => value ? new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : '';
const blank = () => ({ session_id: '', title: '', content: '', takeaway: '', next_step: '', reviewed: false });
const noteFields = item => ({ session_id: item.session_id ? String(item.session_id) : '', title: item.title, content: item.content, takeaway: item.takeaway, next_step: item.next_step, reviewed: item.reviewed });
const normalized = draft => ({ ...draft, session_id: draft.session_id ? Number(draft.session_id) : null });
const feelingNames = { HAPPY: '😊 开心', NEUTRAL: '😐 平静', SAD: '😔 低落', ANGRY: '😠 生气', SURPRISED: '😮 惊讶', FEAR: '😟 担忧', DISGUST: '😣 反感' };

export const PersonalNotesPanel = {
  props: ['initialSessionId', 'initialView', 'initialCourseId'],
  emits: ['expired', 'dirty-change', 'navigate'],
  setup(props, { emit }) {
    const screen = ref(props.initialView === 'review' ? 'review' : 'notes'), sessions = ref([]), items = ref([]), total = ref(0), offset = ref(0);
    const filters = reactive({ q: '', session_id: props.initialSessionId ? String(props.initialSessionId) : '', review: 'ALL' }), applied = ref(null);
    const loading = ref(false), saving = ref(false), error = ref(''), message = ref('');
    const editor = ref(false), selected = ref(null), draft = reactive(blank()), baseline = ref(''), confirmDelete = ref(false);
    const days = ref(props.initialView === 'review' ? '90' : '7'), reviewSession = ref(props.initialSessionId ? String(props.initialSessionId) : ''), reviewData = ref(null), reviewDays = ref(''), reviewApplied = ref('');
    const selectedDay = ref(''), dayData = ref(null), dayLoading = ref(false), dayError = ref('');
    const dirty = computed(() => editor.value && JSON.stringify(normalized(draft)) !== baseline.value);
    const filtersChanged = computed(() => applied.value !== JSON.stringify({ ...filters }));
    let alive = true, readAbort, writeAbort, choicesAbort, dayAbort, retry;
    function resetDay() { dayAbort?.abort(); selectedDay.value = ''; dayData.value = null; dayError.value = ''; dayLoading.value = false; }
    async function loadDay(day, feedbackOffset = 0, notesOffset = 0) {
      const review = reviewData.value;
      if (!review || loading.value || saving.value || screen.value !== 'review') return;
      dayAbort?.abort(); const abort = new AbortController(); dayAbort = abort;
      selectedDay.value = day; dayLoading.value = true; dayError.value = ''; dayData.value = null;
      const query = new URLSearchParams({ day, starts_at: review.starts_at, ends_at: review.ends_at, feedback_offset: feedbackOffset, notes_offset: notesOffset });
      if (review.session_id) query.set('session_id', review.session_id);
      try {
        const result = await api(`/api/personal/review/day?${query}`, { signal: abort.signal });
        if (alive && !abort.signal.aborted) dayData.value = result.data;
      } catch (failure) { if (alive && !abort.signal.aborted) { if (failure.status === 401) emit('expired'); else dayError.value = failure.message; } }
      finally { if (alive && dayAbort === abort) dayLoading.value = false; }
    }
    const fail = failure => { if (failure.status === 401) emit('expired'); else error.value = failure.message; };
    watch(dirty, value => emit('dirty-change', value), { flush: 'sync' });
    const beforeUnload = event => { if (dirty.value) { event.preventDefault(); event.returnValue = ''; } };
    const params = (values = filters) => {
      const query = new URLSearchParams({ review: values.review });
      if (values.q.trim()) query.set('q', values.q.trim());
      if (values.session_id) query.set('session_id', values.session_id);
      return query;
    };
    async function loadNotes(nextOffset = 0) {
      readAbort?.abort(); const abort = new AbortController(); readAbort = abort;
      loading.value = true; error.value = '';
      const values = { ...filters }, signature = JSON.stringify(values), query = params(values);
      const fetchPage = async page => {
        query.set('limit', '12'); query.set('offset', String(page));
        return (await api(`/api/personal/notes?${query}`, { signal: abort.signal })).data;
      };
      try {
        let data = await fetchPage(nextOffset);
        if (!alive || abort.signal.aborted) return;
        const lastOffset = Math.max(0, Math.floor((data.total - 1) / 12) * 12);
        if (nextOffset > lastOffset) { nextOffset = lastOffset; data = await fetchPage(nextOffset); }
        if (alive && !abort.signal.aborted) { items.value = data.items; total.value = data.total; offset.value = nextOffset; applied.value = signature; }
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (readAbort === abort && alive) loading.value = false; }
    }
    async function loadSessions() {
      choicesAbort?.abort(); const abort = new AbortController(); choicesAbort = abort;
      try {
        const result = await api('/api/personal/notes/sessions', { signal: abort.signal });
        if (alive && !abort.signal.aborted) sessions.value = result.data.items;
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
    }
    async function loadReview() {
      resetDay();
      readAbort?.abort(); const abort = new AbortController(); readAbort = abort;
      loading.value = true; error.value = ''; const period = days.value, classroom = reviewSession.value;
      try {
        const query = new URLSearchParams({ days: period }); if (classroom) query.set('session_id', classroom);
        const result = await api(`/api/personal/review?${query}`, { signal: abort.signal });
        if (alive && !abort.signal.aborted) { reviewData.value = result.data; reviewDays.value = period; reviewApplied.value = query.toString(); }
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (readAbort === abort && alive) loading.value = false; }
    }
    function setDraft(item = null) {
      selected.value = item; Object.assign(draft, item ? noteFields(item) : { ...blank(), session_id: filters.session_id });
      baseline.value = JSON.stringify(normalized(draft)); editor.value = true; confirmDelete.value = false; retry = null;
      message.value = ''; error.value = '';
    }
    async function open(item) {
      if (loading.value || saving.value) return;
      resetDay();
      readAbort?.abort(); const abort = new AbortController(); readAbort = abort;
      loading.value = true; error.value = '';
      try {
        const result = await api(`/api/personal/notes/${item.id}`, { signal: abort.signal });
        if (alive && !abort.signal.aborted) setDraft(result.data);
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (readAbort === abort && alive) loading.value = false; }
    }
    async function save(event) {
      event.preventDefault(); if (saving.value || !dirty.value || !draft.title.trim() || !draft.content.trim()) return;
      saving.value = true; error.value = ''; message.value = ''; confirmDelete.value = false;
      const body = normalized(draft), signature = JSON.stringify(body), item = selected.value;
      if (!item && retry?.signature !== signature) retry = { signature, request_id: crypto.randomUUID() };
      const abort = new AbortController(); writeAbort = abort;
      try {
        const result = await api(item ? `/api/personal/notes/${item.id}` : '/api/personal/notes', { method: item ? 'PUT' : 'POST', body: item ? { ...body, version: item.version } : { ...body, request_id: retry.request_id }, signal: abort.signal });
        if (alive) { setDraft(result.data); message.value = result.message; }
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) saving.value = false; }
    }
    function close() {
      if (saving.value) return;
      editor.value = false; selected.value = null; confirmDelete.value = false; Object.assign(draft, blank());
      error.value = ''; message.value = ''; retry = null; loadNotes(offset.value);
    }
    async function remove() {
      if (saving.value || !selected.value || !confirmDelete.value) return;
      saving.value = true; error.value = ''; const abort = new AbortController(); writeAbort = abort;
      try {
        const item = selected.value;
        await api(`/api/personal/notes/${item.id}?version=${item.version}`, { method: 'DELETE', signal: abort.signal });
        if (alive) { saving.value = false; close(); message.value = '笔记已删除'; }
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) saving.value = false; }
    }
    async function download() {
      if (saving.value || loading.value || filtersChanged.value || editor.value) return;
      saving.value = true; error.value = ''; const abort = new AbortController(); writeAbort = abort;
      try {
        const count = await downloadCsv(`/api/personal/notes/export?${params()}`, abort.signal);
        if (alive) message.value = `已导出 ${count} 篇个人笔记`;
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) saving.value = false; }
    }
    async function downloadReview() {
      if (loading.value || saving.value || !reviewApplied.value) return;
      saving.value = true; error.value = ''; const abort = new AbortController(); writeAbort = abort;
      try { await downloadCsv(`/api/personal/review/export?${reviewApplied.value}`, abort.signal); if (alive) message.value = '个人回顾已导出'; }
      catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) saving.value = false; }
    }
    function switchScreen(next) {
      if (editor.value || saving.value) return;
      resetDay();
      screen.value = next; error.value = ''; message.value = '';
      if (next === 'review') loadReview(); else loadNotes();
    }
    function findNotes(sessionId = '', review = 'ALL') {
      resetDay();
      screen.value = 'notes'; Object.assign(filters, { q: '', session_id: String(sessionId), review }); loadNotes();
    }
    onMounted(() => { loadSessions(); if (screen.value === 'review') loadReview(); else loadNotes(); if (typeof window !== 'undefined') window.addEventListener('beforeunload', beforeUnload); });
    onBeforeUnmount(() => { alive = false; readAbort?.abort(); writeAbort?.abort(); choicesAbort?.abort(); dayAbort?.abort(); emit('dirty-change', false); if (typeof window !== 'undefined') window.removeEventListener('beforeunload', beforeUnload); });
    const field = (label, name, key, limit, { input = false, ...options } = {}) => h('label', { class: 'field' }, [h('span', label), h(input ? 'input' : 'textarea', { name, value: draft[key], maxlength: limit, disabled: saving.value, onInput: event => draft[key] = event.target.value, ...options })]);
    const sessionSelect = (value, onChange, name, first) => h('select', { name, value, disabled: loading.value || saving.value, onChange: event => onChange(event.target.value) }, [h('option', { value: '' }, first), ...sessions.value.map(item => h('option', { value: String(item.id) }, `${item.course_name} · ${item.class_name} · ${dateText(item.starts_at)}`))]);
    function editForm() {
      return h('form', { class: 'note-editor', onSubmit: save }, [
        h('div', { class: 'note-editor-top' }, [h('h3', selected.value ? '编辑笔记' : '写一篇新笔记'), h('span', { class: 'note-save-state', role: 'status' }, saving.value ? '正在保存…' : dirty.value ? '有未保存的修改' : selected.value ? '已保存' : '仅自己可见')]),
        field('标题', 'note_title', 'title', 80, { input: true, required: true, placeholder: '给这一页起个名字' }),
        h('label', { class: 'field' }, [h('span', '关联课堂（可选）'), sessionSelect(draft.session_id, value => draft.session_id = value, 'note_session', '不关联课堂')]),
        field('笔记正文', 'note_content', 'content', 5000, { required: true, rows: 10, placeholder: '记下想法、知识点，或还没有想明白的问题。' }),
        h('div', { class: 'note-reflections' }, [field('我的收获', 'note_takeaway', 'takeaway', 300, { rows: 3, placeholder: '今天理解了什么？' }), field('下一步', 'note_next_step', 'next_step', 300, { rows: 3, placeholder: '接下来想练习或弄清什么？' })]),
        h('label', { class: 'note-reviewed' }, [h('input', { name: 'note_reviewed', type: 'checkbox', checked: draft.reviewed, disabled: saving.value, onChange: event => draft.reviewed = event.target.checked }), '这篇笔记已经回顾过了']),
        h('div', { class: 'note-editor-bottom' }, [h('span', { class: 'muted' }, `${draft.content.length} / 5000`), h('div', { class: 'note-actions' }, [h('button', { type: 'button', class: 'secondary-button', disabled: saving.value, onClick: close }, dirty.value ? '放弃修改并返回' : '返回笔记'), h('button', { class: 'primary-button', disabled: saving.value || !dirty.value || !draft.title.trim() || !draft.content.trim() }, saving.value ? '正在保存…' : '保存笔记')])]),
        selected.value ? h('div', { class: 'note-delete-area' }, [confirmDelete.value ? h('div', { class: 'note-delete-confirm' }, [h('span', '删除后无法恢复，确认删除这篇笔记？'), h('button', { type: 'button', class: 'quiet-button', disabled: saving.value, onClick: () => confirmDelete.value = false }, '保留笔记'), h('button', { type: 'button', class: 'note-delete-button', disabled: saving.value, onClick: remove }, '确认删除笔记')]) : h('button', { type: 'button', class: 'quiet-button', disabled: saving.value, onClick: () => confirmDelete.value = true }, '删除这篇笔记')]) : null,
      ]);
    }
    function notebook() {
      return editor.value ? editForm() : h('div', [
        h('form', { class: 'note-search', onSubmit: event => { event.preventDefault(); message.value = ''; loadNotes(); } }, [
          h('label', { class: 'field' }, [h('span', '查找笔记'), h('input', { name: 'note_query', value: filters.q, maxlength: 80, placeholder: '搜索标题、正文、收获或下一步', disabled: saving.value, onInput: event => filters.q = event.target.value })]),
          h('label', { class: 'field' }, [h('span', '课堂'), sessionSelect(filters.session_id, value => filters.session_id = value, 'notes_session_filter', '全部课堂与随记')]),
          h('label', { class: 'field' }, [h('span', '回顾状态'), h('select', { name: 'notes_review_filter', value: filters.review, disabled: saving.value, onChange: event => filters.review = event.target.value }, [['ALL', '全部笔记'], ['PENDING', '待回顾'], ['DONE', '已回顾']].map(([value, label]) => h('option', { value }, label)))]),
          h('button', { class: 'secondary-button', disabled: loading.value || saving.value }, '查找笔记'),
        ]),
        h('div', { class: 'note-list-top' }, [h('span', { class: 'muted' }, loading.value ? '正在整理笔记…' : `共 ${total.value} 篇${filtersChanged.value && applied.value ? ' · 条件已修改，请查找' : ''}`), h('button', { class: 'quiet-button', disabled: loading.value || saving.value || filtersChanged.value || !total.value, onClick: download }, [icon('download', 15), '导出笔记'])]),
        !loading.value && !error.value && !items.value.length ? h('div', { class: 'empty-state note-empty' }, [icon('book', 30), h('h3', '留一页给自己的想法'), h('p', filters.q || filters.session_id || filters.review !== 'ALL' ? '没有符合条件的笔记，试试调整筛选。' : '课堂里的小收获，值得记下来。')]) : null,
        h('div', { class: 'note-grid' }, items.value.map(item => h('article', { class: 'personal-note-card', key: item.id }, [
          h('div', { class: 'note-card-labels' }, [h('span', { class: ['note-status', { done: item.reviewed }] }, item.reviewed ? '已回顾' : '待回顾'), h('span', { class: 'muted' }, dateText(item.updated_at))]),
          h('h3', item.title), item.course_name ? h('p', { class: 'note-course' }, `${item.course_name} · ${item.class_name}`) : h('p', { class: 'note-course' }, '个人随记'),
          h('p', { class: 'note-preview' }, item.content),
          item.takeaway ? h('p', { class: 'note-takeaway' }, ['收获 · ', item.takeaway]) : null,
          h('button', { class: 'quiet-button', disabled: loading.value || saving.value, 'aria-label': `打开笔记：${item.title}`, onClick: () => open(item) }, ['打开笔记', icon('arrow', 15)]),
        ]))),
        total.value > 12 || offset.value ? h('div', { class: 'pagination' }, [h('button', { disabled: loading.value || saving.value || filtersChanged.value || offset.value === 0, onClick: () => loadNotes(offset.value - 12) }, '上一页'), h('span', `第 ${Math.floor(offset.value / 12) + 1} 页`), h('button', { disabled: loading.value || saving.value || filtersChanged.value || offset.value + 12 >= total.value, onClick: () => loadNotes(offset.value + 12) }, '下一页')]) : null,
      ]);
    }
    function dayDetails() {
      if (!selectedDay.value) return null;
      const data = dayData.value;
      const pager = (kind, label) => {
        const page = data[kind];
        if (page.total <= page.limit && !page.offset) return null;
        const move = offset => loadDay(selectedDay.value, kind === 'feedback' ? offset : data.feedback.offset, kind === 'notes' ? offset : data.notes.offset);
        return h('div', { class: 'pagination' }, [h('button', { disabled: dayLoading.value || !page.offset, onClick: () => move(Math.max(0, page.offset - page.limit)) }, `上一页${label}`), h('span', `第 ${Math.floor(page.offset / page.limit) + 1} 页`), h('button', { disabled: dayLoading.value || page.offset + page.limit >= page.total, onClick: () => move(page.offset + page.limit) }, `下一页${label}`)]);
      };
      return h('section', { class: 'review-day-detail', 'aria-busy': dayLoading.value, 'aria-label': '当天回顾详情' }, [
        h('div', { class: 'section-title' }, [h('div', [h('h3', `${selectedDay.value.replaceAll('-', '/')} 的记录`), h('p', { class: 'data-note' }, 'UTC 日期 · 沿用上方课堂与回顾时段')]), h('button', { class: 'quiet-button', onClick: resetDay }, '收起当天详情')]),
        dayLoading.value ? h('p', { class: 'muted', role: 'status' }, '正在打开这一天…') : null,
        dayError.value ? h('div', [h('p', { class: 'form-notice', role: 'alert' }, dayError.value), h('button', { class: 'quiet-button', onClick: () => loadDay(selectedDay.value) }, '重试当天详情')]) : null,
        data ? h('div', [
          h('p', { class: 'review-day-summary', role: 'status' }, `${data.feedback.total} 条反馈 · ${data.notes.total} 篇新笔记`),
          h('div', { class: 'review-day-columns' }, [
            h('section', [h('h4', '当天的感受'), data.feedback.items.length ? h('ul', { class: 'review-day-feedback' }, data.feedback.items.map(item => h('li', { key: item.id }, [h('time', { datetime: item.recorded_at }, item.recorded_at.slice(11, 16)), h('div', [h('strong', feelingNames[item.emotion] || item.emotion), h('p', `${item.course_name} · ${item.class_name}`)])]))) : h('p', { class: 'empty-note' }, '这一天没有手动反馈记录。'), pager('feedback', '反馈')]),
            h('section', [h('h4', '当天写下的笔记'), data.notes.items.length ? data.notes.items.map(item => h('article', { class: 'review-day-note', key: item.id }, [h('div', [h('strong', item.title), h('span', { class: 'note-status' }, item.reviewed ? '已回顾' : '待回顾')]), h('p', { class: 'note-course' }, item.course_name ? `${item.course_name} · ${item.class_name}` : '个人随记'), h('p', { class: 'note-preview' }, item.content), h('button', { class: 'quiet-button', disabled: loading.value || saving.value, 'aria-label': `打开当天笔记：${item.title}`, onClick: async () => { screen.value = 'notes'; await open(item); } }, ['打开当天笔记', icon('arrow', 15)])])) : h('p', { class: 'empty-note' }, '这一天没有新建笔记。'), pager('notes', '笔记')]),
          ]),
        ]) : null,
      ]);
    }
    function reviewPage() {
      const data = reviewData.value;
      return h('div', { class: 'personal-review' }, [
        h('div', { class: 'personal-review-toolbar' }, [h('label', { class: 'field' }, [h('span', '回顾时间'), h('select', { name: 'personal_review_days', value: days.value, disabled: loading.value || saving.value, onChange: event => { days.value = event.target.value; loadReview(); } }, [7, 30, 90].map(value => h('option', { value: String(value) }, `近 ${value} 天`)))]), h('label', { class: 'field review-session-select' }, [h('span', '课堂范围'), sessionSelect(reviewSession.value, value => { reviewSession.value = value; loadReview(); }, 'personal_review_session', '全部课堂与随记')]), h('button', { class: 'quiet-button', disabled: loading.value || saving.value, onClick: loadReview }, [icon('refresh', 15), '刷新回顾']), h('button', { class: 'secondary-button', disabled: loading.value || saving.value || !data || !!error.value, onClick: downloadReview }, [icon('download', 15), '导出个人回顾'])]),
        loading.value ? h('p', { class: 'muted', role: 'status' }, '正在整理你的回顾…') : null,
        data ? h('div', [
          h('p', { class: 'data-note' }, `近 ${reviewDays.value} 天 · 仅本人手动反馈 · 日期按 UTC 统计`),
          h('div', { class: 'personal-review-metrics' }, [['反馈记录', data.summary.feedback_count], ['记录天数', data.summary.active_days], ['新建笔记', data.summary.note_count], ['范围内待回顾', data.summary.pending_count]].map(([label, value]) => h('div', [h('strong', String(value)), h('span', label)]))),
          h('div', { class: 'personal-review-charts' }, [h('section', [h('h3', '这些日子的感受'), h(EmotionDistribution, { items: data.emotions }), h('p', { class: 'data-note' }, '按反馈次数统计，仅用来回看自己的记录。')]), h('section', [h('h3', '记录的节奏'), h(TrendChart, { points: data.trend, bucket: 'day', realtime: false, maxPoints: 92, interactive: true, selectedDate: selectedDay.value, disabled: loading.value || saving.value || !!error.value, onSelect: point => loadDay(point.timestamp.slice(0, 10)) }), h('div', { class: 'review-day-picker' }, [h('p', { class: 'data-note' }, '点击日期节点查看当天反馈与笔记，长图可左右滑动。'), h('label', [h('span', '选择日期'), h('input', { type: 'date', name: 'review_day', value: selectedDay.value, min: data.trend[0]?.timestamp.slice(0, 10), max: data.trend.at(-1)?.timestamp.slice(0, 10), disabled: loading.value || saving.value || !!error.value, onChange: event => event.target.value ? loadDay(event.target.value) : resetDay() })])])])]),
          dayDetails(),
          h('div', { class: 'personal-review-reminder' }, [h('div', [h('h3', data.summary.pending_count ? '再看一眼，理解可能不同' : '给新的想法留一点空间'), h('p', data.summary.pending_count ? `你有 ${data.summary.pending_count} 篇笔记待回顾，来自当前课堂范围全部时间。` : '可以写下一个收获，或下一步想做的事。')]), h('button', { class: 'secondary-button', disabled: loading.value || saving.value, onClick: () => findNotes(data.session_id || '', data.summary.pending_count ? 'PENDING' : 'ALL') }, data.summary.pending_count ? '查看待回顾笔记' : '回到笔记本')]),
          data.recent_notes?.length ? h('section', { class: 'review-note-excerpts' }, [h('h3', '留给下一次的想法'), h('p', { class: 'data-note' }, '所选时段内新建、最近更新的 6 篇笔记。'), ...data.recent_notes.map(item => h('article', { class: 'review-note-excerpt', key: item.id }, [h('header', [h('strong', item.title), h('span', item.reviewed ? '已回顾' : '待回顾')]), item.takeaway ? h('p', ['收获 · ', item.takeaway]) : null, item.next_step ? h('p', ['下一步 · ', item.next_step]) : null, h('button', { class: 'quiet-button', disabled: loading.value || saving.value, onClick: async () => { screen.value = 'notes'; await open(item); } }, '打开这篇笔记')]))]) : null,
          data.sessions.length ? h('section', { class: 'personal-review-sessions' }, [h('h3', '回到课堂'), h('p', { class: 'data-note' }, '所选时段内有本人反馈或新笔记的课堂，最近 10 节。'), ...data.sessions.map(item => h('div', { class: 'personal-review-session' }, [h('div', [h('strong', item.course_name), h('span', `${item.class_name} · ${dateText(item.starts_at)} · 反馈 ${item.feedback_count} 次 · 新笔记 ${item.note_count} 篇`)]), h('button', { class: 'quiet-button', disabled: loading.value, onClick: () => findNotes(item.id) }, '查看课堂笔记')]))]) : null,
        ]) : null,
      ]);
    }
    return () => h('section', { class: 'personal-notes-panel', 'aria-busy': loading.value || saving.value }, [
      props.initialCourseId ? h('button', { type: 'button', class: 'quiet-button course-return', disabled: editor.value || saving.value, onClick: () => emit('navigate', { tab: 'courses', courseId: props.initialCourseId }) }, '返回课程详情') : null,
      h('div', { class: 'section-title' }, [h('div', [h('h2', '笔记与回顾'), h('p', { class: 'muted notebook-subtitle' }, '记下收获，也给自己一点回看的时间。仅自己可见。')]), screen.value === 'notes' && !editor.value ? h('button', { class: 'primary-button', disabled: loading.value || saving.value, onClick: () => setDraft() }, '新建笔记') : null]),
      h('div', { class: 'notebook-tabs', role: 'group', 'aria-label': '笔记与回顾视图' }, [['notes', '我的笔记'], ['review', '个人回顾']].map(([key, label]) => h('button', { class: { active: screen.value === key }, 'aria-pressed': screen.value === key, disabled: editor.value || saving.value, onClick: () => switchScreen(key) }, label))),
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null,
      message.value ? h('p', { class: 'form-notice success', role: 'status' }, message.value) : null,
      screen.value === 'notes' ? notebook() : reviewPage(),
    ]);
  },
};
