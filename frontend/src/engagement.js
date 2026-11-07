import { h, ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api, downloadCsv } from './api.js';
import { EmotionDistribution } from './charts.js';
import { icon } from './ui.js';

const categories = [['PACE', '讲得太快'], ['EXAMPLE', '希望举例'], ['REPEAT', '需要再讲一次'], ['OTHER', '其他问题']];
const categoryName = code => categories.find(item => item[0] === code)?.[1] || code;
const dateText = value => new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value));

export const QuestionsPanel = {
  props: ['sessionId', 'ongoing', 'user'], emits: ['expired', 'dirty-change'],
  setup(props, { emit }) {
    const student = props.user.role === 'STUDENT';
    const items = ref([]), summary = ref({ total: 0, open: 0, resolved: 0 }), total = ref(0), offset = ref(0), filter = ref('ALL');
    const category = ref('EXAMPLE'), text = ref(''), error = ref(''), message = ref(''), loading = ref(false), saving = ref(false);
    const editing = ref(null), draft = reactive({ reply: '', status: 'OPEN', version: 1 }), readFailed = ref(false);
    const baseline = ref('');
    const dirty = computed(() => student ? Boolean(text.value.trim()) : Boolean(editing.value) && JSON.stringify(draft) !== baseline.value);
    watch(dirty, value => emit('dirty-change', value), { flush: 'sync' });
    let alive = true, readAbort, writeAbort, retry, timer;
    const fail = failure => { if (failure.status === 401) emit('expired'); else error.value = failure.message; };
    async function load(nextOffset = offset.value, quiet = false) {
      readAbort?.abort(); const abort = new AbortController(); readAbort = abort;
      if (!quiet) { loading.value = true; error.value = ''; }
      try {
        let result = await api(`/api/sessions/${props.sessionId}/questions?status=${filter.value}&limit=12&offset=${nextOffset}`, { signal: abort.signal });
        if (!alive || abort.signal.aborted) return;
        // Resolving the last card can remove the current page from this filter.
        const lastOffset = Math.max(0, Math.floor((result.data.total - 1) / 12) * 12);
        if (nextOffset > lastOffset) {
          nextOffset = lastOffset;
          result = await api(`/api/sessions/${props.sessionId}/questions?status=${filter.value}&limit=12&offset=${nextOffset}`, { signal: abort.signal });
        }
        if (alive && !abort.signal.aborted) { items.value = result.data.items; total.value = result.data.total; summary.value = result.data.summary; offset.value = nextOffset; readFailed.value = false; }
      } catch (failure) {
        if (alive && !abort.signal.aborted) { readFailed.value = true; if (!quiet || failure.status === 401) fail(failure); }
      }
      finally { if (readAbort === abort) { loading.value = false; readAbort = null; } }
    }
    async function send(event) {
      event.preventDefault(); if (saving.value || !props.ongoing) return;
      saving.value = true; error.value = ''; message.value = '';
      const signature = `${category.value}:${text.value.trim()}`;
      if (retry?.signature !== signature) retry = { signature, request_id: crypto.randomUUID() };
      const abort = new AbortController(); writeAbort = abort;
      try {
        const result = await api(`/api/sessions/${props.sessionId}/questions`, { method: 'POST', signal: abort.signal, body: { category: category.value, text: text.value.trim(), request_id: retry.request_id } });
        if (!alive) return;
        retry = null; text.value = ''; message.value = result.message; filter.value = 'ALL'; await load(0);
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) saving.value = false; }
    }
    async function save(event) {
      event.preventDefault(); if (saving.value || !editing.value) return;
      saving.value = true; error.value = ''; message.value = '';
      const abort = new AbortController(); writeAbort = abort;
      try {
        const result = await api(`/api/sessions/${props.sessionId}/questions/${editing.value}`, { method: 'PUT', body: { ...draft }, signal: abort.signal });
        if (!alive) return;
        editing.value = null; message.value = result.message; await load();
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive) saving.value = false; }
    }
    onMounted(() => { load(0); timer = setInterval(() => { if (!document.hidden && !saving.value && !editing.value && !readAbort) load(offset.value, true); }, 15000); });
    onBeforeUnmount(() => { alive = false; readAbort?.abort(); writeAbort?.abort(); clearInterval(timer); emit('dirty-change', false); });
    return () => h('section', { class: 'question-panel' }, [
      h('div', { class: 'section-title' }, [h('div', [h('p', { class: 'eyebrow' }, '一起把课堂讲明白'), h('h3', '匿名问题卡')]), h('button', { class: 'quiet-button', disabled: loading.value || saving.value, onClick: () => { editing.value = null; message.value = ''; load(); } }, [icon('refresh', 15), editing.value ? '放弃修改并刷新' : '刷新问题'])]),
      h('p', { class: 'question-privacy' }, '列表不显示提问人；请勿在内容中填写姓名或联系方式。'),
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null,
      message.value ? h('p', { class: 'form-notice success', role: 'status' }, message.value) : null,
      readFailed.value && !error.value ? h('p', { class: 'data-note', role: 'status' }, '暂时无法更新问题，当前显示上次结果。可点击刷新重试。') : null,
      student && props.ongoing ? h('form', { class: 'question-compose', onSubmit: send }, [
        h('div', { class: 'question-categories', role: 'group', 'aria-label': '问题类型' }, categories.map(([code, label]) => h('button', { type: 'button', class: ['question-chip', { selected: category.value === code }], 'aria-pressed': category.value === code, disabled: saving.value, onClick: () => category.value = code }, label))),
        h('label', { class: 'field' }, [h('span', '想问什么'), h('textarea', { name: 'question_text', value: text.value, maxlength: 300, rows: 2, placeholder: '补充一个具体问题（选填）', required: category.value === 'OTHER', disabled: saving.value, onInput: event => text.value = event.target.value })]),
        h('div', { class: 'compose-footer' }, [h('span', { class: 'muted' }, `${text.value.length} / 300`), text.value ? h('button', { type: 'button', class: 'quiet-button', disabled: saving.value, onClick: () => text.value = '' }, '清空问题草稿') : null, h('button', { class: 'primary-button', disabled: saving.value || (category.value === 'OTHER' && !text.value.trim()) }, saving.value ? '正在送达…' : '匿名提问')]),
      ]) : student ? h('p', { class: 'muted' }, '课堂进行时可以提问，课后仍可查看老师的回应。') : null,
      h('div', { class: 'question-toolbar' }, [h('div', { class: 'question-filters', role: 'group', 'aria-label': '筛选问题' }, [['ALL', `全部 ${summary.value.total}`], ['OPEN', `待回应 ${summary.value.open}`], ['RESOLVED', `已解决 ${summary.value.resolved}`]].map(([code, label]) => h('button', { class: { active: filter.value === code }, 'aria-pressed': filter.value === code, disabled: saving.value || !!editing.value, onClick: () => { filter.value = code; message.value = ''; load(0); } }, label))), loading.value ? h('span', { class: 'muted', role: 'status' }, '更新中…') : null]),
      !items.value.length && !loading.value && !readFailed.value ? h('p', { class: 'empty-note' }, filter.value === 'ALL' ? '还没有问题卡。一个小问题，也能让理解更进一步。' : '这里暂时没有问题卡。') : null,
      h('div', { class: 'question-list' }, items.value.map(item => h('article', { class: ['question-card', { resolved: item.status === 'RESOLVED' }], key: item.id }, [
        h('div', { class: 'question-card-top' }, [h('strong', categoryName(item.category)), h('span', { class: 'question-state' }, item.status === 'RESOLVED' ? '已解决' : '待回应')]),
        item.text ? h('p', { class: 'question-copy' }, item.text) : null,
        item.reply ? h('div', { class: 'question-reply' }, [h('span', '老师回应'), h('p', item.reply)]) : null,
        h('div', { class: 'question-card-bottom' }, [h('span', `${dateText(item.created_at)}${item.is_mine ? ' · 我提出的' : ''}`), !student ? h('button', { class: 'quiet-button', disabled: saving.value || !!editing.value, onClick: () => { Object.assign(draft, { reply: item.reply, status: item.status, version: item.version }); baseline.value = JSON.stringify(draft); editing.value = item.id; message.value = ''; } }, item.reply ? '编辑回应' : '回应问题') : null]),
        editing.value === item.id ? h('form', { class: 'question-answer', onSubmit: save }, [
          h('label', { class: 'field' }, [h('span', '教师回应'), h('textarea', { name: 'question_reply', rows: 3, maxlength: 1000, value: draft.reply, disabled: saving.value, onInput: event => draft.reply = event.target.value })]),
          h('label', { class: 'answer-resolved' }, [h('input', { type: 'checkbox', name: 'question_resolved', checked: draft.status === 'RESOLVED', disabled: saving.value, onChange: event => draft.status = event.target.checked ? 'RESOLVED' : 'OPEN' }), '标记为已解决']),
          h('div', { class: 'action-row' }, [h('button', { type: 'button', class: 'secondary-button', disabled: saving.value, onClick: () => editing.value = null }, '取消'), h('button', { class: 'primary-button', disabled: saving.value }, saving.value ? '正在保存…' : '保存回应')]),
        ]) : null,
      ]))),
      total.value > 12 || offset.value > 0 ? h('div', { class: 'pagination' }, [h('button', { disabled: loading.value || saving.value || !!editing.value || offset.value === 0, onClick: () => load(offset.value - 12) }, '上一页'), h('span', `第 ${Math.floor(offset.value / 12) + 1} 页 · 共 ${total.value} 条`), h('button', { disabled: loading.value || saving.value || !!editing.value || offset.value + 12 >= total.value, onClick: () => load(offset.value + 12) }, '下一页')]) : null,
    ]);
  },
};

