import { h, ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { DataScope, matchesScope } from './data-scope.js';
import { feedbackAvailable, sessionAt } from './session-time.js';
import { api } from './api.js';
import { icon } from './ui.js';
import { JoinClassPanel, JoinCodePanel } from './join-codes.js';
import { SchedulePanel } from './schedule.js';
import { Timetable, departmentStyle } from './timetable.js';

const names = { UPCOMING: '未开始', ONGOING: '进行中', ENDED: '已结束' };
const date = value => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
const time = value => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));

export const CoursesPanel = {
  props: ['user', 'initialCourseId'], emits: ['expired', 'navigate', 'dirty-change'],
  setup(props, { emit }) {
    const courses = ref([]), sessions = ref([]), detail = ref(null), selected = ref(props.initialCourseId || null);
    const loading = ref(false), error = ref(''), message = ref(''), adding = ref(false), scope = ref('ALL'), invitation = ref('');
    const clock = ref(Date.now());
    const scheduleDirty = ref(false);
    const dataScope = ref('ALL'), archived = ref('ACTIVE');
    const layout = ref('cards'), department = ref('ALL'), query = ref('');
    const departments = computed(() => [...new Map(courses.value.filter(item => item.department_id).map(item => [item.department_id, item])).values()]);
    const filteredCourses = computed(() => courses.value.filter(item => matchesScope(item, dataScope.value) && (archived.value === 'ALL' || !item.archived) && (department.value === 'ALL' || item.department_id === department.value) && `${item.name} ${item.teacher_name || ''} ${item.department_name || ''}`.toLowerCase().includes(query.value.trim().toLowerCase())));
    const filteredIds = computed(() => new Set(filteredCourses.value.map(item => item.id)));
    const student = props.user.role === 'STUDENT';
    let alive = true, readAbort, timer;
    const available = item => feedbackAvailable(item, clock.value);
    const timed = items => items.map(item => sessionAt(item, clock.value));
    const ordered = items => [...items].sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at) || a.id - b.id);
    const nextClass = items => ordered(timed(items)).find(item => item.status === 'ONGOING') || ordered(timed(items)).find(item => item.status === 'UPCOMING');
    const visible = computed(() => ordered(timed(detail.value?.sessions || [])).filter(item => scope.value === 'ALL' || item.status === scope.value));
    const inviteClass = computed(() => timed(detail.value?.sessions || []).find(item => String(item.id) === invitation.value));
    function fail(failure) { if (failure.status === 401) emit('expired'); else error.value = failure.message; }
    async function load(courseId = selected.value) {
      if (scheduleDirty.value) { error.value = '新课堂安排尚未保存，请先保存或放弃安排。'; return; }
      readAbort?.abort(); const abort = new AbortController(); readAbort = abort;
      selected.value = courseId || null; detail.value = null; error.value = ''; loading.value = true;
      try {
        if (courseId) {
          const result = await api(`/api/courses/${courseId}`, { signal: abort.signal });
          if (!alive || abort.signal.aborted) return;
          detail.value = result.data;
          const item = nextClass(result.data.sessions) || ordered(result.data.sessions).at(-1);
          invitation.value = item ? String(item.id) : '';
        } else {
          const results = await Promise.all([api('/api/courses', { signal: abort.signal }), api('/api/sessions', { signal: abort.signal })]);
          if (!alive || abort.signal.aborted) return;
          courses.value = results[0].data.items; sessions.value = results[1].data.items;
        }
      } catch (failure) { if (alive && !abort.signal.aborted) fail(failure); }
      finally { if (alive && readAbort === abort) loading.value = false; }
    }
    function open(id) { scope.value = 'ALL'; adding.value = false; message.value = ''; load(id); }
    function navigate(tab, item, view) { emit('navigate', { tab, courseId: selected.value, sessionId: item.id, view }); }
    const badge = item => h('span', { class: ['session-status', item.status.toLowerCase()] }, available(item) && item.status === 'ENDED' ? '课后可评价' : names[item.status]);
    const metric = (label, value) => h('div', [h('strong', String(value)), h('span', label)]);
    function cards() {
      return filteredCourses.value.length ? h('div', { class: 'course-card-grid' }, filteredCourses.value.map((course, index) => {
        const items = timed(sessions.value).filter(item => item.course_id === course.id), next = nextClass(items);
        return h('button', { type: 'button', class: 'course-card', style: departmentStyle(course), key: course.id, 'aria-label': `查看课程详情：${course.name}`, onClick: () => open(course.id) }, [
          h('div', { class: 'course-card-top' }, [h('span', { class: 'course-book' }, icon('book', 24)), h('span', { class: 'course-number' }, String(index + 1).padStart(2, '0'))]),
          h('span', { class: 'department-badge' }, course.department_name || '综合课程'), h('h3', course.name), h('p', { class: 'course-teacher' }, `任课教师 · ${course.teacher_name || '待安排'}${course.is_demo ? ' · 演示' : ''}`),
          h('div', { class: 'course-card-next' }, [h('span', next ? next.status === 'ONGOING' ? '此刻的课堂' : '下一次课堂' : '课堂安排'), h('strong', next ? date(next.starts_at) : items.length ? '本轮课堂已结束' : '等待老师安排'), next ? h('small', `${next.classroom} · ${next.class_name}`) : null]),
          h('div', { class: 'course-card-bottom' }, [h('span', `共 ${items.length} 节 · ${items.filter(item => item.status === 'ENDED').length} 节已结束`), h('span', { class: 'course-detail-link' }, ['查看详情', icon('arrow', 15)])]),
        ]);
      })) : h('div', { class: 'empty-state' }, [icon('book', 30), h('h3', courses.value.length ? '没有符合条件的课程' : student ? '还没有加入课程' : '暂未分配课程'), h('p', courses.value.length ? '试试其他关键词或院系。' : student ? '添加一门课程，开始留下课堂的点滴。' : '课程分配后会显示在这里。')]);
    }
    function classroom(item) {
      return h('article', { class: 'course-class', key: item.id }, [
        h('div', { class: 'course-class-heading' }, [h('div', [h('h4', date(item.starts_at)), h('p', `${time(item.starts_at)} — ${time(item.ends_at)} · ${item.classroom} · ${item.class_name}`)]), badge(item)]),
        h('div', { class: 'course-class-bottom' }, [h('p', { class: 'data-note' }, student ? `我的反馈 ${item.personal.feedback_count} 次 · 笔记 ${item.personal.note_count} 篇${item.personal.pending_count ? ` · ${item.personal.pending_count} 篇待回顾` : ''}` : `名单 ${item.scheduled_count} 人 · 反馈 ${item.record_count} 条`),
          h('div', { class: 'course-class-actions' }, [
            student && Date.parse(item.ends_at) > clock.value ? h('button', { type: 'button', class: 'quiet-button', 'aria-label': `课堂请假：${item.id}`, onClick: () => navigate('leaves', item) }, '申请请假') : null,
            !student ? h('button', { type: 'button', class: 'quiet-button', onClick: () => navigate('dashboard', item), 'aria-label': `实时看板：${item.id}` }, '实时看板') : null,
            !student || item.guide_published ? h('button', { type: 'button', class: 'quiet-button', onClick: () => navigate('classroom', item, 'guide'), 'aria-label': `学习指引：${item.id}` }, '学习指引') : null,
            student ? h('button', { type: 'button', class: 'quiet-button', onClick: () => navigate('notes', item, 'notes'), 'aria-label': `课堂笔记：${item.id}` }, '课堂笔记') : null,
            student ? h('button', { type: 'button', class: 'quiet-button', onClick: () => navigate('notes', item, 'review'), 'aria-label': `个人回顾：${item.id}` }, '个人回顾') : null,
            h('button', { type: 'button', class: available(item) && student ? 'primary-button' : 'secondary-button', onClick: () => navigate('classroom', item), 'aria-label': `打开课堂：${item.id}` }, student && available(item) ? '去评价' : student ? '查看课堂' : '课堂管理'),
          ]),
        ]),
      ]);
    }
    function details() {
      const { course } = detail.value, items = timed(detail.value.sessions), next = nextClass(items);
      const summary = { ...detail.value.summary, ...Object.fromEntries(['UPCOMING', 'ONGOING', 'ENDED'].map(status => [status.toLowerCase(), items.filter(item => item.status === status).length])) };
      return h('div', { class: 'course-detail' }, [
        h('section', { class: 'course-hero', style: departmentStyle(course) }, [h('span', { class: 'course-eyebrow' }, course.department_name || (student ? '我的学习旅程' : '课程空间')), h('h2', course.name), course.archived ? h('span', { class: 'table-badge' }, '已归档') : null, h('p', `任课教师 · ${course.teacher_name || '待安排'}${course.is_demo ? ' · 演示课程' : ''}`),
          h('div', { class: 'course-hero-next' }, [icon('classroom', 19), h('div', [h('span', next ? next.status === 'ONGOING' ? '课堂正在进行' : '下一次课堂' : '课程动态'), h('strong', next ? `${date(next.starts_at)} · ${next.classroom}` : items.length ? '已安排的课堂均已结束，随时回来看看。' : '还没有课堂安排，稍后再来看看。')])]),
        ]),
        h('div', { class: 'course-metrics' }, [metric('已安排课堂', summary.total), metric('已结束课堂', summary.ended), ...(student ? [metric('我的反馈', summary.feedback_count), metric('我的笔记', summary.note_count)] : [metric('进行中', summary.ongoing), metric('待开始', summary.upcoming)])]),
        student && summary.total ? h('p', { class: 'course-personal-note' }, `已在 ${summary.participated_sessions} 节课堂留下感受${summary.pending_count ? `，还有 ${summary.pending_count} 篇笔记等待回顾` : ''}。`) : null,
        !student && !course.archived ? h(SchedulePanel, { courseId: course.id, onExpired: () => emit('expired'), onDirtyChange: value => { scheduleDirty.value = value; emit('dirty-change', value); }, onCreated: async (_, notice) => { scheduleDirty.value = false; emit('dirty-change', false); message.value = notice; await load(course.id); } }) : null,
        h('div', { class: 'course-schedule-title' }, [h('h3', '课堂安排'), h('div', { class: 'course-scope', role: 'group', 'aria-label': '筛选课堂状态' }, [['ALL', '全部'], ['UPCOMING', '未开始'], ['ONGOING', '进行中'], ['ENDED', '已结束']].map(([key, label]) => h('button', { type: 'button', class: { active: scope.value === key }, 'aria-pressed': scope.value === key, onClick: () => scope.value = key }, label)))]),
        visible.value.length ? h('div', { class: 'course-schedule' }, visible.value.map(classroom)) : h('p', { class: 'empty-note' }, items.length ? '这个状态下还没有课堂。' : '老师安排课堂后，会显示在这里。'),
        !student && !course.archived && items.length ? h('section', { class: 'course-invitation' }, [h('h3', '邀请学生加入课程'), h('label', { class: 'field' }, [h('span', '用于加入的课堂'), h('select', { name: 'course_invitation_session', value: invitation.value, onChange: event => invitation.value = event.target.value }, ordered(items).map(item => h('option', { value: String(item.id) }, `${date(item.starts_at)} · ${item.class_name} · ${names[item.status]}`)))]), inviteClass.value ? h(JoinCodePanel, { key: invitation.value, sessionId: Number(invitation.value), ended: inviteClass.value.status === 'ENDED', onExpired: () => emit('expired') }) : null]) : null,
      ]);
    }
    onMounted(() => { load(); timer = setInterval(() => { clock.value = Date.now(); }, 1000); });
    onBeforeUnmount(() => { alive = false; readAbort?.abort(); clearInterval(timer); });
    return () => h('div', { class: 'courses-panel', 'aria-busy': loading.value }, [
      h('div', { class: 'section-title' }, [selected.value ? h('button', { type: 'button', class: 'quiet-button', onClick: () => { message.value = ''; load(null); } }, props.user.role === 'ADMIN' ? '返回全校课程' : '返回我的课程') : h('h2', props.user.role === 'ADMIN' ? '全校课程' : '我的课程'), h('div', { class: 'course-actions' }, [selected.value ? h('button', { class: 'secondary-button', disabled: scheduleDirty.value, onClick: () => emit('navigate', { tab: 'evaluations', courseId: selected.value }) }, '课程评价') : null, student && !selected.value ? h('button', { type: 'button', class: 'secondary-button', 'aria-expanded': adding.value, onClick: () => adding.value = !adding.value }, adding.value ? '收起添加' : '添加课程') : null, h('button', { type: 'button', class: 'quiet-button', disabled: loading.value, onClick: () => load() }, [icon('refresh', 15), '刷新'])])]),
      error.value ? h('div', { class: 'form-notice', role: 'alert' }, [error.value, h('button', { type: 'button', class: 'quiet-button', onClick: () => load() }, '重试')]) : null,
      message.value ? h('p', { class: 'form-notice success', role: 'status' }, message.value) : null,
      adding.value && !selected.value ? h(JoinClassPanel, { onExpired: () => emit('expired'), onJoined: async (_, notice) => { adding.value = false; message.value = notice; await load(null); } }) : null,
      !selected.value && courses.value.length ? h('div', { class: 'course-browse-tools' }, [h(DataScope, { modelValue: dataScope.value, 'onUpdate:modelValue': value => dataScope.value = value }), h('select', { 'aria-label': '课程显示范围', value: archived.value, onChange: e => archived.value = e.target.value }, [h('option', { value: 'ACTIVE' }, '当前课程'), h('option', { value: 'ALL' }, '含已归档课程')]), h('input', { name: 'course_query', 'aria-label': '搜索我的课程', placeholder: '课程、院系或教师', value: query.value, onInput: event => query.value = event.target.value }), h('select', { name: 'course_department', 'aria-label': '筛选课程院系', value: department.value, onChange: event => department.value = event.target.value }, [h('option', { value: 'ALL' }, '全部院系'), ...departments.value.map(item => h('option', { value: item.department_id }, item.department_name))]), h('div', { class: 'campus-view-switch', role: 'group', 'aria-label': '课程展示方式' }, [['cards', '课程卡片'], ['calendar', '课程表']].map(([value, label]) => h('button', { class: { active: layout.value === value }, 'aria-pressed': layout.value === value, onClick: () => layout.value = value }, label)))]) : null,
      loading.value ? h('p', { class: 'empty-note', role: 'status' }, '正在读取课程…') : selected.value ? detail.value ? details() : null : layout.value === 'calendar' ? h(Timetable, { sessions: timed(sessions.value).filter(item => filteredIds.value.has(item.course_id)), onOpen: item => emit('navigate', { tab: 'classroom', courseId: item.course_id, sessionId: item.id }) }) : cards(),
    ]);
  },
};
