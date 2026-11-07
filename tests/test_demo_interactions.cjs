// Full App interactions with isolated demo identities and member data.
const assert = require('node:assert/strict');
const { createRenderer, h, nextTick } = require('../frontend/node_modules/vue');
const node = (type, text = '') => ({ type, text, props: {}, children: [], parent: null });
const detach = n => { if (n.parent) { n.parent.children.splice(n.parent.children.indexOf(n), 1); n.parent = null; } };
const renderer = createRenderer({ createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text), setText: (n, text) => n.text = text, setElementText: (n, text) => { n.text = text; n.children = []; }, patchProp: (n, key, old, value) => n.props[key] = value, insert(n, parent, anchor) { detach(n); const index = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(index < 0 ? parent.children.length : index, 0, n); n.parent = parent; }, remove: detach, parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] || null });
const walk = n => [n, ...n.children.flatMap(walk)], text = n => (n.type === '#comment' ? '' : n.text) + n.children.map(text).join('');
const find = (root, match) => { const n = walk(root).find(match); assert(n, 'Control not found'); return n; };
const button = (root, label) => find(root, n => n.type === 'button' && text(n) === label);
const field = (root, name) => find(root, n => n.props.name === name);
const form = (root, name) => find(root, n => n.type === 'form' && String(n.props.class || '').includes(name));
const aria = (root, label) => find(root, n => n.props['aria-label'] === label);
const settle = async () => { for (let i = 0; i < 8; i++) { await new Promise(setImmediate); await nextTick(); } };
const mount = (component, props) => { const root = node('root'), app = renderer.createApp({ render: () => h(component, props) }); app.mount(root); return { root, app }; };

