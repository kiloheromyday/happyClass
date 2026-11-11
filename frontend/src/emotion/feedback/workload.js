import { computed, h, onBeforeUnmount, ref, watch } from 'vue';
import { downloadCsv } from '../../api.js';
import { read, scoped, url, useResource } from './client.js';
import { filterFields } from './queue.js';
import {
  actions, all, badge, button, date, empty, field, input, keyValues, notice,
  option, recordList, section, select, submit, table,
} from './ui.js';

const activityRows = [
  ['acknowledgements', '手动确认'],
  ['starts', '开始处理'],
  ['questions', '请学生补充'],
  ['resolutions', '教师说明后关闭'],
  ['reopened', '学生请求继续跟进'],
  ['reviews', '发起回访'],
  ['answers', '收到回访答复'],
  ['reminders', '发送回访提醒'],
];

const summaryRows = [
  ['total', '提交反馈'],
  ['active', '目前进行中'],
  ['waiting_staff', '目前待教师处理'],
  ['waiting_student', '目前待学生'],
  ['closed', '目前已结案'],
  ['confirmed', '学生确认改善'],
  ['staff_closed', '教师说明后关闭'],
  ['demo', '其中演示反馈'],
];

function periodName(period) {
  return period.start_date + ' 至 ' + period.end_date;
}

function displayRate(value) {
  return value === null ? '—' : value + '%';
}

function duration(value, samples) {
  if (!samples || value === null) return '—';
  if (value < 1) return Math.round(value * 60) + ' 分钟 · ' + samples + ' 条';
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) + ' 小时 · ' + samples + ' 条';
}

function delta(a, b) {
  const value = a - b;
  if (value === 0) return '0';
  return value > 0 ? '+' + value : String(value);
}

function cohortTable(data) {
  const current = data.current.summary;
  const previous = data.previous.summary;
  return table(['提交区间与处理状态', '本期', '上期', '变化'], summaryRows.map(([key, title]) => ({
    id: key,
    cells: [title, current[key], previous[key], delta(current[key], previous[key])],
  })), '按提交日期分组。表中的处理状态取统计生成时的最新状态。');
}

function serviceTable(data) {
  const a = data.current.summary;
  const b = data.previous.summary;
  return table(['确认状态', '本期提交', '上期提交'], [
    ...Object.entries(data.service_labels).map(([key, title]) => ({
      id: key,
      cells: [title, a.service_counts[key], b.service_counts[key]],
    })),
    {
      id: 'rate',
      cells: [
        '按时确认率',
        displayRate(a.on_time_rate) + '（' + a.service_decided + ' 条计入）',
        displayRate(b.on_time_rate) + '（' + b.service_decided + ' 条计入）',
      ],
    },
  ], '按课程当前的确认时限计算。尚未到期和确认前撤回的反馈不计入按时率。');
}

function activityTable(data) {
  return table(['处理动作', '本期发生', '上期发生', '变化'], activityRows.map(([key, title]) => {
    const current = data.current.activity[key];
    const previous = data.previous.activity[key];
    return {
      id: key,
      cells: [title, current, previous, delta(current, previous)],
    };
  }), '按动作实际发生的日期统计，包含此前提交的反馈。');
}

function responseCards(data) {
  const current = data.current.summary.response;
  const previous = data.previous.summary.response;
  return table(['耗时中位数', '本期提交', '上期提交'], [
    ['acknowledgement', '确认收到'],
    ['response', '首次回应'],
    ['resolution', '结案'],
  ].map(([key, title]) => ({
    id: key,
    cells: [
      title,
      duration(current[key + '_median_hours'], current[key + '_samples']),
      duration(previous[key + '_median_hours'], previous[key + '_samples']),
    ],
  })), '耗时从提交算起，只统计已经完成这一步的反馈。');
}

const courseSorts = [
  option('volume', '本期提交较多在前'),
  option('overdue', '确认逾期较多在前'),
  option('waiting', '待教师较多在前'),
];

const CourseBreakdown = {
  props: ['items'],
  emits: ['filter'],
  setup(props, { emit }) {
    const course = ref('');
    const sort = ref('volume');
    const visible = computed(() => {
      const rows = props.items.filter(item => !course.value || String(item.course_id) === course.value);
      if (sort.value === 'overdue') {
        rows.sort((a, b) => b.current.service_counts.OVERDUE - a.current.service_counts.OVERDUE || b.current.total - a.current.total);
      } else if (sort.value === 'waiting') {
        rows.sort((a, b) => b.current.waiting_staff - a.current.waiting_staff || b.current.total - a.current.total);
      }
      return rows;
    });

    function controls() {
      return h('div', { class: 'ef-grid' }, [
        field('在结果中查找课程', select(course.value, [
          all('全部课程'), ...props.items.map(item => option(item.course_id, item.course_name)),
        ], value => { course.value = value; })),
        field('结果排序', select(sort.value, courseSorts, value => { sort.value = value; })),
      ]);
    }

    return () => section('按课程核对', [
      controls(),
      visible.value.length
        ? table([
          '课程', '确认时限', '提交（本期 / 上期）', '待教师', '逾期未确认', '按时率（本期 / 上期）', '反馈',
        ], visible.value.map(item => ({
          id: item.course_id,
          cells: [
            h('strong', item.course_name),
            item.target_hours + ' 小时',
            item.current.total + ' / ' + item.previous.total,
            item.current.waiting_staff,
            item.current.service_counts.OVERDUE,
            displayRate(item.current.on_time_rate) + ' / ' + displayRate(item.previous.on_time_rate),
            button('打开课程反馈', () => emit('filter', { course_id: item.course_id, session_id: null })),
          ],
        })))
        : empty('当前区间暂无课程数据'),
    ]);
  },
};

