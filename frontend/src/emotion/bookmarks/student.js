import { computed, h, onBeforeUnmount, ref, watch } from 'vue';
import { useDraft } from '../feedback/client.js';
import {
  actions, all, badge, button, check, date, empty, field, input, keyValues,
  notice, number, option, pager, section, select, submit, textarea,
} from '../feedback/ui.js';
import { minuteText, rangeText, sessionPath, useBookmarkResource, useBookmarkWrite } from './client.js';
import { useBookmarkDownload } from './download.js';

const states = [
  option('ALL', '全部书签'), option('OPEN', '还没复习'), option('REVIEWED', '已复习'),
];
const orders = [
  option('RECENT', '最近修改'), option('LESSON', '按课堂和分钟'),
];

function markFields() {
  return { title: '', note: '', reason: 'REVISIT', minute: null };
}

const BookmarkEditor = {
  props: ['session', 'item', 'reasons', 'expired'],
  emits: ['dirty', 'saved', 'cancel', 'reload'],
  setup(props, { emit }) {
    const command = useBookmarkWrite(props.expired);
    const initial = () => props.item ? {
      title: props.item.title,
      note: props.item.note,
      reason: props.item.reason,
      reviewed: props.item.reviewed,
    } : markFields();
    const draft = useDraft(initial(), value => emit('dirty', value), command.busy);
    const { values } = draft;
    const version = ref(props.item?.version);
    const validation = ref('');

    function cancel() {
      if (draft.dirty.value && !window.confirm('放弃这次编辑？')) return;
      draft.restore();
      emit('cancel');
    }

    function adopt() {
      if (!window.confirm('用当前草稿继续编辑最新版本？')) return;
      version.value = props.item.version;
      command.reset();
    }

    async function save(event) {
      event.preventDefault();
      validation.value = '';
      const payload = {
        title: values.title.trim(),
        note: values.note.trim(),
        reason: values.reason,
      };
      let result;
      if (props.item) {
        if (version.value !== props.item.version) return;
        result = await command.run('/mine/' + props.item.id, {
          ...payload, reviewed: values.reviewed, version: version.value,
        }, { method: 'PUT', idempotent: false });
      } else {
        if (!Number.isInteger(values.minute) || values.minute < 0 || values.minute >= props.session.elapsed_minutes) {
          validation.value = '请选择这节课已经讲过的分钟。';
          return;
        }
        result = await command.run(sessionPath(props.session.id, 'mine'), {
          ...payload, minute: values.minute,
        });
      }
      if (!result) return;
      draft.restore();
      emit('saved', result);
    }

    return () => {
      const changed = props.item && version.value !== props.item.version;
      return section(props.item ? '编辑我的书签' : '补记课堂书签', h('form', { class: 'ef-form', onSubmit: save }, [
        props.item
          ? h('p', { class: 'ef-meta' }, props.item.course_name + ' · ' + minuteText(props.item.minute))
          : field('开课后第几分钟', number(values.minute, value => { values.minute = value; }, {
            min: 0,
            max: Math.max(0, props.session.elapsed_minutes - 1),
            required: true,
          }), '下课后七天内可以补记。'),
        field('为什么做书签？', select(values.reason, props.reasons, value => { values.reason = value; })),
        field('书签标题（可选）', input(values.title, value => { values.title = value; }, {
          maxlength: 100, placeholder: '比如：尾指针什么时候移动',
        })),
        field('我的笔记（可选）', textarea(values.note, value => { values.note = value; }, {
          placeholder: '记下想再看一遍的内容',
        }), '只给自己看 · ' + values.note.length + ' / 2000'),
        props.item && check('我已复习这段内容', values.reviewed, value => { values.reviewed = value; }),
        notice(validation.value || command.error.value),
        command.conflict.value && button('刷新书签', () => emit('reload')),
        changed && notice('书签有新版本。先核对再保存。', 'waiting'),
        changed && button('核对后继续', adopt),
        actions(
          submit(command.busy.value ? '正在保存…' : '保存书签', command.busy.value || changed),
          button('取消', cancel, { disabled: command.busy.value }),
        ),
      ]));
    };
  },
};

