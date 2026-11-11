import { computed, h, ref, watch } from 'vue';
import { read, useCommand, useDraft, useResource } from './client.js';
import {
  actions, all, badge, button, check, date, empty, field, input, label,
  notice, number, option, section, select, submit, textarea,
} from './ui.js';

const policyFields = [
  {
    key: 'response_hours',
    label: '确认反馈的目标时限（小时）',
    min: 1, max: 168,
    hint: '到点还没确认，老师的待办会标成逾期。',
  },
  {
    key: 'review_days',
    label: '回访默认答复时间（天）',
    min: 1, max: 14,
    hint: '每次发回访时，老师也可以单独改天数。',
  },
  {
    key: 'submit_grace_hours',
    label: '课后可提交反馈的时间（小时）',
    min: 0, max: 168,
    hint: '从每节课堂结束时开始计算。填 0 表示课后停止接收。',
  },
  {
    key: 'daily_case_limit',
    label: '每位学生每节课堂每日最多提交条数',
    min: 1, max: 20,
    hint: '提交上限按 UTC 日期重置。',
  },
  {
    key: 'reopen_days',
    label: '结案后学生可请求继续跟进的时间（天）',
    min: 1, max: 14,
    hint: '从最近一次结案时开始计算。',
  },
];

function policyValues(item) {
  return Object.fromEntries(policyFields.map(({ key }) => [key, item[key]]));
}

const PolicyForm = {
  props: ['policy', 'expired'],
  emits: ['dirty', 'saved', 'refresh'],
  setup(props, { emit }) {
    const command = useCommand(props.expired);
    const draft = useDraft(policyValues(props.policy), value => emit('dirty', value), command.busy);
    const version = ref(props.policy.version);
    const validation = ref('');

    function reset() {
      draft.restore(policyValues(props.policy));
      version.value = props.policy.version;
      validation.value = '';
      command.reset();
    }

    async function save(event) {
      event.preventDefault();
      validation.value = '';
      for (const rule of policyFields) {
        const value = draft.values[rule.key];
        if (!Number.isInteger(value) || value < rule.min || value > rule.max) {
          validation.value = rule.label + '需填写 ' + rule.min + '～' + rule.max + ' 之间的整数。';
          return;
        }
      }
      const result = await command.run('/courses/' + props.policy.course_id + '/policy', {
        ...draft.values, version: version.value,
      }, { method: 'PUT' });
      if (!result) return;
      draft.restore(policyValues(result));
      version.value = result.version;
      emit('saved', result);
    }

    return () => h('form', { class: 'ef-form', onSubmit: save }, [
      h('p', { class: 'ef-meta' }, props.policy.course_name + (props.policy.updated_at
        ? ' · 上次保存于 ' + date(props.policy.updated_at)
        : ' · 当前使用默认设置')),
      h('div', { class: 'ef-grid' }, policyFields.map(rule => field(rule.label, number(
        draft.values[rule.key],
        value => { draft.values[rule.key] = value; },
        { min: rule.min, max: rule.max, required: true, disabled: command.busy.value },
      ), rule.hint))),
      notice(validation.value || command.error.value),
      command.conflict.value && button('读取最新规则', () => emit('refresh')),
      version.value !== props.policy.version && notice('已有更新，请恢复当前规则或核对后再保存。', 'waiting'),
      version.value !== props.policy.version && button('采用最新版本继续编辑', () => {
        if (window.confirm('保存时将用草稿替换此课程的最新规则。确定继续？')) {
          version.value = props.policy.version;
          command.reset();
        }
      }),
      actions(
        submit('保存课程处理规则', command.busy.value || !draft.dirty.value || version.value !== props.policy.version),
        button('恢复当前规则', reset, { disabled: command.busy.value }),
      ),
    ]);
  },
};

export const FeedbackPolicies = {
  props: ['catalog', 'initialCourse', 'expired'],
  emits: ['dirty', 'changed'],
  setup(props, { emit }) {
    const courseId = ref(props.initialCourse || props.catalog.courses[0]?.id || null);
    const dirty = ref(false);
    const saved = ref('');
    const policy = useResource((signal, id) => read('/courses/' + id + '/policy', {}, signal), props.expired);

    function load() {
      if (courseId.value) policy.load(courseId.value);
    }

    watch(courseId, () => {
      policy.clear();
      saved.value = '';
      load();
    }, { immediate: true });

    function update(result) {
      policy.value.value = { ...policy.value.value, ...result };
      saved.value = '规则已保存。';
      emit('changed');
    }

    return () => section('课程反馈处理规则', [
      field('管理课程', select(courseId.value, [
        all('请选择课程'), ...props.catalog.courses.map(item => option(item.id, item.name)),
      ], value => { courseId.value = value ? Number(value) : null; }, { disabled: dirty.value })),
      notice(saved.value, 'good'),
      notice(policy.error.value),
      policy.error.value && button('重试读取规则', load),
      policy.loading.value && notice('正在获取规则…', 'info'),
      policy.value.value && h(PolicyForm, {
        key: courseId.value,
        policy: policy.value.value,
        expired: props.expired,
        onDirty: value => {
          dirty.value = value;
          emit('dirty', value);
        },
        onSaved: update,
        onRefresh: load,
      }),
      !props.catalog.courses.length && empty('暂无可管理课程'),
    ]);
  },
};

