import { h, ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api, downloadCsv } from './api.js';
import { DataScope } from './data-scope.js';
import { departmentStyle } from './timetable.js';

const dimensions = [['clarity', '讲解清晰'], ['pace', '节奏合适'], ['engagement', '课堂互动'], ['gain', '学习收获']];
const stamp = value => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
const blank = () => ({ clarity: 0, pace: 0, engagement: 0, gain: 0, comment: '' });

export const EvaluationsPanel = {
  props: ['user', 'initialSessionId', 'initialCourseId', 'initialDataScope'], emits: ['expired', 'dirty-change', 'navigate'],
  setup(props, { emit }) {
    const student = props.user.role === 'STUDENT', sessions = ref([]), courses = ref([]), selected = ref('');
    const course = ref(props.initialCourseId ? String(props.initialCourseId) : ''), all = ref(Boolean(props.initialSessionId)), dataScope = ref(props.initialDataScope || 'ALL');
    const loading = ref(false), saving = ref(false), error = ref(''), message = ref(''), ready = ref(false);
    const form = reactive(blank()), baseline = ref(JSON.stringify(form)), version = ref(0), report = ref(null), offset = ref(0), clock = ref(Date.now());
    const dirty = computed(() => student && JSON.stringify(form) !== baseline.value), locked = computed(() => loading.value || saving.value);
    const current = computed(() => sessions.value.find(item => String(item.id) === selected.value));
    const canRate = item => item && Date.parse(item.starts_at) <= clock.value && clock.value < Date.parse(item.feedback_closes_at);
    const choices = computed(() => sessions.value.filter(item => (!course.value || String(item.course_id) === course.value) && (!student || all.value || canRate(item))));
    let alive = true, readAbort, writeAbort, timer, retry;
    watch(() => dirty.value || saving.value, value => emit('dirty-change', value), { flush: 'sync' });
    function fail(e) { if (e.status === 401) emit('expired'); else error.value = e.message; }
    function params(page = offset.value) { const p = new URLSearchParams({ data_scope: dataScope.value, limit: '10', offset: String(page) }); if (course.value) p.set('course_id', course.value); if (selected.value) p.set('session_id', selected.value); return p; }
    async function load(page = 0) {
      if (dirty.value || saving.value) return;
      readAbort?.abort(); const controller = new AbortController(); readAbort = controller;
      loading.value = true; ready.value = false; error.value = ''; report.value = null;
      try {
        if (student && selected.value) {
          const r = await api(`/api/sessions/${selected.value}/evaluation`, { signal: controller.signal });
          if (!alive || controller.signal.aborted) return;
          Object.assign(form, r.data.item ? Object.fromEntries(Object.keys(blank()).map(key => [key, r.data.item[key]])) : blank());
          baseline.value = JSON.stringify(form); version.value = r.data.item?.version || 0; retry = null;
        } else if (!student) {
          let r = await api('/api/evaluations/report?' + params(page), { signal: controller.signal });
          if (!alive || controller.signal.aborted) return;
          const last = Math.max(0, Math.floor((r.data.total - 1) / 10) * 10);
          if (page > last) { page = last; r = await api('/api/evaluations/report?' + params(page), { signal: controller.signal }); }
          if (!alive || controller.signal.aborted) return;
          report.value = r.data; offset.value = page;
        }
        if (alive && !controller.signal.aborted) ready.value = true;
      } catch (e) { if (alive && !controller.signal.aborted) fail(e); }
      finally { if (alive && readAbort === controller) loading.value = false; }
    }
    async function boot() {
      if (locked.value || dirty.value) return;
      readAbort?.abort(); const controller = new AbortController(); readAbort = controller; loading.value = true; error.value = '';
      try {
        const r = await Promise.all([api('/api/courses', { signal: controller.signal }), api('/api/sessions', { signal: controller.signal })]);
        if (!alive || controller.signal.aborted) return;
        courses.value = r[0].data.items; sessions.value = r[1].data.items;
        selected.value = String((choices.value.find(item => String(item.id) === selected.value) || choices.value.find(item => item.id === Number(props.initialSessionId)) || (student ? choices.value.find(canRate) || choices.value[0] : null))?.id || '');
      } catch (e) { if (alive && !controller.signal.aborted) fail(e); }
      finally { if (alive && readAbort === controller) loading.value = false; }
      if (alive && !error.value) await load();
    }
    function discard() { Object.assign(form, JSON.parse(baseline.value)); message.value = ''; error.value = ''; retry = null; }
    function change(key, value) {
      if (dirty.value || locked.value) return;
      if (key === 'course') { course.value = value; selected.value = student ? String(choices.value.find(canRate)?.id || choices.value[0]?.id || '') : ''; }
      if (key === 'session') selected.value = value;
      if (key === 'scope') dataScope.value = value;
      if (key === 'all') { all.value = value === 'ALL'; selected.value = String(choices.value.find(canRate)?.id || choices.value[0]?.id || ''); }
      message.value = ''; load();
    }
    async function save(event) {
      event.preventDefault(); if (locked.value || !ready.value || !canRate(current.value)) return;
      if (dimensions.some(([key]) => !form[key])) { error.value = '请为四个项目分别选择 1～5 分。'; return; }
      const body = { ...form, comment: form.comment.trim(), version: version.value }, signature = JSON.stringify([selected.value, body]);
      if (retry?.signature !== signature) retry = { signature, request_id: crypto.randomUUID() };
      saving.value = true; error.value = message.value = ''; writeAbort = new AbortController();
      try {
        const r = await api(`/api/sessions/${selected.value}/evaluation`, { method: 'PUT', signal: writeAbort.signal, body: { ...body, request_id: retry.request_id } });
        if (!alive) return;
        Object.assign(form, Object.fromEntries(Object.keys(blank()).map(key => [key, r.data[key]]))); baseline.value = JSON.stringify(form); version.value = r.data.version; retry = null;
        message.value = '评价已保存，谢谢你的认真反馈。';
      } catch (e) { if (alive && !writeAbort.signal.aborted) fail(e); }
      finally { if (alive) saving.value = false; }
    }
    async function exportReport() {
      if (locked.value || !report.value) return;
      saving.value = true; error.value = ''; writeAbort = new AbortController();
      try { const count = await downloadCsv('/api/evaluations/export?' + params(), writeAbort.signal); if (alive) message.value = `已导出 ${count} 份匿名评价。`; }
      catch (e) { if (alive && !writeAbort.signal.aborted) fail(e); }
      finally { if (alive) saving.value = false; }
    }
    function editor() {
      if (!current.value) return h('p', { class: 'empty-note' }, '暂无可评价课堂，可切换“全部课堂”查看已保存的评价。');
      const editable = canRate(current.value) && ready.value && !locked.value;
      return h('section', { class: 'evaluation-editor', style: departmentStyle(current.value) }, [
        h('span', { class: 'department-badge' }, current.value.department_name || '课程评价'), h('h3', current.value.course_name),
        h('p', { class: 'data-note' }, `${stamp(current.value.starts_at)} · ${current.value.classroom} · ${version.value ? '已评价' : '尚未评价'}`),
        h('form', { onSubmit: save }, [
          ...dimensions.map(([key, label]) => h('fieldset', { class: 'evaluation-rating', disabled: !editable }, [h('legend', label), h('div', { role: 'group', 'aria-label': label }, [1, 2, 3, 4, 5].map(n => h('button', { type: 'button', class: { chosen: form[key] === n }, 'aria-pressed': form[key] === n, 'aria-label': `${label} ${n} 分`, onClick: () => form[key] = n }, [h('span', { 'aria-hidden': 'true' }, '✦'), String(n)])))])),
          h('p', { class: 'data-note' }, '1 分较不满意 · 3 分一般 · 5 分很满意'),
          h('label', { class: 'field' }, [h('span', '给课堂的建议（选填）'), h('textarea', { name: 'evaluation_comment', maxlength: 1000, rows: 4, value: form.comment, disabled: !editable, placeholder: '哪些内容帮助了你？还希望有什么改进？', onInput: e => form.comment = e.target.value })]),
          h('div', { class: 'evaluation-footer' }, [h('span', { class: 'data-note' }, '教师查看汇总评分与匿名建议'), h('div', { class: 'guide-actions' }, [dirty.value ? h('button', { type: 'button', class: 'quiet-button', disabled: saving.value, onClick: discard }, '放弃评价草稿') : null, h('button', { class: 'primary-button', disabled: !editable }, saving.value ? '正在保存…' : version.value ? '更新课程评价' : '提交课程评价')])]),
          !canRate(current.value) ? h('p', { class: 'data-note' }, current.value.status === 'UPCOMING' ? '课堂开始后可以评价。' : '评价时段已结束，已保存内容仍可查看。') : null,
        ]),
      ]);
    }
    function results() {
      if (!report.value) return null;
      const data = report.value;
      return h('div', [h('div', { class: 'evaluation-metrics' }, [h('div', [h('strong', String(data.total)), h('span', '份课程评价')]), ...dimensions.map(([key, label]) => h('div', [h('strong', data.summary[key] == null ? '—' : Number(data.summary[key]).toFixed(1)), h('span', label)]))]),
        data.by_course.length ? h('div', { class: 'evaluation-comparison' }, data.by_course.map(item => h('div', [h('span', item.course_name), h('progress', { max: 5, value: item.average, 'aria-label': `${item.course_name}平均分` }), h('strong', `${Number(item.average).toFixed(1)} / 5`), h('small', `${item.total} 份`)]))) : null,
        h('div', { class: 'section-title' }, [h('h3', '匿名评价'), h('button', { class: 'quiet-button', disabled: locked.value || !data.total, onClick: exportReport }, '导出匿名评价')]),
        data.items.length ? h('div', { class: 'evaluation-comments' }, data.items.map((item, i) => h('article', { key: i }, [h('h4', `${item.course_name}${item.is_demo ? ' · 演示' : ''}`), h('p', { class: 'data-note' }, `${stamp(item.starts_at)} · ${dimensions.map(([key, label]) => `${label} ${item[key]}`).join(' / ')}`), h('p', { class: 'evaluation-comment' }, item.comment || '本次只提交了评分。')]))) : h('p', { class: 'empty-note' }, '这个范围还没有课程评价。'),
        data.total > 10 ? h('div', { class: 'pagination' }, [h('button', { disabled: locked.value || offset.value === 0, onClick: () => load(offset.value - 10) }, '上一页评价'), h('span', `共 ${data.total} 份 · 第 ${offset.value / 10 + 1} 页`), h('button', { disabled: locked.value || offset.value + 10 >= data.total, onClick: () => load(offset.value + 10) }, '下一页评价')]) : null,
      ]);
    }
    onMounted(() => { boot(); timer = setInterval(() => clock.value = Date.now(), 1000); });
    onBeforeUnmount(() => { alive = false; readAbort?.abort(); writeAbort?.abort(); clearInterval(timer); emit('dirty-change', false); });
    return () => h('section', { class: 'evaluations-panel', 'aria-busy': locked.value }, [
      h('div', { class: 'section-title' }, [h('div', [h('p', { class: 'campus-eyebrow' }, 'COURSE / 课堂回声'), h('h2', '课程评价')]), h('button', { class: 'quiet-button', disabled: locked.value || dirty.value, onClick: boot }, '刷新评价')]),
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null, message.value ? h('p', { class: 'form-notice success', role: 'status' }, message.value) : null,
      h('div', { class: 'extension-filters' }, [
        h('select', { name: 'evaluation_course', 'aria-label': '评价课程', value: course.value, disabled: locked.value || dirty.value, onChange: e => change('course', e.target.value) }, [h('option', { value: '' }, '全部课程'), ...courses.value.map(item => h('option', { value: String(item.id) }, item.name))]),
        student ? h('select', { name: 'evaluation_range', 'aria-label': '评价课堂范围', value: all.value ? 'ALL' : 'OPEN', disabled: locked.value || dirty.value, onChange: e => change('all', e.target.value) }, [h('option', { value: 'OPEN' }, '正在进行与刚结束'), h('option', { value: 'ALL' }, '全部课堂（含历史）')]) : h(DataScope, { modelValue: dataScope.value, disabled: locked.value, 'onUpdate:modelValue': value => change('scope', value) }),
        h('select', { name: 'evaluation_session', 'aria-label': '评价课堂', value: selected.value, disabled: locked.value || dirty.value, onChange: e => change('session', e.target.value) }, [h('option', { value: '' }, student ? '请选择课堂' : '全部课堂'), ...choices.value.map(item => h('option', { value: String(item.id) }, `${item.course_name} · ${stamp(item.starts_at)}`))]),
      ]),
      loading.value ? h('p', { role: 'status', class: 'empty-note' }, '正在读取课程评价…') : student ? ready.value ? editor() : null : results(),
    ]);
  },
};
