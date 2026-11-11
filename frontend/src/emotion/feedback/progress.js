import { computed, h, ref, watch } from 'vue';
import { read, useResource } from './client.js';
import {
  actions, badge, button, casePath, date, empty, keyValues,
  notice, pager, section, table,
} from './ui.js';

function duration(hours) {
  if (hours === null) return '—';
  const minutes = Math.round(hours * 60);
  if (minutes < 60) return minutes + ' 分钟';
  if (minutes < 1440) return Math.floor(minutes / 60) + ' 小时 ' + minutes % 60 + ' 分钟';
  return Math.floor(minutes / 1440) + ' 天 ' + Math.floor(minutes % 1440 / 60) + ' 小时';
}

const destinations = {
  REPLY: { tab: 'conversation', text: '补充反馈' },
  CONVERSATION: { tab: 'conversation', text: '查看交流' },
  REVIEW: { tab: 'reviews', text: '查看回访' },
  WORKFLOW: { tab: 'workflow', text: '打开处理操作' },
};

const reasons = {
  CREATED: '提交反馈',
  ACKNOWLEDGE: '老师确认收到',
  START: '老师开始处理',
  ASK_STUDENT: '老师请求补充',
  MESSAGE: '交流后状态更新',
  GROUP_REPLY: '集中处理回应',
  REVIEW_REQUESTED: '发起回访',
  REVIEW_ANSWERED: '学生提交回访',
  REVIEW_CANCELLED: '回访取消',
  RESOLVE: '教师说明后关闭',
  REOPEN: '学生重新跟进',
  WITHDRAW: '学生撤回反馈',
};

function isTerminal(value) {
  return value === 'RESOLVED' || value === 'WITHDRAWN';
}

export const FeedbackProgress = {
  props: ['item', 'expired'],
  emits: ['tab'],
  setup(props, { emit }) {
    const resource = useResource(signal => read(casePath(props.item.id) + '/progress', {}, signal), props.expired);
    const view = ref('milestones');
    const offset = ref(0);
    const limit = 10;
    const slice = computed(() => {
      const items = resource.value.value?.recent_visits || [];
      return {
        items: items.slice(offset.value, offset.value + limit),
        total: items.length,
        offset: offset.value,
        limit,
        has_more: offset.value + limit < items.length,
      };
    });

    watch(() => props.item.version, () => {
      offset.value = 0;
      resource.load();
    }, { immediate: true });

    function current(data) {
      const next = data.next;
      const target = destinations[next.action];
      return [
        h('p', next.label),
        keyValues([
          ['当前进度', data.current.label],
          ['进入当前状态', date(data.current.started_at)],
          ['当前状态持续时间', isTerminal(data.current.state) ? '—' : duration(data.current.duration_hours)],
          ['目标时间', date(next.deadline)],
        ]),
        next.overdue && notice('已经超过截止时间。', 'waiting'),
        target && actions(button(target.text, () => emit('tab', target.tab), { primary: true })),
      ];
    }

    function milestones(data) {
      return h('ol', { class: 'ef-timeline' }, data.stamps.map(item => h('li', { key: item.key }, [
        h('div', { class: 'ef-list-row' }, [
          h('strong', item.label),
          item.at ? h('time', { datetime: item.at }, date(item.at)) : badge('暂无记录'),
        ]),
      ])));
    }

    function visits(data) {
      const page = slice.value;
      return [
        h('p', { class: 'ef-meta' }, '共 ' + data.total_visits + ' 次进入状态。刷新可以更新当前阶段的耗时。'),
        data.total_visits > page.total && notice('这里展示最近 ' + page.total + ' 段状态，完整事件可到时间线查看。', 'info'),
        table(['状态', '触发动作', '开始', '结束', '持续时间'], page.items.map(item => ({
          id: item.state + item.started_at + item.entered_by,
          cells: [
            actions(badge(item.label), item.current && badge('当前')),
            reasons[item.entered_by] || '处理更新',
            date(item.started_at),
            item.ended_at ? date(item.ended_at) : '—',
            isTerminal(item.state) ? '—' : duration(item.duration_hours),
          ],
        }))),
        pager(page, resource.loading.value, value => { offset.value = value; }),
      ];
    }

    function totals(data) {
      return [
        data.state_totals.length ? table(['处理阶段', '进入次数', '累计时间'], data.state_totals.map(item => ({
          id: item.state,
          cells: [item.label, item.visits, duration(item.duration_hours)],
        }))) : empty('暂无处理阶段记录'),
        keyValues([
          ['发起回访', data.review_counts.total],
          ['等待答复', data.review_counts.open],
          ['收到答复', data.review_counts.answered],
          ['已取消', data.review_counts.cancelled],
        ]),
      ];
    }

    return () => {
      const data = resource.value.value;
      return [
        section('当前进度', [
          notice(resource.error.value),
          resource.loading.value && notice('正在读取处理进度…', 'info'),
          data && current(data),
        ], button('刷新进度', () => resource.load(), { disabled: resource.loading.value })),
        data && section('处理记录汇总', [
          h('nav', { class: 'ef-tabs', 'aria-label': '处理进度视图' }, [
            ['milestones', '关键节点'],
            ['visits', '状态变化'],
            ['totals', '累计耗时'],
          ].map(([key, title]) => button(title, () => { view.value = key; }, { key, 'aria-pressed': view.value === key }))),
          view.value === 'milestones' ? milestones(data) : view.value === 'visits' ? visits(data) : totals(data),
          h('p', { class: 'ef-meta' }, '统计于 ' + date(data.generated_at)),
        ]),
      ];
    };
  },
};
