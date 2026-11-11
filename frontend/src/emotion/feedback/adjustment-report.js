import { h, onBeforeUnmount, ref, watch } from 'vue';
import { downloadCsv } from '../../api.js';
import { read, scoped, url, useResource } from './client.js';
import { filterFields } from './queue.js';
import {
  actions, badge, button, date, emotion, empty, field, keyValues, label,
  notice, option, outcomes, pager, section, select, sessionLabel, status, submit, table,
} from './ui.js';

const filters = [
  option('ALL', '全部关联反馈'),
  option('ANSWERED', '已收到调整后答复'),
  option('WAITING', '等待调整后答复'),
  option('UNREQUESTED', '尚无有效回访'),
];
const sorts = [
  option('LATEST', '最近关联在前'),
  option('WAITING', '等待跟进较多在前'),
  option('LINKS', '关联反馈较多在前'),
];
const statuses = {
  PLANNED: '计划中',
  DONE: '已完成',
  CANCELLED: '已取消',
};
const basis = '每条反馈看关联调整后发起的最后一次未取消的回访。一条反馈可能关联多项调整。';

function period(item) {
  const end = item.end_minute === null ? '' : '至第 ' + item.end_minute + ' 分钟';
  return '课堂第 ' + item.start_minute + ' 分钟' + end;
}

const AdjustmentDetails = {
  props: ['id', 'scope', 'catalog', 'expired'],
  emits: ['back', 'open', 'navigate'],
  setup(props, { emit }) {
    const selection = ref('ALL');
    const resource = useResource((signal, value, offset) => read('/adjustment-report/' + props.id, {
      ...props.scope, followup: value, offset, limit: 15,
    }, signal), props.expired);

    function load(offset = 0) {
      resource.load(selection.value, offset);
    }
    watch(selection, () => load(), { immediate: true });

    function evidence(item) {
      const followup = item.followup;
      const feedback = item.case;
      return h('li', { key: feedback.id }, [
        h('div', { class: 'ef-list-row' }, [
          button(feedback.title, () => emit('open', feedback.id), { class: 'ef-link' }),
          actions(status(feedback), badge(followup.label), feedback.is_demo && badge('演示')),
        ]),
        h('p', { class: 'ef-meta' }, feedback.number + ' · 关联于 ' + date(followup.linked_at)),
        h('p', { class: 'ef-text' }, followup.public_summary),
        followup.outcome && keyValues([
          ['回访答复', label(outcomes, followup.outcome)],
          ['答复时间', date(followup.answered_at)],
          ['原反馈情绪', emotion(props.catalog, followup.original_emotion)],
          ['回访情绪', emotion(props.catalog, followup.review_emotion)],
        ]),
        followup.status === 'WAITING' && h('p', { class: 'ef-meta' }, '期望答复于 ' + date(followup.due_at)),
        actions(button('查看完整反馈', () => emit('open', feedback.id))),
      ]);
    }

    return () => {
      const page = resource.value.value;
      const item = page?.adjustment;
      return [
        actions(
          button('返回调整统计', () => emit('back')),
          item && button('查看课堂洞察', () => emit('navigate', { tab: 'insights', sessionId: item.session_id })),
          button('刷新关联反馈', () => load(page?.offset), { disabled: resource.loading.value }),
        ),
        notice(resource.error.value),
        resource.loading.value && notice('正在读取调整后的反馈…', 'info'),
        item && section(item.title, [
          h('p', { class: 'ef-meta' }, sessionLabel(item) + ' · ' + period(item)),
          keyValues([
            ['关联反馈', item.linked_count],
            ['进行中', item.active_count],
            ['收到调整后答复', item.answered],
            ['仍待答复', item.waiting],
            ['尚无有效回访', item.unrequested],
            ['学生确认改善结案', item.student_confirmed_count],
          ]),
          h('p', { class: 'ef-meta' }, basis),
          field('按回访进度筛选', select(selection.value, filters, value => { selection.value = value; })),
          page.items.length
            ? h('ul', { class: 'ef-list' }, page.items.map(evidence))
            : empty('没有符合条件的关联反馈'),
          pager(page, resource.loading.value, load),
        ], badge(statuses[item.adjustment_status] || item.adjustment_status)),
      ];
    };
  },
};

