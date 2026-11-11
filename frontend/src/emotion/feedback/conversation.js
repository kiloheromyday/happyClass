import { h, ref, watch } from 'vue';
import { read, useCommand, useDraft, useResource } from './client.js';
import {
  actions, all, badge, button, casePath, date, empty, field, notice, option, section,
  select, submit, textarea,
} from './ui.js';

export const FeedbackConversation = {
  props: ['item', 'staff', 'expired'],
  emits: ['dirty', 'changed'],
  setup(props, { emit }) {
    const command = useCommand(props.expired);
    const initial = { content: '', visibility: 'SHARED', template_id: null };
    const draft = useDraft(initial, value => emit('dirty', value), command.busy);
    const editing = ref(null);
    const filter = ref('ALL');
    const messages = ref([]);
    const page = ref(null);
    const feedback = ref('');
    const thread = useResource((signal, before) => read(casePath(props.item.id) + '/messages', {
      before_id: before,
    }, signal), props.expired);
    const templates = useResource(signal => read('/templates', {}, signal), props.expired);

    async function load(before = null) {
      const result = await thread.load(before);
      if (!result) return;
      page.value = result;
      messages.value = before ? [...result.items, ...messages.value] : result.items;
    }

    watch(() => props.item.version, () => load(), { immediate: true });
    if (props.staff) templates.load();

    function reset() {
      editing.value = null;
      draft.restore(initial);
      command.reset();
    }

    function edit(item) {
      if (draft.dirty.value || command.busy.value) return;
      editing.value = item;
      draft.restore({ content: item.content, visibility: item.visibility, template_id: null });
      command.reset();
      feedback.value = '';
    }

    function applyTemplate(value) {
      const template = templates.value.value?.items.find(item => item.id === Number(value));
      if (!template) {
        draft.values.template_id = null;
        return;
      }
      if (draft.values.content.trim() && !window.confirm('用这个模板替换当前回应草稿？')) return;
      draft.values.content = template.content;
      draft.values.template_id = template.id;
      draft.values.visibility = 'SHARED';
    }

    async function send(event) {
      event.preventDefault();
      const content = draft.values.content.trim();
      if (!content || !props.item.capabilities.reply) return;
      const original = editing.value;
      const path = casePath(props.item.id) + '/messages';
      const result = original
        ? await command.run(path + '/' + original.id, {
          version: original.version, content,
        }, { method: 'PUT' })
        : await command.run(path, {
          content,
          visibility: draft.values.visibility,
          template_id: draft.values.visibility === 'SHARED' ? draft.values.template_id : null,
        });
      if (!result) return;
      reset();
      feedback.value = original ? '交流记录已修订。' : '回应已发送。';
      emit('changed');
    }

    async function remove(item) {
      if (!window.confirm('撤回这条交流记录？')) return;
      const result = await command.run(casePath(props.item.id) + '/messages/' + item.id + '/withdraw', {
        version: item.version,
      });
      if (!result) return;
      if (editing.value?.id === item.id) reset();
      feedback.value = '交流记录已撤回。';
      emit('changed');
    }

    async function reloadEditing() {
      const previous = editing.value;
      await load();
      if (!previous || thread.error.value) return;
      const latest = messages.value.find(item => item.id === previous.id);
      if (latest?.can_edit && window.confirm('记录已有更新。保留草稿，并以最新版本继续编辑？')) {
        editing.value = latest;
        command.reset();
      }
    }

    function card(item) {
      const revised = !item.deleted && item.updated_at !== item.created_at;
      return h('li', {
        key: item.id,
        class: ['ef-message', item.visibility === 'STAFF' && 'ef-internal'],
      }, [
        h('header', { class: 'ef-list-row' }, [
          actions(
            h('strong', item.actor),
            item.visibility === 'STAFF' && badge('教师内部备注', 'waiting'),
            revised && badge('已修订'),
          ),
          h('time', { datetime: item.created_at }, date(item.created_at)),
        ]),
        h('p', { class: item.deleted ? 'ef-meta' : 'ef-text' }, item.deleted ? '这条消息已撤回。' : item.content),
        item.can_edit && props.item.capabilities.reply && actions(
          button('修订', () => edit(item), { disabled: draft.dirty.value || command.busy.value }),
          button('撤回消息', () => remove(item), { disabled: command.busy.value }),
        ),
      ]);
    }

    function form() {
      const note = draft.values.visibility === 'STAFF';
      const options = templates.value.value?.items || [];
      return h('form', { class: 'ef-form', onSubmit: send }, [
        props.staff && !editing.value && field('回应可见范围', select(draft.values.visibility, [
          option('SHARED', '发送给学生'),
          option('STAFF', '教师内部备注'),
        ], value => {
          draft.values.visibility = value;
          if (value === 'STAFF') draft.values.template_id = null;
        })),
        props.staff && !note && !editing.value && options.length > 0 && field('使用我的回应模板', select(
          draft.values.template_id,
          [all('手动撰写'), ...options.map(item => option(item.id, item.title))],
          applyTemplate,
        )),
        props.staff && templates.error.value && actions(
          h('span', { class: 'ef-meta' }, '回应模板暂不可用。'),
          button('重试读取模板', () => templates.load()),
        ),
        field(editing.value ? '修订内容' : note ? '教师内部备注' : '回复内容',
          textarea(draft.values.content, value => { draft.values.content = value; }, {
            required: true,
            placeholder: note ? '记录后续处理安排' : '写下你的回应',
          }),
          (note ? '学生不可见。' : '这条交流仅在本反馈单中展示。') + ' ' + draft.values.content.length + ' / 2000',
        ),
        actions(
          submit(editing.value ? '保存修订' : note ? '保存内部备注' : '发送回应', command.busy.value || !draft.values.content.trim()),
          (draft.dirty.value || editing.value) && button('放弃编辑', reset, { disabled: command.busy.value }),
        ),
      ]);
    }

    return () => {
      const visible = messages.value.filter(item => filter.value === 'ALL' || item.visibility === filter.value);
      return section('反馈交流', [
        props.staff && field('记录类型', select(filter.value, [
          option('ALL', '全部记录'),
          option('SHARED', '与学生交流'),
          option('STAFF', '内部备注'),
        ], value => { filter.value = value; })),
        notice(thread.error.value || command.error.value),
        notice(feedback.value, 'good'),
        command.conflict.value && button('刷新并核对记录', reloadEditing),
        thread.loading.value && h('p', { role: 'status' }, '正在读取交流记录…'),
        page.value?.has_more && button('加载更早的交流', () => load(page.value.next_before_id), { disabled: thread.loading.value }),
        visible.length ? h('ul', { class: 'ef-list' }, visible.map(card)) : empty('暂无交流记录'),
        props.item.capabilities.reply ? form() : [
          h('p', { class: 'ef-meta' }, '反馈已结束。'),
          draft.dirty.value && section('尚未发送的草稿', [
            h('p', { class: 'ef-text' }, draft.values.content),
            button('清空草稿', reset),
          ]),
        ],
      ], button('刷新交流', () => load(), { disabled: thread.loading.value }));
    };
  },
};

