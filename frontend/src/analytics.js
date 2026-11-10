import { h, ref, reactive, computed, onMounted, onUnmounted } from 'vue';
import { DataScope } from './data-scope.js';
import { api, downloadCsv } from './api.js';
import { emotions } from './classroom.js';
import { createPoller } from './polling.js';
import { EmotionDistribution, TrendChart } from './charts.js';
import { icon } from './ui.js';

const stamp = value => new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value));
const emotionLabel = value => emotions.find(item => item[0] === value)?.slice(1).join(' ') || value;
const statusName = { ONGOING: '进行中', UPCOMING: '未开始', ENDED: '已结束' };
const queryString = filters => new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== null && value !== undefined && value !== '').map(([key, value]) => [key, String(value)])).toString();
const select = (label, value, update, options, disabled = false) => h('label', { class: 'field' }, [h('span', label), h('select', { value, disabled, onChange: event => update(event.target.value) }, options.map(([key, text]) => h('option', { value: key }, text)))]);

export const AnalyticsPanel = {
  props: ['user', 'realtime', 'initialSessionId', 'initialCourseId', 'initialDataScope'], emits: ['expired', 'navigate'],
  setup(props, { emit }) {
    const sessions = ref([]), courses = ref([]), selected = ref(''), auto = ref(true);
    const data = ref(null), loading = ref(false), exporting = ref(false), error = ref(''), message = ref('');
    const draft = reactive({ course_id: props.initialCourseId ? String(props.initialCourseId) : '', session_id: props.initialSessionId ? String(props.initialSessionId) : '', class_name: '', from_time: '', to_time: '', source: '', bucket: 'day', data_scope: props.initialDataScope || 'ALL' });
    const appliedDraft = ref('');
    const filtersChanged = computed(() => !props.realtime && Boolean(appliedDraft.value) && JSON.stringify(draft) !== appliedDraft.value);
    const classes = computed(() => [...new Set(sessions.value.filter(item => !draft.course_id || item.course_id === Number(draft.course_id)).map(item => item.class_name))].sort());
    let disposed = false, reportRequest = null, exportRequest = null, bootRequest = null;
    function fail(failure) {
      if (failure.status === 401) { poller.stop(); emit('expired'); }
      else {
        error.value = failure.message;
        if (failure.status === 403) { data.value = null; poller.stop(); }
      }
    }
    const poller = createPoller({
      load: async (id, signal) => (await api(`/api/dashboard/realtime?session_id=${id}&data_scope=${draft.data_scope}`, { signal })).data,
      onData: result => {
        data.value = result; loading.value = false; error.value = '';
        sessions.value = sessions.value.map(item => item.id === result.session.id ? { ...item, ...result.session } : item);
      },
      onError: failure => { loading.value = false; fail(failure); },
    });
    function startDashboard(clear = false) {
      if (clear) data.value = null;
      error.value = '';
      if (!selected.value) { poller.stop(); loading.value = false; return; }
      loading.value = !data.value;
      poller.start(selected.value, { repeat: auto.value });
    }
    function visibilityChanged() {
      if (document.visibilityState === 'hidden') { poller.stop(); loading.value = false; }
      else if (props.realtime && auto.value) startDashboard();
    }
    async function loadReport(event) {
      event?.preventDefault();
      reportRequest?.abort();
      const controller = new AbortController();
      reportRequest = controller;
      loading.value = true; error.value = ''; message.value = '';
      try {
        const filters = { ...draft, from_time: draft.from_time ? new Date(draft.from_time).toISOString() : '', to_time: draft.to_time ? new Date(draft.to_time).toISOString() : '' };
        const signature = JSON.stringify(draft);
        const result = await api('/api/reports/statistics?' + queryString(filters), { signal: controller.signal });
        if (!disposed && !controller.signal.aborted) { data.value = result.data; appliedDraft.value = signature; }
      } catch (failure) { if (!disposed && !controller.signal.aborted) fail(failure); }
      finally { if (reportRequest === controller) loading.value = false; }
    }
    async function exportReport() {
      if (!data.value || exporting.value || loading.value || filtersChanged.value) return;
      exportRequest = new AbortController();
      exporting.value = true; error.value = ''; message.value = '';
      try {
        const count = await downloadCsv('/api/reports/export?' + queryString(data.value.filters), exportRequest.signal);
        if (!disposed) message.value = `已生成 ${count} 条记录的 CSV 下载。`;
      } catch (failure) { if (!disposed && !exportRequest.signal.aborted) fail(failure); }
      finally { exporting.value = false; }
    }
    onMounted(async () => {
      bootRequest = new AbortController();
      loading.value = true;
      try {
        const result = await Promise.all([api('/api/sessions', { signal: bootRequest.signal }), api('/api/courses', { signal: bootRequest.signal })]);
        if (disposed) return;
        sessions.value = result[0].data.items; courses.value = result[1].data.items;
        if (props.realtime) {
          selected.value = String((sessions.value.find(item => item.id === Number(props.initialSessionId)) || sessions.value.find(item => item.status === 'ONGOING') || sessions.value[0])?.id || '');
          document.addEventListener('visibilitychange', visibilityChanged);
          startDashboard(true);
        } else await loadReport();
      } catch (failure) { if (!disposed && !bootRequest.signal.aborted) { loading.value = false; fail(failure); } }
    });
    onUnmounted(() => {
      disposed = true; poller.stop(); reportRequest?.abort(); exportRequest?.abort(); bootRequest?.abort();
      document.removeEventListener('visibilitychange', visibilityChanged);
    });
    function metrics() {
      const summary = data.value.summary;
      return h('div', { class: 'metric-grid analytics-metrics' }, [['反馈记录', summary.total], ['反馈学生', summary.responding_students], [props.realtime ? '名单人数' : '有反馈课堂', props.realtime ? data.value.session.scheduled_count : summary.session_count], ['AI 记录', summary.ai_count]].map(([label, count]) => h('div', [h('span', label), h('strong', String(count))])));
    }
    function distribution() {
      return h('section', { class: 'chart-panel distribution-section' }, [h('div', { class: 'chart-heading' }, [h('h3', '情绪分布'), h('span', '按反馈次数')]), h(EmotionDistribution, { items: data.value.emotions })]);
    }
    function trend() {
      return h('section', { class: 'chart-panel trend-section' }, [
        h('div', { class: 'chart-heading' }, [h('h3', props.realtime ? '近一小时趋势' : '反馈趋势'), h('span', props.realtime ? '每 5 分钟' : `UTC · 按${data.value.filters.bucket === 'day' ? '天' : '小时'}`)]),
        h(TrendChart, { points: data.value.trend, realtime: props.realtime, bucket: data.value.filters?.bucket }),
        props.realtime ? h('p', { class: 'data-note' }, '当前时段的数据仍在更新。') : null,
        data.value.trend.length > 48 ? h('p', { class: 'data-note' }, '展示最近 48 个时段，汇总与导出包含完整范围。') : null,
      ]);
    }
    function dimension(title, values, name) {
      return h('section', { class: 'dimension-section' }, [h('h3', title), values.length ? h('div', { class: 'table-wrap' }, h('table', [h('thead', h('tr', [name === 'course_name' ? '课程' : '班级', '反馈记录', '反馈学生', '有反馈课堂'].map(text => h('th', { scope: 'col' }, text)))), h('tbody', values.map(item => h('tr', [h('td', item[name]), h('td', String(item.total)), h('td', String(item.responding_students)), h('td', String(item.session_count))])))])) : h('p', { class: 'empty-note' }, '此范围内暂无反馈。')]);
    }
    function filterForm() {
      return h('form', { class: 'report-filters', onSubmit: loadReport }, [
        h(DataScope, { modelValue: draft.data_scope, disabled: loading.value || exporting.value, 'onUpdate:modelValue': value => draft.data_scope = value }),
        select('课程', draft.course_id, value => { draft.course_id = value; draft.session_id = ''; draft.class_name = ''; }, [['', '全部课程'], ...courses.value.map(item => [String(item.id), item.name])], loading.value || exporting.value),
        select('班级', draft.class_name, value => draft.class_name = value, [['', '全部班级'], ...classes.value.map(name => [name, name])], loading.value || exporting.value),
        ...[['开始时间（可选）', 'from_time'], ['结束时间（可选）', 'to_time']].map(([label, key]) => h('label', { class: 'field' }, [h('span', label), h('input', { type: 'datetime-local', value: draft[key], disabled: loading.value || exporting.value, onInput: event => draft[key] = event.target.value })])),
        select('记录来源', draft.source, value => draft.source = value, [['', '全部来源'], ['MANUAL', '手动反馈'], ['AI', 'AI 记录']], loading.value || exporting.value),
        select('趋势粒度', draft.bucket, value => draft.bucket = value, [['day', '按天'], ['hour', '按小时']], loading.value || exporting.value),
        h('p', { class: 'data-note filter-note' }, '本地时间 · 留空默认近 7 天 · 导出沿用已查询条件'),
        filtersChanged.value ? h('p', { class: 'data-note filter-note', role: 'status' }, '筛选条件已修改，请先查询统计；下方仍为上次查询结果。') : null,
        h('div', { class: 'report-actions' }, [h('button', { class: 'primary-button', disabled: loading.value || exporting.value }, loading.value ? '正在查询…' : '查询统计'), h('button', { class: 'secondary-button', type: 'button', disabled: loading.value || exporting.value || !data.value || filtersChanged.value, onClick: exportReport }, [icon('download', 15), exporting.value ? '正在生成…' : '导出 CSV'])]),
      ]);
    }
    function dashboardControls() {
      return h('div', { class: 'dashboard-controls' }, [h(DataScope, { modelValue: draft.data_scope, 'onUpdate:modelValue': value => { draft.data_scope = value; startDashboard(true); } }), select('选择课堂', selected.value, value => { selected.value = value; startDashboard(true); }, [['', '请选择课堂'], ...sessions.value.map(item => [String(item.id), `${item.course_name} · ${item.class_name} · ${statusName[item.status]}`])]),
        h('div', { class: 'live-controls' }, [h('label', [h('input', { type: 'checkbox', checked: auto.value, onChange: event => { auto.value = event.target.checked; if (auto.value) startDashboard(); else { poller.stop(); loading.value = false; } } }), '自动更新（约每 5 秒）']), h('button', { class: 'secondary-button', disabled: !selected.value, onClick: () => startDashboard() }, [icon('refresh', 15), '刷新'])]),
      ]);
    }
    function latest() {
      return h('section', { class: 'latest-feedback' }, [h('h3', '最新反馈'), data.value.latest.length ? h('div', { class: 'table-wrap' }, h('table', [h('thead', h('tr', ['学生', '表情', '来源', '时间'].map(text => h('th', { scope: 'col' }, text)))), h('tbody', data.value.latest.map(record => h('tr', { key: record.id }, [h('td', { title: record.username || '匿名' }, record.username || '匿名'), h('td', emotionLabel(record.emotion)), h('td', record.is_demo ? '演示' : record.source === 'MANUAL' ? '手动' : 'AI'), h('td', stamp(record.recorded_at))])))])) : h('p', { class: 'empty-note' }, '还没有反馈记录。')]);
    }
    return () => h('div', { class: 'analytics-panel' }, [
      props.initialCourseId ? h('button', { class: 'quiet-button course-return', onClick: () => emit('navigate', { tab: 'courses', courseId: props.initialCourseId }) }, '返回课程详情') : null,
      h('h2', props.realtime ? '实时看板' : '统计与导出'),
      !props.realtime && draft.session_id ? h('p', { class: 'data-note' }, [`当前仅统计所选课堂 #${draft.session_id}。`, h('button', { class: 'quiet-button', disabled: loading.value || exporting.value, onClick: () => { draft.session_id = ''; loadReport(); } }, '查看整门课程')]) : null,
      props.realtime && selected.value ? h('button', { class: 'quiet-button', onClick: () => emit('navigate', { tab: 'classroom', sessionId: Number(selected.value), courseId: sessions.value.find(item => item.id === Number(selected.value))?.course_id }) }, '打开对应课堂') : null,
      props.realtime ? dashboardControls() : filterForm(),
      props.realtime && selected.value ? h('button', { type: 'button', class: 'secondary-button replay-entry', onClick: () => emit('navigate', { tab: 'replay', sessionId: Number(selected.value) }) }, [icon('history', 17), '打开情绪回放']) : null,
      error.value ? h('div', { class: 'form-notice', role: 'alert' }, `${error.value}${data.value ? ' 当前保留上次成功查询的数据。' : ''}`) : null,
      message.value ? h('div', { class: 'form-notice success', role: 'status' }, message.value) : null,
      loading.value ? h('p', { class: 'muted', role: 'status' }, '正在获取数据…') : null,
      data.value ? h('div', { class: 'analytics-results' }, [
        h('p', { class: 'updated-label', role: 'status' }, `更新于 ${stamp(data.value.updated_at)}${props.realtime ? ` · ${statusName[data.value.session.status]}` : ''}`),
        metrics(), h('div', { class: 'analytics-visuals' }, [distribution(), trend()]),
        props.realtime ? latest() : h('div', { class: 'dimension-grid' }, [dimension('按课程统计', data.value.by_course, 'course_name'), dimension('按班级统计', data.value.by_class, 'class_name')]),
        h('p', { class: 'data-note' }, '分布按反馈次数统计，学生人数仅对手动反馈去重。'),
      ]) : !loading.value && !error.value ? h('div', { class: 'empty-state' }, [h('span', { class: 'empty-icon' }, icon('chart', 28)), h('h3', props.realtime ? '等待课堂开始' : '等待一份课堂反馈'), h('p', props.realtime ? '选择课堂，听见大家此刻的感受。' : '设置筛选条件，查看课堂中的情绪变化。')]) : null,
    ]);
  },
};
