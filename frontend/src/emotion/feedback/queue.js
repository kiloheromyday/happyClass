import { h, onBeforeUnmount, ref, watch } from 'vue';
import { csv, defaultFilters, normalizeFilters, read, useCommand, useDraft, useResource } from './client.js';
import {
  actions, all, badge, button, check, empty, field, input, notice, option,
  orderings, pager, priorities, recordList, scopes, section, select, sessionLabel, submit,
} from './ui.js';

export function filterFields(catalog, values, update, { staff = false, compact = false } = {}) {
  const sessions = catalog.sessions.filter(item => !values.course_id || item.course_id === values.course_id);
  return h('div', { class: 'ef-grid' }, [
    field('课程', select(values.course_id, [all('全部课程'), ...catalog.courses.map(item => option(item.id, item.name))],
      value => {
        update('course_id', value ? Number(value) : null);
        update('session_id', null);
      },
    )),
    field('课堂', select(values.session_id, [all('全部课堂'), ...sessions.map(item => option(item.id, sessionLabel(item)))],
      value => update('session_id', value ? Number(value) : null),
    )),
    field('数据范围', select(values.data_scope, scopes, value => update('data_scope', value))),
    !compact && field('进度', select(values.state, [option('ALL', '全部进度'), ...catalog.states], value => update('state', value))),
    !compact && field('情绪', select(values.emotion, [option('ALL', '全部情绪'), ...catalog.emotions], value => update('emotion', value))),
    !compact && field('原因', select(values.reason, [option('ALL', '全部原因'), ...catalog.reasons], value => update('reason', value))),
    !compact && staff && field('优先级', select(values.priority, [option('ALL', '全部优先级'), ...priorities], value => update('priority', value))),
    !compact && field('排序', select(values.sort, staff ? orderings : orderings.filter(item => item.value !== 'PRIORITY'),
      value => update('sort', value),
    )),
    !compact && field('关键词', input(values.search, value => update('search', value), {
      type: 'search',
      maxlength: 120,
      placeholder: '搜索反馈标题或说明',
    })),
    !compact && staff && check('只看我关注的反馈', values.watched, value => update('watched', value)),
    !compact && staff && check('只看确认逾期的反馈', values.overdue, value => update('overdue', value)),
    !compact && check('只看回访逾期的反馈', values.review_overdue, value => update('review_overdue', value)),
    !compact && check('只看进行中的反馈', values.active_only, value => update('active_only', value)),
  ]);
}

export const SavedFilters = {
  props: ['applied', 'expired'],
  emits: ['apply', 'dirty'],
  setup(props, { emit }) {
    const listing = useResource(signal => read('/views', {}, signal), props.expired);
    const command = useCommand(props.expired);
    const draft = useDraft({ title: '' }, value => emit('dirty', value), command.busy);
    const editing = ref(null);
    const open = ref(false);
    const saved = ref('');
    listing.load();

    function start(item = null) {
      editing.value = item;
      draft.restore({ title: item?.title || '' });
      open.value = true;
      command.reset();
      saved.value = '';
    }

    function cancel() {
      draft.restore({ title: '' });
      open.value = false;
      editing.value = null;
      command.reset();
    }

    async function save(event) {
      event.preventDefault();
      const current = editing.value;
      const result = await command.run(current ? '/views/' + current.id : '/views', {
        title: draft.values.title.trim(),
        filters: normalizeFilters(props.applied),
        version: current?.version || 0,
      }, { method: current ? 'PUT' : 'POST' });
      if (!result) return;
      cancel();
      saved.value = '筛选条件已保存。';
      listing.load();
    }

    async function remove(item) {
      if (!window.confirm('删除筛选视图「' + item.title + '」？')) return;
      const result = await command.run('/views/' + item.id + '/delete', { version: item.version });
      if (!result) return;
      if (editing.value?.id === item.id) cancel();
      saved.value = '筛选视图已删除。';
      listing.load();
    }

    return () => h('details', { class: 'ef-disclosure' }, [
      h('summary', '已保存的筛选'),
      notice(listing.error.value || command.error.value),
      (listing.error.value || command.conflict.value) && button('刷新已保存的筛选', () => listing.load()),
      notice(saved.value, 'good'),
      listing.loading.value && h('p', { role: 'status' }, '正在读取…'),
      listing.value.value?.items.length
        ? h('ul', { class: 'ef-list' }, listing.value.value.items.map(item => h('li', { key: item.id }, [
          h('strong', item.title),
          actions(
            button('应用', () => emit('apply', item.filters), { disabled: draft.dirty.value || command.busy.value }),
            button('用当前筛选更新', () => start(item), { disabled: draft.dirty.value || command.busy.value }),
            button('删除', () => remove(item), { disabled: command.busy.value }),
          ),
        ])))
        : h('p', { class: 'ef-meta' }, '可以把经常使用的筛选保存下来。'),
      open.value ? h('form', { class: 'ef-form', onSubmit: save }, [
        field('视图名称', input(draft.values.title, value => { draft.values.title = value; }, {
          required: true, minlength: 2, maxlength: 80,
        })),
        actions(submit('保存当前筛选', command.busy.value), button('取消', cancel, { disabled: command.busy.value })),
      ]) : button('保存当前筛选', () => start()),
    ]);
  },
};