export const FeedbackAdjustmentReport = {
  props: ['catalog', 'selection', 'expired'],
  emits: ['open', 'navigate'],
  setup(props, { emit }) {
    const initial = { ...scoped(props.selection), adjustment_sort: 'LATEST' };
    const filters = ref({ ...initial });
    const applied = ref({ ...initial });
    const inspected = ref(null);
    const exportBusy = ref(false);
    const exportStatus = ref('');
    let download;
    const resource = useResource((signal, selection, offset) => read('/adjustment-report', {
      ...selection, offset, limit: 15,
    }, signal), props.expired);

    function load(offset = 0) {
      return resource.load(applied.value, offset);
    }
    load();
    onBeforeUnmount(() => download?.abort());

    function apply(event) {
      event.preventDefault();
      applied.value = { ...filters.value };
      load();
    }

    async function exportData() {
      if (exportBusy.value) {
        download.abort();
        return;
      }
      download = new AbortController();
      exportBusy.value = true;
      exportStatus.value = '';
      try {
        const count = await downloadCsv(url('/adjustment-report/export.csv', applied.value), download.signal);
        exportStatus.value = '已导出 ' + count + ' 项调整的统计。';
      } catch (failure) {
        if (!download.signal.aborted) {
          if (failure.status === 401) props.expired?.();
          else exportStatus.value = failure.message;
        }
      } finally {
        exportBusy.value = false;
      }
    }

    function summary(data) {
      return keyValues([
        ['教学调整', data.adjustments],
        ['关联条次', data.links],
        ['有答复的关联', data.answered_links],
        ['等待答复的关联', data.waiting_links],
        ['尚无有效回访的关联', data.unrequested_links],
      ]);
    }

    function reportTable(items) {
      return table([
        '教学调整', '关联反馈', '调整后答复', '等待中', '尚无回访',
        '已改善 / 部分改善 / 未改善', '查看',
      ], items.map(item => ({
        id: item.id,
        cells: [
          h('div', [
            h('strong', item.title),
            h('p', { class: 'ef-meta' }, sessionLabel(item)),
            actions(badge(statuses[item.adjustment_status]), item.demo_count > 0 && badge('含演示')),
          ]),
          item.linked_count,
          item.answered,
          item.waiting,
          item.unrequested,
          [item.helped, item.partly, item.unchanged].join(' / '),
          button('查看关联反馈', () => { inspected.value = item.id; }),
        ],
      })));
    }

    function controls() {
      return h('form', { class: 'ef-form', onSubmit: apply }, [
        filterFields(props.catalog, filters.value, (key, value) => { filters.value[key] = value; }, { compact: true }),
        field('排序', select(filters.value.adjustment_sort, sorts, value => { filters.value.adjustment_sort = value; })),
        actions(submit('更新调整统计', resource.loading.value)),
      ]);
    }

    return () => {
      if (inspected.value) return h(AdjustmentDetails, {
        id: inspected.value, scope: applied.value, catalog: props.catalog, expired: props.expired,
        onBack: () => { inspected.value = null; },
        onOpen: id => emit('open', id),
        onNavigate: target => emit('navigate', target),
      });
      const page = resource.value.value;
      return section('教学调整跟进', [
        controls(),
        h('p', { class: 'ef-meta' }, basis),
        notice(resource.error.value),
        notice(exportStatus.value, 'info'),
        resource.loading.value && notice('正在汇总关联反馈…', 'info'),
        page && summary(page.totals),
        page?.items.length
          ? reportTable(page.items)
          : !resource.loading.value && empty('这里还没有关联的教学调整', '可在反馈详情中关联本课堂的教学调整。'),
        pager(page, resource.loading.value, load),
      ], button(exportBusy.value ? '取消导出' : '导出调整统计', exportData, {
        disabled: !exportBusy.value && !page?.total,
      }));
    };
  },
};
