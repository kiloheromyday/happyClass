import { computed, h, onBeforeUnmount, ref, watch } from 'vue';
import {
  actions, all, badge, button, check, date, empty, field, input, keyValues,
  notice, option, section, select, table,
} from '../feedback/ui.js';
import {
  exportTimeline, rangeText, sessionPath, useBookmarkResource, useBookmarkWrite, within,
} from './client.js';
import { MaterialEditor } from './material-editor.js';

const buckets = [
  option('1', '每分钟'), option('5', '每 5 分钟'), option('10', '每 10 分钟'),
];
const stateOptions = [
  option('DRAFT', '草稿'), option('PUBLISHED', '已发布'), option('ARCHIVED', '已归档'),
];
const stateTitles = Object.fromEntries(stateOptions.map(item => [item.value, item.label]));
const materialActions = {
  DRAFT: [
    ['PUBLISH', '发布', '发布后，这节课的学生可以查看。确定发布？'],
    ['ARCHIVE', '归档', '归档这份草稿？之后仍可以恢复。'],
  ],
  PUBLISHED: [
    ['UNPUBLISH', '撤回发布', '撤回后，学生暂时看不到这份资料。继续？'],
    ['ARCHIVE', '归档', '归档后，学生看不到这份资料。继续？'],
  ],
  ARCHIVED: [
    ['RESTORE', '恢复为草稿', '恢复为草稿后可以继续编辑。确定恢复？'],
  ],
};

