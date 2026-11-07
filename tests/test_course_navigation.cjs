// Exercise actual Vue routing and controls with isolated mock data, without a browser.
const assert = require('node:assert/strict');
const { createRenderer, h, nextTick } = require('../frontend/node_modules/vue');
const make = (type, text = '') => ({ type, text, children: [], props: {}, parent: null });
const remove = child => { if (child.parent) { child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null; } };
const renderer = createRenderer({
  createElement: type => make(type), createText: text => make('#text', text), createComment: text => make('#comment', text),
  setText: (n, value) => n.text = value, setElementText: (n, value) => { n.text = value; n.children = []; },
  patchProp: (n, key, old, value) => n.props[key] = value,
  insert(n, parent, anchor) { remove(n); const index = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(index < 0 ? parent.children.length : index, 0, n); n.parent = parent; },
  remove, parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] || null,
});
const all = n => [n, ...n.children.flatMap(all)];
const text = n => (n.type === '#comment' ? '' : n.text) + n.children.map(text).join('');
const find = (root, predicate) => { const n = all(root).find(predicate); assert(n, 'Control not found'); return n; };
const button = (root, label) => find(root, n => n.type === 'button' && text(n) === label);
const aria = (root, label) => find(root, n => n.props['aria-label'] === label);
const input = (root, name) => find(root, n => n.props.name === name);
const settle = async () => { for (let i = 0; i < 8; i++) { await new Promise(setImmediate); await nextTick(); } };
const mount = (component, props) => { const root = make('root'), app = renderer.createApp({ render: () => h(component, props) }); app.mount(root); return { root, app }; };