function filtersDefault() {
  return { state: 'ALL', reason: '', term: '', order: 'RECENT' };
}

export const PersonalBookmarks = {
  props: ['session', 'catalog', 'revision', 'expired'],
  emits: ['dirty', 'open-material', 'changed'],
  setup(props, { emit }) {
    const editable = ref(null);
    const editing = ref(false);
    const formMode = ref('');
    const selected = ref([]);
    const announcement = ref('');
    const filters = ref(filtersDefault());
    const applied = ref(filtersDefault());
    const listing = useBookmarkResource('/mine', props.expired);
    const command = useBookmarkWrite(props.expired);
    const exportFile = useBookmarkDownload(props.expired);

    watch(command.busy, value => emit('dirty', value), { flush: 'sync' });
    onBeforeUnmount(() => emit('dirty', false));

    async function load(offset = 0) {
      const next = await listing.load({
        ...applied.value, session_id: props.session?.id, offset, limit: 12,
      });
      if (!next) return;
      selected.value = selected.value.filter(id => next.items.some(item => item.id === id));
      if (next.total && !next.items.length && offset > 0) {
        await load(Math.max(0, offset - 12));
        return;
      }
      if (editable.value) {
        const refreshed = next.items.find(item => item.id === editable.value.id);
        if (refreshed) editable.value = refreshed;
      }
    }

    watch(() => props.session?.id, () => {
      selected.value = [];
      listing.clear();
      load();
    }, { immediate: true });
    watch(() => props.revision, () => load(listing.value.value?.offset || 0));

    function apply(event) {
      event.preventDefault();
      applied.value = { ...filters.value, term: filters.value.term.trim() };
      selected.value = [];
      load();
    }

    function resetFilters() {
      filters.value = filtersDefault();
      applied.value = filtersDefault();
      selected.value = [];
      load();
    }

    function saveCsv() {
      exportFile.download('/mine.csv', {
        ...applied.value,
        session_id: props.session?.id,
      }, '已导出当前筛选中的书签。');
    }

    function start(mode, item = null) {
      formMode.value = mode;
      editable.value = item;
      editing.value = true;
      announcement.value = '';
    }

    function cancel() {
      editing.value = false;
      editable.value = null;
      formMode.value = '';
    }

    function saved(result) {
      cancel();
      announcement.value = result.created === false
        ? '这一分钟已有书签。可以在列表中编辑原来的那条。'
        : '书签已保存。';
      emit('changed');
    }

    function selectItem(id, value) {
      selected.value = value
        ? [...new Set([...selected.value, id])]
        : selected.value.filter(item => item !== id);
    }

    async function batch(reviewed) {
      const result = await command.run('/mine/review', {
        bookmark_ids: [...selected.value],
        reviewed,
      }, { idempotent: false });
      if (!result) return;
      selected.value = [];
      announcement.value = reviewed
        ? '已标记 ' + result.changed.length + ' 条为已复习。'
        : '已移回 ' + result.changed.length + ' 条待复习。';
      emit('changed');
    }

    async function remove(item) {
      if (!window.confirm('删除「' + (item.title || minuteText(item.minute)) + '」这条个人书签？')) return;
      const result = await command.run('/mine/' + item.id, undefined, {
        method: 'DELETE',
        idempotent: false,
        params: { version: item.version },
      });
      if (!result) return;
      announcement.value = '书签已删除。';
      emit('changed');
    }

    async function review(item) {
      const result = await command.run('/mine/' + item.id, {
        reason: item.reason,
        title: item.title,
        note: item.note,
        version: item.version,
        reviewed: !item.reviewed,
      }, { method: 'PUT', idempotent: false });
      if (!result) return;
      announcement.value = result.reviewed ? '已标记为已复习。' : '已移回待复习。';
      emit('changed');
    }

    function controls() {
      return h('form', { class: 'ef-form', onSubmit: apply }, [
        h('div', { class: 'ef-grid' }, [
          field('复习状态', select(filters.value.state, states, value => { filters.value.state = value; })),
          field('书签原因', select(filters.value.reason, [all('全部原因'), ...props.catalog.reasons],
            value => { filters.value.reason = value; },
          )),
          field('排序', select(filters.value.order, orders, value => { filters.value.order = value; })),
          field('搜索我的书签', input(filters.value.term, value => { filters.value.term = value; }, {
            type: 'search', maxlength: 100, placeholder: '输入标题或笔记里的词',
          })),
        ]),
        actions(
          submit('应用筛选', listing.loading.value),
          button('清空筛选', resetFilters, { disabled: listing.loading.value }),
        ),
      ]);
    }

    function materialLinks(item) {
      if (!item.materials.length) {
        return h('p', { class: 'ef-meta' }, '老师还没给这段发布资料。');
      }
      return h('div', { class: 'bookmark-related' }, [
        h('strong', '这一段的资料'),
        h('ul', item.materials.map(material => h('li', { key: material.id }, [
          button(material.title, () => emit('open-material', item.session_id, material.id), { class: 'ef-link' }),
          material.completed && badge('已看过', 'good'),
          material.changed_after_review && badge('资料已更新', 'waiting'),
        ]))),
      ]);
    }

    function card(item) {
      return h('li', { key: item.id }, [
        h('div', { class: 'ef-list-row' }, [
          h('strong', item.title || minuteText(item.minute)),
          actions(
            badge(item.reason_label),
            item.reviewed ? badge('已复习', 'good') : badge('待复习'),
          ),
        ]),
        h('p', { class: 'ef-meta' }, item.course_name + ' · ' + item.class_name + ' · ' + minuteText(item.minute)),
        item.note && h('p', { class: 'ef-text' }, item.note),
        materialLinks(item),
        actions(
          check('选择书签', selected.value.includes(item.id), value => selectItem(item.id, value), command.busy.value),
          button('编辑', () => start('edit', item), { disabled: command.busy.value }),
          button(item.reviewed ? '移回待复习' : '标为已复习', () => review(item), { disabled: command.busy.value }),
          button('删除书签', () => remove(item), { disabled: command.busy.value }),
        ),
      ]);
    }

    return () => {
      if (editing.value) return h(BookmarkEditor, {
        key: formMode.value + ':' + (editable.value?.id || ''),
        session: props.session,
        item: editable.value,
        reasons: props.catalog.reasons,
        expired: props.expired,
        onDirty: value => emit('dirty', value),
        onCancel: cancel,
        onSaved: saved,
        onReload: () => load(listing.value.value?.offset || 0),
      });
      const data = listing.value.value;
      return section('我的书签', [
        data && keyValues([
          ['书签总数', data.summary.total],
          ['待复习', data.summary.open],
          ['已复习', data.summary.reviewed],
          ['涉及课堂', data.summary.lessons],
        ]),
        controls(),
        notice(announcement.value, 'good'),
        notice(exportFile.status.value, 'info'),
        notice(listing.error.value || command.error.value),
        command.conflict.value && button('刷新后重试', () => load()),
        selected.value.length > 0 && actions(
          badge('已选 ' + selected.value.length + ' 条'),
          button('批量标为已复习', () => batch(true), { disabled: command.busy.value }),
          button('批量移回待复习', () => batch(false), { disabled: command.busy.value }),
          button('取消选择', () => { selected.value = []; }, { disabled: command.busy.value }),
        ),
        listing.loading.value && notice('正在加载书签…', 'info'),
        data?.items.length
          ? h('ul', { class: 'ef-list' }, data.items.map(card))
          : !listing.loading.value && empty('没有符合条件的书签', '可以从正在进行的课堂记下一分钟，或选择一节课补记。'),
        pager(data, listing.loading.value || command.busy.value, load),
      ], actions(
        props.session?.can_add_past && button('补记一个时间点', () => start('add'), { primary: true }),
        button(exportFile.busy.value ? '取消导出' : '导出我的书签', saveCsv, {
          disabled: !exportFile.busy.value && (!data?.total || listing.loading.value),
        }),
        button('刷新书签', () => load(data?.offset), { disabled: listing.loading.value || command.busy.value }),
      ));
    };
  },
};

