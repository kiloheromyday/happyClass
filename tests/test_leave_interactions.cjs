const assert = require('node:assert/strict');
const { createRenderer, h, nextTick } = require('../frontend/node_modules/vue');
const node = (type, text = '') => ({ type, text, props: {}, children: [], parent: null });
const detach = n => { if (n.parent) { n.parent.children.splice(n.parent.children.indexOf(n), 1); n.parent = null; } };
const renderer = createRenderer({ createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text), setText: (n, value) => n.text = value, setElementText: (n, value) => { n.text = value; n.children = []; }, patchProp: (n, key, old, value) => n.props[key] = value, insert(n, parent, anchor) { detach(n); const i = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(i < 0 ? parent.children.length : i, 0, n); n.parent = parent; }, remove: detach, parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] || null });
const walk = n => [n, ...n.children.flatMap(walk)], text = n => (n.type === '#comment' ? '' : n.text) + n.children.map(text).join('');
const find = (root, predicate) => { const n = walk(root).find(predicate); assert(n, 'Control not found'); return n; };
const button = (root, label) => find(root, n => n.type === 'button' && text(n) === label);
const field = (root, name) => find(root, n => n.props.name === name);
const form = (root, name) => find(root, n => n.type === 'form' && n.props.class === name);
const settle = async () => { for (let i = 0; i < 8; i++) { await new Promise(setImmediate); await nextTick(); } };
const mount = (component, props) => { const root = node('root'), app = renderer.createApp({ render: () => h(component, props) }); app.mount(root); return { root, app }; };