(async () => {
  const { Workspace } = await import('../frontend/src/accounts.js');
  const { CoursesPanel } = await import('../frontend/src/courses.js');
  const originalFetch = global.fetch;
  const user = { id: 1, role: 'STUDENT', username: 'student01' };
  const course = { id: 7, name: '交互设计', teacher_name: '设计老师' };
  const session = { id: 21, course_id: 7, course_name: course.name, teacher_name: course.teacher_name, class_name: '设计一班', classroom: 'B203', status: 'ONGOING', can_feedback: true, starts_at: new Date(Date.now() - 60000).toISOString(), ends_at: new Date(Date.now() + 60000).toISOString(), feedback_closes_at: '2099-01-01T00:00:00Z', personal: { feedback_count: 2, note_count: 1, pending_count: 1 } };
  const older = { ...session, id: 22, status: 'ENDED', can_feedback: false, starts_at: '2026-10-01T08:00:00Z', ends_at: '2026-10-01T12:00:00Z', feedback_closes_at: '2026-10-01T12:30:00Z' };
  const classrooms = [session, older], requests = [];
  const data = { course, sessions: classrooms, summary: { total: 2, ongoing: 1, ended: 1, upcoming: 0, feedback_count: 4, note_count: 2, pending_count: 2, participated_sessions: 2 } };
  const response = (value, status = 200) => new Response(JSON.stringify({ data: value, message: status === 200 ? '成功' : '暂时无法读取' }), { status });
  let mode = 'normal', pendingSignal;
  global.fetch = async (path, options = {}) => {
    const url = new URL(path, 'http://localhost'); requests.push(url);
    if (url.pathname === '/api/courses/7') {
      if (mode === 'error') return response(null, 503);
      if (mode === 'slow') { pendingSignal = options.signal; return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))); }
      return response(data);
    }
    if (url.pathname === '/api/courses') return response({ items: [course] });
    if (url.pathname === '/api/sessions' || url.pathname === '/api/personal/notes/sessions') return response({ items: classrooms });
    if (url.pathname === '/api/emoji/history' || url.pathname === '/api/personal/notes') return response({ items: [], total: 0 });
    if (/\/questions$/.test(url.pathname)) return response({ items: [], total: 0, summary: { total: 0, open: 0, resolved: 0, categories: [] } });
    if (/\/learning-guide$/.test(url.pathname)) return response({ published: null });
    if (url.pathname === '/api/personal/review') return response({ summary: { feedback_count: 0, active_days: 0, note_count: 0, pending_count: 0 }, session_id: Number(url.searchParams.get('session_id')), emotions: [], trend: [], sessions: [], recent_notes: [] });
    throw new Error(`Unexpected request ${path}`);
  };
  let workspace;
  try {
    workspace = mount(Workspace, { user }); await settle();
    await button(workspace.root, '我的课程').props.onClick(); await settle();
    assert(!text(workspace.root).includes('课程加入码'));
    await aria(workspace.root, '查看课程详情：交互设计').props.onClick(); await settle();
    assert(text(workspace.root).includes('设计老师') && text(workspace.root).includes('B203'));
    assert(text(workspace.root).includes('2 篇笔记等待回顾'));
    await button(workspace.root, '已结束').props.onClick(); await nextTick();
    assert(!all(workspace.root).some(n => n.props['aria-label'] === '打开课堂：21'));
    await aria(workspace.root, '打开课堂：22').props.onClick(); await settle();
    assert.equal(input(workspace.root, 'daily_session').props.value, '22', 'old class remains selected even outside feedback window');
    assert.equal(input(workspace.root, 'daily_course_filter').props.value, '7');
    assert.equal(input(workspace.root, 'daily_session_scope').props.value, 'ALL');
    assert.equal(requests.filter(u => u.pathname === '/api/emoji/history').at(-1).searchParams.get('session_id'), '22');
    assert(button(workspace.root, '提交本次感受').props.disabled);
    await button(workspace.root, '返回课程详情').props.onClick(); await settle();
    await aria(workspace.root, '课堂笔记：22').props.onClick(); await settle();
    assert.equal(input(workspace.root, 'notes_session_filter').props.value, '22');
    assert.equal(requests.filter(u => u.pathname === '/api/personal/notes').at(-1).searchParams.get('session_id'), '22');
    await button(workspace.root, '新建笔记').props.onClick(); await nextTick();
    assert.equal(input(workspace.root, 'note_session').props.value, '22');
    input(workspace.root, 'note_title').props.onInput({ target: { value: '尚未保存的课堂笔记' } }); await nextTick();
    assert(button(workspace.root, '返回课程详情').props.disabled);
    await button(workspace.root, '我的课程').props.onClick(); await nextTick();
    assert(text(workspace.root).includes('笔记尚未保存'));
    await button(workspace.root, '放弃修改并返回').props.onClick(); await settle();
    await button(workspace.root, '返回课程详情').props.onClick(); await settle();
    await aria(workspace.root, '个人回顾：22').props.onClick(); await settle();
    assert.equal(input(workspace.root, 'personal_review_session').props.value, '22');
    assert.equal(input(workspace.root, 'personal_review_days').props.value, '90');
    assert.equal(requests.filter(u => u.pathname === '/api/personal/review').at(-1).searchParams.get('session_id'), '22');
    workspace.app.unmount(); workspace = null;
    mode = 'error'; const errors = mount(CoursesPanel, { user, initialCourseId: 7 }); await settle();
    assert(text(errors.root).includes('暂时无法读取'));
    mode = 'normal'; await button(errors.root, '重试').props.onClick(); await settle();
    assert(text(errors.root).includes('课堂安排')); errors.app.unmount();
    mode = 'slow'; const slow = mount(CoursesPanel, { user, initialCourseId: 7 }); await settle();
    await button(slow.root, '返回我的课程').props.onClick(); await settle();
    assert(pendingSignal.aborted && text(slow.root).includes('查看详情'));
    slow.app.unmount();
    const pending = mount(CoursesPanel, { user, initialCourseId: 7 }); await settle(); pending.app.unmount();
    assert(pendingSignal.aborted);
    console.log('Course navigation passed: cards, filters, exact old class, notes/review context, drafts, errors/retry and cancelled reads.');
  } finally { workspace?.app.unmount(); global.fetch = originalFetch; }
})().catch(error => { console.error(error); process.exitCode = 1; });
