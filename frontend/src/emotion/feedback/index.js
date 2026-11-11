import { h, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { createPoller } from '../../polling.js';
import { defaultFilters, normalizeFilters, read, scoped, useResource } from './client.js';
import { FeedbackComposer } from './composer.js';
import { FeedbackDetail } from './detail.js';
import { FeedbackQueue } from './queue.js';
import { FeedbackReports, FeedbackTodos } from './dashboard.js';
import { FeedbackGroups } from './groups.js';
import { FeedbackInbox } from './inbox.js';
import { FeedbackReviewDesk } from './review-desk.js';
import { FeedbackPolicies, FeedbackTemplates } from './settings.js';
import { actions, badge, button, notice } from './ui.js';

const sharedTabs = [
  ['todos', '待办'],
  ['queue', '反馈列表'],
  ['review-desk', '回访日程'],
  ['inbox', '通知'],
  ['reports', '处理统计'],
];

const staffTabs = [
  ['groups', '集中处理'],
  ['templates', '回应模板'],
  ['policy', '课程规则'],
];

export const FeedbackCenter = {
  props: ['user', 'initialSessionId', 'initialCourseId', 'initialView'],
  emits: ['dirty-change', 'navigate', 'expired'],
  setup(props, { emit }) {
    const staff = props.user.role !== 'STUDENT';
    const expired = () => emit('expired');
    const catalog = useResource(signal => read('/options', {}, signal), expired);
    const selection = ref(normalizeFilters({
      session_id: props.initialSessionId || null,
      course_id: props.initialCourseId || null,
    }));
    const startPage = props.initialView === 'compose' && !staff
      ? 'compose'
      : props.initialSessionId ? 'queue' : 'todos';
    const page = ref(startPage);
    const caseId = ref(null);
    const detailTab = ref('overview');
    const from = ref('queue');
    const seed = ref([]);
    const groupId = ref(null);
    const unread = ref(0);
    const revision = ref(0);
    const dirty = ref(false);
    const announcement = ref('');
    const heading = ref(null);

    let inboxRevision = 0;
    const poller = createPoller({
      interval: 30000,
      load: async (_, signal) => {
        const revision = inboxRevision;
        return { revision, data: await read('/inbox', { limit: 1 }, signal) };
      },
      onData: result => { if (result.revision === inboxRevision) unread.value = result.data.unread_count; },
      onError: failure => { if (failure.status === 401) expired(); },
    });

    onMounted(() => {
      catalog.load();
      poller.start('feedback');
    });

    onBeforeUnmount(() => {
      poller.stop();
      emit('dirty-change', false);
    });

    function onDirty(value) {
      dirty.value = value;
      emit('dirty-change', value);
    }

    function focusHeading() {
      nextTick(() => heading.value?.focus({ preventScroll: true }));
    }

    function go(next) {
      if (dirty.value || next === page.value) return;
      if (next === 'groups') {
        seed.value = [];
        groupId.value = null;
      }
      announcement.value = '';
      page.value = next;
      focusHeading();
    }

    function changed() {
      revision.value += 1;
      inboxRevision += 1;
      poller.start('feedback');
    }

    function open(id, tab = 'overview') {
      if (dirty.value) return;
      if (page.value !== 'detail') from.value = page.value;
      caseId.value = id;
      detailTab.value = tab;
      page.value = 'detail';
      focusHeading();
    }

    function back() {
      if (dirty.value) return;
      page.value = ['detail', 'compose'].includes(from.value) ? 'queue' : from.value;
      announcement.value = '';
      focusHeading();
    }

    function compose() {
      if (staff || dirty.value) return;
      from.value = page.value;
      announcement.value = '';
      page.value = 'compose';
      focusHeading();
    }

    function saved(result) {
      changed();
      catalog.load();
      from.value = 'queue';
      open(result.id);
      from.value = 'queue';
      announcement.value = '反馈已发送。可在这里查看老师的回应和后续回访。';
    }

    function setFilters(values) {
      selection.value = normalizeFilters(values);
    }

    function filter(extra) {
      if (dirty.value) return;
      selection.value = normalizeFilters({ ...defaultFilters(), ...scoped(selection.value), ...extra });
      go('queue');
    }

    function group(items) {
      if (!staff || dirty.value) return;
      go('groups');
      seed.value = items;
      groupId.value = null;
    }

    function inspectGroup(id) {
      if (!staff || dirty.value) return;
      go('groups');
      groupId.value = id;
    }

    function navigate(target) {
      if (!dirty.value) emit('navigate', target);
    }

    function renderPage(data) {
      const common = {
        catalog: data,
        expired,
      };
      if (page.value === 'detail') return h(FeedbackDetail, {
        ...common,
        key: caseId.value + ':' + detailTab.value,
        id: caseId.value,
        staff,
        initialTab: detailTab.value,
        onDirty, onBack: back, onGroup: inspectGroup, onChanged: changed, onNavigate: navigate,
      });
      if (page.value === 'compose') return h(FeedbackComposer, {
        ...common, initialSession: selection.value.session_id,
        onSaved: saved, onCancel: back, onDirty,
      });
      if (page.value === 'queue') return h(FeedbackQueue, {
        ...common, staff, selection: selection.value, revision: revision.value,
        onDirty, onOpen: open, onSelect: setFilters, onCreate: compose, onGroup: group,
      });
      if (page.value === 'inbox') return h(FeedbackInbox, { expired, revision: revision.value, onOpen: open, onChanged: changed });
      if (page.value === 'review-desk') return h(FeedbackReviewDesk, {
        catalog: data, staff, selection: selection.value, expired, revision: revision.value,
        onOpen: open, onChanged: changed, onDirty,
      });
      if (page.value === 'reports') return h(FeedbackReports, {
        ...common, staff, selection: selection.value, revision: revision.value,
        onOpen: open, onFilter: filter, onNavigate: navigate,
      });
      if (page.value === 'groups' && staff) return h(FeedbackGroups, {
        ...common, key: groupId.value || (seed.value.length ? 'create' : 'list'),
        seed: seed.value, initialGroup: groupId.value, initialSession: selection.value.session_id,
        onDirty, onOpen: open, onChanged: changed,
      });
      if (page.value === 'templates' && staff) return h(FeedbackTemplates, { ...common, onDirty });
      if (page.value === 'policy' && staff) return h(FeedbackPolicies, {
        ...common, initialCourse: selection.value.course_id, onDirty, onChanged: changed,
      });
      return h(FeedbackTodos, {
        ...common, staff, selection: selection.value, revision: revision.value,
        onOpen: open, onFilter: filter, onCreate: compose,
      });
    }

    function renderTabs() {
      const tabs = staff ? [...sharedTabs, ...staffTabs] : sharedTabs;
      const current = page.value === 'detail' || page.value === 'compose' ? from.value : page.value;
      return h('nav', { class: 'ef-tabs', 'aria-label': '情绪反馈处理中心导航' }, tabs.map(([key, title]) =>
        button([title, key === 'inbox' && unread.value > 0 && badge(unread.value > 99 ? '99+' : unread.value)], () => go(key), {
          key, 'aria-pressed': current === key, disabled: dirty.value,
        }),
      ));
    }

    return () => h('section', { class: 'emotion-feedback', 'aria-label': '情绪反馈处理中心' }, [
      h('header', { class: 'ef-header' }, [
        h('div', [
          h('h2', { tabindex: -1, ref: heading }, '情绪反馈处理中心'),
          h('p', staff
            ? '在这里查看学生的反馈、回复或发回访。'
            : '遇到什么问题可以写给老师，之后也能回来看看回复。',
          ),
        ]),
        !staff && page.value !== 'compose' && button('提交新反馈', compose, {
          primary: true, disabled: dirty.value || !catalog.value.value,
        }),
      ]),
      renderTabs(),
      dirty.value && notice('这段内容还没保存。保存或取消后再切换页面。', 'info'),
      notice(announcement.value, 'good'),
      notice(catalog.error.value),
      catalog.error.value && actions(button('重新加载课堂', () => catalog.load())),
      catalog.loading.value && !catalog.value.value && notice('正在加载课堂…', 'info'),
      catalog.value.value && renderPage(catalog.value.value),
    ]);
  },
};
