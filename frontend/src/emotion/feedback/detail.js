import { computed, h, ref } from 'vue';
import { read, useCommand, useDraft, useResource, url } from './client.js';
import { FeedbackComposer } from './composer.js';
import { FeedbackConversation, FeedbackHistory } from './conversation.js';
import { FeedbackReviews } from './review.js';
import { FeedbackProgress } from './progress.js';
import {
  actions, all, badge, button, casePath, date, emotion, empty, field, impacts, input,
  keyValues, label, notice, option, priorities, section, select, sessionLabel, status,
  submit, textarea,
} from './ui.js';

const transitions = [
  { flag: 'acknowledge', code: 'ACKNOWLEDGE', label: '确认收到' },
  { flag: 'start', code: 'START', label: '开始处理' },
  { flag: 'ask', code: 'ASK_STUDENT', label: '请学生补充', needsText: true },
  { flag: 'resolve', code: 'RESOLVE', label: '说明后结案', needsText: true },
  { flag: 'reopen', code: 'REOPEN', label: '请求继续跟进', needsText: true },
  { flag: 'withdraw', code: 'WITHDRAW', label: '撤回反馈' },
];

const transitionHints = {
  ACKNOWLEDGE: '学生会看到老师已收到反馈。',
  START: '将这条反馈转入处理中。',
  ASK_STUDENT: '写下需要补充的课堂环节或遇到的困难。',
  RESOLVE: '请说明已经采取的措施，或暂时无法处理的原因。',
  REOPEN: '说说还有哪些地方需要继续跟进。',
  WITHDRAW: '撤回后停止处理及回访，仍可查看原有记录。',
};

const resolutionLabels = {
  STAFF_CLOSED: '老师说明后关闭',
  STUDENT_CONFIRMED: '学生确认改善',
};

const FeedbackActions = {
  props: ['item', 'expired'],
  emits: ['dirty', 'changed', 'refresh'],
  setup(props, { emit }) {
    const command = useCommand(props.expired);
    const draft = useDraft({ content: '' }, value => emit('dirty', value), command.busy);
    const choice = ref(null);
    const version = ref(props.item.version);
    const updated = ref(false);

    function start(item) {
      choice.value = item;
      version.value = props.item.version;
      updated.value = false;
      command.reset();
    }

    function cancel() {
      choice.value = null;
      draft.restore();
      command.reset();
    }

    async function save(event) {
      event.preventDefault();
      const selected = choice.value;
      if (!selected || !props.item.capabilities[selected.flag]) return;
      const content = draft.values.content.trim();
      if (selected.needsText && content.length < 2) return;
      const result = await command.run(casePath(props.item.id) + '/actions', {
        version: version.value,
        action: selected.code,
        content,
      });
      if (!result) return;
      cancel();
      updated.value = true;
      emit('changed', result);
    }

    function adopt() {
      if (!window.confirm('确认已核对最新状态，并用当前草稿继续操作？')) return;
      version.value = props.item.version;
      command.reset();
    }

    return () => {
      const available = transitions.filter(item => props.item.capabilities[item.flag]);
      return section('更新处理进度', [
        updated.value && notice('处理进度已更新。', 'good'),
        available.length ? actions(...available.map(item => button(item.label, () => start(item), {
          disabled: Boolean(choice.value) || command.busy.value,
        }))) : h('p', { class: 'ef-meta' }, '当前没有可用的状态操作。'),
        choice.value && h('form', { class: 'ef-form', onSubmit: save }, [
          h('strong', choice.value.label),
          h('p', transitionHints[choice.value.code]),
          field(choice.value.needsText ? '说明' : '说明（可选）',
            textarea(draft.values.content, value => { draft.values.content = value; }, {
              required: choice.value.needsText,
              minlength: choice.value.needsText ? 2 : undefined,
            }),
          ),
          notice(command.error.value),
          command.conflict.value && button('刷新当前状态', () => emit('refresh')),
          version.value !== props.item.version && notice('状态版本已变化，请核对后再提交。', 'waiting'),
          version.value !== props.item.version && button('使用最新状态', adopt),
          actions(
            submit('确认' + choice.value.label, command.busy.value || version.value !== props.item.version || !props.item.capabilities[choice.value.flag]),
            button('取消', cancel, { disabled: command.busy.value }),
          ),
        ]),
      ]);
    };
  },
};

