import { computed, h, ref, watch } from 'vue';
import { read, scoped, useCommand, useResource } from './client.js';
import { filterFields } from './queue.js';
import {
  actions, badge, button, date, empty, field, label, notice, option,
  outcomes, pager, section, select, submit, table,
} from './ui.js';

const states = [
  option('OPEN', '待答复'),
  option('OVERDUE', '已逾期'),
  option('ANSWERED', '已答复'),
  option('CANCELLED', '已取消'),
  option('ALL', '全部轮次'),
];
const sorts = [
  option('DUE', '截止时间从早到晚'),
  option('NEWEST', '最近发起在前'),
];
const dateLabel = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'full' });

function groupsByDue(items) {
  const groups = new Map();
  for (const item of items) {
    const day = dateLabel.format(new Date(item.due_at));
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day).push(item);
  }
  return [...groups.entries()];
}

export const FeedbackReviewDesk = {
  props: ['catalog', 'staff', 'selection', 'revision', 'expired', 'initialStatus'],
  emits: ['open', 'changed', 'dirty'],
  setup(props, { emit }) {
    const values = ref({
      ...scoped(props.selection),
      status: props.initialStatus || 'OPEN',
      review_sort: 'DUE',
    });
    const applied = ref({ ...values.value });
    const display = ref('schedule');
    const message = ref('');
    const command = useCommand(props.expired);
    const activeReminder = ref(null);
    const resource = useResource((signal, filters, offset) => read('/review-desk', {
      ...filters, offset, limit: 20,
    }, signal), props.expired);

    const sections = computed(() => groupsByDue(resource.value.value?.items || []));
    watch(command.busy, value => emit('dirty', value), { flush: 'sync' });

    function load(offset = 0) {
      return resource.load(applied.value, offset);
    }

    function apply(event) {
      event.preventDefault();
      applied.value = { ...values.value };
      message.value = '';
      load();
    }

    watch(() => props.revision, () => load(resource.value.value?.offset || 0));
    load();

    function showStatus(item) {
      if (item.overdue) return badge('待答复 · 已逾期', 'waiting');
      if (item.outcome) return badge(label(outcomes, item.outcome), item.outcome === 'HELPED' ? 'good' : '');
      return badge(label(states, item.state));
    }

    async function remind(item) {
      if (!item.can_remind || command.busy.value) return;
      if (!window.confirm('向这位学生发送一条站内回访提醒？')) return;
      activeReminder.value = item.id;
      message.value = '';
      try {
        const result = await command.run('/reviews/' + item.id + '/remind', { version: item.version });
        if (!result) return;
        message.value = '已发送回访提醒。';
        emit('changed');
      } finally {
        activeReminder.value = null;
      }
    }

    function rowActions(item) {
      const destination = props.staff || item.state !== 'OPEN'
        ? '查看回访'
        : '填写回访';
      return actions(
        button(destination, () => emit('open', item.case_id, 'reviews'), {
          disabled: command.busy.value,
        }),
        props.staff && item.can_remind && button(activeReminder.value === item.id ? '正在提醒…' : '提醒学生', () => remind(item), {
          disabled: command.busy.value,
        }),
      );
    }

    function reminderSummary(item) {
      if (!item.reminder_count) return null;
      return h('p', { class: 'ef-meta' }, [
        '已提醒 ' + item.reminder_count + ' 次 · 最近 ' + date(item.last_reminded_at),
        item.next_reminder_at ? ' · 下次可提醒 ' + date(item.next_reminder_at) : '',
      ]);
    }

    function card(item) {
      return h('li', { key: item.id }, [
        h('div', { class: 'ef-list-row' }, [
          h('strong', item.case_title),
          actions(showStatus(item), item.is_demo && badge('演示')),
        ]),
        h('p', { class: 'ef-meta' }, item.course_name + ' · ' + item.class_name + ' · ' + item.case_state),
        h('p', { class: 'ef-text' }, item.prompt),
        h('p', { class: 'ef-meta' }, '发起于 ' + date(item.created_at) + ' · 期望答复于 ' + date(item.due_at)),
        item.answered_at && h('p', { class: 'ef-meta' }, '答复于 ' + date(item.answered_at)),
        reminderSummary(item),
        rowActions(item),
      ]);
    }

    function grid(items) {
      return table(['关联反馈', '回访问题', '期望答复时间', '状态', '操作'], items.map(item => ({
        id: item.id,
        cells: [
          h('div', [h('strong', item.case_title), h('p', { class: 'ef-meta' }, item.course_name + ' · ' + item.class_name)]),
          h('p', { class: 'ef-text' }, item.prompt),
          date(item.due_at),
          showStatus(item),
          rowActions(item),
        ],
      })));
    }

    function calendar() {
      return sections.value.map(([day, items]) => h('div', { key: day, class: 'ef-section' }, [
        h('div', { class: 'ef-list-row' }, [h('h4', day), badge(items.length + ' 轮')]),
        h('ul', { class: 'ef-list' }, items.map(card)),
      ]));
    }

    function controls() {
      return h('form', { class: 'ef-form', onSubmit: apply }, [
        filterFields(props.catalog, values.value, (key, value) => { values.value[key] = value; }, { compact: true }),
        h('div', { class: 'ef-grid' }, [
          field('回访状态', select(values.value.status, states, value => { values.value.status = value; })),
          field('排序方式', select(values.value.review_sort, sorts, value => { values.value.review_sort = value; })),
        ]),
        actions(submit('筛选回访', resource.loading.value || command.busy.value)),
      ]);
    }

    return () => {
      const page = resource.value.value;
      return section('回访日程', [
        controls(),
        notice(resource.error.value || command.error.value),
        notice(message.value, 'good'),
        resource.loading.value && notice('正在读取回访日程…', 'info'),
        page && h('p', { class: 'ef-meta' }, '共 ' + page.total + ' 轮 · 更新于 ' + date(page.generated_at)),
        page?.items.length > 0
          ? display.value === 'schedule' ? calendar() : grid(page.items)
          : !resource.loading.value && empty('没有符合条件的回访', '可调整范围或查看其他状态。'),
        pager(page, resource.loading.value || command.busy.value, load),
      ], actions(
        button('按截止日查看', () => { display.value = 'schedule'; }, { 'aria-pressed': display.value === 'schedule' }),
        button('表格', () => { display.value = 'table'; }, { 'aria-pressed': display.value === 'table' }),
        button('刷新', () => load(page?.offset), { disabled: resource.loading.value || command.busy.value }),
      ));
    };
  },
};