export const StudentMaterials = {
  props: ['session', 'expired', 'initialMaterialId'],
  emits: ['dirty', 'back', 'changed'],
  setup(props, { emit }) {
    const listing = useBookmarkResource(() => sessionPath(props.session.id, 'materials'), props.expired);
    const command = useBookmarkWrite(props.expired);
    const onlyUnread = ref(false);
    const expanded = ref(props.initialMaterialId || null);
    const term = ref('');
    const announcement = ref('');
    const items = computed(() => {
      const search = term.value.trim().toLowerCase();
      return (listing.value.value?.items || []).filter(item =>
        (!onlyUnread.value || !item.completed) &&
        (!search || (item.title + ' ' + item.content).toLowerCase().includes(search)),
      );
    });
    watch(command.busy, value => emit('dirty', value), { flush: 'sync' });
    onBeforeUnmount(() => emit('dirty', false));
    listing.load();

    async function mark(item) {
      const result = await command.run('/materials/' + item.id + '/progress', {
        completed: !item.completed,
        version: item.version,
      }, { method: 'PUT', idempotent: false });
      if (!result) return;
      announcement.value = result.completed ? '资料已标为看过。' : '已取消看过标记。';
      emit('changed');
      await listing.load();
    }

    function card(item) {
      return h('li', { key: item.id }, [
        h('div', { class: 'ef-list-row' }, [
          button(item.title, () => { expanded.value = expanded.value === item.id ? null : item.id; }, {
            class: 'ef-link',
            'aria-expanded': expanded.value === item.id,
          }),
          actions(badge(rangeText(item.start_minute, item.end_minute)), item.completed && badge('已看过', 'good')),
        ]),
        item.changed_after_review && notice('老师改过这份资料，可以再看一遍。', 'waiting'),
        expanded.value === item.id && h('div', { class: 'bookmark-material-body' }, [
          item.content && h('p', { class: 'ef-text' }, item.content),
          item.links.length > 0 && h('ul', item.links.map(link => h('li', { key: link.url }, [
            h('a', { href: link.url, target: '_blank', rel: 'noopener noreferrer' }, link.label),
          ]))),
          h('p', { class: 'ef-meta' }, '发布于 ' + date(item.published_at)),
          actions(button(item.completed ? '取消看过标记' : '标为已看过', () => mark(item), { disabled: command.busy.value })),
        ]),
      ]);
    }

    return () => section('课堂资料', [
      h('p', { class: 'ef-meta' }, props.session.course_name + ' · ' + props.session.class_name),
      h('div', { class: 'ef-grid' }, [
        field('查找资料', input(term.value, value => { term.value = value; }, { type: 'search', maxlength: 100 })),
        check('只看没看过的资料', onlyUnread.value, value => { onlyUnread.value = value; }),
      ]),
      listing.value.value && badge('已看 ' + listing.value.value.completed + ' / ' + listing.value.value.total + ' 份'),
      notice(announcement.value, 'good'),
      notice(listing.error.value || command.error.value),
      command.conflict.value && button('刷新后查看最新版', () => listing.load()),
      listing.loading.value && notice('正在读取课堂资料…', 'info'),
      items.value.length
        ? h('ul', { class: 'ef-list' }, items.value.map(card))
        : !listing.loading.value && empty('没有符合条件的资料', '老师发布后会按课堂时间点显示在这里。'),
    ], actions(
      button('返回我的书签', () => emit('back'), { disabled: command.busy.value }),
      button('刷新资料', () => listing.load(), { disabled: listing.loading.value }),
    ));
  },
};
