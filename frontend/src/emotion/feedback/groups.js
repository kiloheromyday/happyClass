import { computed, h, ref, watch } from 'vue';
import { read, useCommand, useDraft, useResource } from './client.js';
import { FeedbackSuggestions } from './suggestions.js';
import {
  actions, all, badge, button, check, date, empty, field, input, notice, number,
  option, pager, recordList, section, select, sessionLabel, submit, textarea,
} from './ui.js';

const batchOperations = [
  option('REPLY', '统一回应'),
  option('ACKNOWLEDGE', '统一确认收到'),
  option('START', '统一开始处理'),
  option('REQUEST_REVIEW', '统一发起回访'),
];

function eligible(item, action) {
  return {
    REPLY: item.capabilities.reply,
    ACKNOWLEDGE: item.capabilities.acknowledge,
    START: item.capabilities.start,
    REQUEST_REVIEW: item.capabilities.request_review,
  }[action];
}

function groupLabel(group) {
  return group.course_name ? group.course_name + ' · ' + group.class_name : '';
}

const BatchForm = {
  props: ['group', 'catalog', 'expired'],
  emits: ['dirty', 'saved', 'refresh'],
  setup(props, { emit }) {
    const command = useCommand(props.expired);
    const initial = { action: 'REPLY', content: '', due_days: 3, case_ids: [] };
    const draft = useDraft(initial, value => emit('dirty', value), command.busy);
    const { values } = draft;
    const expected = ref(props.group.version);
    const preview = ref(false);
    const allowed = computed(() => props.group.members.filter(item => eligible(item, values.action)));
    const selected = computed(() => allowed.value.filter(item => values.case_ids.includes(item.id)));
    const requiresReview = computed(() => values.action === 'REQUEST_REVIEW');

    function toggle(identifier, checked) {
      values.case_ids = checked ? [...values.case_ids, identifier] : values.case_ids.filter(id => id !== identifier);
      preview.value = false;
    }

    function setAction(value) {
      values.action = value;
      values.case_ids = values.case_ids.filter(id => allowed.value.some(item => item.id === id));
    }

    function reset() {
      draft.restore(initial);
      expected.value = props.group.version;
      preview.value = false;
      command.reset();
    }

    function refresh() {
      preview.value = false;
      emit('refresh');
    }

    function adopt() {
      expected.value = props.group.version;
      values.case_ids = selected.value.map(item => item.id);
      command.reset();
    }

    async function send(event) {
      event.preventDefault();
      if (!selected.value.length || values.content.trim().length < 2 || expected.value !== props.group.version) return;
      if (!preview.value) {
        preview.value = true;
        return;
      }
      const result = await command.run('/groups/' + props.group.id + '/batch', {
        version: expected.value,
        action: values.action,
        content: values.content.trim(),
        due_days: values.due_days || 3,
        members: selected.value.map(item => ({ case_id: item.id, version: item.version })),
      });
      if (!result) return;
      reset();
      expected.value = result.group.version;
      emit('saved', result);
    }

    watch(() => props.group.version, () => {
      if (!draft.dirty.value) expected.value = props.group.version;
    });

    function picker() {
      return [
        actions(
          button('选择所有可处理反馈', () => { values.case_ids = allowed.value.map(item => item.id); }, { disabled: !allowed.value.length }),
          button('清空选择', () => { values.case_ids = []; }, { disabled: !values.case_ids.length }),
          badge('已选 ' + selected.value.length + ' / ' + props.group.members.length),
        ),
        allowed.value.length ? h('ul', { class: 'ef-list' }, props.group.members.map(item => h('li', { key: item.id }, [
          check(item.number + ' · ' + item.title, values.case_ids.includes(item.id), value => toggle(item.id, value), !eligible(item, values.action)),
          h('p', { class: 'ef-meta' }, item.state_label + (eligible(item, values.action) ? '' : ' · 当前状态不支持所选操作')),
        ]))) : empty('当前组中没有可执行此操作的反馈'),
      ];
    }

    function editor() {
      return [
        field('批量操作', select(values.action, batchOperations, setAction)),
        picker(),
        field(requiresReview.value ? '发送给每位学生的回访问题' : '发送给每位学生的处理说明', textarea(values.content, value => {
          values.content = value;
        }, {
          required: true, minlength: 2, maxlength: requiresReview.value ? 1000 : 2000,
        })),
        requiresReview.value && field('期望答复天数', number(values.due_days, value => { values.due_days = value; }, {
          required: true, min: 1, max: 14,
        })),
      ];
    }

    function confirmation() {
      return [
        h('p', '将分别向 ' + selected.value.length + ' 条反馈发送以下内容。学生只会在自己的反馈单里看到回应。'),
        h('p', { class: 'ef-text' }, values.content.trim()),
        h('ul', selected.value.map(item => h('li', { key: item.id }, item.number + ' · ' + item.title))),
      ];
    }

    return () => section('集中处理操作', h('form', { class: 'ef-form', onSubmit: send }, [
      preview.value ? confirmation() : editor(),
      notice(command.error.value),
      command.conflict.value && button('刷新成员状态', refresh),
      expected.value !== props.group.version && notice('处理组已有更新，请检查成员与状态。', 'waiting'),
      expected.value !== props.group.version && button('采用最新的处理组版本', adopt),
      actions(
        submit(preview.value ? '确认处理所选反馈' : '预览批量操作', command.busy.value || !selected.value.length || expected.value !== props.group.version),
        preview.value && button('返回调整', () => { preview.value = false; }, { disabled: command.busy.value }),
        button('重置操作', reset, { disabled: command.busy.value }),
      ),
    ]));
  },
};

