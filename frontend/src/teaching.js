import { h, ref, computed, onMounted, onBeforeUnmount } from 'vue';
import { api } from './api.js';
import { departmentStyle } from './timetable.js';
import { icon } from './ui.js';

const date = value => new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
const names = { ONGOING: '进行中', UPCOMING: '未开始', ENDED: '已结束' };
export const TeachingPanel = {
  props: ['user'], emits: ['expired', 'navigate'],
  setup(props, { emit }) {
    const data = ref(null), busy = ref(false), error = ref(''), scope = ref('ACTION');
    let alive = true, abort;
    const ordered = computed(() => [...(data.value?.sessions || [])].sort((a, b) => Date.parse(a.starts_at) - Date.parse(b.starts_at) || a.id - b.id));
    const featured = computed(() => ordered.value.find(item => item.status === 'ONGOING') || ordered.value.find(item => item.status === 'UPCOMING'));
    const pending = item => item.pending_leaves > 0 || item.open_questions > 0 || item.status === 'ENDED' && !item.has_reflection;
    const visible = computed(() => scope.value === 'ACTION' ? ordered.value.filter(pending).sort((a, b) => b.open_questions - a.open_questions || Date.parse(b.ends_at) - Date.parse(a.ends_at)) : scope.value === 'ALL' ? [...ordered.value].reverse() : ordered.value.filter(item => item.status === scope.value));
    async function load() {
      abort?.abort(); const controller = new AbortController(); abort = controller;
      busy.value = true; error.value = '';
      try { const result = await api('/api/teaching/overview', { signal: controller.signal }); if (alive && !controller.signal.aborted) data.value = result.data; }
      catch (failure) { if (alive && !controller.signal.aborted) { if (failure.status === 401) emit('expired'); else error.value = failure.message; } }
      finally { if (alive && abort === controller) busy.value = false; }
    }
    function go(item, tab = 'classroom', view = 'overview') { emit('navigate', { tab, view, sessionId: item.id, courseId: item.course_id }); }
    const action = (label, item, tab, view, primary = false) => h('button', { type: 'button', class: primary ? 'primary-button' : 'secondary-button', 'aria-label': `${label}：${item.id}`, onClick: () => go(item, tab, view) }, label);
    onMounted(load); onBeforeUnmount(() => { alive = false; abort?.abort(); });
    return () => h('section', { class: 'teaching-panel', 'aria-busy': busy.value }, [
      h('div', { class: 'section-title' }, [h('div', [h('p', { class: 'eyebrow' }, '把每一节课，连接起来'), h('h2', '教学工作台')]), h('button', { class: 'quiet-button', disabled: busy.value, onClick: load }, [icon('refresh', 15), '刷新教学安排'])]),
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, [error.value, h('button', { class: 'quiet-button', onClick: load }, '重试')]) : null,
      busy.value ? h('p', { class: 'data-note', role: 'status' }, '正在整理课程与待办…') : null,
      data.value ? h('div', [
        h('div', { class: 'leave-teaching-entry' }, [h('span', data.value.summary.pending_leaves ? `${data.value.summary.pending_leaves} 份请假申请待审批` : '课堂请假'), h('button', { class: 'secondary-button', onClick: () => emit('navigate', 'leaves') }, props.user.role === 'ADMIN' ? '查看请假记录' : '进入请假审批')]),
        h('div', { class: 'course-metrics teaching-metrics' }, [['所授课程', data.value.summary.courses], ['进行中课堂', data.value.summary.ongoing], ['待回应问题', data.value.summary.open_questions], ['待写教学反思', data.value.summary.pending_reflections]].map(([label, value]) => h('div', [h('strong', String(value)), h('span', label)]))),
        featured.value ? h('section', { class: 'teaching-feature', style: departmentStyle(featured.value) }, [h('div', [h('span', { class: 'course-eyebrow' }, featured.value.status === 'ONGOING' ? '正在上课' : '下一节课堂'), h('h3', featured.value.course_name), h('p', `${date(featured.value.starts_at)} · ${featured.value.classroom} · ${featured.value.class_name}`), h('p', { class: 'data-note' }, `名单 ${featured.value.scheduled_count} 人 · 反馈 ${featured.value.record_count} 条`)]), h('div', { class: 'teaching-feature-actions' }, [action('进入课堂', featured.value, 'classroom', 'overview', true), action('实时看板', featured.value, 'dashboard'), action('学习指引', featured.value, 'classroom', 'guide')])]) : null,
        h('div', { class: 'course-schedule-title' }, [h('h3', '课堂与跟进'), h('button', { class: 'quiet-button', onClick: () => emit('navigate', 'courses') }, ['查看所授课程', icon('arrow', 15)])]),
        h('div', { class: 'course-scope teaching-filters', role: 'group', 'aria-label': '教学课堂范围' }, [['ACTION', '待跟进'], ['ONGOING', '进行中'], ['UPCOMING', '待上课'], ['ENDED', '已结束'], ['ALL', '全部']].map(([key, label]) => h('button', { class: { active: scope.value === key }, 'aria-pressed': scope.value === key, onClick: () => scope.value = key }, label))),
        h('div', { class: 'teaching-session-list' }, visible.value.map(item => h('article', { class: 'course-class teaching-colored-class', style: departmentStyle(item), key: item.id }, [h('div', { class: 'course-class-heading' }, [h('div', [h('h4', item.course_name), h('p', `${date(item.starts_at)} · ${item.classroom} · ${item.class_name}`)]), h('span', { class: ['session-status', item.status.toLowerCase()] }, names[item.status])]), h('div', { class: 'teaching-state-row' }, [item.pending_leaves ? h('span', `${item.pending_leaves} 份请假待审批`) : null, item.approved_leaves ? h('span', `${item.approved_leaves} 人已准假`) : null,h('span', item.open_questions ? `${item.open_questions} 个问题待回应` : item.question_count ? '问题已跟进' : '暂无问题卡'), h('span', item.guide_published ? '学习指引已发布' : '学习指引未发布'), item.status === 'ENDED' ? h('span', item.has_reflection ? '教学反思已保存' : '待写教学反思') : null]), h('div', { class: 'course-class-actions' }, [action('课堂反馈', item, 'classroom', 'overview'), action('回应问题', item, 'classroom', 'questions'), action('学习指引', item, 'classroom', 'guide'), item.status === 'ENDED' ? action('课后小结', item, 'classroom', 'recap') : null])]))),
        !visible.value.length ? h('div', { class: 'empty-state' }, [icon('book', 28), h('h3', scope.value === 'ACTION' ? '暂时没有待跟进事项' : '这个范围还没有课堂'), h('p', data.value.summary.courses ? '可以到所授课程中安排课堂、准备学习指引。' : '课程分配后，将在这里展示教学安排。')]) : null,
      ]) : null,
    ]);
  },
};