const FeedbackManagement = {
  props: ['item', 'expired'],
  emits: ['dirty', 'changed', 'refresh'],
  setup(props, { emit }) {
    const command = useCommand(props.expired);
    const initial = () => ({ priority: props.item.priority, tags: props.item.tags.join('，') });
    const draft = useDraft(initial(), value => emit('dirty', value), command.busy);
    const version = ref(props.item.version);
    const error = ref('');
    const saved = ref(false);

    function reset() {
      draft.restore(initial());
      version.value = props.item.version;
      command.reset();
      error.value = '';
    }

    async function save(event) {
      event.preventDefault();
      const tags = [...new Set(draft.values.tags.split(/[,，、]/).map(value => value.trim()).filter(Boolean))];
      if (tags.length > 5 || tags.some(value => value.length > 24)) {
        error.value = '最多填写 5 个标签，每个标签不超过 24 字。';
        return;
      }
      const result = await command.run(casePath(props.item.id) + '/management', {
        priority: draft.values.priority, tags, version: version.value,
      }, { method: 'PUT' });
      if (!result) return;
      draft.restore({ priority: result.priority, tags: result.tags.join('，') });
      version.value = result.version;
      error.value = '';
      saved.value = true;
      emit('changed', result);
    }

    async function toggleWatch() {
      const result = await command.run(casePath(props.item.id) + '/watch', undefined, {
        method: 'PUT', idempotent: false, params: { enabled: !props.item.watched },
      });
      if (result) emit('refresh');
    }

    return () => section('内部处理信息', [
      h('p', { class: 'ef-meta' }, '优先级和标签仅对有权限处理本条反馈的教师和管理员可见。'),
      notice(error.value || command.error.value),
      saved.value && notice('已保存内部处理信息。', 'good'),
      command.conflict.value && button('刷新反馈并查看最新值', () => emit('refresh')),
      props.item.capabilities.manage && h('form', { class: 'ef-form', onSubmit: save }, [
        field('处理优先级', select(draft.values.priority, priorities, value => { draft.values.priority = value; })),
        field('标签', input(draft.values.tags, value => { draft.values.tags = value; }, {
          maxlength: 128,
          placeholder: '例如：节奏调整，需补充示例',
        }), '用逗号分隔标签。'),
        actions(
          submit('保存优先级和标签', command.busy.value || !draft.dirty.value),
          button('恢复当前值', reset, { disabled: command.busy.value }),
        ),
      ]),
    ], button(props.item.watched ? '取消关注' : '关注这条反馈', toggleWatch, {
      disabled: command.busy.value || draft.dirty.value,
    }));
  },
};