const GroupEditor = {
  props: ['group', 'seed', 'suggestion', 'catalog', 'expired'],
  emits: ['saved', 'cancel', 'dirty', 'refresh'],
  setup(props, { emit }) {
    const command = useCommand(props.expired);
    const initial = {
      title: props.group?.title || props.suggestion?.title || '',
      description: props.group?.description || props.suggestion?.description || '',
      session_id: props.group?.session_id ?? props.seed?.[0]?.session_id ?? null,
      archived: props.group?.archived ?? false,
      case_ids: (props.group?.members || props.seed || []).map(item => item.id),
    };
    const draft = useDraft(initial, value => emit('dirty', value), command.busy);
    const { values } = draft;
    const members = ref(new Map((props.group?.members || props.seed || []).map(item => [item.id, item])));
    const search = ref('');
    const candidates = useResource((signal, id, term, offset) => read('/cases', {
      session_id: id, search: term, offset, limit: 15,
    }, signal), props.expired);
    const selected = computed(() => values.case_ids.map(id => members.value.get(id)).filter(Boolean));
    const version = ref(props.group?.version ?? 0);

    async function load(offset = 0) {
      if (!values.session_id) return;
      await candidates.load(values.session_id, search.value.trim(), offset);
    }

    watch(() => values.session_id, id => {
      candidates.clear();
      if (id) load();
    }, { immediate: true });

    function changeSession(value) {
      if (values.case_ids.length && !window.confirm('切换课堂将清空已选成员，继续吗？')) return;
      values.case_ids = [];
      members.value = new Map();
      values.session_id = value ? Number(value) : null;
    }

    function toggle(item, checked) {
      if (checked) {
        if (values.case_ids.length >= 50 || values.case_ids.includes(item.id)) return;
        members.value.set(item.id, item);
        values.case_ids = [...values.case_ids, item.id];
      } else {
        values.case_ids = values.case_ids.filter(id => id !== item.id);
      }
    }

    function cancel() {
      if (draft.dirty.value && !window.confirm('放弃这次处理组编辑？')) return;
      draft.restore();
      emit('cancel');
    }

    async function save(event) {
      event.preventDefault();
      if (!values.case_ids.length || !values.session_id || values.title.trim().length < 2) return;
      const payload = {
        title: values.title.trim(),
        description: values.description.trim(),
        case_ids: [...values.case_ids],
      };
      const result = props.group
        ? await command.run('/groups/' + props.group.id, {
          ...payload, version: version.value, archived: values.archived,
        }, { method: 'PUT' })
        : await command.run('/groups', { ...payload, session_id: values.session_id });
      if (!result) return;
      draft.restore();
      emit('saved', result);
    }

    function selection() {
      const page = candidates.value.value;
      return [
        h('div', { class: 'ef-grid' }, [
          field('查找本课堂反馈', input(search.value, value => { search.value = value; }, {
            type: 'search', maxlength: 120,
            onKeydown: event => { if (event.key === 'Enter') { event.preventDefault(); load(); } },
          })),
          actions(button('搜索成员', () => load(), { disabled: candidates.loading.value || !values.session_id })),
        ]),
        notice(candidates.error.value),
        candidates.loading.value && notice('正在读取课堂反馈…', 'info'),
        page?.items.length
          ? h('ul', { class: 'ef-list' }, page.items.map(item => h('li', { key: item.id }, [
            check(item.number + ' · ' + item.title, values.case_ids.includes(item.id), checked => toggle(item, checked),
              values.case_ids.length >= 50 && !values.case_ids.includes(item.id)),
            h('p', { class: 'ef-meta' }, item.reason_labels.join('、') + ' · ' + item.state_label),
          ])))
          : values.session_id && !candidates.loading.value && empty('没有匹配的反馈'),
        pager(page, candidates.loading.value, load),
        h('h4', '已选成员（' + selected.value.length + ' / 50）'),
        actions(...selected.value.map(item => button('移除 ' + item.number, () => toggle(item, false), {
          key: item.id, title: item.title, disabled: command.busy.value,
        }))),
      ];
    }

    return () => section(props.group ? '编辑处理组' : '创建集中处理组', h('form', { class: 'ef-form', onSubmit: save }, [
      field('课堂', select(values.session_id, [
        all('请选择课堂'), ...props.catalog.sessions.map(item => option(item.id, sessionLabel(item))),
      ], changeSession, { required: true, disabled: Boolean(props.group) })),
      field('处理组名称', input(values.title, value => { values.title = value; }, {
        required: true, minlength: 2, maxlength: 120,
      })),
      field('内部说明（可选）', textarea(values.description, value => { values.description = value; })),
      props.group && check('归档此处理组', values.archived, value => { values.archived = value; }),
      selection(),
      notice(command.error.value),
      command.conflict.value && button('刷新处理组', () => emit('refresh')),
      props.group && version.value !== props.group.version && button('核对后使用最新版本', () => {
        if (window.confirm('保存会使用当前编辑中的成员列表，是否继续？')) version.value = props.group.version;
      }),
      actions(
        submit('保存处理组', command.busy.value || !values.case_ids.length || Boolean(props.group && version.value !== props.group.version)),
        button('取消', cancel, { disabled: command.busy.value }),
      ),
    ]));
  },
};