export const BookmarkTimeline = {
  props: ['session', 'initialMinute', 'revision', 'expired'],
  emits: ['materials', 'create', 'replay'],
  setup(props, { emit }) {
    const bucket = ref('5');
    const selectMinute = ref(props.initialMinute ?? null);
    const onlyMarked = ref(true);
    const mode = ref('chart');
    const exportBusy = ref(false);
    const exportMessage = ref('');
    let download;
    const data = useBookmarkResource(() => sessionPath(props.session.id, 'timeline'), props.expired);

    function refresh() {
      data.load({ bucket: bucket.value });
    }
    watch(bucket, refresh, { immediate: true });
    watch(() => props.revision, refresh);
    onBeforeUnmount(() => download?.abort());

    const selected = computed(() => {
      const segments = data.value.value?.segments || [];
      return segments.find(item => selectMinute.value !== null && within(item, selectMinute.value))
        ?? segments.find(item => item.count)
        ?? segments.find(item => item.started)
        ?? segments[0];
    });

    const visible = computed(() => (data.value.value?.segments || []).filter(item =>
      !onlyMarked.value || item.count || item.materials.length || item.draft_count,
    ));
    const peak = computed(() => Math.max(1, ...visible.value.map(item => item.count)));

    async function saveCsv() {
      if (exportBusy.value) {
        download.abort();
        return;
      }
      download = new AbortController();
      exportBusy.value = true;
      exportMessage.value = '';
      try {
        await exportTimeline(props.session.id, bucket.value, download.signal);
        exportMessage.value = '时段统计已导出。';
      } catch (error) {
        if (!download.signal.aborted) {
          if (error.status === 401) props.expired?.();
          else exportMessage.value = error.message;
        }
      } finally {
        exportBusy.value = false;
      }
    }

    function choose(item) {
      selectMinute.value = item.start_minute;
    }

    function row(item) {
      return {
        id: item.start_minute,
        cells: [
          button(rangeText(item.start_minute, item.end_minute), () => choose(item), {
            class: 'ef-link', 'aria-pressed': selected.value?.start_minute === item.start_minute,
          }),
          item.count,
          item.student_count,
          item.reasons[0]?.label || '—',
          item.materials.length,
          item.draft_count,
        ],
      };
    }

    function chart() {
      return h('div', { class: 'bookmark-chart', 'aria-label': '按时间段选择书签统计' },
        visible.value.map(item => h('button', {
          type: 'button',
          key: item.start_minute,
          class: ['bookmark-segment', { 'bookmark-selected': selected.value?.start_minute === item.start_minute }],
          'aria-pressed': selected.value?.start_minute === item.start_minute,
          onClick: () => choose(item),
        }, [
          h('span', { class: 'bookmark-bar-track', 'aria-hidden': 'true' }, [
            h('span', { style: { height: 100 * item.count / peak.value + '%' } }),
          ]),
          h('strong', item.count + ' 条'),
          h('small', rangeText(item.start_minute, item.end_minute)),
          item.materials.length > 0 && badge(item.materials.length + ' 份资料'),
        ])),
      );
    }

    function details(item) {
      return section('第 ' + rangeText(item.start_minute, item.end_minute), [
        keyValues([
          ['书签条数', item.count],
          ['做了书签的学生', item.student_count],
          ['已发布资料', item.materials.length],
          ['草稿', item.draft_count],
        ]),
        item.reasons.length
          ? h('div', { class: 'bookmark-reasons' }, item.reasons.map(reason => badge(reason.label + ' ' + reason.count)))
          : h('p', { class: 'ef-meta' }, item.started ? '这一段还没有书签。' : '还没有讲到这一段。'),
        item.materials.length > 0 && h('ul', { class: 'bookmark-inline-materials' }, item.materials.map(material => h('li', {
          key: material.id,
        }, button(material.title, () => emit('materials', item, material.id), { class: 'ef-link' })))),
        actions(
          button('给这段加资料', () => emit('create', item), { primary: true }),
          button('查看这段的资料', () => emit('materials', item)),
        ),
      ]);
    }

    function totals(report) {
      const totals = report.summary;
      return keyValues([
        ['这节课的书签', totals.bookmarks],
        ['学生人数', totals.students],
        ['已有资料的卡点时段', totals.with_materials + ' / ' + totals.with_bookmarks],
        ['已发布资料', totals.published],
      ]);
    }

    return () => {
      const report = data.value.value;
      return [
        section('按课堂时段查看书签', [
          notice(data.error.value),
          notice(exportMessage.value, 'info'),
          data.loading.value && notice('正在加载时段统计…', 'info'),
          report && totals(report),
          h('div', { class: 'ef-grid' }, [
            field('按几分钟分一段', select(bucket.value, buckets, value => { bucket.value = value; })),
            check('只看有书签或资料的时段', onlyMarked.value, value => { onlyMarked.value = value; }),
          ]),
          report && report.bucket_minutes !== report.requested_bucket_minutes && notice(
            '这节课较长，实际按每 ' + report.bucket_minutes + ' 分钟分段。',
            'info',
          ),
          actions(
            button('时间条', () => { mode.value = 'chart'; }, { 'aria-pressed': mode.value === 'chart' }),
            button('数据表', () => { mode.value = 'table'; }, { 'aria-pressed': mode.value === 'table' }),
          ),
          visible.value.length
            ? mode.value === 'chart'
              ? chart()
              : table(['时段', '书签', '学生', '常见原因', '资料', '草稿'], visible.value.map(row))
            : !data.loading.value && empty('当前没有符合条件的时段', '可以取消筛选，查看整节课。'),
        ], actions(
          button('刷新统计', refresh, { disabled: data.loading.value }),
          button(exportBusy.value ? '取消导出' : '导出时段 CSV', saveCsv, { disabled: !report }),
          button('打开情绪回放', () => emit('replay', selected.value?.start_minute ?? null)),
        )),
        selected.value && details(selected.value),
      ];
    };
  },
};