const TemplateEditor = {
  props: ['item', 'catalog', 'expired'],
  emits: ['dirty', 'saved', 'cancel'],
  setup(props, { emit }) {
    const command = useCommand(props.expired);
    const initial = {
      title: props.item?.title || '',
      content: props.item?.content || '',
      reason: props.item?.reason || '',
      archived: props.item?.archived ?? false,
    };
    const draft = useDraft(initial, value => emit('dirty', value), command.busy);
    const { values } = draft;
    const validation = ref('');

    function cancel() {
      if (draft.dirty.value && !window.confirm('放弃模板编辑？')) return;
      draft.restore();
      emit('cancel');
    }

    async function save(event) {
      event.preventDefault();
      if (values.title.trim().length < 2 || values.content.trim().length < 2) {
        validation.value = '标题和内容各至少填写两个字。';
        return;
      }
      const current = props.item;
      const result = await command.run(current ? '/templates/' + current.id : '/templates', {
        title: values.title.trim(),
        content: values.content.trim(),
        reason: values.reason || null,
        archived: values.archived,
        version: current?.version || 0,
      }, { method: current ? 'PUT' : 'POST' });
      if (!result) return;
      draft.restore();
      emit('saved', result);
    }

    return () => section(props.item ? '编辑回应模板' : '新建回应模板', h('form', { class: 'ef-form', onSubmit: save }, [
      field('模板标题', input(values.title, value => { values.title = value; }, {
        required: true, minlength: 2, maxlength: 120,
      })),
      field('适用原因（可选）', select(values.reason, [all('通用'), ...props.catalog.reasons], value => { values.reason = value; })),
      field('回应文本', textarea(values.content, value => { values.content = value; }, {
        required: true, minlength: 2, maxlength: 2000,
        placeholder: '比如：谢谢你告诉我。下节课开头我再讲一道例题。',
      }), '填写模板后，可以在单条反馈的交流区载入并修改文本。'),
      props.item && check('归档此模板', values.archived, value => { values.archived = value; }),
      notice(validation.value || command.error.value),
      actions(
        submit('保存模板', command.busy.value),
        button('取消', cancel, { disabled: command.busy.value }),
      ),
    ]));
  },
};

export const FeedbackTemplates = {
  props: ['catalog', 'expired'],
  emits: ['dirty'],
  setup(props, { emit }) {
    const listing = useResource((signal, archived) => read('/templates', { archived }, signal), props.expired);
    const mode = ref('list');
    const editing = ref(null);
    const archived = ref(false);
    const term = ref('');
    const reason = ref('');
    const noticeText = ref('');
    const visible = computed(() => {
      const text = term.value.trim().toLocaleLowerCase();
      return (listing.value.value?.items || []).filter(item => {
        const matches = !text || (item.title + ' ' + item.content).toLocaleLowerCase().includes(text);
        return matches && (!reason.value || item.reason === reason.value);
      });
    });

    function load() {
      listing.load(archived.value);
    }

    watch(archived, load, { immediate: true });

    function start(item = null) {
      editing.value = item;
      noticeText.value = '';
      mode.value = 'edit';
    }

    function back() {
      editing.value = null;
      mode.value = 'list';
    }

    function saved(item) {
      back();
      noticeText.value = item.archived ? '模板已归档。' : '回应模板已保存。';
      if (archived.value !== item.archived) archived.value = item.archived;
      else load();
    }

    function card(item) {
      return h('li', { key: item.id }, [
        h('div', { class: 'ef-list-row' }, [
          h('strong', item.title),
          actions(
            badge(item.reason ? label(props.catalog.reasons, item.reason) : '通用'),
            badge('已使用 ' + item.uses + ' 次'),
          ),
        ]),
        h('p', { class: 'ef-text' }, item.content),
        h('div', { class: 'ef-list-row' }, [
          h('p', { class: 'ef-meta' }, '更新于 ' + date(item.updated_at)),
          button(item.archived ? '查看或恢复' : '编辑模板', () => start(item)),
        ]),
      ]);
    }

    return () => mode.value === 'edit'
      ? h(TemplateEditor, {
        item: editing.value,
        catalog: props.catalog,
        expired: props.expired,
        onDirty: value => emit('dirty', value),
        onSaved: saved,
        onCancel: back,
      })
      : section('我的回应模板', [
        notice(noticeText.value, 'good'),
        notice(listing.error.value),
        h('div', { class: 'ef-grid' }, [
          field('搜索模板', input(term.value, value => { term.value = value; }, { type: 'search', maxlength: 120 })),
          field('适用原因', select(reason.value, [all('全部原因'), ...props.catalog.reasons], value => { reason.value = value; })),
          check('查看归档模板', archived.value, value => { archived.value = value; }),
        ]),
        listing.loading.value && notice('正在读取回应模板…', 'info'),
        visible.value.length
          ? h('ul', { class: 'ef-list' }, visible.value.map(card))
          : !listing.loading.value && empty('没有符合条件的模板', '可在此保存常用回应，再到反馈交流中使用。'),
      ], actions(
        button('刷新模板', load, { disabled: listing.loading.value }),
        button('新建模板', () => start(), { primary: true }),
      ));
  },
};