(async () => {
  const { LeavesPanel } = await import('../frontend/src/leaves.js');
  const { Workspace } = await import('../frontend/src/accounts.js');
  const originalFetch = global.fetch;
  const course = { id: 7, name: '数学分析', teacher_name: '数学教师' };
  const session = { id: 31, course_id: 7, course_name: '数学分析', starts_at: new Date(Date.now() + 86400000).toISOString(), ends_at: new Date(Date.now() + 90000000).toISOString(), status: 'UPCOMING', class_name: '数学班', classroom: '东区101', teacher_name: '数学教师' };
  const student = { id: 1, username: 'demo_student', role: 'STUDENT', status: 'ACTIVE' }, teacher = { id: 2, username: 'demo_teacher', role: 'TEACHER', status: 'ACTIVE' };
  const records = [], requests = [], dirty = [];
  let lost = true, conflict = false, mounted;
  const json = (data, status = 200, message = '已保存') => new Response(JSON.stringify({ data, message }), { status });
  global.fetch = async (path, options = {}) => {
    const url = new URL(path, 'http://local'), body = options.body ? JSON.parse(options.body) : undefined;
    requests.push({ path: url.pathname, body, query: url.searchParams });
    if (url.pathname === '/api/courses') return json({ items: [course] });
    if (url.pathname === '/api/sessions') return json({ items: [session] });
    if (url.pathname === '/api/emoji/history') return json({ items: [], total: 0 });
    if (url.pathname.endsWith('/questions')) return json({ items: [], total: 0, summary: { total: 0, open: 0, resolved: 0 } });
    if (url.pathname.endsWith('/learning-guide')) return json({ published: null });
    if (url.pathname === '/api/leaves') {
      if (body) {
        let item = records.find(item => item.request_id === body.request_id);
        if (!item) { item = { ...session, ...body, id: records.length + 1, student_name: '演示学生', student_username: 'demo_student', status: 'PENDING', version: 1, created_at: new Date().toISOString(), reviewed_at: null }; records.push(item); }
        if (lost) { lost = false; throw new TypeError('Lost response'); } return json(item);
      }
      const summary = Object.fromEntries(['PENDING', 'APPROVED', 'REJECTED', 'CANCELLED'].map(key => [key, records.filter(item => item.status === key).length]));
      const selected = records.filter(item => url.searchParams.get('status') === 'ALL' || item.status === url.searchParams.get('status'));
      return json({ items: selected.map(item => ({ ...item })), total: selected.length, summary });
    }
    if (url.pathname.endsWith('/cancel')) { const item = records.find(item => item.id === Number(url.pathname.split('/')[3])); item.status = 'CANCELLED'; item.version++; return json(item); }
    if (url.pathname.endsWith('/decision')) {
      if (conflict) { conflict = false; return json(null, 409, '申请状态已变化'); }
      const item = records.find(item => item.id === Number(url.pathname.split('/')[3])); Object.assign(item, { status: body.decision, reply: body.reply, reviewer_name: '数学教师', reviewed_at: new Date().toISOString(), version: item.version + 1 }); return json(item);
    }
    throw new Error(path);
  };
  try {
    mounted = mount(LeavesPanel, { user: student, initialSessionId: 31, onDirtyChange: value => dirty.push(value) }); await settle();
    assert.equal(field(mounted.root, 'leave_session').props.value, '31');
    field(mounted.root, 'leave_reason').props.onInput({ target: { value: '需要办理个人事务' } }); await nextTick(); assert.equal(dirty.at(-1), true);
    assert(field(mounted.root, 'leave_filter_status').props.disabled);
    await form(mounted.root, 'leave-request-form').props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(field(mounted.root, 'leave_reason').props.value, '需要办理个人事务');
    await form(mounted.root, 'leave-request-form').props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(records.length, 1); assert.equal(dirty.at(-1), false);
    const creates = requests.filter(item => item.path === '/api/leaves' && item.body); assert.equal(creates[0].body.request_id, creates[1].body.request_id);
    await button(mounted.root, '撤回申请').props.onClick(); await nextTick(); assert.equal(records[0].status, 'PENDING');
    await button(mounted.root, '确认撤回申请').props.onClick(); await settle(); assert.equal(records[0].status, 'CANCELLED');
    mounted.app.unmount();
    records.push({ ...records[0], id: 2, status: 'PENDING', version: 1, request_id: 'another' });
    mounted = mount(LeavesPanel, { user: teacher, onDirtyChange: value => dirty.push(value) }); await settle();
    assert(!walk(mounted.root).some(n => n.type === 'button' && text(n) === '申请请假'));
    await button(mounted.root, '处理申请').props.onClick(); await nextTick(); assert.equal(dirty.at(-1), true);
    field(mounted.root, 'leave_decision').props.onChange({ target: { value: 'REJECTED' } }); await nextTick();
    await form(mounted.root, 'leave-review-form').props.onSubmit({ preventDefault() {} }); await settle();
    assert(text(mounted.root).includes('请填写原因'));
    field(mounted.root, 'leave_reply').props.onInput({ target: { value: '请补充具体说明。' } }); conflict = true;
    await form(mounted.root, 'leave-review-form').props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(field(mounted.root, 'leave_reply').props.value, '请补充具体说明。');
    await form(mounted.root, 'leave-review-form').props.onSubmit({ preventDefault() {} }); await settle(); assert.equal(records[1].status, 'REJECTED');
    mounted.app.unmount();
    mounted = mount(LeavesPanel, { user: student }); await settle(); assert(text(mounted.root).includes('请补充具体说明。'));
    mounted.app.unmount();
    mounted = mount(LeavesPanel, { user: { role: 'ADMIN' } }); await settle();
    assert(text(mounted.root).includes('全校请假记录') && !walk(mounted.root).some(n => n.type === 'button' && ['申请请假', '处理申请', '撤回申请'].includes(text(n))));
    mounted.app.unmount();
    mounted = mount(Workspace, { user: student }); await settle();
    await button(mounted.root, '请假申请').props.onClick(); await settle();
    await button(mounted.root, '申请请假').props.onClick(); await nextTick();
    field(mounted.root, 'leave_reason').props.onInput({ target: { value: '尚未提交的原因' } }); await nextTick();
    await button(mounted.root, '我的课程').props.onClick(); await settle(); assert(text(mounted.root).includes('请假申请或审批尚未保存'));
    await button(mounted.root, '退出登录').props.onClick(); await settle(); assert(!requests.some(item => item.path === '/api/auth/logout'));
    await button(mounted.root, '放弃请假草稿').props.onClick(); await nextTick();
    await button(mounted.root, '我的课程').props.onClick(); await settle(); assert(text(mounted.root).includes('数学分析'));
    mounted.app.unmount(); mounted = null;
    let aborted = false;
    global.fetch = (path, options) => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => { aborted = true; reject(new DOMException('Aborted', 'AbortError')); }));
    mounted = mount(LeavesPanel, { user: student }); await settle(); mounted.app.unmount(); mounted = null; assert(aborted);
    console.log('Leave interactions passed: context form, request retry, cancel confirmation, teacher rejection and conflict drafts, student results, admin read-only, workspace guards and cancelled reads.');
  } finally { mounted?.app.unmount(); global.fetch = originalFetch; }
})().catch(error => { console.error(error); process.exitCode = 1; });
