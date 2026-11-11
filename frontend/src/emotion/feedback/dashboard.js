import { computed, h, ref, watch } from 'vue';
import { defaultFilters, read, scoped, useResource } from './client.js';
import { filterFields } from './queue.js';
import { FeedbackAdjustmentReport } from './adjustment-report.js';
import { FeedbackWorkload } from './workload.js';
import {
  actions, badge, button, date, empty, field, keyValues, notice, option, recordList,
  section, select, submit, table,
} from './ui.js';

const staffBuckets = [
  ['new', '待确认', '老师还未确认收到的反馈。', { state: 'NEW' }],
  ['overdue', '确认已逾期', '已超过课程设置的确认时限。', { overdue: true }],
  ['reply', '正在处理', '已开始处理或已收到学生补充的反馈。', { state: 'IN_PROGRESS' }],
  ['review', '回访已逾期', '已超过期望答复日期的回访。', { review_overdue: true }],
  ['high_priority', '优先处理', '由教师标记为优先的进行中反馈。', { priority: 'HIGH', active_only: true }],
];

const studentBuckets = [
  ['reply', '老师请你补充', '老师正在等待你提供更多课堂细节。', { state: 'WAITING_STUDENT' }],
  ['review', '等待你的回访', '告诉老师教学调整有没有帮助。', { state: 'WAITING_REVIEW' }],
];

function hours(value) {
  if (value === null || value === undefined) return '—';
  if (value < 1) return Math.round(value * 60) + ' 分钟';
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) + ' 小时';
}

function percent(value) {
  return value === null || value === undefined ? '—' : value + '%';
}

export const FeedbackTodos = {
  props: ['catalog', 'staff', 'selection', 'expired', 'revision'],
  emits: ['filter', 'open', 'create'],
  setup(props, { emit }) {
    const todos = useResource((signal, selection) => read('/todos', selection, signal), props.expired);
    const selected = ref(props.staff ? 'new' : 'review');

    function reload() {
      return todos.load(scoped(props.selection));
    }

    watch(() => [props.selection, props.revision], reload, { immediate: true });

    function buckets() {
      return props.staff ? staffBuckets : studentBuckets;
    }

    function detail(data) {
      const entry = buckets().find(([key]) => key === selected.value);
      const [key, title, description, filters] = entry;
      const value = data.buckets[key];
      return section(title, [
        h('p', { class: 'ef-meta' }, description),
        value.items.length
          ? recordList(value.items, props.catalog, id => {
            const tab = key === 'review' ? 'reviews' : key === 'reply' ? 'conversation' : 'workflow';
            emit('open', id, tab);
          })
          : empty('这类待办已清空'),
        value.count > value.items.length && h('p', { class: 'ef-meta' },
          '这里显示最早的 ' + value.items.length + ' 条，列表中可查看对应范围。',
        ),
      ], value.count > 0 && button('打开对应列表', () => emit('filter', filters)));
    }

    return () => {
      const data = todos.value.value;
      return [
        section('反馈待办', [
          notice(todos.error.value),
          todos.loading.value && notice('正在读取待办…', 'info'),
          data && h('div', { class: 'ef-metrics' }, buckets().map(([key, title]) => h('button', {
            key,
            type: 'button',
            class: ['ef-metric', selected.value === key && 'ef-selected'],
            'aria-pressed': selected.value === key,
            onClick: () => { selected.value = key; },
          }, [
            h('span', title),
            h('strong', data.buckets[key].count),
          ]))),
          data && h('p', { class: 'ef-meta' }, '更新于 ' + date(data.generated_at)),
        ], actions(
          button('刷新待办', reload, { disabled: todos.loading.value }),
          !props.staff && button('提交新反馈', () => emit('create'), { primary: true }),
        )),
        data && detail(data),
      ];
    };
  },
};

function metrics(items) {
  return h('div', { class: 'ef-metrics' }, items.map(([name, value, hint]) => h('div', {
    key: name,
    class: 'ef-metric',
  }, [
    h('span', name),
    h('strong', value),
    hint && h('small', hint),
  ])));
}

function distribution(rows, selectRow) {
  if (!rows.some(item => item.count)) return empty('暂无可统计的数据');
  return h('ul', { class: 'ef-bars' }, rows.map(item => h('li', { key: item.value }, [
    selectRow
      ? button(item.label, () => selectRow(item.value), { class: 'ef-link', disabled: !item.count })
      : h('span', item.label),
    h('div', { class: 'ef-bar-track', 'aria-hidden': 'true' }, [
      h('div', { class: 'ef-bar-fill', style: { width: item.percent + '%' } }),
    ]),
    h('span', item.count + ' 条 · ' + item.percent + '%'),
  ])));
}

