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
const change = (root, name, value) => field(root, name).props.onChange({ target: { value } });

(async () => {
  const { EvaluationsPanel } = await import('../frontend/src/evaluations.js');
  const { MessagesPanel } = await import('../frontend/src/messages.js');
  const { CatalogPanel } = await import('../frontend/src/catalog.js');
  const { CampusPanel } = await import('../frontend/src/campus.js');
  const { Workspace } = await import('../frontend/src/accounts.js');
  const originalFetch = global.fetch, originalWindow = global.window;
  const student = { id: 1, role: 'STUDENT', username: 'student01' }, teacher = { id: 2, role: 'TEACHER' }, admin = { id: 3, role: 'ADMIN' };
  const course = { id: 10, name: '数值分析', teacher_id: 2, teacher_name: '教师', department_id: 'math', department_name: '数学学院', department_short: '数学', department_color: '#668572', is_demo: 1, version: 1, archived: 0 };
  const session = { ...course, id: 12, course_id: 10, course_name: course.name, starts_at: new Date(Date.now() - 60000).toISOString(), ends_at: new Date(Date.now() + 60000).toISOString(), feedback_closes_at: new Date(Date.now() + 1860000).toISOString(), status: 'ONGOING', can_feedback: true, classroom: '101', class_name: '一班', scheduled_count: 1, record_count: 0 };
  const unit = { id: 'math', name: '数学学院', short_name: '数学', color: '#668572', background: '#f0f5eb', version: 1 };
  let currentEvaluation = null, lost = true, conflict = false, mounted;
  const requests = [], dirty = [], navigation = [], counts = [];
  const message = { id: 1, kind: 'GUIDE', title: '学习指引已发布', body: '概念和例子', target_tab: 'classroom', session_id: 12, course_id: 10, created_at: new Date().toISOString(), read_at: null };
  const response = (data, status = 200, message = '已保存') => new Response(JSON.stringify({ data, message }), { status, headers: { 'Content-Type': 'application/json' } });
  global.window = { addEventListener() {}, removeEventListener() {} };
  global.fetch = async (path, options = {}) => {
    const url = new URL(path, 'http://test.local'), body = options.body ? JSON.parse(options.body) : null;
    requests.push({ path: url.pathname, params: Object.fromEntries(url.searchParams), method: options.method || 'GET', body });
    if (url.pathname === '/api/courses') return response({ items: [course] });
    if (url.pathname === '/api/sessions') return response({ items: [session] });
    if (url.pathname === '/api/departments') return response({ items: [unit] });
    if (url.pathname === '/api/admin/people') return response({ items: [{ ...teacher, username: 'teacher01' }] });
    if (url.pathname === '/api/sessions/12/evaluation') {
      if (options.method === 'PUT') {
        if (conflict) return response(null, 409, '评价已更新，草稿已保留');
        currentEvaluation = { ...body, version: 1 };
        if (lost) { lost = false; throw new Error('lost response'); }
        return response(currentEvaluation);
      }
      return response({ item: currentEvaluation });
    }
    if (url.pathname === '/api/evaluations/report') return response({ summary: { total: 1, clarity: 5, pace: 4, engagement: 3, gain: 5 }, total: 1, items: [{ ...session, course_name: '数值分析', clarity: 5, pace: 4, engagement: 3, gain: 5, comment: '希望增加例子' }], by_course: [{ course_name: '数值分析', total: 1, average: 4.25 }] });
    if (url.pathname === '/api/messages') return response({ items: url.searchParams.get('unread') === 'true' && message.read_at ? [] : [message], total: 1, unread_count: message.read_at ? 0 : 1 });
    if (url.pathname === '/api/messages/1/read' || url.pathname === '/api/messages/read-all') { message.read_at = new Date().toISOString(); return response({ unread_count: 0 }); }
    if (url.pathname === '/api/admin/departments/math' && options.method === 'PUT') { if (conflict) return response(null, 409, '信息已更新'); Object.assign(unit, body, { version: unit.version + 1 }); return response(unit); }
    if (url.pathname === '/api/admin/courses/10') { Object.assign(course, body, { version: course.version + 1 }); return response(course); }
    if (url.pathname === '/api/admin/campus') return response({ courses: url.searchParams.get('data_scope') === 'REAL' ? [] : [{ ...course, summary: { feedback_count: 0, session_count: 1, responding_students: 0, demo_feedback_count: 0 }, emotions: [] }], sessions: [session], summary: { demo_feedback_count: 0 } });
    if (url.pathname === '/api/emoji/history') return response({ items: [], total: 0 });
    if (url.pathname === '/api/sessions/12/learning-guide') return response({ published: null });
    if (url.pathname === '/api/sessions/12/questions') return response({ items: [], total: 0, summary: { open: 0, total: 0 } });
    throw new Error(path);
  };
  try {
    mounted = mount(EvaluationsPanel, { user: student, initialSessionId: 12, onDirtyChange: value => dirty.push(value) }); await settle();
    assert.equal(field(mounted.root, 'evaluation_session').props.value, '12');
    for (const label of ['讲解清晰', '节奏合适', '课堂互动', '学习收获']) { await find(mounted.root, n => n.props['aria-label'] === `${label} 5 分`).props.onClick(); await nextTick(); }
    field(mounted.root, 'evaluation_comment').props.onInput({ target: { value: '请保留我的建议' } }); await nextTick(); assert(dirty.at(-1));
    const form = find(mounted.root, n => n.type === 'form'); await form.props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(field(mounted.root, 'evaluation_comment').props.value, '请保留我的建议');
    await form.props.onSubmit({ preventDefault() {} }); await settle();
    const writes = requests.filter(r => r.path.endsWith('/evaluation') && r.method === 'PUT'); assert.equal(writes[0].body.request_id, writes[1].body.request_id);
    assert(!dirty.at(-1) && text(mounted.root).includes('更新课程评价'));
    conflict = true; field(mounted.root, 'evaluation_comment').props.onInput({ target: { value: '冲突时保留草稿' } }); await nextTick(); await form.props.onSubmit({ preventDefault() {} }); await settle();
    assert(text(mounted.root).includes('草稿已保留') && field(mounted.root, 'evaluation_comment').props.value === '冲突时保留草稿');
    await button(mounted.root, '放弃评价草稿').props.onClick(); await nextTick(); assert(!dirty.at(-1)); mounted.app.unmount(); conflict = false;

    mounted = mount(EvaluationsPanel, { user: teacher, initialCourseId: 10, initialDataScope: 'REAL' }); await settle();
    assert(text(mounted.root).includes('匿名评价') && text(mounted.root).includes('希望增加例子'));
    assert(!walk(mounted.root).some(n => n.props.name === 'evaluation_comment'));
    assert.equal(requests.filter(r => r.path === '/api/evaluations/report').at(-1).params.data_scope, 'REAL');
    change(mounted.root, 'data_scope', 'DEMO'); await settle(); assert.equal(requests.filter(r => r.path === '/api/evaluations/report').at(-1).params.data_scope, 'DEMO'); mounted.app.unmount();

    mounted = mount(MessagesPanel, { onUnreadChange: value => counts.push(value), onNavigate: value => navigation.push(value) }); await settle();
    assert.equal(counts.at(-1), 1);
    await button(mounted.root, '查看详情').props.onClick(); await settle();
    assert.equal(counts.at(-1), 0); assert.deepEqual(navigation.at(-1), { tab: 'classroom', sessionId: 12, courseId: 10, view: 'guide' }); mounted.app.unmount();

    mounted = mount(CatalogPanel, { onDirtyChange: value => dirty.push(value) }); await settle();
    await button(mounted.root, '院系与配色').props.onClick(); await nextTick(); await button(mounted.root, '编辑信息').props.onClick(); await nextTick();
    assert.equal(field(mounted.root, 'catalog_id').props.disabled, true);
    field(mounted.root, 'catalog_name').props.onInput({ target: { value: '数学科学学院' } }); await nextTick(); assert(dirty.at(-1));
    conflict = true; await find(mounted.root, n => n.type === 'form').props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(field(mounted.root, 'catalog_name').props.value, '数学科学学院'); conflict = false;
    await find(mounted.root, n => n.type === 'form').props.onSubmit({ preventDefault() {} }); await settle(); assert.equal(unit.name, '数学科学学院'); assert(!dirty.at(-1));
    await button(mounted.root, '课程维护').props.onClick(); await nextTick(); await button(mounted.root, '编辑信息').props.onClick(); await nextTick();
    const archive = find(mounted.root, n => n.type === 'input' && n.props.type === 'checkbox'); archive.props.onChange({ target: { checked: true } }); await nextTick();
    await find(mounted.root, n => n.type === 'form').props.onSubmit({ preventDefault() {} }); await settle(); assert(course.archived); mounted.app.unmount();

    mounted = mount(CampusPanel, { onNavigate: value => navigation.push(value) }); await settle();
    change(mounted.root, 'data_scope', 'DEMO'); await settle(); await button(mounted.root, '课程与评价').props.onClick(); await nextTick(); await button(mounted.root, '评价统计').props.onClick();
    assert.deepEqual(navigation.at(-1), { tab: 'reports', courseId: 10, dataScope: 'DEMO' });
    change(mounted.root, 'data_scope', 'REAL'); await settle(); assert(text(mounted.root).includes('没有符合条件的课程')); mounted.app.unmount();

    mounted = mount(Workspace, { user: student }); await settle(); await button(mounted.root, '课程评价').props.onClick(); await settle();
    field(mounted.root, 'evaluation_comment').props.onInput({ target: { value: '未保存的评价' } }); await nextTick();
    await button(mounted.root, '消息中心').props.onClick(); await nextTick(); assert(text(mounted.root).includes('表单内容尚未保存'));
    assert.equal(field(mounted.root, 'evaluation_comment').props.value, '未保存的评价');
    await button(mounted.root, '退出登录').props.onClick(); await nextTick(); assert.equal(field(mounted.root, 'evaluation_comment').props.value, '未保存的评价');
    await button(mounted.root, '放弃评价草稿').props.onClick(); await nextTick(); await button(mounted.root, '消息中心').props.onClick(); await settle(); assert(text(mounted.root).includes('学习指引已发布')); mounted.app.unmount(); mounted = null;
    let aborted = false;
    global.fetch = (path, options) => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => { aborted = true; reject(new DOMException('Aborted', 'AbortError')); }));
    mounted = mount(MessagesPanel, {}); await settle(); mounted.app.unmount(); mounted = null; assert(aborted);
    console.log('Extension interactions passed: evaluation score/save/retry/conflict drafts, staff anonymity, source context, messages/read/navigation, catalog colors/archive/conflicts, workspace guards and aborted reads.');
  } finally { mounted?.app.unmount(); global.fetch = originalFetch; global.window = originalWindow; }
})().catch(error => { console.error(error); process.exitCode = 1; });
