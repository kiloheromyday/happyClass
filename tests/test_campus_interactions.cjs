const assert = require('node:assert/strict');
const { createRenderer, h, nextTick } = require('../frontend/node_modules/vue');
const node = (type, text = '') => ({ type, text, props: {}, children: [], parent: null });
const detach = child => { if (child.parent) { child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null; } };
const renderer = createRenderer({ createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text), setText: (n, value) => n.text = value, setElementText: (n, value) => { n.text = value; n.children = []; }, patchProp: (n, key, old, value) => n.props[key] = value, insert(n, parent, anchor) { detach(n); const i = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(i < 0 ? parent.children.length : i, 0, n); n.parent = parent; }, remove: detach, parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] || null });
const walk = n => [n, ...n.children.flatMap(walk)], text = n => (n.type === '#comment' ? '' : n.text) + n.children.map(text).join('');
const find = (root, condition) => { const n = walk(root).find(condition); assert(n, 'Control not found'); return n; };
const button = (root, label) => find(root, n => n.type === 'button' && text(n) === label);
const field = (root, name) => find(root, n => n.props.name === name);
const settle = async () => { for (let i = 0; i < 8; i++) { await new Promise(setImmediate); await nextTick(); } };
const mount = (component, props) => { const root = node('root'), app = renderer.createApp({ render: () => h(component, props) }); app.mount(root); return { root, app }; };

(async () => {
  const { CampusPanel } = await import('../frontend/src/campus.js');
  const { CoursesPanel } = await import('../frontend/src/courses.js');
  const { Timetable, chinaDay } = await import('../frontend/src/timetable.js');
  assert.equal(chinaDay('2026-11-03T20:00:00Z'), '2026-11-04');
  const today = chinaDay(new Date()), day = new Date(today), monday = new Date(day.getTime() - ((day.getUTCDay() + 6) % 7) * 86400000).toISOString().slice(0, 10);
  const summary = { feedback_count: 12, responding_students: 10, session_count: 2, demo_feedback_count: 12 };
  const courses = [
    { id: 1, name: '数学分析', teacher_name: '数学教师', department_id: 'math', department_name: '数学科学学院', department_short: '数学', department_color: '#5365aa', department_background: '#edf0ff', is_demo: 1, summary, emotions: [{ emotion: 'HAPPY', count: 12 }] },
    { id: 2, name: '音乐欣赏', teacher_name: '艺术教师', department_id: 'arts', department_name: '艺术教学中心', department_short: '艺术', department_color: '#a35a97', department_background: '#faedf7', is_demo: 1, summary: { ...summary, feedback_count: 0 }, emotions: [] },
  ];
  const sessions = [{ ...courses[0], id: 11, course_id: 1, course_name: '数学分析', starts_at: `${monday}T00:00:00Z`, ends_at: `${monday}T01:35:00Z`, status: 'ENDED', record_count: 12, scheduled_count: 20, classroom: '东区101', class_name: '演示班' }, { ...courses[1], id: 12, course_id: 2, course_name: '音乐欣赏', starts_at: `${monday}T12:15:00Z`, ends_at: `${monday}T13:50:00Z`, status: 'UPCOMING', record_count: 0, scheduled_count: 20, classroom: '艺术教室', class_name: '演示班' }];
  let originalFetch = global.fetch, mounted;
  const navigation = [], requests = [];
  const response = data => new Response(JSON.stringify({ data }), { status: 200 });
  global.fetch = async path => { requests.push(path); if (path === '/api/admin/campus') return response({ courses, sessions, summary: { demo_feedback_count: 12 } }); if (path === '/api/courses') return response({ items: courses }); if (path === '/api/sessions') return response({ items: sessions }); throw new Error(path); };
  try {
    mounted = mount(CampusPanel, { onNavigate: value => navigation.push(value) }); await settle();
    assert(text(mounted.root).includes('全校开课') && text(mounted.root).includes('北京时间'));
    const cells = walk(mounted.root).filter(n => n.type === 'td'); assert.equal(cells.length, 42);
    const evening = cells.find(n => n.props['data-day'] === monday && n.props['data-slot'] === 5);
    assert(text(evening).includes('音乐欣赏') && text(evening).includes('20:15'));
    await find(mounted.root, n => String(n.props['aria-label'] || '').startsWith('查看课表课堂：12 ')).props.onClick(); await nextTick();
    assert(text(mounted.root).includes('名单 20 人') && text(mounted.root).includes('课堂评价 0 条'));
    await button(mounted.root, '本节评价统计').props.onClick(); assert.deepEqual(navigation.at(-1), { tab: 'reports', courseId: 2, sessionId: 12 });
    field(mounted.root, 'campus_department').props.onChange({ target: { value: 'math' } }); await nextTick();
    assert(!walk(mounted.root).some(n => String(n.props['aria-label'] || '').startsWith('查看课表课堂：12 ')));
    await button(mounted.root, '课程与评价').props.onClick(); await nextTick();
    assert(text(mounted.root).includes('数学分析') && text(mounted.root).includes('开心 12') && !text(mounted.root).includes('音乐欣赏'));
    const card = find(mounted.root, n => n.props.class === 'campus-course-card'); assert.equal(card.props.style['--dept-color'], '#5365aa');
    await find(mounted.root, n => n.props['aria-label'] === '查看课程评价：1').props.onClick(); assert.deepEqual(navigation.at(-1), { tab: 'reports', courseId: 1 });
    field(mounted.root, 'campus_query').props.onInput({ target: { value: '不存在' } }); await nextTick(); assert(text(mounted.root).includes('没有符合条件'));
    mounted.app.unmount();
    mounted = mount(CoursesPanel, { user: { role: 'STUDENT' }, onNavigate: value => navigation.push(value) }); await settle();
    assert(walk(mounted.root).filter(n => n.props.class === 'course-card').length === 2);
    await button(mounted.root, '课程表').props.onClick(); await nextTick();
    await find(mounted.root, n => String(n.props['aria-label'] || '').startsWith('查看课表课堂：11 ')).props.onClick(); assert.deepEqual(navigation.at(-1), { tab: 'classroom', courseId: 1, sessionId: 11 });
    await button(mounted.root, '下一周 →').props.onClick(); await nextTick(); assert(text(mounted.root).includes('本周没有课堂安排'));
    await button(mounted.root, '本周').props.onClick(); await nextTick(); assert(!text(mounted.root).includes('本周没有课堂安排'));
    mounted.app.unmount();
    let aborted = false;
    global.fetch = (path, options) => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => { aborted = true; reject(new DOMException('Aborted', 'AbortError')); }));
    mounted = mount(CampusPanel, {}); await settle(); mounted.app.unmount(); mounted = null; assert(aborted);
    console.log('Campus interactions passed: China dates, 42 timetable cells, evenings, exact classroom/statistics navigation, department colors/filtering, search, student timetable, week switching and request cancellation.');
  } finally { mounted?.app.unmount(); global.fetch = originalFetch; }
})().catch(error => { console.error(error); process.exitCode = 1; });