function trend(rows) {
  if (!rows.some(item => item.created || item.resolved)) return empty('所选日期内暂无新增或结案');
  const peak = Math.max(1, ...rows.map(item => Math.max(item.created, item.resolved)));
  return [
    actions(badge('新增'), badge('结案', 'good')),
    h('div', { class: 'ef-trend-scroll' }, [
      h('div', {
        class: 'ef-trend',
        role: 'img',
        'aria-label': '各日新增和结案数量，详细数据见表格',
        style: { '--ef-days': rows.length },
      }, rows.map(item => h('div', {
        key: item.date,
        class: 'ef-trend-day',
        title: item.date + ' · 新增 ' + item.created + ' · 结案 ' + item.resolved,
      }, [
        h('div', { class: 'ef-trend-pair' }, [
          h('div', { class: 'ef-new-bar', style: { height: 100 * item.created / peak + '%' } }),
          h('div', { class: 'ef-done-bar', style: { height: 100 * item.resolved / peak + '%' } }),
        ]),
        h('span', item.date.slice(5)),
      ]))),
    ]),
    h('details', { class: 'ef-disclosure' }, [
      h('summary', '查看逐日数据'),
      table(['日期（UTC）', '新增反馈', '结案反馈'], rows.map(item => ({
        id: item.date,
        cells: [item.date, item.created, item.resolved],
      }))),
    ]),
  ];
}

function compareSessions(items, onFilter, onNavigate) {
  if (!items.length) return empty('当前范围内没有课堂反馈');
  return table(['课堂', '反馈', '进行中', '学生确认改善', '回访答复', '首次回应中位数', '查看'], items.map(item => ({
    id: item.session_id,
    cells: [
      h('div', [
        h('strong', item.course_name + ' · ' + item.class_name),
        h('p', { class: 'ef-meta' }, date(item.starts_at)),
      ]),
      item.total,
      item.active,
      item.confirmed,
      item.reviews.answered + ' / ' + item.reviews.denominator,
      hours(item.response_median_hours),
      actions(
        button('反馈', () => onFilter({ course_id: item.course_id, session_id: item.session_id })),
        button('情绪回放', () => onNavigate({ tab: 'replay', sessionId: item.session_id })),
      ),
    ],
  })));
}

function reasonTable(items, onFilter) {
  const visible = items.filter(item => item.count);
  if (!visible.length) return empty('暂无课堂原因可统计');
  return table(['课堂原因', '涉及反馈', '待处理', '已结案', '学生确认改善', '回访答复'], visible.map(item => ({
    id: item.reason,
    cells: [
      button(item.label, () => onFilter({ reason: item.reason }), { class: 'ef-link' }),
      item.count,
      item.active,
      item.resolved,
      item.confirmed,
      item.reviews.answered + ' / ' + item.reviews.denominator,
    ],
  })), '一条反馈可包含多个原因。');
}

