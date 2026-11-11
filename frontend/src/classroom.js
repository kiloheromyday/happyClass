import { h, ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { feedbackAvailable, sessionAt } from './session-time.js';
import { api } from './api.js';
import { departmentStyle } from './timetable.js';
import { CameraPanel } from './camera.js';
import { icon, moodFace } from './ui.js';
import { EmotionDistribution } from './charts.js';
import { QuestionsPanel, RecapPanel } from './engagement.js';
import { DataScope } from './data-scope.js';
import { LearningGuidePanel } from './learning-guide.js';
import { QuickBookmark } from './emotion/bookmarks/quick.js';

export const emotions = [
  ['HAPPY', '😊', '开心'], ['NEUTRAL', '😐', '平静'], ['SAD', '😔', '低落'],
  ['ANGRY', '😠', '生气'], ['SURPRISED', '😮', '惊讶'], ['FEAR', '😟', '担忧'], ['DISGUST', '😣', '反感'],
];
const emotionLabel = code => emotions.find(item => item[0] === code)?.slice(1).join(' ') || code;
const statusNames = { UPCOMING: '未开始', ONGOING: '进行中', ENDED: '已结束' };
const dateText = value => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
const localInput = value => {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
};
const textField = (label, name, model, key, options = {}) => h('label', { class: 'field' }, [h('span', label), h('input', { name, value: model[key], onInput: event => model[key] = event.target.value, required: true, maxlength: 120, ...options })]);
const selectField = (label, value, onChange, items, options = {}) => h('label', { class: 'field' }, [h('span', label), h('select', { value, onChange: event => onChange(event.target.value), ...options }, items.map(([id, text]) => h('option', { value: id }, text)))]);

export const ClassroomPanel = {
  props: ['user', 'historyOnly', 'initialSessionId', 'initialCourseId', 'initialView', 'initialDataScope'], emits: ['expired', 'navigate', 'dirty-change'],
  setup(props, { emit }) {
    const sessions = ref([]), courses = ref([]), people = ref([]), selected = ref('');
    const roster = ref([]), selectedStudents = ref(new Set()), stats = ref(null);
    const records = ref([]), total = ref(0), offset = ref(0);
    const loading = ref(false), saving = ref(false), error = ref(''), message = ref('');
    const selectedEmotion = ref(''), retry = ref(null), dataScope = ref(props.initialDataScope || 'ALL');
    const showAll = ref(Boolean(props.initialSessionId)), courseFilter = ref(props.initialCourseId ? String(props.initialCourseId) : ''), clock = ref(Date.now());
    let feedbackAbort = null, detailAbort, refreshAbort, alive = true, courseRetry, sessionRetry;
    const course = reactive({ name: '', teacher_id: '', department_id: '' });
    const departments = ref([]);
    const session = reactive({ course_id: '', starts_at: localInput(new Date()), ends_at: localInput(new Date(Date.now() + 3600000)), classroom: '', class_name: '' });
    const admin = props.user.role === 'ADMIN', student = props.user.role === 'STUDENT';
    const view = ref(['questions', 'guide', 'recap', 'roster'].includes(props.initialView) ? props.initialView : 'overview');
    const drafts = reactive({ questions: false, guide: false, recap: false });
    const hasDraft = computed(() => Object.values(drafts).some(Boolean));
    function dirtyChange(key, value) { drafts[key] = value; emit('dirty-change', hasDraft.value); }
    function mayLeave() { if (hasDraft.value) { error.value = '本节课堂有未保存的内容，请先保存，或在对应功能中取消、放弃修改。'; return false; } return true; }
    function switchView(next) { if (mayLeave()) { view.value = next; error.value = ''; } }
    const timedSessions = computed(() => sessions.value.map(item => sessionAt(item, clock.value)));
    const current = computed(() => timedSessions.value.find(item => String(item.id) === selected.value));
    const canEvaluate = item => feedbackAvailable(item, clock.value);
    const visibleSessions = computed(() => timedSessions.value.filter(item => !student || props.historyOnly || ((!courseFilter.value || String(item.course_id) === courseFilter.value) && (showAll.value || canEvaluate(item)))));
    const locked = computed(() => loading.value || saving.value);
    const students = computed(() => {
      const candidates = new Map(people.value.filter(person => person.role === 'STUDENT').map(person => [person.id, { ...person, status: 'ACTIVE' }]));
      roster.value.forEach(person => candidates.set(person.id, person));
      return [...candidates.values()].sort((a, b) => a.username.localeCompare(b.username));
    });
    function fail(failure) {
      if (failure.status === 401) emit('expired');
      else error.value = failure.message;
    }
    async function refreshAiFeedback() {
      if (feedbackAbort || loading.value || !selected.value) return;
      const sessionId = selected.value, pageOffset = offset.value, scope = dataScope.value;
      const abort = new AbortController(); feedbackAbort = abort;
      try {
        const [summary, history] = await Promise.all([
          api(`/api/sessions/${sessionId}/statistics${scope === 'ALL' ? '' : '?data_scope=' + scope}`, { signal: abort.signal }),
          api(`/api/emoji/history?limit=10&offset=${pageOffset}&session_id=${sessionId}&data_scope=${scope}`, { signal: abort.signal }),
        ]);
        if (alive && !abort.signal.aborted && dataScope.value === scope && selected.value === sessionId && !loading.value) {
          stats.value = summary.data;
          if (offset.value === pageOffset) { records.value = history.data.items; total.value = history.data.total; }
        }
      } catch (failure) { if (alive && !abort.signal.aborted && dataScope.value === scope && selected.value === sessionId) fail(failure); }
      finally { if (feedbackAbort === abort) feedbackAbort = null; }
    }
    onBeforeUnmount(() => { alive = false; feedbackAbort?.abort(); detailAbort?.abort(); refreshAbort?.abort(); emit('dirty-change', false); });
    async function fetchHistory(nextOffset, sessionId, signal) {
      const filter = sessionId ? `&session_id=${sessionId}` : '';
      const result = await api(`/api/emoji/history?limit=10&offset=${nextOffset}${filter}&data_scope=${dataScope.value}`, { signal });
      if (alive && !signal.aborted && selected.value === sessionId) { records.value = result.data.items; total.value = result.data.total; offset.value = nextOffset; }
    }
    async function details(nextOffset = 0) {
      feedbackAbort?.abort(); feedbackAbort = null;
      detailAbort?.abort(); const controller = new AbortController(); detailAbort = controller;
      const sessionId = selected.value;
      const currentRead = () => alive && !controller.signal.aborted && selected.value === sessionId;
      loading.value = true; error.value = ''; stats.value = null; records.value = [];
      roster.value = []; total.value = 0;
      try {
        const tasks = [fetchHistory(nextOffset, sessionId, controller.signal)];
        if (sessionId && !student && !props.historyOnly) tasks.push(api(`/api/sessions/${sessionId}/statistics${dataScope.value === 'ALL' ? '' : '?data_scope=' + dataScope.value}`, { signal: controller.signal }).then(result => { if (currentRead()) stats.value = result.data; }));
        if (sessionId && !student && !props.historyOnly) tasks.push(api(`/api/sessions/${sessionId}/roster`, { signal: controller.signal }).then(result => { if (currentRead()) { roster.value = result.data.items; selectedStudents.value = new Set(result.data.items.map(item => item.id)); } }));
        await Promise.all(tasks);
      } catch (failure) { if (currentRead()) fail(failure); }
      finally { if (alive && detailAbort === controller) loading.value = false; }
    }
    async function refresh(preferred) {
      if (!mayLeave()) return;
      refreshAbort?.abort(); detailAbort?.abort(); const controller = new AbortController(); refreshAbort = controller;
      loading.value = true; error.value = '';
      try {
        const tasks = [api('/api/sessions', { signal: controller.signal }), api('/api/courses', { signal: controller.signal })];
        if (admin) tasks.push(api('/api/admin/people', { signal: controller.signal }), api('/api/departments', { signal: controller.signal }));
        const results = await Promise.all(tasks);
        if (!alive || controller.signal.aborted) return;
        sessions.value = results[0].data.items; courses.value = results[1].data.items;
        if (admin) { people.value = results[2].data.items; departments.value = results[3].data.items; }
        if (!session.course_id && courses.value.length) session.course_id = String(courses.value[0].id);
        const keep = preferred ?? selected.value;
        selected.value = visibleSessions.value.some(item => String(item.id) === keep) ? keep : props.historyOnly ? '' : String((visibleSessions.value.find(item => item.status === 'ONGOING') || visibleSessions.value[0])?.id || '');
        await details();
      } catch (failure) { if (alive && !controller.signal.aborted) fail(failure); }
      finally { if (alive && refreshAbort === controller) loading.value = false; }
    }
    async function mutate(operation) {
      if (locked.value) return;
      saving.value = true; error.value = ''; message.value = '';
      try { await operation(); }
      catch (failure) { fail(failure); }
      finally { saving.value = false; }
    }
    async function createCourse(event) {
      event.preventDefault();
      await mutate(async () => {
        const body = { name: course.name.trim(), teacher_id: Number(course.teacher_id), department_id: course.department_id || null }, signature = JSON.stringify(body);
        if (courseRetry?.signature !== signature) courseRetry = { signature, request_id: crypto.randomUUID() };
        const result = await api('/api/admin/courses', { method: 'POST', body: { ...body, request_id: courseRetry.request_id } });
        courseRetry = null;
        session.course_id = String(result.data.id); course.name = ''; message.value = result.message;
        await refresh();
      });
    }
    async function createSession(event) {
      event.preventDefault();
      if (new Date(session.ends_at) <= new Date(session.starts_at)) { error.value = '结束时间必须晚于开始时间。'; return; }
      await mutate(async () => {
        const body = { ...session, course_id: Number(session.course_id), starts_at: new Date(session.starts_at).toISOString(), ends_at: new Date(session.ends_at).toISOString() }, signature = JSON.stringify(body);
        if (sessionRetry?.signature !== signature) sessionRetry = { signature, request_id: crypto.randomUUID() };
        const result = await api('/api/admin/sessions', { method: 'POST', body: { ...body, request_id: sessionRetry.request_id } });
        sessionRetry = null;
        message.value = result.message; await refresh(String(result.data.id));
      });
    }
    async function saveRoster() {
      await mutate(async () => {
        const result = await api(`/api/admin/sessions/${selected.value}/schedule`, { method: 'PUT', body: { user_ids: [...selectedStudents.value] } });
        message.value = result.message; await refresh(selected.value);
      });
    }
    async function sendEmotion() {
      if (!selectedEmotion.value || !canEvaluate(current.value)) return;
      await mutate(async () => {
        const signature = `${selected.value}:${selectedEmotion.value}`;
        if (retry.value?.signature !== signature) retry.value = { signature, request_id: crypto.randomUUID() };
        const result = await api('/api/emoji', { method: 'POST', body: { session_id: Number(selected.value), emotion: selectedEmotion.value, request_id: retry.value.request_id } });
        retry.value = null; selectedEmotion.value = ''; message.value = result.message;
        await refresh(selected.value);
      });
    }
    let ticker;
    watch(() => visibleSessions.value.map(item => item.id).join(','), () => {
      if (student && !props.historyOnly && !loading.value && !saving.value && !hasDraft.value && !visibleSessions.value.some(item => String(item.id) === selected.value)) {
        const next = String(visibleSessions.value.find(item => item.status === 'ONGOING')?.id || visibleSessions.value[0]?.id || '');
        if (next === selected.value) return;
        selected.value = next; selectedEmotion.value = ''; retry.value = null;
        details();
      }
    });
    onMounted(() => { refresh(props.initialSessionId ? String(props.initialSessionId) : undefined); ticker = setInterval(() => { clock.value = Date.now(); }, 1000); });
    onBeforeUnmount(() => clearInterval(ticker));
    function changeScope() {
      selected.value = String((visibleSessions.value.find(item => item.status === 'ONGOING') || visibleSessions.value[0])?.id || '');
      selectedEmotion.value = ''; retry.value = null; message.value = ''; details();
    }

    function adminForms() {
      return h('details', { class: 'management-tools' }, [h('summary', '创建课程与课堂'), h('div', { class: 'admin-forms' }, [
        h('form', { onSubmit: createCourse }, [h('h3', '1. 创建课程'), textField('课程名称', 'course_name', course, 'name'), selectField('开课院系', course.department_id, value => course.department_id = value, [['', '综合课程 / 未分配'], ...departments.value.map(item => [item.id, item.name])], { name: 'course_department_id' }), selectField('任课教师', course.teacher_id, value => course.teacher_id = value, [['', '请选择教师'], ...people.value.filter(person => person.role === 'TEACHER').map(person => [String(person.id), person.username])], { required: true }), h('p', { class: 'muted' }, '未找到教师时，先到“用户列表”创建教师账号，再返回刷新。'), h('button', { class: 'primary-button', disabled: locked.value }, '创建课程')]),
        h('form', { onSubmit: createSession }, [h('h3', '2. 创建课堂'), selectField('所属课程', session.course_id, value => session.course_id = value, [['', '请选择课程'], ...courses.value.map(item => [String(item.id), item.name])], { required: true }), h('div', { class: 'form-pair' }, [textField('开始时间', 'starts_at', session, 'starts_at', { type: 'datetime-local' }), textField('结束时间', 'ends_at', session, 'ends_at', { type: 'datetime-local' })]), h('p', { class: 'muted' }, '按你电脑的本地时间填写。'), h('div', { class: 'form-pair' }, [textField('教室', 'classroom', session, 'classroom'), textField('班级', 'class_name', session, 'class_name')]), h('button', { class: 'primary-button', disabled: locked.value }, '创建课堂')]),
      ])]);
    }
    function historyTable() {
      return h('section', { class: 'feedback-history' }, [
        h('div', { class: 'section-title' }, [h('h3', student ? '我的反馈历史' : '课堂反馈明细'), h(DataScope, { modelValue: dataScope.value, disabled: locked.value || hasDraft.value, 'onUpdate:modelValue': value => { dataScope.value = value; details(); } }), h('span', { class: 'count' }, `共 ${total.value} 条`)]),
        !loading.value && records.value.length === 0 ? h('p', { class: 'empty-note' }, '暂无反馈记录。') : h('div', { class: 'table-wrap' }, [h('table', [
          h('thead', h('tr', [...(student ? [] : ['学生']), '课程 / 班级', '表情', '来源', '记录时间'].map(text => h('th', { scope: 'col' }, text)))),
          h('tbody', records.value.map(record => h('tr', { key: record.id }, [...(student ? [] : [h('td', record.username || '匿名')]), h('td', `${record.course_name} / ${record.class_name}`), h('td', emotionLabel(record.emotion)), h('td', record.is_demo ? '演示' : record.source === 'MANUAL' ? '手动' : 'AI'), h('td', dateText(record.recorded_at))]))),
        ])]),
        total.value > 10 || offset.value > 0 ? h('div', { class: 'pagination' }, [h('button', { disabled: locked.value || offset.value === 0, onClick: () => details(offset.value - 10) }, '上一页'), h('span', `第 ${Math.floor(offset.value / 10) + 1} 页`), h('button', { disabled: locked.value || offset.value + 10 >= total.value, onClick: () => details(offset.value + 10) }, '下一页')]) : null,
      ]);
    }
    function statistics() {
      if (!stats.value) return null;
      const data = stats.value;
      return h('section', { class: 'statistics' }, [
        h('div', { class: 'metric-grid' }, [['反馈记录', data.total], ['反馈学生', data.responding_students], ['名单人数', data.session.scheduled_count]].map(([label, count]) => h('div', [h('span', label), h('strong', String(count))]))),
        h('h3', '课堂情绪分布'), h(EmotionDistribution, { items: data.emotions }),
        h('p', { class: 'data-note' }, `手动 ${data.manual_count} 条 · AI ${data.ai_count} 条 · 按反馈次数统计${data.demo_count ? ` · 含 ${data.demo_count} 条演示评价` : ''}`),
      ]);
    }
    function rosterEditor() {
      return h('details', { class: 'roster-editor' }, [h('summary', `安排学生名单（已选 ${selectedStudents.value.size} 人）`),
        h('p', { class: 'muted' }, '勾选后点击保存，将替换这节课堂的当前名单。已结束课堂的名单不能修改。'),
        h('div', { class: 'student-options' }, students.value.map(person => h('label', [h('input', { type: 'checkbox', checked: selectedStudents.value.has(person.id), disabled: locked.value || current.value?.status === 'ENDED' || (person.status !== 'ACTIVE' && !selectedStudents.value.has(person.id)), onChange: event => { const next = new Set(selectedStudents.value); event.target.checked ? next.add(person.id) : next.delete(person.id); selectedStudents.value = next; } }), `${person.username}${person.leave_status === 'APPROVED' ? '（已准假）' : person.leave_status === 'PENDING' ? '（请假待审批）' : ''}${person.status === 'ACTIVE' ? '' : '（已停用）'}`]))),
        students.value.length === 0 ? h('p', { class: 'empty-note' }, '还没有学生账号，请先让学生注册。') : null,
        h('button', { class: 'secondary-button', disabled: locked.value || current.value?.status === 'ENDED', onClick: saveRoster }, '保存课堂名单'),
      ]);
    }
    function studentFeedback() {
      return h('section', { class: 'student-feedback' }, [h('h3', current.value.status === 'ENDED' && canEvaluate(current.value) ? '回想刚才的课堂，你感觉如何？' : '此刻，你感觉如何？'), h('p', { class: 'muted' }, canEvaluate(current.value) ? current.value.status === 'ENDED' ? `课后评价开放至 ${dateText(current.value.feedback_closes_at)}。` : '不用想太多，选择最贴近自己的感受。' : current.value.status === 'UPCOMING' ? '课堂尚未开始。' : '本次评价已结束，可以回顾历史记录。'),
        h('p', { class: 'data-note' }, current.value.privacy_mode === 'AGGREGATE' ? '这节课老师只能看到统计，你还可以看自己的记录。' : current.value.privacy_mode === 'ANONYMOUS' ? '老师看到的表情反馈会隐藏账号，你仍能查到自己的记录。' : '这节课用标准模式，老师能看到反馈账号。详情见「反馈隐私」。'),
        h('div', { class: 'emoji-picker', role: 'group', 'aria-label': '选择此刻的感受' }, emotions.map(([code, , label]) => h('button', { class: { chosen: selectedEmotion.value === code }, 'data-emotion': code, type: 'button', disabled: locked.value || !canEvaluate(current.value), 'aria-pressed': selectedEmotion.value === code, onClick: () => { selectedEmotion.value = code; retry.value = null; message.value = ''; } }, [moodFace(code), h('span', label), h('span', { class: 'emotion-selected-dot', 'aria-hidden': 'true' })]))),
        h('button', { class: 'primary-button submit-emotion', disabled: locked.value || !selectedEmotion.value || !canEvaluate(current.value), onClick: sendEmotion }, saving.value ? '正在记录…' : '提交本次感受'),
      ]);
    }
    function learningGuide() {
      return h(LearningGuidePanel, { key: `guide:${selected.value}`, sessionId: Number(selected.value), courseId: current.value.course_id, user: props.user, onDirtyChange: value => dirtyChange('guide', value), onNavigate: value => { if (mayLeave()) emit('navigate', value); }, onExpired: () => emit('expired') });
    }
    return () => h('div', { class: 'classroom-panel', 'aria-busy': locked.value }, [
      props.initialCourseId ? h('button', { type: 'button', class: 'quiet-button course-return', onClick: () => emit('navigate', { tab: 'courses', courseId: props.initialCourseId }) }, '返回课程详情') : null,
      h('div', { class: 'section-title' }, [h('h2', props.historyOnly ? '我的情绪记录' : admin ? '课程与课堂' : student ? '我的课堂' : '课堂反馈'), h('button', { class: 'secondary-button', disabled: locked.value, onClick: () => refresh() }, [icon('refresh', 15), '刷新'])]),
      error.value ? h('div', { class: 'form-notice', role: 'alert' }, error.value) : null,
      message.value ? h('div', { class: 'form-notice success', role: 'status' }, message.value) : null,
      admin && !props.historyOnly ? adminForms() : null,
      student && !props.historyOnly ? h('div', { class: 'daily-classroom-filters' }, [selectField('已加入课程', courseFilter.value, value => { if (!mayLeave()) return; courseFilter.value = value; changeScope(); }, [['', '全部已加入课程'], ...courses.value.map(item => [String(item.id), item.name])], { name: 'daily_course_filter', disabled: locked.value || hasDraft.value }), selectField('课堂范围', showAll.value ? 'ALL' : 'AVAILABLE', value => { if (!mayLeave()) return; showAll.value = value === 'ALL'; changeScope(); }, [['AVAILABLE', '进行中与刚结束'], ['ALL', '全部课堂']], { name: 'daily_session_scope', disabled: locked.value || hasDraft.value })]) : null,
      selectField('选择课堂', selected.value, value => { if (!mayLeave()) return; selected.value = value; selectedEmotion.value = ''; retry.value = null; message.value = ''; details(); }, [...(props.historyOnly ? [['', '全部课堂历史']] : [['', visibleSessions.value.length ? '请选择课堂' : '暂无可评价课堂']]), ...visibleSessions.value.map(item => [String(item.id), `${item.course_name} · ${item.class_name} · ${dateText(item.starts_at)} · ${student && item.status === 'ENDED' && canEvaluate(item) ? '刚结束 · 可评价' : statusNames[item.status]}`])], { disabled: locked.value || hasDraft.value, name: 'daily_session' }),
      loading.value ? h('p', { role: 'status', class: 'muted' }, '正在加载课堂数据…') : null,
      current.value && !props.historyOnly ? h('div', { class: 'session-detail', style: departmentStyle(current.value) }, [h('span', { class: 'department-badge' }, `${current.value.department_name || '综合课程'}${current.value.is_demo ? ' · 演示课程' : ''}`),
        h('div', { class: 'session-meta' }, [h('span', { class: ['session-status', current.value.status.toLowerCase()] }, statusNames[current.value.status]), h('span', `${current.value.teacher_name} · ${current.value.classroom}`), h('span', `${dateText(current.value.starts_at)} — ${dateText(current.value.ends_at)}`)]),
        !student ? h('div', { class: 'classroom-view-tabs', role: 'group', 'aria-label': '课堂教学功能' }, [['overview', '反馈概览'], ['questions', '问题回应'], ['guide', '学习指引'], ['recap', '课后小结'], ['roster', '课堂名单']].map(([key, label]) => h('button', { class: { active: view.value === key }, 'aria-pressed': view.value === key, onClick: () => switchView(key) }, label))) : null,
        admin && !loading.value && view.value === 'roster' ? rosterEditor() : null,
        !admin && !student && view.value === 'roster' ? h('section', { class: 'teaching-roster' }, [h('h3', '本节课堂名单'), h('p', { class: 'data-note' }, `已安排 ${current.value.scheduled_count} 人。学生通过课程加入码添加课程后会自动安排；名单调整由管理员完成。`), h('ul', roster.value.map(person => h('li', { key: person.id }, `${person.username}${person.leave_status === 'APPROVED' ? '（已准假）' : person.leave_status === 'PENDING' ? '（请假待审批）' : ''}`))), !roster.value.length ? h('p', { class: 'empty-note' }, '暂无学生名单。') : null]) : null,
        student && view.value === 'guide' ? learningGuide() : null,
        student && Date.parse(current.value.ends_at) > clock.value ? h('button', { class: 'quiet-button classroom-leave-link', onClick: () => emit('navigate', { tab: 'leaves', sessionId: current.value.id, courseId: current.value.course_id }) }, '本节课申请请假') : null,
        h('button', { class: 'secondary-button', disabled: hasDraft.value, onClick: () => { if (mayLeave()) emit('navigate', { tab: 'evaluations', sessionId: current.value.id, courseId: current.value.course_id }); } }, student ? '填写完整课程评价' : '查看多项评分与匿名建议'),
        (student || view.value === 'overview') && h('button', {
          type: 'button',
          class: 'secondary-button',
          disabled: hasDraft.value,
          onClick: () => {
            if (!mayLeave()) return;
            emit('navigate', {
              tab: 'feedback',
              sessionId: current.value.id,
              courseId: current.value.course_id,
              view: student ? 'compose' : 'queue',
            });
          },
        }, student ? '给老师写条反馈' : '处理本节课堂的情绪反馈'),
        student && h(QuickBookmark, {
          key: current.value.id,
          session: current.value,
          disabled: hasDraft.value,
          expired: () => emit('expired'),
          onBusy: value => dirtyChange('bookmark', value),
          onOpen: target => { if (mayLeave()) emit('navigate', target); },
        }),
        !student && view.value === 'overview' && h('button', {
          type: 'button',
          class: 'secondary-button',
          disabled: hasDraft.value,
          onClick: () => {
            if (mayLeave()) emit('navigate', { tab: 'bookmarks', sessionId: current.value.id, view: 'timeline' });
          },
        }, '查看本节书签统计'),
        student ? studentFeedback() : view.value === 'overview' ? statistics() : null,
        !student && view.value === 'overview' ? h('div', { class: 'guide-actions' }, [h('button', { class: 'secondary-button', onClick: () => emit('navigate', { tab: 'dashboard', sessionId: Number(selected.value), courseId: current.value.course_id }) }, '打开本节实时看板'), h('button', { class: 'quiet-button', onClick: () => emit('navigate', { tab: 'reports', courseId: current.value.course_id }) }, '查看课程统计')]) : null,
        !student && view.value === 'overview' ? h(CameraPanel, { key: `${selected.value}:${current.value.status}`, sessionId: Number(selected.value), ongoing: current.value.status === 'ONGOING', onExpired: () => emit('expired'), onSaved: refreshAiFeedback }) : null,
        !student && view.value === 'overview' ? h('button', { type: 'button', class: 'secondary-button replay-entry', onClick: () => emit('navigate', { tab: 'replay', sessionId: Number(selected.value), courseId: current.value.course_id }) }, [icon('history', 17), '回放本节课堂情绪']) : null,
        student || view.value === 'questions' ? h(QuestionsPanel, { key: `questions:${selected.value}`, sessionId: Number(selected.value), ongoing: current.value.status === 'ONGOING', user: props.user, onDirtyChange: value => dirtyChange('questions', value), onExpired: () => emit('expired') }) : null,
        student && view.value !== 'guide' || !student && view.value === 'guide' ? learningGuide() : null,
        !student && view.value === 'recap' ? h(RecapPanel, { key: `recap:${selected.value}`, sessionId: Number(selected.value), initialOpen: true, onDirtyChange: value => dirtyChange('recap', value), onExpired: () => emit('expired') }) : null,
      ]) : !loading.value && !props.historyOnly ? h('div', { class: 'empty-state' }, [h('span', { class: 'empty-icon' }, icon('classroom', 28)), h('h3', student ? '暂时没有可评价的课堂' : '还没有课堂安排'), h('p', student ? '课程已在“我的课程”中。课堂进行时及结束后 30 分钟内可评价。' : '课堂创建完成后，会显示在这里。')]) : null,
      (props.historyOnly || current.value && (student || view.value === 'overview')) ? historyTable() : null,
    ]);
  },
};