export const FeedbackWorkload = {
  props: ['catalog', 'selection', 'expired'],
  emits: ['open', 'filter'],
  setup(props, { emit }) {
    const defaults = () => ({
      ...scoped(props.selection),
      period_days: 7,
      period_end: '',
    });
    const values = ref(defaults());
    const applied = ref(defaults());
    const view = ref('comparison');
    const exportStatus = ref('');
    const exportBusy = ref(false);
    let controller;
    const resource = useResource((signal, values) => read('/workload', values, signal), props.expired);
    const maxDate = new Date().toISOString().slice(0, 10);

    onBeforeUnmount(() => controller?.abort());

    function load() {
      resource.load(applied.value);
    }

    watch(() => props.selection, () => {
      values.value = { ...values.value, ...scoped(props.selection) };
      applied.value = { ...applied.value, ...scoped(props.selection) };
      load();
    }, { immediate: true });

    function update(event) {
      event.preventDefault();
      applied.value = { ...values.value };
      exportStatus.value = '';
      load();
    }

    async function download() {
      if (exportBusy.value) {
        controller.abort();
        return;
      }
      controller = new AbortController();
      exportBusy.value = true;
      exportStatus.value = '';
      try {
        const count = await downloadCsv(url('/workload/export.csv', applied.value), controller.signal);
        exportStatus.value = '已导出 ' + count + ' 条课程区间汇总。';
      } catch (error) {
        if (!controller.signal.aborted) {
          if (error.status === 401) props.expired?.();
          else exportStatus.value = error.message;
        }
      } finally {
        exportBusy.value = false;
      }
    }

    function controls() {
      return h('form', { class: 'ef-form', onSubmit: update }, [
        filterFields(props.catalog, values.value, (key, value) => { values.value[key] = value; }, { compact: true }),
        h('div', { class: 'ef-grid' }, [
          field('每期长度', select(values.value.period_days, [
            option(7, '7 天'), option(14, '14 天'), option(30, '30 天'), option(60, '60 天'),
          ], value => { values.value.period_days = Number(value); })),
          field('统计截止日期（UTC）', input(values.value.period_end, value => { values.value.period_end = value; }, {
            type: 'date', max: maxDate,
          }), '留空时统计到今天。上期取相邻的同等天数。'),
        ]),
        actions(
          submit('更新区间', resource.loading.value),
          button('恢复默认区间', () => {
            values.value = defaults();
            applied.value = defaults();
            load();
          }),
        ),
      ]);
    }

    function overdue(data) {
      const items = data.overdue.items;
      return section('本期提交且逾期未确认', [
        items.length
          ? recordList(items, props.catalog, id => emit('open', id), item =>
            h('p', { class: 'ef-meta' }, '确认截止于 ' + date(item.target_at)),
          )
          : empty('本期没有逾期未确认的反馈'),
        data.overdue.total > items.length && h('p', { class: 'ef-meta' },
          '显示最早到期的 ' + items.length + ' 条，共 ' + data.overdue.total + ' 条。',
        ),
      ], badge(data.overdue.total + ' 条'));
    }

    function body(data) {
      if (view.value === 'service') return [
        section('确认时限对照', serviceTable(data)),
        overdue(data),
      ];
      if (view.value === 'activity') return [
        section('处理动作', activityTable(data)),
        section('完成各环节的耗时', responseCards(data)),
      ];
      if (view.value === 'courses') return h(CourseBreakdown, {
        items: data.courses,
        onFilter: filters => emit('filter', { ...scoped(applied.value), ...filters }),
      });
      return section('两期反馈进度', cohortTable(data));
    }

    return () => {
      const data = resource.value.value;
      return [
        section('处理量与确认时限', [
          controls(),
          notice(resource.error.value),
          notice(exportStatus.value, 'info'),
          resource.loading.value && notice('正在汇总两个统计区间…', 'info'),
          data && keyValues([
            ['本期', periodName(data.current)],
            ['上期', periodName(data.previous)],
            ['统计生成时间', date(data.generated_at)],
          ]),
          data && h('nav', { class: 'ef-tabs', 'aria-label': '处理量统计视图' }, [
            ['comparison', '进度对照'],
            ['service', '确认时限'],
            ['activity', '处理动作'],
            ['courses', '按课程查看'],
          ].map(([key, title]) => button(title, () => { view.value = key; }, {
            key, 'aria-pressed': view.value === key,
          }))),
        ], button(exportBusy.value ? '取消导出' : '导出课程汇总', download, {
          disabled: !exportBusy.value && (!data?.courses.length || resource.loading.value),
        })),
        data && body(data),
      ];
    };
  },
};
