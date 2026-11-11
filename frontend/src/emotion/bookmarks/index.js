import { computed, h, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import {
  actions, badge, button, date, empty, notice, section,
} from '../feedback/ui.js';
import { useBookmarkResource } from './client.js';
import { PersonalBookmarks, StudentMaterials } from './student.js';
import { BookmarkTimeline, TeacherMaterials } from './staff.js';
import { QuickBookmark } from './quick.js';
import { ReviewDesk } from './review-desk.js';
import { ReadingReport } from './reading-report.js';
import { BookmarkSessionPicker, currentSession } from './session-picker.js';

const studentTabs = [
  ['mine', '我的书签'],
  ['review', '开始复习'],
  ['materials', '课堂资料'],
];

const staffTabs = [
  ['timeline', '时段统计'],
  ['materials', '资料管理'],
  ['reading', '阅读汇总'],
];

export const BookmarksPanel = {
  props: ['user', 'initialSessionId', 'initialView', 'initialMinute', 'initialMaterialId'],
  emits: ['dirty-change', 'expired', 'navigate'],
  setup(props, { emit }) {
    const student = props.user.role === 'STUDENT';
    const tabs = student ? studentTabs : staffTabs;
    const first = tabs[0][0];
    const expired = () => emit('expired');
    const chosen = ref(props.initialSessionId || null);
    const page = ref(tabs.some(([key]) => key === props.initialView) ? props.initialView : first);
    const dirty = ref(false);
    const quickBusy = ref(false);
    const revision = ref(0);
    const interval = ref(null);
    const initialMinute = ref(props.initialMinute ?? null);
    const materialId = ref(props.initialMaterialId ?? null);
    const startEditor = ref(false);
    const materialKey = ref(0);
    const heading = ref(null);
    const clock = ref(Date.now());
    let offset = 0;
    let timer;
    const catalog = useBookmarkResource('/catalog', expired);
    const active = computed(() => {
      const data = catalog.value.value;
      const item = data?.sessions.find(item => item.id === chosen.value);
      return currentSession(item, clock.value, data?.manual_days || 7);
    });
    const locked = computed(() => dirty.value || quickBusy.value);

    onMounted(() => {
      timer = setInterval(() => { clock.value = Date.now() + offset; }, 1000);
    });
    onBeforeUnmount(() => {
      clearInterval(timer);
      emit('dirty-change', false);
    });

    async function bootstrap() {
      const result = await catalog.load();
      if (!result) return;
      const serverTime = Date.parse(result.server_time);
      if (Number.isFinite(serverTime)) offset = serverTime - Date.now();
      clock.value = Date.now() + offset;
      const matches = result.sessions.some(item => item.id === chosen.value);
      if (matches) return;
      if (student && page.value !== 'materials') {
        chosen.value = null;
      } else {
        chosen.value = result.sessions.find(item => item.live)?.id || result.sessions[0]?.id || null;
      }
    }

    bootstrap();

    function onDirty(value) {
      dirty.value = value;
      emit('dirty-change', locked.value);
    }

    function onQuickBusy(value) {
      quickBusy.value = value;
      emit('dirty-change', locked.value);
    }

    function focus() {
      nextTick(() => heading.value?.focus({ preventScroll: true }));
    }

    function resetMaterialContext() {
      interval.value = null;
      materialId.value = null;
      startEditor.value = false;
      materialKey.value += 1;
    }

    function selectSession(value) {
      if (locked.value) return;
      chosen.value = value ? Number(value) : null;
      initialMinute.value = null;
      resetMaterialContext();
      if (!chosen.value && page.value === 'materials') page.value = first;
    }

    function switchPage(next) {
      if (locked.value || next === page.value) return;
      if (next === 'materials' && !chosen.value) {
        chosen.value = catalog.value.value?.sessions.find(item => item.live)?.id ||
          catalog.value.value?.sessions[0]?.id || null;
      }
      resetMaterialContext();
      page.value = next;
      focus();
    }

    function openMaterial(sessionId, identifier) {
      if (locked.value) return;
      chosen.value = sessionId;
      resetMaterialContext();
      materialId.value = identifier;
      page.value = 'materials';
      focus();
    }

    function openStaffMaterials(selected, identifier = null, create = false) {
      if (locked.value) return;
      interval.value = selected;
      materialId.value = identifier;
      startEditor.value = create;
      materialKey.value += 1;
      initialMinute.value = selected.start_minute;
      page.value = 'materials';
      focus();
    }

    function openStaffMaterial(identifier) {
      if (locked.value) return;
      resetMaterialContext();
      materialId.value = identifier;
      page.value = 'materials';
      focus();
    }

    function changed() {
      revision.value += 1;
    }

    function openReplay(minute) {
      if (locked.value) return;
      emit('navigate', { tab: 'replay', sessionId: active.value.id, minute });
    }

    function selectedClass(data) {
      return h(BookmarkSessionPicker, {
        sessions: data.sessions,
        value: chosen.value,
        allowAll: student && page.value !== 'materials',
        locked: locked.value,
        now: clock.value,
        onSelect: selectSession,
      });
    }

    function overview() {
      const item = active.value;
      if (!item) return null;
      return actions(
        badge(item.live ? '正在上课' : item.elapsed_minutes ? '已开课' : '未开课'),
        badge('课长 ' + item.duration_minutes + ' 分钟'),
        h('span', { class: 'ef-meta' }, date(item.starts_at)),
      );
    }

    function content(data) {
      if (!data.sessions.length) {
        return empty(
          '还没有可用的课堂',
          student ? '加入课堂后就能做书签。' : '安排课堂后，学生就可以从课堂页记下时间点。',
        );
      }
      if (student) {
        if (page.value === 'mine') return h(PersonalBookmarks, {
          session: active.value, catalog: data, revision: revision.value, expired,
          onDirty, onChanged: changed, onOpenMaterial: openMaterial,
        });
        if (page.value === 'review') return h(ReviewDesk, {
          key: chosen.value || 'all',
          session: active.value, expired, revision: revision.value,
          onDirty, onChanged: changed, onOpenMaterial: openMaterial,
          onBack: () => switchPage('mine'),
        });
        if (active.value) return h(StudentMaterials, {
          key: active.value.id + ':' + materialKey.value,
          session: active.value, initialMaterialId: materialId.value, expired,
          onDirty, onChanged: changed, onBack: () => switchPage('mine'),
        });
      } else if (active.value) {
        if (page.value === 'reading') return h(ReadingReport, {
          key: active.value.id,
          session: active.value,
          expired,
          onOpen: openStaffMaterial,
        });
        if (page.value === 'timeline') return h(BookmarkTimeline, {
          key: active.value.id,
          session: active.value, initialMinute: initialMinute.value, revision: revision.value, expired,
          onCreate: selected => openStaffMaterials(selected, null, true),
          onMaterials: openStaffMaterials, onReplay: openReplay,
        });
        return h(TeacherMaterials, {
          key: active.value.id + ':' + materialKey.value,
          session: active.value,
          initialInterval: interval.value,
          initialMaterialId: materialId.value,
          initialCreate: startEditor.value,
          expired, onDirty, onChanged: changed,
          onBack: () => switchPage('timeline'),
        });
      }
      return empty('请选择一节课堂');
    }

    return () => {
      const data = catalog.value.value;
      return h('div', { class: 'emotion-feedback classroom-bookmarks' }, [
        h('header', { class: 'ef-header' }, [
          h('div', [
            h('h2', { ref: heading, tabindex: -1 }, '课堂卡点书签'),
            h('p', student
              ? '把没听懂的那一段记下来，课后从书签找老师补的讲解。'
              : '按时间找学生做书签较多的地方，给那一段补讲解或资料。',
            ),
          ]),
        ]),
        notice(catalog.error.value),
        catalog.error.value && actions(button('重试加载课堂', bootstrap)),
        catalog.loading.value && !data && notice('正在读取课堂…', 'info'),
        data && section('课堂范围', [
          selectedClass(data),
          overview(),
          student && active.value?.live && h(QuickBookmark, {
            key: active.value.id,
            session: active.value, disabled: dirty.value, expired,
            onCreated: changed, onBusy: onQuickBusy, onOpen: () => switchPage('mine'),
          }),
        ], actions(button('刷新课堂', bootstrap, { disabled: locked.value || catalog.loading.value }))),
        data && h('nav', { class: 'ef-tabs', 'aria-label': '课堂书签功能' }, tabs.map(([key, label]) =>
          button(label, () => switchPage(key), { key, 'aria-pressed': page.value === key, disabled: locked.value }),
        )),
        dirty.value && notice('有内容还没保存。保存或取消后再切换。', 'info'),
        data && content(data),
      ]);
    };
  },
};