export const RecapPanel = {
  props: ['sessionId', 'initialOpen'], emits: ['expired', 'dirty-change'],
  setup(props, { emit }) {
    const data = ref(null), reflection = ref(''), error = ref(''), message = ref(''), busy = ref(false), opened = ref(Boolean(props.initialOpen));
    const dirty = computed(() => Boolean(data.value) && reflection.value !== data.value.reflection.reflection);
    watch(dirty, value => emit('dirty-change', value), { flush: 'sync' });
    let alive = true, abort;
    const fail = failure => { if (failure.status === 401) emit('expired'); else error.value = failure.message; };
    async function load() {
      if (busy.value) return;
      busy.value = true; error.value = ''; message.value = ''; const controller = new AbortController(); abort = controller;
      try {
        const result = await api(`/api/sessions/${props.sessionId}/recap`, { signal: controller.signal });
        if (alive) { data.value = result.data; reflection.value = result.data.reflection.reflection; }
      } catch (failure) { if (alive && !controller.signal.aborted) fail(failure); }
      finally { if (alive) busy.value = false; }
    }
    async function save(event) {
      event.preventDefault(); if (busy.value || !data.value) return;
      busy.value = true; error.value = ''; message.value = ''; const controller = new AbortController(); abort = controller;
      try {
        const result = await api(`/api/sessions/${props.sessionId}/recap`, { method: 'PUT', signal: controller.signal, body: { reflection: reflection.value, version: data.value.reflection.version } });
        if (alive) { data.value.reflection = result.data; reflection.value = result.data.reflection; message.value = result.message; }
      } catch (failure) { if (alive && !controller.signal.aborted) fail(failure); }
      finally { if (alive) busy.value = false; }
    }
    async function download() {
      if (busy.value) return;
      busy.value = true; error.value = ''; const controller = new AbortController(); abort = controller;
      try { await downloadCsv(`/api/sessions/${props.sessionId}/recap/export`, controller.signal); }
      catch (failure) { if (alive && !controller.signal.aborted) fail(failure); }
      finally { if (alive) busy.value = false; }
    }
    onMounted(() => { if (props.initialOpen) load(); });
    onBeforeUnmount(() => { alive = false; abort?.abort(); emit('dirty-change', false); });
    return () => h('details', { class: 'recap-panel', open: opened.value, onToggle: event => { opened.value = event.target.open; if (opened.value && !data.value) load(); } }, [
      h('summary', [h('span', '课堂小结'), h('span', { class: 'muted recap-summary-note' }, '回顾这一节课')]),
      opened.value ? h('div', { class: 'recap-content' }, [
        error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null,
        message.value ? h('p', { class: 'form-notice success', role: 'status' }, message.value) : null,
        h('div', { class: 'recap-actions' }, [h('span', { class: 'muted' }, data.value ? `${data.value.session.status === 'ENDED' ? '课后回顾' : '阶段小结'} · ${dateText(data.value.generated_at)}` : '正在整理课堂记录…'), h('div', { class: 'action-row' }, [h('button', { class: 'quiet-button', disabled: busy.value, onClick: load }, data.value && reflection.value !== data.value.reflection.reflection ? '放弃修改并更新' : '更新小结'), h('button', { class: 'secondary-button', disabled: busy.value || !data.value || reflection.value !== data.value.reflection.reflection, onClick: download }, [icon('download', 15), '导出课堂小结'])])]),
        data.value ? h('div', [
          h('div', { class: 'recap-metrics' }, [['反馈记录', data.value.summary.total], ['反馈学生', data.value.summary.responding_students], ['问题卡', data.value.questions.total], ['已解决', data.value.questions.resolved]].map(([label, count]) => h('div', [h('strong', String(count)), h('span', label)]))),
          h('div', { class: 'recap-periods' }, data.value.periods.map(period => h('section', [h('div', { class: 'section-title' }, [h('h4', period.label), h('span', { class: 'muted' }, `${period.total} 条`)]), h(EmotionDistribution, { items: period.emotions, scaleMaximum: Math.max(1, ...data.value.periods.flatMap(part => part.emotions.map(item => item.count))) })]))),
          h('p', { class: 'data-note' }, `按课堂时间中点分段，两图采用相同的反馈次数刻度。${data.value.outside_period_count ? `另有 ${data.value.outside_period_count} 条在课堂时段以外。` : ''}分布变化不代表教学效果或心理诊断。`),
          h('div', { class: 'recap-topics' }, data.value.questions.categories.map(item => h('span', [categoryName(item.category), h('strong', String(item.count))]))),
          h('form', { class: 'reflection-form', onSubmit: save }, [h('label', { class: 'field' }, [h('span', '教学反思'), h('textarea', { name: 'classroom_reflection', rows: 4, maxlength: 2000, disabled: busy.value, value: reflection.value, placeholder: '记下这一节课的收获，以及下次想调整的地方。', onInput: event => reflection.value = event.target.value })]), h('div', { class: 'compose-footer' }, [h('span', { class: 'muted' }, `${reflection.value.length} / 2000`), h('button', { class: 'primary-button', disabled: busy.value || reflection.value === data.value.reflection.reflection }, busy.value ? '处理中…' : '保存教学反思')])]),
        ]) : busy.value ? h('p', { role: 'status', class: 'muted' }, '正在生成小结…') : null,
      ]) : null,
    ]);
  },
};
