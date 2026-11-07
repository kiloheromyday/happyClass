import { h, ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { DataScope } from './data-scope.js';
import { api } from './api.js';
import { icon } from './ui.js';
import { Timetable, departmentStyle, chinaDay } from './timetable.js';

const states = { ONGOING: '进行中', UPCOMING: '未开始', ENDED: '已结束' };
const emotions = { HAPPY: ['开心', '#e4b955'], NEUTRAL: ['平静', '#86b391'], SURPRISED: ['惊讶', '#a799c9'], SAD: ['低落', '#88a9cb'], FEAR: ['担忧', '#d29d79'], ANGRY: ['生气', '#cc7e7e'], DISGUST: ['反感', '#a4a982'] };
const date = value => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));

export const CampusPanel = {
  emits: ['navigate', 'expired'],
  setup(_, { emit }) {
    const data = ref(null), loading = ref(false), error = ref(''), q = ref(''), department = ref('ALL'), view = ref('calendar'), state = ref('ALL'), selected = ref(null);
    const selectionElement = ref(null), dataScope = ref('ALL');
    let alive = true, abort;
    async function load() {
      abort?.abort(); const controller = new AbortController(); abort = controller; loading.value = true; error.value = '';
      try { const response = await api('/api/admin/campus' + (dataScope.value === 'ALL' ? '' : '?data_scope=' + dataScope.value), { signal: controller.signal }); if (alive && !controller.signal.aborted) data.value = response.data; }
      catch (failure) { if (alive && !controller.signal.aborted) { if (failure.status === 401) emit('expired'); else error.value = failure.message; } }
      finally { if (alive && abort === controller) loading.value = false; }
    }
    const departments = computed(() => [...new Map((data.value?.courses || []).filter(item => item.department_id).map(item => [item.department_id, item])).values()]);
    const courses = computed(() => (data.value?.courses || []).filter(item => (department.value === 'ALL' || (item.department_id || 'none') === department.value) && (state.value === 'ALL' || data.value.sessions.some(session => session.course_id === item.id && session.status === state.value)) && `${item.name} ${item.teacher_name} ${item.department_name || ''}`.toLowerCase().includes(q.value.trim().toLowerCase())));
    const ids = computed(() => new Set(courses.value.map(item => item.id)));
    const sessions = computed(() => (data.value?.sessions || []).filter(item => ids.value.has(item.course_id) && (state.value === 'ALL' || state.value === item.status)));
    const active = computed(() => sessions.value.find(item => item.id === selected.value));
    const feedback = computed(() => courses.value.reduce((sum, item) => sum + item.summary.feedback_count, 0));
    const today = chinaDay(new Date());
    const scopeContext = () => dataScope.value === 'ALL' ? {} : { dataScope: dataScope.value };
    function navigate(tab, item) { emit('navigate', { tab, courseId: item.course_id, sessionId: item.id, ...scopeContext() }); }
    async function open(item) { selected.value = item.id; await nextTick(); selectionElement.value?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }); selectionElement.value?.focus?.({ preventScroll: true }); }
    function courseCard(item) {
      const counts = item.summary;
      return h('article', { class: 'campus-course-card', style: departmentStyle(item), key: item.id }, [
        h('div', { class: 'campus-course-heading' }, [h('span', { class: 'department-badge' }, item.department_name || '综合课程'), item.is_demo ? h('span', { class: 'demo-data-badge' }, '演示') : null]),
        h('h3', item.name), h('p', { class: 'campus-teacher' }, item.teacher_name),
        h('div', { class: 'campus-card-metrics' }, [['节课堂', counts.session_count], ['条评价', counts.feedback_count], ['位参与学生', counts.responding_students]].map(([label, count]) => h('div', [h('strong', String(count)), h('span', label)]))),
        h('div', { class: 'campus-emotion-bar', 'aria-label': `课程情绪分布，共 ${counts.feedback_count} 条` }, item.emotions.map(entry => h('span', { style: { background: emotions[entry.emotion]?.[1], width: `${entry.count / Math.max(1, counts.feedback_count) * 100}%` }, title: `${emotions[entry.emotion]?.[0]} ${entry.count} 条` }))),
        h('p', { class: 'campus-emotion-caption' }, counts.feedback_count ? item.emotions.map(entry => `${emotions[entry.emotion]?.[0] || entry.emotion} ${entry.count}`).join(' · ') : '还没有课堂评价'),
        h('div', { class: 'campus-card-actions' }, [h('span', counts.demo_feedback_count ? `含 ${counts.demo_feedback_count} 条演示评价` : '课堂评价汇总'), h('button', { class: 'quiet-button', onClick: () => emit('navigate', { tab: 'courses', courseId: item.id }) }, ['课程详情', icon('arrow', 14)]), h('button', { class: 'quiet-button', 'aria-label': `查看课程评价：${item.id}`, onClick: () => emit('navigate', { tab: 'reports', courseId: item.id, ...scopeContext() }) }, '评价统计'), h('button', { class: 'quiet-button', onClick: () => emit('navigate', { tab: 'evaluations', courseId: item.id, ...scopeContext() }) }, '多项评分')]),
      ]);
    }
    function detail() {
      const item = active.value;
      if (!item) return null;
      return h('section', { ref: selectionElement, tabindex: -1, class: 'campus-selection', style: departmentStyle(item), 'aria-label': '所选课堂详情' }, [h('div', [h('span', { class: 'department-badge' }, item.department_name || '综合课程'), h('h3', item.course_name), h('p', `${date(item.starts_at)} — ${date(item.ends_at)} · ${item.classroom} · ${item.class_name}`), h('p', `${item.teacher_name} · ${states[item.status]} · 名单 ${item.scheduled_count} 人 · 课堂评价 ${item.record_count} 条`)]), h('div', { class: 'campus-selection-actions' }, [h('button', { class: 'secondary-button', onClick: () => navigate('classroom', item) }, '查看本节评价'), h('button', { class: 'quiet-button', onClick: () => navigate('reports', item) }, '本节评价统计'), h('button', { class: 'quiet-button', onClick: () => selected.value = null }, '收起课堂详情')])]);
    }
    onMounted(load); onBeforeUnmount(() => { alive = false; abort?.abort(); });
    return () => h('section', { class: 'campus-panel', 'aria-busy': loading.value }, [
      h('div', { class: 'section-title' }, [h('div', [h('p', { class: 'campus-eyebrow' }, 'CAMPUS / 全校教学'), h('h2', '全校开课')]), h('button', { class: 'quiet-button', disabled: loading.value, onClick: load }, [icon('refresh', 15), '刷新'])]),
      h('p', { class: 'campus-intro' }, '从一周课表，看到每一间课堂。'),
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, [error.value, h('button', { class: 'quiet-button', onClick: load }, '重试')]) : null,
      data.value ? h('div', [
        h('div', { class: 'campus-summary' }, [['门课程', courses.value.length], ['节今日课堂', sessions.value.filter(item => chinaDay(item.starts_at) === today).length], ['节开课安排', sessions.value.length], ['条课堂评价', feedback.value]].map(([label, count]) => h('div', [h('strong', String(count)), h('span', label)]))),
        h('div', { class: 'campus-filters' }, [h(DataScope, { modelValue: dataScope.value, disabled: loading.value, 'onUpdate:modelValue': value => { dataScope.value = value; selected.value = null; data.value = null; load(); } }), h('input', { name: 'campus_query', 'aria-label': '搜索全校课程', placeholder: '搜索课程、院系或教师', value: q.value, onInput: event => q.value = event.target.value }), h('select', { name: 'campus_department', 'aria-label': '筛选开课院系', value: department.value, onChange: event => department.value = event.target.value }, [h('option', { value: 'ALL' }, '全部院系'), ...departments.value.map(item => h('option', { value: item.department_id }, item.department_name)), h('option', { value: 'none' }, '未分配院系')]), h('select', { name: 'campus_status', 'aria-label': '筛选开课状态', value: state.value, onChange: event => state.value = event.target.value }, [['ALL', '全部状态'], ...Object.entries(states)].map(([value, label]) => h('option', { value }, label)))]),
        h('div', { class: 'department-legend', 'aria-label': '院系颜色图例' }, departments.value.map(item => h('button', { class: ['department-chip', { selected: department.value === item.department_id }], style: departmentStyle(item), 'aria-pressed': department.value === item.department_id, onClick: () => department.value = department.value === item.department_id ? 'ALL' : item.department_id }, [h('i'), item.department_short]))),
        h('div', { class: 'campus-view-switch', role: 'group', 'aria-label': '全校开课展示方式' }, [['calendar', '一周课表'], ['courses', '课程与评价']].map(([value, label]) => h('button', { class: { active: view.value === value }, 'aria-pressed': view.value === value, onClick: () => view.value = value }, label))),
        view.value === 'calendar' ? h(Timetable, { sessions: sessions.value, onOpen: open }) : h('div', { class: 'campus-course-grid' }, courses.value.map(courseCard)),
        detail(), !courses.value.length ? h('p', { class: 'empty-note' }, '没有符合条件的课程。') : null,
        data.value.summary.demo_feedback_count ? h('p', { class: 'campus-demo-note' }, '演示课程参考中国科大学科设置；排课、成员与标注的评价为合成演示数据。') : null,
      ]) : loading.value ? h('p', { class: 'empty-note', role: 'status' }, '正在读取全校开课信息…') : null,
    ]);
  },
};