export const FeedbackHistory = {
  props: ['item', 'catalog', 'expired'],
  setup(props) {
    const history = useResource((signal, before) => read(casePath(props.item.id) + '/events', {
      before_id: before,
    }, signal), props.expired);
    const events = ref([]);
    async function load(before = null) {
      const next = await history.load(before);
      if (next) events.value = before ? [...events.value, ...next.items] : next.items;
    }
    watch(() => props.item.version, () => load(), { immediate: true });
    function state(value) {
      return props.catalog.states.find(item => item.value === value)?.label || value;
    }
    return () => section('处理时间线', [
      notice(history.error.value),
      history.loading.value && h('p', { role: 'status' }, '正在读取处理记录…'),
      h('ol', { class: 'ef-timeline' }, events.value.map(item => h('li', { key: item.id }, [
        h('div', { class: 'ef-list-row' }, [
          h('strong', item.title),
          h('time', { datetime: item.created_at }, date(item.created_at)),
        ]),
        actions(
          badge(item.actor),
          item.visibility === 'STAFF' && badge('内部记录'),
          item.from_state !== item.to_state && badge(state(item.from_state) + ' → ' + state(item.to_state)),
        ),
        item.detail && h('p', { class: 'ef-text' }, item.detail),
      ]))),
      history.value.value?.has_more && button('查看更多处理记录', () => load(history.value.value.next_before_id), {
        disabled: history.loading.value,
      }),
    ], button('刷新记录', () => load(), { disabled: history.loading.value }));
  },
};