(async () => {
  const { App } = await import('../frontend/src/app.js');
  const { DeveloperPanel } = await import('../frontend/src/developer.js');
  const originalFetch = global.fetch, originalDocument = global.document;
  global.document = { hidden: false, visibilityState: 'visible', addEventListener() {}, removeEventListener() {} };
  const student = { id: 1, username: 'demo_student', role: 'STUDENT', status: 'ACTIVE', created_at: '2026-11-01T00:00:00Z' };
  const teacher = { ...student, id: 2, username: 'demo_teacher', role: 'TEACHER' };
  const admin = { ...student, id: 9, username: 'demo_admin', role: 'ADMIN' };
  const accounts = [{ username: student.username, role: 'STUDENT', label: '演示学生' }, { username: teacher.username, role: 'TEACHER', label: '演示教师' }, { username: admin.username, role: 'ADMIN', label: '演示管理员' }];
  const members = [{ ...student, email: null, nickname: '', protected: true }, { ...teacher, email: null, nickname: '', protected: true }, { ...student, id: 3, username: 'member_one', email: null, nickname: '', protected: false }];
  const classroom = { id: 1, course_id: 1, course_name: '演示课程', teacher_name: 'demo_teacher', status: 'ONGOING', can_feedback: true, feedback_closes_at: '2099-01-01T00:00:00Z', starts_at: new Date(Date.now() - 60000).toISOString(), ends_at: new Date(Date.now() + 60000).toISOString(), class_name: '演示一班', classroom: 'A101', scheduled_count: 3, record_count: 0 };
  const requests = []; let active = false, current = null, failUpdate = false, resetCount = 0;
  const json = (data, status = 200, message = '已保存') => new Response(JSON.stringify({ data, message }), { status });
  global.fetch = async (path, options = {}) => {
    const url = new URL(path, 'http://localhost'), body = options.body ? JSON.parse(options.body) : null;
    requests.push({ path: url.pathname, body });
    if (url.pathname === '/api/health') return json({ status: 'ok' });
    if (url.pathname === '/api/users/me') return current ? json(current) : json(null, 401);
    if (url.pathname === '/api/demo/status') return json({ enabled: true, active, accounts: active ? accounts : [] });
    if (url.pathname === '/api/demo/enable') { active = true; return json({ enabled: true, active, accounts }); }
    if (url.pathname === '/api/demo/disable') { active = false; return json({ enabled: true, active, accounts: [] }); }
    if (url.pathname === '/api/demo/login') { assert(!body.password); current = { demo_student: student, demo_teacher: teacher, demo_admin: admin }[body.username]; assert(current); return json(current); }
    if (url.pathname === '/api/demo/members') {
      if (body) { members.push({ ...student, ...body, id: members.length + 1, email: body.email, nickname: '', protected: false }); return json(members.at(-1), 201); }
      const matching = members.filter(item => (url.searchParams.get('role') === 'ALL' || item.role === url.searchParams.get('role')) && (url.searchParams.get('status') === 'ALL' || item.status === url.searchParams.get('status')) && `${item.username} ${item.nickname} ${item.email || ''}`.includes(url.searchParams.get('q')));
      return json({ items: matching, total: matching.length });
    }
    if (/\/api\/demo\/members\/\d+/.test(url.pathname)) {
      const item = members.find(item => item.id === Number(url.pathname.split('/')[4]));
      if (failUpdate) { failUpdate = false; return json(null, 401, '开发者模式已过期'); }
      if (url.pathname.endsWith('/password')) { resetCount++; return json(null); }
      Object.assign(item, body); return json(item);
    }
    if (url.pathname === '/api/sessions') return json({ items: [classroom] });
    if (url.pathname === '/api/admin/campus') return json({ courses: [], sessions: [], summary: { demo_feedback_count: 0 } });
    if (url.pathname === '/api/departments') return json({ items: [] });
    if (url.pathname === '/api/admin/people') return json({ items: members });
    if (url.pathname === '/api/admin/users') { assert.equal(current.role, 'ADMIN'); return json({ items: [...members, admin], total: members.length + 1 }); }
    if (url.pathname.endsWith('/roster')) return json({ items: [] });
    if (url.pathname.endsWith('/statistics')) return json({ session: classroom, total: 0, responding_students: 0, emotions: [], manual_count: 0, ai_count: 0 });
    if (url.pathname === '/api/courses') return json({ items: [{ id: 1, name: '演示课程' }] });
    if (url.pathname === '/api/emoji/history') return json({ items: [], total: 0 });
    if (url.pathname.endsWith('/questions')) return json({ items: [], total: 0, summary: { total: 0, open: 0, resolved: 0 } });
    if (url.pathname.endsWith('/learning-guide')) return json(current.role === 'STUDENT' ? { published: null } : { published: null, draft: { title: '', content: '', practice: '' }, version: 0 });
    if (url.pathname === '/api/teaching/overview') return json({ summary: { courses: 1, sessions: 1, ongoing: 1, open_questions: 0, pending_reflections: 0 }, sessions: [classroom] });
    throw new Error(`Unexpected request ${path}`);
  };
  let main;
  try {
    main = mount(App); await settle(); assert(text(main.root).includes('欢迎回到课堂'));
    await button(main.root, '开发者模式').props.onClick(); await nextTick();
    await button(main.root, '开启演示开发者模式').props.onClick(); await settle();
    assert(button(main.root, '演示学生') && button(main.root, '演示教师') && button(main.root, '演示管理员'));
    await button(main.root, '管理学生与教师').props.onClick(); await settle();
    assert(text(main.root).includes('固定演示账号') && !walk(main.root).some(n => n.props['aria-label'] === '切换成员状态：demo_student'));
    await button(main.root, '新建成员').props.onClick(); await nextTick();
    for (const [key, value] of [['username', 'new_teacher'], ['password', 'LocalOnly123!'], ['confirm', 'LocalOnly123!']]) field(main.root, `demo_${key}`).props.onInput({ target: { value } });
    field(main.root, 'demo_role').props.onChange({ target: { value: 'TEACHER' } }); await nextTick();
    assert(button(main.root, '演示教师').props.disabled, 'unsaved member creation prevents switching');
    assert(button(main.root, '演示管理员').props.disabled);
    const ordinaryLogin = find(main.root, n => n.type === 'form' && walk(n).some(child => child.props.name === 'username'));
    await ordinaryLogin.props.onSubmit({ preventDefault() {} }); await settle();
    assert(text(main.root).includes('成员修改尚未保存'));
    await form(main.root, 'demo-member-form').props.onSubmit({ preventDefault() {} }); await settle();
    assert(members.some(item => item.username === 'new_teacher' && item.role === 'TEACHER'));
    assert(!walk(main.root).some(n => n.props.name === 'demo_password'));
    await aria(main.root, '编辑成员：member_one').props.onClick(); await nextTick();
    field(main.root, 'demo_nickname').props.onInput({ target: { value: '新昵称' } }); await nextTick();
    failUpdate = true; await form(main.root, 'demo-member-form').props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(field(main.root, 'demo_nickname').props.value, '新昵称');
    await button(main.root, '重新开启开发者模式').props.onClick(); await settle();
    assert.equal(field(main.root, 'demo_nickname').props.value, '新昵称', 'renewing capability preserves member edits');
    await form(main.root, 'demo-member-form').props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(members[2].nickname, '新昵称');
    await aria(main.root, '切换成员状态：member_one').props.onClick(); await nextTick(); assert.equal(members[2].status, 'ACTIVE');
    await button(main.root, '确认停用').props.onClick(); await settle(); assert.equal(members[2].status, 'DISABLED');
    await aria(main.root, '切换成员状态：member_one').props.onClick(); await nextTick(); await button(main.root, '确认启用').props.onClick(); await settle(); assert.equal(members[2].status, 'ACTIVE');
    await aria(main.root, '重设密码：member_one').props.onClick(); await nextTick();
    field(main.root, 'demo_password').props.onInput({ target: { value: 'ChangedPass123!' } }); field(main.root, 'demo_confirm').props.onInput({ target: { value: 'ChangedPass123!' } }); await nextTick();
    await form(main.root, 'demo-member-form').props.onSubmit({ preventDefault() {} }); await nextTick(); assert.equal(resetCount, 0);
    await form(main.root, 'demo-member-form').props.onSubmit({ preventDefault() {} }); await settle(); assert.equal(resetCount, 1);
    await button(main.root, '演示学生').props.onClick(); await settle();
    assert(text(main.root).includes('此刻，你感觉如何？') && !text(main.root).includes('欢迎回到课堂'));
    field(main.root, 'question_text').props.onInput({ target: { value: '尚未提交的问题' } }); await nextTick();
    assert(button(main.root, '演示教师').props.disabled);
    assert(button(main.root, '演示管理员').props.disabled);
    await button(main.root, '清空问题草稿').props.onClick(); await settle();
    await button(main.root, '演示教师').props.onClick(); await settle();
    assert(text(main.root).includes('课堂与跟进') && !text(main.root).includes('提交本次感受'), 'changing identity remounts role workspace');
    await button(main.root, '演示管理员').props.onClick(); await settle();
    assert(text(main.root).includes('课程与课堂') && !text(main.root).includes('好友学伴'));
    await button(main.root, '用户列表').props.onClick(); await settle();
    assert(text(main.root).includes('demo_admin') && requests.some(item => item.path === '/api/admin/users'));
    await button(main.root, '演示学生').props.onClick(); await settle(); assert(text(main.root).includes('提交本次感受') && !walk(main.root).some(n => n.type === 'button' && text(n) === '用户列表'));
    await button(main.root, '关闭开发者模式').props.onClick(); await settle();
    assert(text(main.root).includes('提交本次感受') && !walk(main.root).some(n => n.type === 'button' && text(n) === '演示教师'));
    assert.deepEqual(requests.filter(item => item.path === '/api/demo/login').map(item => item.body.username), ['demo_student', 'demo_teacher', 'demo_admin', 'demo_student']);
    main.app.unmount(); main = null;
    let aborted = false;
    global.fetch = (path, options) => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => { aborted = true; reject(new DOMException('Aborted', 'AbortError')); }));
    const pending = mount(DeveloperPanel, { state: { enabled: true, active: true, accounts }, user: student });
    await button(pending.root, '管理学生与教师').props.onClick(); await settle(); pending.app.unmount(); assert(aborted);
    console.log('Demo App interactions passed: login entry, capability renewal, member create/edit/status/password confirmations, protected accounts, real role switching, draft guards, mode close and cancellation.');
  } finally { main?.app.unmount(); global.fetch = originalFetch; global.document = originalDocument; }
})().catch(error => { console.error(error); process.exitCode = 1; });
