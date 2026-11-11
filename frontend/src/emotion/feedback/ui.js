import { cloneVNode, h, useId } from 'vue';

export const all = label => ({ value: '', label });
export const option = (value, label) => ({ value, label });
export const casePath = id => '/cases/' + id;

export const impacts = [
  option('LOW', '轻微'),
  option('MEDIUM', '影响学习'),
  option('HIGH', '明显影响'),
];
export const outcomes = [
  option('HELPED', '已改善'),
  option('PARTLY', '部分改善'),
  option('UNCHANGED', '仍未改善'),
];
export const priorities = [
  option('NORMAL', '常规'),
  option('HIGH', '优先处理'),
];
export const scopes = [
  option('ALL', '全部数据'),
  option('REAL', '真实课堂'),
  option('DEMO', '演示课堂'),
];
export const orderings = [
  option('UPDATED', '最近更新'),
  option('CREATED', '最近提交'),
  option('OLDEST', '最早提交'),
  option('PRIORITY', '优先处理在前'),
];

export function label(items, value) {
  return items.find(item => item.value === value)?.label || value || '—';
}

const dateFormat = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

export function date(value) {
  if (!value) return '—';
  const time = new Date(value);
  return Number.isFinite(time.getTime()) ? dateFormat.format(time) : '—';
}

export function sessionLabel(item) {
  return [item.course_name, item.class_name, date(item.starts_at)].filter(Boolean).join(' · ');
}

export function badge(value, tone = '') {
  return h('span', { class: ['ef-badge', tone && 'ef-' + tone] }, value);
}

export function status(item) {
  const tone = item.state === 'RESOLVED' ? 'good' : item.state.startsWith('WAITING_') ? 'waiting' : '';
  return badge(item.state_label, tone);
}

export function emotion(catalog, value) {
  const item = catalog.emotions.find(entry => entry.value === value);
  return item ? item.emoji + ' ' + item.label : '—';
}

export function button(title, onClick, options = {}) {
  const { primary = false, ...attributes } = options;
  return h('button', {
    type: 'button',
    class: primary ? 'primary-button' : 'ef-button',
    onClick,
    ...attributes,
  }, title);
}

export function submit(title, disabled) {
  return button(title, undefined, { primary: true, type: 'submit', disabled });
}

const FeedbackField = {
  props: ['title', 'control', 'hint'],
  setup(props) {
    const identifier = useId();
    const hintId = identifier + '-hint';
    return () => h('div', { class: 'ef-field' }, [
      h('label', { for: identifier }, props.title),
      cloneVNode(props.control, {
        id: identifier,
        'aria-describedby': props.hint ? hintId : undefined,
      }),
      props.hint && h('small', { id: hintId }, props.hint),
    ]);
  },
};

export function field(title, control, hint) {
  return h(FeedbackField, { title, control, hint });
}

export function input(value, update, attrs = {}) {
  return h('input', {
    value,
    onInput: event => update(event.target.value),
    ...attrs,
  });
}

export function number(value, update, attrs = {}) {
  return input(value ?? '', value => update(value === '' ? null : Number(value)), {
    type: 'number',
    step: 1,
    ...attrs,
  });
}

export function textarea(value, update, attrs = {}) {
  return h('textarea', {
    value,
    rows: 4,
    maxlength: 2000,
    onInput: event => update(event.target.value),
    ...attrs,
  });
}

export function select(value, items, update, attrs = {}) {
  return h('select', {
    value: value ?? '',
    onChange: event => update(event.target.value),
    ...attrs,
  }, items.map(item => h('option', {
    key: item.value,
    value: item.value,
    disabled: item.disabled,
  }, item.label)));
}

export function check(title, checked, update, disabled = false) {
  return h('label', { class: 'ef-check' }, [
    h('input', {
      type: 'checkbox',
      checked,
      disabled,
      onChange: event => update(event.target.checked),
    }),
    h('span', title),
  ]);
}

export function notice(message, tone = 'error') {
  return message ? h('div', {
    class: ['ef-notice', 'ef-' + tone],
    role: tone === 'error' ? 'alert' : 'status',
  }, message) : null;
}

export function empty(title, description, action) {
  return h('div', { class: 'ef-empty' }, [
    h('strong', title),
    description && h('p', description),
    action,
  ]);
}

export function section(title, contents, tools) {
  return h('section', { class: 'ef-section' }, [
    h('header', { class: 'ef-section-head' }, [h('h3', title), tools]),
    contents,
  ]);
}

export function actions(...children) {
  return h('div', { class: 'ef-actions' }, children);
}

export function keyValues(items) {
  return h('dl', { class: 'ef-values' }, items.map(([name, value]) => h('div', { key: name }, [
    h('dt', name),
    h('dd', value ?? '—'),
  ])));
}

export function table(headers, entries, caption) {
  return h('div', { class: 'ef-table' }, [
    h('table', [
      caption && h('caption', caption),
      h('thead', h('tr', headers.map(value => h('th', { key: value, scope: 'col' }, value)))),
      h('tbody', entries.map(({ id, cells }) => h('tr', { key: id },
        cells.map((cell, index) => h('td', { key: index }, cell)),
      ))),
    ]),
  ]);
}

export function pager(page, loading, setPage) {
  if (!page || (!page.offset && !page.has_more)) return null;
  const current = Math.floor(page.offset / page.limit) + 1;
  const count = Math.max(1, Math.ceil(page.total / page.limit));
  return actions(
    button('上一页', () => setPage(Math.max(0, page.offset - page.limit)), {
      disabled: loading || page.offset === 0,
    }),
    h('span', '第 ' + current + ' / ' + count + ' 页'),
    button('下一页', () => setPage(page.offset + page.limit), {
      disabled: loading || !page.has_more,
    }),
  );
}

export function recordList(items, catalog, open, renderExtra) {
  return h('ul', { class: 'ef-list' }, items.map(item => h('li', { key: item.id }, [
    h('div', { class: 'ef-list-row' }, [
      h('div', [
        button(item.title, () => open(item.id), { class: 'ef-link' }),
        h('p', { class: 'ef-meta' }, [item.number, item.course_name, item.class_name, date(item.updated_at)].join(' · ')),
      ]),
      actions(
        badge(emotion(catalog, item.emotion)),
        status(item),
        item.is_demo && badge('演示'),
        item.acknowledgement_overdue && badge('确认逾期', 'waiting'),
      ),
    ]),
    item.reason_labels.length ? h('p', { class: 'ef-meta' }, item.reason_labels.join('、')) : null,
    renderExtra?.(item),
  ])));
}