export const FeedbackReports = {
  props: ['catalog', 'staff', 'selection', 'revision', 'expired'],
  emits: ['open', 'filter', 'navigate'],
  setup(props, { emit }) {
    const days = ref(14);
    const applied = ref(scoped(props.selection));
    const values = ref({ ...applied.value });
    const panel = ref('summary');
    const report = useResource((signal, selection, period) => read('/dashboard', {
      ...selection, days: period,
    }, signal), props.expired);

    function load() {
      return report.load(applied.value, days.value);
    }

    watch(() => props.selection, value => {
      applied.value = scoped(value);
      values.value = { ...applied.value };
      load();
    }, { immediate: true });
    watch(() => props.revision, load);

    function submitFilter(event) {
      event.preventDefault();
      applied.value = scoped(values.value);
      load();
    }

    function openFilters(extra) {
      emit('filter', { ...defaultFilters(), ...applied.value, ...extra });
    }

    const currentScope = computed(() => {
      const selected = props.catalog.courses.find(item => item.id === applied.value.course_id);
      return selected?.name || '全部可见课程';
    });

    function summary(data) {
      return [
        metrics([
          ['反馈总量', data.total, data.real_count + ' 条真实 · ' + data.demo_count + ' 条演示'],
          ['进行中', data.active, data.waiting_student + ' 条等待学生'],
          ['已结案', data.resolved, data.staff_closed + ' 条由教师说明后关闭'],
          ['学生确认改善', data.confirmed_improved, '来自学生已答复的回访'],
        ]),
        section('确认与处理耗时', keyValues([
          ['确认中位数', hours(data.response.acknowledgement_median_hours) + '（' + data.response.acknowledgement_samples + ' 条）'],
          ['首次回应中位数', hours(data.response.response_median_hours) + '（' + data.response.response_samples + ' 条）'],
          ['结案中位数', hours(data.response.resolution_median_hours) + '（' + data.response.resolution_samples + ' 条）'],
          ['确认逾期', data.acknowledgement_overdue + ' 条'],
        ])),
        section('反馈进度', distribution(data.states, state => openFilters({ state }))),
        section('每天的新增与结案', trend(data.timeline)),
        data.oldest_active.length > 0 && section('等待时间最长的进行中反馈', recordList(
          data.oldest_active, props.catalog, id => emit('open', id),
        )),
      ];
    }

    function review(data) {
      const values = data.reviews;
      return [
        metrics([
          ['已发起回访', values.total, values.cancelled + ' 轮已取消'],
          ['回访答复率', percent(values.answer_rate), values.answered + ' / ' + values.denominator + ' 轮'],
          ['已答复中改善比例', percent(values.helped_rate), values.helped + ' / ' + values.answered + ' 轮'],
          ['待答复', values.open, values.overdue + ' 轮逾期'],
        ]),
        section('学生答复结果', keyValues([
          ['已改善', values.helped],
          ['部分改善', values.partly],
          ['仍未改善', values.unchanged],
        ])),
        section('结案依据', keyValues([
          ['学生确认改善', data.confirmed_improved],
          ['老师说明后关闭', data.staff_closed],
          ['学生撤回', data.withdrawn],
        ])),
        h('p', { class: 'ef-meta' }, '答复率以未取消的回访轮次为分母。改善比例以已答复的回访轮次为分母。'),
      ];
    }

    function content(data) {
      if (panel.value === 'summary') return summary(data);
      if (panel.value === 'reviews') return review(data);
      if (panel.value === 'adjustments') return h(FeedbackAdjustmentReport, {
        catalog: props.catalog, selection: applied.value, expired: props.expired,
        onOpen: id => emit('open', id), onNavigate: target => emit('navigate', target),
      });
      if (panel.value === 'workload') return h(FeedbackWorkload, {
        catalog: props.catalog, selection: applied.value, expired: props.expired,
        onOpen: id => emit('open', id), onFilter: openFilters,
      });
      if (panel.value === 'classes') return section('按课堂查看', compareSessions(data.sessions, openFilters, value => emit('navigate', value)));
      return [
        section('课堂原因', reasonTable(data.reasons, openFilters)),
        section('反馈中的情绪', distribution(data.emotions, emotion => openFilters({ emotion }))),
        section('学习影响程度', distribution(data.impacts)),
      ];
    }

    return () => {
      const data = report.value.value;
      return [
        section('反馈处理统计', [
          h('form', { class: 'ef-form', onSubmit: submitFilter }, [
            filterFields(props.catalog, values.value, (key, value) => { values.value[key] = value; }, { compact: true }),
            field('趋势跨度', select(days.value, [
              option(7, '最近 7 天'), option(14, '最近 14 天'), option(30, '最近 30 天'), option(90, '最近 90 天'),
            ], value => { days.value = Number(value); })),
            actions(submit('更新统计', report.loading.value)),
          ]),
          notice(report.error.value),
          report.loading.value && notice('正在统计反馈…', 'info'),
          data && h('p', { class: 'ef-meta' }, currentScope.value + ' · 统计于 ' + date(data.generated_at)),
          data && h('nav', { class: 'ef-tabs', 'aria-label': '统计视图' }, [
            ['summary', '处理进度'],
            ['reasons', '课堂原因与情绪'],
            ['reviews', '回访结果'],
            ...(props.staff ? [['classes', '课堂对比'], ['adjustments', '教学调整'], ['workload', '处理量与时限']] : []),
          ].map(([key, title]) => button(title, () => { panel.value = key; }, {
            key, 'aria-pressed': panel.value === key,
          }))),
        ]),
        data && content(data),
      ];
    };
  },
};