const TeachingAdjustments = {
  props: ['item', 'staff', 'expired'],
  emits: ['dirty', 'changed', 'navigate', 'refresh'],
  setup(props, { emit }) {
    const command = useCommand(props.expired);
    const draft = useDraft({ adjustment_id: null, public_summary: '' }, value => emit('dirty', value), command.busy);
    const context = useResource(signal => read('/sessions/' + props.item.session_id + '/context', {}, signal), props.expired);
    const version = ref(props.item.version);
    const hasContext = ref(false);
    const editing = ref(false);

    function start(item = null) {
      if (draft.dirty.value || command.busy.value) return;
      draft.restore({
        adjustment_id: item?.adjustment_id ?? null,
        public_summary: item?.public_summary || '',
      });
      version.value = props.item.version;
      editing.value = true;
      command.reset();
      if (!hasContext.value) {
        context.load().then(result => { hasContext.value = Boolean(result); });
      }
    }

    function close() {
      editing.value = false;
      draft.restore({ adjustment_id: null, public_summary: '' });
      command.reset();
    }

    async function save(event) {
      event.preventDefault();
      if (!draft.values.adjustment_id || draft.values.public_summary.trim().length < 2) return;
      const result = await command.run(casePath(props.item.id) + '/adjustments', {
        adjustment_id: draft.values.adjustment_id,
        public_summary: draft.values.public_summary.trim(),
        version: version.value,
      });
      if (!result) return;
      close();
      emit('changed', result);
    }

    async function remove(item) {
      if (!window.confirm('解除这项教学调整与反馈的关联？')) return;
      const result = await command.run(
        casePath(props.item.id) + '/adjustments/' + item.adjustment_id + '/unlink',
        { version: props.item.version },
      );
      if (result) emit('changed', result);
    }

    function form() {
      const options = context.value.value?.adjustments || [];
      if (context.loading.value) return notice('正在读取本课堂的教学调整…', 'info');
      if (context.error.value) return actions(notice(context.error.value), button('重试', () => context.load()), button('返回', close));
      if (!options.length) return empty('本课堂还没有教学调整', '可在情绪洞察中先记录一项教学调整。',
        actions(button('前往情绪洞察', () => emit('navigate', { tab: 'insights', sessionId: props.item.session_id })), button('返回', close)),
      );
      return h('form', { class: 'ef-form', onSubmit: save }, [
        field('本课堂的调整', select(draft.values.adjustment_id, [
          all('请选择调整'), ...options.map(item => option(item.id, item.title)),
        ], value => {
          draft.values.adjustment_id = value ? Number(value) : null;
        }, { required: true })),
        field('给学生看的说明', textarea(draft.values.public_summary, value => { draft.values.public_summary = value; }, {
          required: true, maxlength: 1000, minlength: 2,
        }), '只向学生展示这里填写的说明。'),
        version.value !== props.item.version && button('使用刷新后的反馈版本', () => { version.value = props.item.version; }),
        actions(submit('保存关联', command.busy.value), button('取消', close, { disabled: command.busy.value })),
      ]);
    }

    return () => section('教学调整', [
      notice(command.error.value),
      command.conflict.value && button('刷新反馈', () => emit('refresh')),
      props.item.adjustments.length
        ? h('ul', { class: 'ef-list' }, props.item.adjustments.map(item => h('li', { key: item.adjustment_id }, [
          props.staff && h('strong', item.title),
          h('p', { class: 'ef-text' }, item.public_summary),
          h('p', { class: 'ef-meta' }, '关联于 ' + date(item.created_at)),
          props.staff && actions(
            props.item.state !== 'WITHDRAWN' && button('更新公开说明', () => start(item), { disabled: editing.value || command.busy.value }),
            button('解除关联', () => remove(item), { disabled: editing.value || command.busy.value }),
          ),
        ]))) : empty('暂无关联的教学调整'),
      editing.value && form(),
    ], props.staff && props.item.state !== 'WITHDRAWN' && button('关联教学调整', () => start(), {
      disabled: editing.value || command.busy.value,
    }));
  },
};