export const FeedbackGroups = {
  props: ['catalog', 'seed', 'initialGroup', 'initialSession', 'expired'],
  emits: ['open', 'dirty', 'changed'],
  setup(props, { emit }) {
    const archived = ref(false);
    const session = ref(props.initialSession ?? null);
    const mode = ref(props.seed?.length ? 'create' : 'list');
    const dirty = ref(false);
    const resultNote = ref('');
    const suggestion = ref(null);
    const currentId = ref(props.initialGroup ?? null);
    const group = useResource((signal, id) => read('/groups/' + id, {}, signal), props.expired);
    const listing = useResource((signal, id, isArchived) => read('/groups', {
      session_id: id, archived: isArchived,
    }, signal), props.expired);

    function onDirty(value) {
      dirty.value = value;
      emit('dirty', value);
    }

    function load() {
      return listing.load(session.value, archived.value);
    }

    async function open(id) {
      if (dirty.value) return;
      currentId.value = id;
      group.clear();
      mode.value = 'detail';
      await group.load(id);
    }

    function back() {
      if (dirty.value) return;
      resultNote.value = '';
      mode.value = 'list';
      load();
    }

    function saved(item) {
      currentId.value = item.id;
      group.value.value = item;
      mode.value = 'detail';
      resultNote.value = '处理组已保存。';
      emit('changed');
    }

    function batchSaved(result) {
      group.value.value = result.group;
      resultNote.value = '已成功处理 ' + result.affected_count + ' 条反馈。';
      emit('changed');
    }

    if (currentId.value) open(currentId.value);
    else if (mode.value === 'list') load();

    function listPage() {
      return section('集中处理组', [
        h('div', { class: 'ef-grid' }, [
          field('课堂', select(session.value, [
            all('全部课堂'), ...props.catalog.sessions.map(item => option(item.id, sessionLabel(item))),
          ], value => { session.value = value ? Number(value) : null; load(); })),
          check('只看归档处理组', archived.value, value => { archived.value = value; load(); }),
        ]),
        notice(listing.error.value),
        listing.loading.value && notice('正在加载处理组…', 'info'),
        listing.value.value?.items.length
          ? h('ul', { class: 'ef-list' }, listing.value.value.items.map(item => h('li', { key: item.id }, [
            h('div', { class: 'ef-list-row' }, [
              button(item.title, () => open(item.id), { class: 'ef-link' }),
              actions(badge(item.member_count + ' 条'), badge(item.active_count + ' 条进行中')),
            ]),
            h('p', { class: 'ef-meta' }, groupLabel(item) + ' · ' + date(item.updated_at)),
            item.description && h('p', { class: 'ef-text' }, item.description),
          ])))
          : !listing.loading.value && empty('暂无处理组', '可从反馈列表选中同一节课堂的反馈来创建。'),
      ], actions(
        button('刷新', load, { disabled: listing.loading.value }),
        button('查看分组建议', () => { mode.value = 'suggestions'; }),
        button('新建处理组', () => { suggestion.value = null; mode.value = 'create'; }, { primary: true }),
      ));
    }

    function detailPage() {
      const current = group.value.value;
      return [
        actions(
          button('返回处理组列表', back, { disabled: dirty.value }),
          current && button('编辑成员与说明', () => { mode.value = 'edit'; }, { disabled: dirty.value }),
        ),
        notice(group.error.value),
        group.error.value && button('重试读取', () => group.load(currentId.value)),
        group.loading.value && notice('正在读取处理组…', 'info'),
        notice(resultNote.value, 'good'),
        current && section(current.title, [
          current.description && h('p', { class: 'ef-text' }, current.description),
          recordList(current.members, props.catalog, id => { if (!dirty.value) emit('open', id); }),
        ], actions(badge(current.members.length + ' 条反馈'), current.archived && badge('已归档'))),
        current && !current.archived && h(BatchForm, {
          group: current, catalog: props.catalog, expired: props.expired,
          onDirty, onSaved: batchSaved, onRefresh: () => group.load(current.id),
        }),
      ];
    }

    return () => {
      if (mode.value === 'list') return listPage();
      if (mode.value === 'detail') return detailPage();
      if (mode.value === 'suggestions') return h(FeedbackSuggestions, {
        catalog: props.catalog,
        selection: { session_id: session.value },
        expired: props.expired,
        onOpen: id => emit('open', id),
        onBack: back,
        onCreate: value => { suggestion.value = value; mode.value = 'create'; },
      });
      return h(GroupEditor, {
        group: mode.value === 'edit' ? group.value.value : null,
        seed: mode.value === 'create' ? (suggestion.value?.members || props.seed) : null,
        suggestion: mode.value === 'create' ? suggestion.value : null,
        catalog: props.catalog,
        expired: props.expired,
        onDirty,
        onSaved: saved,
        onRefresh: () => group.load(currentId.value),
        onCancel: () => { if (mode.value === 'edit') mode.value = 'detail'; else back(); },
      });
    };
  },
};
