import { computed, h, ref } from 'vue';
import { read, scoped, useResource } from './client.js';
import { filterFields } from './queue.js';
import {
  actions, badge, button, check, date, empty, field, keyValues, notice, option,
  recordList, section, select, sessionLabel, submit,
} from './ui.js';

function windowLabel(item) {
  if (item.without_minute) return '未填写课堂时间点';
  if (item.minute_from === null) return '整节课堂';
  return '第 ' + item.minute_from + '～' + item.minute_to + ' 分钟';
}

const windows = [
  option('', '整节课堂'),
  option(5, '每 5 分钟'),
  option(10, '每 10 分钟'),
  option(15, '每 15 分钟'),
  option(30, '每 30 分钟'),
];

function criterionLabel(value) {
  return [
    '至少 ' + value.threshold + ' 条',
    value.topic_window ? '每 ' + value.topic_window + ' 分钟归类' : '按整节课堂归类',
    value.include_grouped ? '含已分组反馈' : '只建议尚未分组的反馈',
  ].join(' · ');
}

const CandidatePreview = {
  props: ['item', 'catalog'],
  emits: ['back', 'create', 'open'],
  setup(props, { emit }) {
    const ids = ref(props.item.members.map(item => item.id));
    const chosen = computed(() => props.item.members.filter(item => ids.value.includes(item.id)));

    function select(id, checked) {
      ids.value = checked ? [...ids.value, id] : ids.value.filter(value => value !== id);
    }

    function create() {
      if (chosen.value.length < 2) return;
      emit('create', {
        title: props.item.reason_label + ' · ' + props.item.class_name,
        description: '共同原因：' + props.item.reason_label + '。范围：' + windowLabel(props.item) + '。',
        members: chosen.value,
      });
    }

    return () => section('核对建议成员', [
      keyValues([
        ['课堂', sessionLabel(props.item)],
        ['共同原因', props.item.reason_label],
        ['时间范围', windowLabel(props.item)],
        ['纳入数量', chosen.value.length + ' / ' + props.item.members.length],
      ]),
      notice(props.item.count > props.item.included_count ? '本建议包含 ' + props.item.count + ' 条候选。先展示最早的 50 条。' : '', 'info'),
      h('p', { class: 'ef-meta' }, '请核对具体诉求后再创建处理组。同一原因的反馈可能需要不同回应。'),
      actions(
        button('全选', () => { ids.value = props.item.members.map(item => item.id); }),
        button('清空', () => { ids.value = []; }),
      ),
      recordList(props.item.members, props.catalog, id => emit('open', id), item =>
        check('纳入反馈 ' + item.number, ids.value.includes(item.id), value => select(item.id, value)),
      ),
      actions(
        button('用选中的反馈建组', create, { primary: true, disabled: chosen.value.length < 2 }),
        button('返回分组建议', () => emit('back')),
      ),
    ]);
  },
};

export const FeedbackSuggestions = {
  props: ['catalog', 'selection', 'expired'],
  emits: ['create', 'open', 'back'],
  setup(props, { emit }) {
    const initial = {
      ...scoped(props.selection),
      minimum: 2,
      topic_window: null,
      include_grouped: false,
    };
    const settings = ref({ ...initial });
    const inspected = ref(null);
    const order = ref('size');
    const report = useResource((signal, filters) => read('/group-suggestions', filters, signal), props.expired);

    const items = computed(() => {
      const list = [...(report.value.value?.items || [])];
      if (order.value === 'priority') {
        list.sort((a, b) => b.high_priority - a.high_priority || b.count - a.count);
      } else if (order.value === 'recent') {
        list.sort((a, b) => b.starts_at.localeCompare(a.starts_at));
      }
      return list;
    });

    function load(event) {
      event?.preventDefault();
      inspected.value = null;
      return report.load({ ...settings.value });
    }
    load();

    function card(item) {
      return h('li', { key: item.key }, [
        h('div', { class: 'ef-list-row' }, [
          h('strong', item.reason_label),
          actions(
            badge(item.count + ' 条可归并反馈'),
            item.is_demo && badge('演示'),
            item.high_priority > 0 && badge(item.high_priority + ' 条优先', 'waiting'),
          ),
        ]),
        h('p', { class: 'ef-meta' }, sessionLabel(item) + ' · ' + windowLabel(item)),
        actions(...item.states.map(entry => badge(entry.label + ' ' + entry.count))),
        actions(...item.emotions.map(entry => badge(entry.label + ' ' + entry.count))),
        actions(button('核对这组反馈', () => { inspected.value = item; }, { primary: true })),
      ]);
    }

    function controls() {
      return h('form', { class: 'ef-form', onSubmit: load }, [
        filterFields(props.catalog, settings.value, (key, value) => { settings.value[key] = value; }, { compact: true }),
        h('div', { class: 'ef-grid' }, [
          field('课堂时间点的归类范围', select(settings.value.topic_window, windows, value => {
            settings.value.topic_window = value ? Number(value) : null;
          }), '选择分钟范围时，未填写时间点的反馈会单独归类。'),
          field('同类反馈达到多少条才建议归组', select(settings.value.minimum, [2, 3, 4, 5, 10].map(value => option(value, value + ' 条')),
            value => { settings.value.minimum = Number(value); },
          )),
          check('也包含已有处理组的反馈', settings.value.include_grouped, value => { settings.value.include_grouped = value; }),
        ]),
        actions(
          submit('重新计算建议', report.loading.value),
          button('恢复默认范围', () => { settings.value = { ...initial }; load(); }),
        ),
      ]);
    }

    function results() {
      const data = report.value.value;
      if (!data) return null;
      return [
        h('div', { class: 'ef-grid' }, [
          keyValues([
            ['扫描反馈', data.scanned_count + ' / ' + data.candidate_count],
            ['建议分组', data.suggestion_count],
            ['生成时间', date(data.generated_at)],
          ]),
          field('排序', select(order.value, [
            option('size', '候选条数在前'),
            option('priority', '优先处理条数在前'),
            option('recent', '最近课堂在前'),
          ], value => { order.value = value; })),
        ]),
        h('p', { class: 'ef-meta' }, criterionLabel(data.settings)),
        data.suggestion_count > items.value.length && notice('当前展示匹配度靠前的 ' + items.value.length + ' 个建议。可缩小课堂范围。', 'info'),
        items.value.length
          ? h('ul', { class: 'ef-list' }, items.value.map(card))
          : empty('当前范围没有达到条件的建议', '可扩大课堂范围、降低起始条数，或从反馈列表手动选组。'),
      ];
    }

    return () => inspected.value
      ? h(CandidatePreview, {
        key: inspected.value.key,
        item: inspected.value,
        catalog: props.catalog,
        onBack: () => { inspected.value = null; },
        onOpen: id => emit('open', id),
        onCreate: value => emit('create', value),
      })
      : section('同类反馈分组建议', [
        h('p', { class: 'ef-meta' }, '按同一课堂和反馈原因整理进行中的反馈。生成建议不会修改任何反馈。'),
        controls(),
        notice(report.error.value),
        report.loading.value && notice('正在整理同类反馈…', 'info'),
        results(),
      ], button('返回处理组', () => emit('back')));
  },
};
