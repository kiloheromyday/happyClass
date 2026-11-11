import { computed, h, ref, watch } from 'vue';
import { actions, all, badge, button, date, field, input, notice, option, select, sessionLabel } from '../feedback/ui.js';

const ranges = [
  option('ALL', '全部课堂'),
  option('LIVE', '正在上课'),
  option('ENDED', '已经下课'),
  option('UPCOMING', '还未开课'),
];

const sources = [
  option('ALL', '全部数据'),
  option('REAL', '真实课堂'),
  option('DEMO', '演示课堂'),
];

function status(item, now) {
  if (now < Date.parse(item.starts_at)) return 'UPCOMING';
  if (now >= Date.parse(item.ends_at)) return 'ENDED';
  return 'LIVE';
}

export function currentSession(item, now, manualDays) {
  if (!item) return null;
  const start = Date.parse(item.starts_at);
  const end = Date.parse(item.ends_at);
  const elapsed = Math.min(item.duration_minutes, Math.max(0, Math.floor((now - start) / 60000) + 1));
  const live = status(item, now) === 'LIVE';
  return {
    ...item,
    elapsed_minutes: elapsed,
    current_minute: live ? elapsed - 1 : null,
    live,
    can_add_past: now >= start && now <= end + manualDays * 86400000,
  };
}

export const BookmarkSessionPicker = {
  props: ['sessions', 'value', 'allowAll', 'locked', 'now'],
  emits: ['select'],
  setup(props, { emit }) {
    const name = ref('');
    const range = ref('ALL');
    const source = ref('ALL');
    const course = ref('');
    const courses = computed(() => {
      const choices = new Map();
      for (const item of props.sessions) choices.set(item.course_id, item.course_name);
      return [...choices].map(([id, label]) => option(id, label));
    });
    watch(() => props.sessions, () => {
      if (course.value && !courses.value.some(item => String(item.value) === course.value)) course.value = '';
    });

    const matches = computed(() => {
      const term = name.value.trim().toLowerCase();
      return props.sessions.filter(item =>
        (!course.value || String(item.course_id) === course.value) &&
        (source.value === 'ALL' || item.is_demo === (source.value === 'DEMO')) &&
        (range.value === 'ALL' || status(item, props.now) === range.value) &&
        (!term || (item.course_name + ' ' + item.class_name + ' ' + date(item.starts_at)).toLowerCase().includes(term)),
      );
    });

    const chosenOutsideFilters = computed(() =>
      props.sessions.find(item => item.id === props.value && !matches.value.some(entry => entry.id === item.id)),
    );

    function reset() {
      name.value = '';
      range.value = 'ALL';
      source.value = 'ALL';
      course.value = '';
    }

    function options() {
      const list = [all(props.allowAll ? '全部课堂' : '请选择一节课')];
      const current = chosenOutsideFilters.value;
      if (current) list.push(option(current.id, sessionLabel(current) + '（当前课堂）'));
      for (const item of matches.value) {
        list.push(option(item.id, sessionLabel(item) + (item.is_demo ? '（演示）' : '')));
      }
      return list;
    }

    return () => [
      field('选择课堂', select(props.value, options(), value => emit('select', value), { disabled: props.locked })),
      h('details', { class: 'bookmark-session-filter' }, [
        h('summary', '筛选课堂列表'),
        h('div', { class: 'ef-grid' }, [
          field('课程', select(course.value, [all('全部课程'), ...courses.value], value => { course.value = value; }, { disabled: props.locked })),
          field('课堂进度', select(range.value, ranges, value => { range.value = value; }, { disabled: props.locked })),
          field('课堂类型', select(source.value, sources, value => { source.value = value; }, { disabled: props.locked })),
          field('搜索课堂', input(name.value, value => { name.value = value; }, {
            type: 'search', maxlength: 100, disabled: props.locked,
          })),
        ]),
        actions(
          badge(matches.value.length + ' 节符合条件'),
          button('清除课堂筛选', reset, { disabled: props.locked }),
        ),
        chosenOutsideFilters.value && notice('当前课堂仍保留在下拉列表中。', 'info'),
        !matches.value.length && notice('没有符合条件的课堂，可以清除筛选。', 'info'),
      ]),
    ];
  },
};
