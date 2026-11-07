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
  const { ClassroomPanel } = await import('../frontend/src/classroom.js');
  const { CoursesPanel } = await import('../frontend/src/courses.js');
  const { CampusPanel } = await import('../frontend/src/campus.js');
  const { CatalogPanel } = await import('../frontend/src/catalog.js');
  const { CameraPanel } = await import('../frontend/src/camera.js');
  const { EvaluationsPanel } = await import('../frontend/src/evaluations.js');
  const { Workspace } = await import('../frontend/src/accounts.js');
  const original = { fetch: global.fetch, now: Date.now, interval: global.setInterval, clear: global.clearInterval, document: global.document };
  let now = Date.parse('2030-01-01T02:00:00Z'), mounted, deferAi = false, failScope = false;
  const ticks = new Set(), pending = [], writes = [];
  Date.now = () => now;
  global.setInterval = callback => { ticks.add(callback); return callback; };
  global.clearInterval = callback => ticks.delete(callback);
  global.document = { addEventListener() {}, removeEventListener() {} };
  const advance = async value => { now = value; [...ticks].forEach(callback => callback()); await settle(); };
  const response = data => new Response(JSON.stringify({ data, message: '已保存' }), { status: 200 });
  const course = { id: 1, name: '边界测试课程', teacher_id: 2, teacher_name: '教师', is_demo: 1 };
  const start = now + 5000, end = start + 60000, close = end + 1800000;
  const session = { id: 11, course_id: 1, course_name: course.name, class_name: '一班', classroom: '101', teacher_name: '教师', starts_at: new Date(start).toISOString(), ends_at: new Date(end).toISOString(), feedback_closes_at: new Date(close).toISOString(), status: 'UPCOMING', can_feedback: false, scheduled_count: 1, record_count: 0, personal: { feedback_count: 0, note_count: 0, pending_count: 0 } };
  const summary = { total: 1, ended: 0, upcoming: 1, ongoing: 0, feedback_count: 0, note_count: 0, pending_count: 0, participated_sessions: 0 };
  let loseCourseResponse = true;
  global.fetch = async (path, options = {}) => {
    const url = new URL(path, 'http://test.local'), scope = url.searchParams.get('data_scope');
    if (path === '/api/courses') return response({ items: [course] });
    if (path === '/api/courses/1') return response({ course, sessions: [session], summary });
    if (path === '/api/sessions') return response({ items: [session] });
    if (path === '/api/departments') return response({ items: [] });
    if (path === '/api/admin/people') return response({ items: [{ id: 2, role: 'TEACHER', username: 'teacher' }] });
    if (path === '/api/admin/courses' && options.method === 'POST') {
      writes.push(JSON.parse(options.body));
      if (loseCourseResponse) { loseCourseResponse = false; throw new Error('response lost after commit'); }
      return response(course);
    }
    if (url.pathname === '/api/admin/campus') {
      if (failScope) throw new Error('offline');
      return response({ courses: [{ ...course, summary: { feedback_count: 42, session_count: 1, responding_students: 1, demo_feedback_count: 42 }, emotions: [] }], sessions: [session], summary: {} });
    }
    if (path === '/api/ai/status') return response({ ready: false });
    if (path.endsWith('/roster')) return response({ items: [] });
    if (path.endsWith('/questions')) return response({ items: [], total: 0, summary: { total: 0, open: 0 } });
    if (path.endsWith('/learning-guide')) return response({ published: null });
    if (url.pathname.endsWith('/statistics') || url.pathname === '/api/emoji/history') {
      const data = url.pathname.endsWith('/statistics')
        ? { session, total: scope === 'REAL' ? 3 : 42, responding_students: 1, manual_count: 1, ai_count: 0, emotions: [] }
        : { items: [], total: scope === 'REAL' ? 3 : 42 };
      if (deferAi && scope !== 'REAL') return new Promise(resolve => pending.push(() => resolve(response(data))));
      return response(data);
    }
    throw new Error(path);
  };
  try {
    mounted = mount(ClassroomPanel, { user: { id: 1, role: 'STUDENT' } }); await settle();
    assert(text(mounted.root).includes('暂时没有可评价的课堂'));
    await advance(start);
    assert(!button(mounted.root, '开心').props.disabled, 'an open page discovers a newly started class');
    assert.equal(field(mounted.root, 'daily_session').props.value, '11');
    await advance(end);
    assert(text(mounted.root).includes('回想刚才的课堂'), 'class status advances without refresh');
    await advance(close);
    assert(!walk(mounted.root).some(n => n.props['data-emotion']), 'deadline is exclusive and expired selection clears');
    mounted.app.unmount();

    now = start - 1;
    mounted = mount(CoursesPanel, { user: { role: 'STUDENT' }, initialCourseId: 1 }); await settle();
    const openClass = () => find(mounted.root, n => n.props['aria-label'] === '打开课堂：11');
    assert.equal(text(openClass()), '查看课堂');
    await advance(start); assert.equal(text(openClass()), '去评价');
    await advance(close); assert.equal(text(openClass()), '查看课堂');
    mounted.app.unmount();

    mounted = mount(CampusPanel, {}); await settle();
    assert(text(mounted.root).includes('42'));
    failScope = true;
    field(mounted.root, 'data_scope').props.onChange({ target: { value: 'REAL' } }); await settle();
    assert(!text(mounted.root).includes('42'), 'failed new scope cannot retain old scope counts');
    assert(!walk(mounted.root).some(n => n.props.class === 'campus-summary'));
    mounted.app.unmount(); failScope = false;

    now = start + 1000;
    mounted = mount(ClassroomPanel, { user: { id: 2, role: 'TEACHER' }, initialSessionId: 11 }); await settle();
    const findComponent = (v, type) => {
      if (!v) return null;
      if (v.type === type) return v;
      return findComponent(v.component?.subTree, type) || (Array.isArray(v.children) ? v.children.map(child => findComponent(child, type)).find(Boolean) : null);
    };
    const camera = findComponent(mounted.app._instance.subTree, CameraPanel); assert(camera);
    deferAi = true; const oldRefresh = camera.props.onSaved(); await settle(); assert.equal(pending.length, 2);
    field(mounted.root, 'data_scope').props.onChange({ target: { value: 'REAL' } }); await settle();
    assert(text(mounted.root).includes('共 3 条'));
    pending.splice(0).forEach(resolve => resolve()); await oldRefresh; await settle();
    assert(text(mounted.root).includes('共 3 条') && !text(mounted.root).includes('共 42 条'), 'late ALL response cannot overwrite REAL scope');
    mounted.app.unmount(); deferAi = false;

    mounted = mount(CatalogPanel, {}); await settle();
    button(mounted.root, '新增课程').props.onClick(); await settle();
    field(mounted.root, 'catalog_name').props.onInput({ target: { value: ' 新课程 ' } });
    field(mounted.root, 'catalog_teacher').props.onChange({ target: { value: '2' } });
    const submit = () => find(mounted.root, n => n.type === 'form').props.onSubmit({ preventDefault() {} });
    await submit(); await settle(); assert(text(mounted.root).includes('连接失败'));
    await submit(); await settle();
    assert.equal(writes.length, 2); assert.equal(writes[0].request_id, writes[1].request_id);
    assert.equal(writes[0].name, '新课程');
    mounted.app.unmount();

    let reportTotal = 11;
    const reportPages = [];
    global.fetch = async path => {
      const url = new URL(path, 'http://test.local');
      if (path === '/api/courses') return response({ items: [course] });
      if (path === '/api/sessions') return response({ items: [session] });
      if (url.pathname === '/api/evaluations/report') {
        const offset = Number(url.searchParams.get('offset')); reportPages.push(offset);
        return response({ total: reportTotal, summary: {}, by_course: [], items: offset < reportTotal ? [{ ...session, clarity: 4, pace: 4, engagement: 4, gain: 4, comment: '分页回归记录' }] : [] });
      }
      throw new Error(path);
    };
    mounted = mount(EvaluationsPanel, { user: { role: 'TEACHER' } }); await settle();
    await button(mounted.root, '下一页评价').props.onClick(); await settle();
    assert(text(mounted.root).includes('第 2 页'));
    reportTotal = 1;
    await button(mounted.root, '刷新评价').props.onClick(); await settle();
    // Refresh intentionally starts on page zero; directly exercise the page-shrink response too.
    reportTotal = 11;
    await button(mounted.root, '刷新评价').props.onClick(); await settle();
    reportTotal = 1;
    await button(mounted.root, '下一页评价').props.onClick(); await settle();
    assert.deepEqual(reportPages.slice(-2), [10, 0]);
    assert(text(mounted.root).includes('分页回归记录'));
    mounted.app.unmount();

    let releasePoll;
    global.fetch = async (path, options = {}) => {
      if (path === '/api/messages?limit=1') return new Promise(resolve => releasePoll = () => resolve(response({ unread_count: 7 })));
      if (path.startsWith('/api/messages?')) return response({ items: [{ id: 1, kind: 'GUIDE', title: '通知', body: '指引', target_tab: 'classroom', created_at: new Date(now).toISOString(), read_at: null }], total: 1, unread_count: 1 });
      if (path === '/api/messages/read-all') return response({ unread_count: 0 });
      if (path === '/api/courses' || path === '/api/sessions') return response({ items: [] });
      if (path.startsWith('/api/emoji/history')) return response({ items: [], total: 0 });
      throw new Error(path);
    };
    mounted = mount(Workspace, { user: { id: 1, role: 'STUDENT', username: 'student' } }); await settle();
    await button(mounted.root, '消息中心').props.onClick(); await settle();
    global.fetch = new Proxy(global.fetch, { apply(target, self, args) {
      if (args[0].startsWith('/api/messages?') && args[0] !== '/api/messages?limit=1') return Promise.resolve(response({ items: [], total: 0, unread_count: 0 }));
      return Reflect.apply(target, self, args);
    } });
    await button(mounted.root, '全部标为已读').props.onClick(); await settle();
    releasePoll(); await settle();
    assert(!walk(mounted.root).some(n => /条未读消息$/.test(n.props['aria-label'] || '')), 'older poll cannot restore unread badge after marking read');
    console.log('Regression interactions passed: automatic start/end/deadline, course feedback entry, failed scope isolation, delayed AI response isolation, lost-response course retry, shrinking report pages and stale unread badge.');
  } finally {
    mounted?.app.unmount(); global.fetch = original.fetch; Date.now = original.now;
    global.setInterval = original.interval; global.clearInterval = original.clear; global.document = original.document;
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