export const FeedbackQueue = {
  props: ['catalog', 'staff', 'selection', 'revision', 'expired'],
  emits: ['select', 'open', 'create', 'group', 'dirty'],
  setup(props, { emit }) {
    const filters = ref(normalizeFilters(props.selection));
    const picked = ref([]);
    const exportStatus = ref('');
    const exporting = ref(false);
    let exportRequest;
    onBeforeUnmount(() => exportRequest?.abort());
    const listing = useResource((signal, selection, offset) => read('/cases', { ...selection, offset, limit: 20 }, signal), props.expired);

    function load(offset = 0) {
      listing.load(props.selection, offset);
    }

    watch(() => props.selection, selection => {
      filters.value = normalizeFilters(selection);
      picked.value = [];
      load();
    }, { immediate: true });

    watch(() => props.revision, () => load(listing.value.value?.offset ?? 0));

    function apply(event) {
      event.preventDefault();
      emit('select', normalizeFilters(filters.value));
    }

    function toggle(item, checked) {
      picked.value = checked
        ? [...picked.value, item]
        : picked.value.filter(value => value.id !== item.id);
    }

    function selectable(item) {
      return !picked.value.length || (picked.value.length < 50 && picked.value[0].session_id === item.session_id);
    }

    async function download() {
      if (exporting.value) return;
      exportRequest = new AbortController();
      exporting.value = true;
      exportStatus.value = '';
      try {
        const count = await csv(props.selection, exportRequest.signal);
        exportStatus.value = '已下载 ' + count + ' 条反馈。';
      } catch (failure) {
        if (!exportRequest.signal.aborted) {
          if (failure.status === 401) props.expired?.();
          else exportStatus.value = failure.message;
        }
      } finally {
        exporting.value = false;
      }
    }

    function extra(item) {
      if (!props.staff) return null;
      const checked = picked.value.some(value => value.id === item.id);
      return actions(
        check('选择反馈 ' + item.number, checked, value => toggle(item, value), !checked && !selectable(item)),
        item.priority === 'HIGH' && badge('优先处理', 'waiting'),
        item.watched && badge('已关注'),
        ...item.tags.map(value => badge(value)),
      );
    }

    function results() {
      const page = listing.value.value;
      return [
        listing.loading.value && h('p', { role: 'status' }, '正在加载反馈…'),
        notice(listing.error.value),
        listing.error.value && button('重试', () => load()),
        !listing.loading.value && !listing.error.value && page && (
          page.items.length
            ? recordList(page.items, props.catalog, id => emit('open', id), extra)
            : empty('没有符合条件的反馈', '可调整筛选，或返回查看全部课堂。')
        ),
        pager(page, listing.loading.value, load),
      ];
    }

    return () => [
      section('筛选反馈', [
        h('form', { class: 'ef-form', onSubmit: apply }, [
          filterFields(props.catalog, filters.value, (key, value) => { filters.value[key] = value; }, { staff: props.staff }),
          actions(
            submit('应用筛选', listing.loading.value),
            button('清空筛选', () => emit('select', defaultFilters())),
          ),
        ]),
        h(SavedFilters, {
          applied: props.selection,
          expired: props.expired,
          onApply: value => emit('select', value),
          onDirty: value => emit('dirty', value),
        }),
      ]),
      section(props.staff ? '课堂反馈列表' : '我提交的反馈', [
        picked.value.length > 0 && actions(
          badge('已选择 ' + picked.value.length + ' 条同课堂反馈'),
          button('新建集中处理组', () => emit('group', [...picked.value]), { primary: true }),
          button('清除选择', () => { picked.value = []; }),
        ),
        notice(exportStatus.value, 'info'),
        results(),
      ], actions(
        badge('共 ' + (listing.value.value?.total ?? 0) + ' 条'),
        button(exporting.value ? '取消导出' : '导出当前结果', () => exporting.value ? exportRequest.abort() : download()),
        button('刷新', () => load(listing.value.value?.offset), { disabled: listing.loading.value }),
        !props.staff && button('提交新反馈', () => emit('create'), { primary: true }),
      )),
    ];
  },
};
