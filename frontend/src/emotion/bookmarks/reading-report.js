import { computed, h, ref } from 'vue';
import {
  actions, badge, button, date, empty, field, input, keyValues, notice, option,
  section, select, table,
} from '../feedback/ui.js';
import { rangeText, sessionPath, useBookmarkResource } from './client.js';
import { useBookmarkDownload } from './download.js';

const ordering = [
  option('TIME', '按课堂分钟'),
  option('MORE_READ', '看过人数从多到少'),
  option('LESS_READ', '看过人数从少到多'),
];
const readFilters = [
  option('ALL', '全部已发布资料'),
  option('UNREAD', '当前版还没人看'),
  option('OLD', '有人只看过旧版'),
];

function rate(value) {
  return value === null ? '—' : value + '%';
}

export const ReadingReport = {
  props: ['session', 'expired'],
  emits: ['open'],
  setup(props, { emit }) {
    const endpoint = suffix => sessionPath(props.session.id, 'reading-report' + suffix);
    const resource = useBookmarkResource(() => endpoint(''), props.expired);
    const exportFile = useBookmarkDownload(props.expired);
    const sort = ref('TIME');
    const filter = ref('ALL');
    const term = ref('');
    const style = ref('cards');

    const items = computed(() => {
      const value = term.value.trim().toLowerCase();
      const matches = (resource.value.value?.items || []).filter(item => {
        if (value && !item.title.toLowerCase().includes(value)) return false;
        if (filter.value === 'UNREAD' && item.read_current) return false;
        return filter.value !== 'OLD' || item.read_older > 0;
      });
      if (sort.value === 'MORE_READ') {
        matches.sort((a, b) => b.read_current - a.read_current || a.start_minute - b.start_minute);
      } else if (sort.value === 'LESS_READ') {
        matches.sort((a, b) => a.read_current - b.read_current || a.start_minute - b.start_minute);
      }
      return matches;
    });

    resource.load();

    function download() {
      exportFile.download(endpoint('.csv'), {}, '已导出这节课的资料阅读汇总。');
    }

    function row(item) {
      return {
        id: item.id,
        cells: [
          button(item.title, () => emit('open', item.id), { class: 'ef-link' }),
          rangeText(item.start_minute, item.end_minute),
          item.read_current,
          item.read_older,
          rate(item.read_rate),
          date(item.updated_at),
        ],
      };
    }

    function card(item) {
      return h('li', { key: item.id }, [
        h('div', { class: 'ef-list-row' }, [
          button(item.title, () => emit('open', item.id), { class: 'ef-link' }),
          badge(rangeText(item.start_minute, item.end_minute)),
        ]),
        h('div', { class: 'ef-grid' }, [
          h('p', '看过当前版 ' + item.read_current + ' 人'),
          h('p', '只看过旧版 ' + item.read_older + ' 人'),
          h('p', '当前版阅读比例 ' + rate(item.read_rate)),
        ]),
        h('p', { class: 'ef-meta' }, '发布 ' + date(item.published_at) + ' · 最近更新 ' + date(item.updated_at)),
      ]);
    }

    function controls() {
      return [
        h('div', { class: 'ef-grid' }, [
          field('搜索资料标题', input(term.value, value => { term.value = value; }, {
            type: 'search', maxlength: 100,
          })),
          field('阅读情况', select(filter.value, readFilters, value => { filter.value = value; })),
          field('资料排序', select(sort.value, ordering, value => { sort.value = value; })),
        ]),
        actions(
          button('列表', () => { style.value = 'cards'; }, { 'aria-pressed': style.value === 'cards' }),
          button('数据表', () => { style.value = 'table'; }, { 'aria-pressed': style.value === 'table' }),
        ),
      ];
    }

    return () => {
      const data = resource.value.value;
      return section('补学资料阅读情况', [
        data && keyValues([
          ['已发布资料', data.summary.published],
          ['课堂名单学生', data.summary.enrolled],
          ['至少看过一份当前资料', data.summary.read_at_least_one],
          ['当前版暂无阅读标记', data.summary.without_reads],
        ]),
        h('p', { class: 'ef-meta' }, '按学生主动点「已看过」的记录统计。更新资料后，旧版标记会单独列出。'),
        controls(),
        notice(resource.error.value),
        notice(exportFile.status.value, 'info'),
        resource.loading.value && notice('正在读取资料阅读情况…', 'info'),
        items.value.length
          ? style.value === 'cards'
            ? h('ul', { class: 'ef-list' }, items.value.map(card))
            : table(['资料', '课堂时段', '已看当前版', '只看过旧版', '当前版阅读比例', '更新时间'], items.value.map(row))
          : !resource.loading.value && empty('没有符合条件的资料', '发布补学资料后，可以在这里看阅读汇总。'),
      ], actions(
        button('刷新阅读情况', () => resource.load(), { disabled: resource.loading.value }),
        button(exportFile.busy.value ? '取消导出' : '导出阅读汇总', download, { disabled: !data?.items.length }),
      ));
    };
  },
};