export const TeacherMaterials = {
  props: ['session', 'initialInterval', 'initialMaterialId', 'initialCreate', 'expired'],
  emits: ['dirty', 'changed', 'back'],
  setup(props, { emit }) {
    const resource = useBookmarkResource(() => sessionPath(props.session.id, 'materials'), props.expired);
    const command = useBookmarkWrite(props.expired);
    const search = ref('');
    const state = ref('');
    const announcement = ref('');
    const interval = ref(props.initialInterval || null);
    const expanded = ref(props.initialMaterialId || null);
    const editing = ref(null);
    const mode = ref(props.initialCreate ? 'create' : 'list');

    watch(command.busy, value => emit('dirty', value), { flush: 'sync' });
    onBeforeUnmount(() => emit('dirty', false));

    async function load() {
      const selected = interval.value;
      const next = await resource.load({
        start_minute: selected?.start_minute, end_minute: selected?.end_minute,
      });
      if (editing.value && next) {
        editing.value = next.items.find(item => item.id === editing.value.id) || editing.value;
      }
    }
    load();

    const items = computed(() => {
      const term = search.value.trim().toLowerCase();
      return (resource.value.value?.items || []).filter(item =>
        (!state.value || item.state === state.value) &&
        (!term || (item.title + ' ' + item.content).toLowerCase().includes(term)),
      );
    });

    function start(item = null) {
      editing.value = item;
      mode.value = item ? 'edit' : 'create';
      announcement.value = '';
    }

    function backToList() {
      mode.value = 'list';
      editing.value = null;
    }

    function saved(item) {
      backToList();
      expanded.value = item.id;
      state.value = '';
      if (interval.value && (item.end_minute <= interval.value.start_minute ||
        item.start_minute >= interval.value.end_minute)) {
        interval.value = null;
      }
      announcement.value = item.state === 'PUBLISHED' ? '资料已保存，学生可以查看。' : '草稿已保存。';
      emit('changed');
      load();
    }

    async function transition(item, action, warning) {
      if (!window.confirm(warning)) return;
      const next = await command.run('/materials/' + item.id + '/state', {
        version: item.version,
        action,
      }, { idempotent: false });
      if (!next) return;
      announcement.value = '资料已更新为「' + stateTitles[next.state] + '」。';
      emit('changed');
      load();
    }

    function card(item) {
      return h('li', { key: item.id }, [
        h('div', { class: 'ef-list-row' }, [
          button(item.title, () => { expanded.value = expanded.value === item.id ? null : item.id; }, {
            class: 'ef-link',
            'aria-expanded': expanded.value === item.id,
          }),
          actions(badge(rangeText(item.start_minute, item.end_minute)), badge(
            stateTitles[item.state], item.state === 'PUBLISHED' ? 'good' : '',
          )),
        ]),
        h('p', { class: 'ef-meta' }, '最近修改 ' + date(item.updated_at)),
        expanded.value === item.id && h('div', { class: 'bookmark-material-body' }, [
          item.content && h('p', { class: 'ef-text' }, item.content),
          item.links.length > 0 && h('ul', item.links.map(link => h('li', { key: link.url }, [
            h('a', { href: link.url, target: '_blank', rel: 'noopener noreferrer' }, link.label),
          ]))),
        ]),
        actions(
          item.state !== 'ARCHIVED' && button('编辑资料', () => start(item), { disabled: command.busy.value }),
          ...materialActions[item.state].map(([code, title, warning]) =>
            button(title, () => transition(item, code, warning), { disabled: command.busy.value }),
          ),
        ),
      ]);
    }

    return () => {
      if (mode.value !== 'list') return h(MaterialEditor, {
        key: mode.value + ':' + (editing.value?.id || ''),
        session: props.session,
        interval: interval.value,
        item: editing.value,
        expired: props.expired,
        onDirty: value => emit('dirty', value),
        onSaved: saved,
        onCancel: backToList,
        onReload: load,
      });
      return section('补学资料管理', [
        interval.value && actions(
          badge('只看 ' + rangeText(interval.value.start_minute, interval.value.end_minute)),
          button('查看整节课资料', () => { interval.value = null; load(); }),
        ),
        h('div', { class: 'ef-grid' }, [
          field('资料状态', select(state.value, [all('全部状态'), ...stateOptions], value => { state.value = value; })),
          field('查找资料', input(search.value, value => { search.value = value; }, { type: 'search', maxlength: 100 })),
        ]),
        notice(announcement.value, 'good'),
        notice(resource.error.value || command.error.value),
        command.conflict.value && button('刷新资料后重试', load),
        resource.loading.value && notice('正在加载资料…', 'info'),
        items.value.length
          ? h('ul', { class: 'ef-list' }, items.value.map(card))
          : !resource.loading.value && empty('没有符合条件的资料', '可以添加讲解或链接，也可以换个筛选条件。'),
      ], actions(
        button('返回时段统计', () => emit('back'), { disabled: command.busy.value }),
        button('刷新资料', load, { disabled: resource.loading.value }),
        button('添加补学资料', () => start(), { primary: true, disabled: command.busy.value }),
      ));
    };
  },
};