export const FeedbackDetail = {
  props: ['id', 'catalog', 'staff', 'expired', 'initialTab'],
  emits: ['back', 'dirty', 'changed', 'navigate', 'group'],
  setup(props, { emit }) {
    const detail = useResource(signal => read(casePath(props.id), {}, signal), props.expired);
    const tab = ref(props.initialTab || 'overview');
    const dirty = ref(false);
    const editing = ref(false);
    const operation = ref('workflow');
    const refreshing = ref(false);
    const item = computed(() => detail.value.value);
    detail.load();

    function onDirty(value) {
      dirty.value = value;
      emit('dirty', value);
    }

    function switchTab(next) {
      if (dirty.value || next === tab.value) return;
      editing.value = false;
      tab.value = next;
    }

    async function reload() {
      refreshing.value = true;
      try {
        await detail.load();
      } finally {
        refreshing.value = false;
      }
    }

    async function changed(result) {
      if (result?.id === props.id) detail.replace(result);
      else await reload();
      emit('changed');
    }

    function overview() {
      if (editing.value) return h(FeedbackComposer, {
        item: item.value,
        catalog: props.catalog,
        expired: props.expired,
        onDirty,
        onRefresh: reload,
        onCancel: () => { editing.value = false; },
        onSaved: result => { editing.value = false; changed(result); },
      });
      const current = item.value;
      return [
        section('原始反馈', [
          keyValues([
            ['课堂', sessionLabel(current)],
            ['情绪', emotion(props.catalog, current.emotion)],
            ['课堂原因', current.reason_labels.join('、')],
            ['学习影响', label(impacts, current.impact)],
            ['课堂时间点', current.topic_minute === null ? '—' : '开课后 ' + current.topic_minute + ' 分钟'],
            ['提交时间', date(current.created_at)],
            ['确认时间', date(current.acknowledged_at)],
            ['首次回应', date(current.first_response_at)],
            ['结案依据', resolutionLabels[current.resolution]],
          ]),
          current.content && h('p', { class: 'ef-text' }, current.content),
        ], current.capabilities.edit && button('编辑反馈', () => { editing.value = true; })),
        current.linked_emotion_record && section('关联的个人情绪记录', [
          keyValues([
            ['当时记录的情绪', emotion(props.catalog, current.linked_emotion_record.emotion)],
            ['记录时间', date(current.linked_emotion_record.recorded_at)],
          ]),
          h('p', { class: 'ef-meta' }, '此记录仅在你的账户中展示。老师可以看到你在反馈里选择的情绪。'),
        ], button('查看我的情绪历史', () => emit('navigate', {
          tab: 'history',
          sessionId: current.session_id,
        }))),
        props.staff && current.groups.length > 0 && section('所属处理组', actions(...current.groups.map(group =>
          button(group.title + (group.archived ? '（已归档）' : ''), () => emit('group', group.id)),
        ))),
      ];
    }

    function currentPanel() {
      const bindings = {
        item: item.value,
        expired: props.expired,
        onDirty,
        onChanged: changed,
        onRefresh: reload,
      };
      if (tab.value === 'overview') return overview();
      if (tab.value === 'progress') return h(FeedbackProgress, {
        item: item.value, expired: props.expired, onTab: switchTab,
      });
      if (tab.value === 'conversation') return h(FeedbackConversation, {
        item: item.value,
        expired: props.expired,
        staff: props.staff,
        onDirty,
        onChanged: changed,
      });
      if (tab.value === 'reviews') return h(FeedbackReviews, { ...bindings, staff: props.staff, catalog: props.catalog });
      if (tab.value === 'history') return h(FeedbackHistory, { item: item.value, catalog: props.catalog, expired: props.expired });
      if (tab.value === 'adjustments') return h(TeachingAdjustments, {
        ...bindings,
        staff: props.staff,
        onNavigate: target => emit('navigate', target),
      });
      return [
        props.staff && actions(
          button('更新状态', () => { operation.value = 'workflow'; }, { disabled: dirty.value, 'aria-pressed': operation.value === 'workflow' }),
          button('内部优先级和标签', () => { operation.value = 'manage'; }, { disabled: dirty.value, 'aria-pressed': operation.value === 'manage' }),
        ),
        operation.value === 'manage'
          ? h(FeedbackManagement, bindings)
          : h(FeedbackActions, bindings),
      ];
    }

    const tabs = [
      ['overview', '反馈内容'],
      ['progress', '处理进度'],
      ['workflow', '处理操作'],
      ['conversation', '反馈交流'],
      ['reviews', '回访'],
      ['adjustments', '教学调整'],
      ['history', '时间线'],
    ];
    return () => [
      actions(
        button('返回列表', () => emit('back'), { disabled: dirty.value }),
        button('刷新反馈', reload, { disabled: refreshing.value || detail.loading.value }),
        item.value && h('a', { class: 'ef-button', href: url(casePath(props.id) + '/print.html') }, '下载可打印记录'),
      ),
      notice(detail.error.value),
      detail.loading.value && notice('正在读取反馈…', 'info'),
      item.value && section(item.value.title, [
        h('p', { class: 'ef-meta' }, [item.value.number, item.value.course_name, item.value.class_name].join(' · ')),
        h('nav', { class: 'ef-tabs', 'aria-label': '反馈详情' }, tabs.map(([key, title]) => button(
          title + (key === 'reviews' && item.value.open_review ? ' · 待答复' : ''),
          () => switchTab(key),
          { key, 'aria-pressed': tab.value === key, disabled: dirty.value && tab.value !== key },
        ))),
      ], actions(status(item.value), item.value.is_demo && badge('演示'))),
      item.value && currentPanel(),
    ];
  },
};
