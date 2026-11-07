// Actual Vue components with a shared isolated teacher/student mock service.
const assert = require('node:assert/strict');
const { createRenderer, h, nextTick } = require('../frontend/node_modules/vue');
const node = (type, text = '') => ({ type, text, props: {}, children: [], parent: null });
const detach = child => { if (child.parent) { child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null; } };
const renderer = createRenderer({
  createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text),
  setText: (n, text) => n.text = text, setElementText: (n, text) => { n.text = text; n.children = []; }, patchProp: (n, key, old, value) => n.props[key] = value,
  insert(n, parent, anchor) { detach(n); const index = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(index < 0 ? parent.children.length : index, 0, n); n.parent = parent; },
  remove: detach, parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] || null,
});
const walk = n => [n, ...n.children.flatMap(walk)];
const text = n => (n.type === '#comment' ? '' : n.text) + n.children.map(text).join('');
const find = (root, predicate) => { const n = walk(root).find(predicate); assert(n, 'Expected control not found'); return n; };
const button = (root, label) => find(root, n => n.type === 'button' && text(n) === label);
const aria = (root, label) => find(root, n => n.props['aria-label'] === label);
const field = (root, name) => find(root, n => n.props.name === name);
const form = (root, className) => find(root, n => n.type === 'form' && String(n.props.class || '').includes(className));
const settle = async () => { for (let i = 0; i < 8; i++) { await new Promise(setImmediate); await nextTick(); } };
const mount = (component, props) => { const root = node('root'), app = renderer.createApp({ render: () => h(component, props) }); app.mount(root); return { root, app }; };

(async () => {
  const { Workspace } = await import('../frontend/src/accounts.js');
  const { LearningGuidePanel } = await import('../frontend/src/learning-guide.js');
  const { TeachingPanel } = await import('../frontend/src/teaching.js');
  const originalFetch = global.fetch, originalDocument = global.document;
  global.document = { hidden: false, visibilityState: 'visible', addEventListener() {}, removeEventListener() {} };
  const teacher = { id: 2, username: 'teacher01', role: 'TEACHER' }, student = { id: 3, username: 'student01', role: 'STUDENT' };
  const course = { id: 9, name: '软件工程', teacher_name: 'teacher01' };
  const current = { id: 21, course_id: 9, course_name: course.name, teacher_name: 'teacher01', starts_at: new Date(Date.now() - 60000).toISOString(), ends_at: new Date(Date.now() + 60000).toISOString(), feedback_closes_at: '2099-01-01T00:00:00Z', status: 'ONGOING', can_feedback: true, scheduled_count: 1, record_count: 4, class_name: '软件一班', classroom: 'B201' };
  const ended = { ...current, id: 22, status: 'ENDED', can_feedback: false, starts_at: '2026-11-01T08:00:00Z', ends_at: '2026-11-01T10:00:00Z', feedback_closes_at: '2026-11-01T10:30:00Z' };
  const sessions = [current, ended], guides = new Map(), keys = new Map(), requests = [];
  const question = { id: 1, category: 'EXAMPLE', text: '想看一个完整的例子', reply: '', status: 'OPEN', version: 1, created_at: ended.starts_at };
  let reflection = { reflection: '', version: 0 }, activeRole = 'TEACHER', failSchedule = true, conflict = false;
  const metrics = { total: 4, responding_students: 1, manual_count: 4, ai_count: 0 };
  const emptyGuide = () => ({ draft: { title: '', content: '', practice: '' }, version: 0, published: null });
  const json = (data, status = 200, message = '已保存') => new Response(JSON.stringify({ data, message }), { status });
  global.fetch = async (path, options = {}) => {
    const url = new URL(path, 'http://localhost'), body = options.body ? JSON.parse(options.body) : null;
    requests.push({ path: url.pathname, params: Object.fromEntries(url.searchParams), body });
    if (url.pathname === '/api/teaching/overview') return json({ summary: { courses: 1, sessions: sessions.length, ongoing: 1, upcoming: sessions.length-2, open_questions: question.status === 'OPEN' ? 1 : 0, pending_reflections: reflection.reflection ? 0 : 1 }, sessions: sessions.map(item => ({ ...item, question_count: item.id === 22 ? 1 : 0, open_questions: item.id === 22 && question.status === 'OPEN' ? 1 : 0, has_reflection: Boolean(reflection.reflection), guide_published: Boolean(guides.get(item.id)?.published) })) });
    if (url.pathname === '/api/courses') return json({ items: [course] });
    if (url.pathname === '/api/sessions' || url.pathname === '/api/personal/notes/sessions') return json({ items: sessions });
    if (url.pathname === '/api/courses/9') return json({ course, sessions: sessions.map(item => ({ ...item, guide_published: Boolean(guides.get(item.id)?.published), personal: { feedback_count: 1, note_count: 0, pending_count: 0 } })), summary: { total: sessions.length, ended: 1, ongoing: 1, upcoming: sessions.length-2, feedback_count: 2, note_count: 0, pending_count: 0, participated_sessions: 2 } });
    if (url.pathname === '/api/teaching/sessions') {
      let created = keys.get(body.request_id);
      if (!created) { created = { ...current, ...body, id: 23, status: 'UPCOMING', can_feedback: false }; sessions.push(created); keys.set(body.request_id, created); }
      if (failSchedule) { failSchedule = false; throw new TypeError('Lost response after committing'); }
      return json(created);
    }
    if (url.pathname === '/api/emoji/history' || url.pathname === '/api/personal/notes') return json({ items: [], total: 0 });
    if (/\/learning-guide$/.test(url.pathname)) {
      const id = Number(url.pathname.split('/')[3]); let guide = guides.get(id) || emptyGuide();
      if (options.method === 'PUT') {
        if (conflict) return json(null, 409, '学习指引已被更新');
        guide = { ...guide, draft: { title: body.title, content: body.content, practice: body.practice }, version: guide.version + 1 };
        if (body.action === 'PUBLISH') guide.published = { ...guide.draft, published_at: current.starts_at };
        if (body.action === 'UNPUBLISH') guide.published = null;
        guides.set(id, guide);
      }
      return json(activeRole === 'STUDENT' ? { published: guide.published } : guide);
    }
    if (/\/questions\/1$/.test(url.pathname)) { Object.assign(question, body, { version: question.version + 1 }); return json(question); }
    if (/\/questions$/.test(url.pathname)) return json({ items: url.pathname.includes('/22/') ? [question] : [], total: url.pathname.includes('/22/') ? 1 : 0, summary: { total: 1, open: question.status === 'OPEN' ? 1 : 0, resolved: question.status === 'RESOLVED' ? 1 : 0 } });
    if (/\/roster$/.test(url.pathname)) return json({ items: [student] });
    if (/\/sessions\/\d+\/statistics$/.test(url.pathname)) return json({ ...metrics, emotions: [], session: ended });
    if (/\/recap$/.test(url.pathname)) {
      if (body) reflection = { reflection: body.reflection, version: reflection.version + 1 };
      if (body) return json(reflection);
      return json({ session: ended, summary: metrics, periods: [], questions: { total: 1, resolved: 1, categories: [] }, reflection, generated_at: current.starts_at });
    }
    if (/\/join-code$/.test(url.pathname)) return json({ code: null, version: 0, status: 'NONE' });
    if (url.pathname === '/api/dashboard/realtime') return json({ session: sessions.find(item => item.id === Number(url.searchParams.get('session_id'))), summary: metrics, emotions: [], trend: [], latest: [], updated_at: current.starts_at });
    if (url.pathname === '/api/reports/statistics') return json({ summary: metrics, emotions: [], trend: [], by_course: [], by_class: [], filters: { course_id: 9, bucket: 'day' }, updated_at: current.starts_at });
    if (url.pathname === '/api/ai/status') return json({ ready: true });
    throw new Error(`Unexpected mocked request ${path}`);
  };
  let staff, learner;
  try {
    staff = mount(Workspace, { user: teacher }); await settle();
    assert(text(staff.root).includes('教学工作台') && text(staff.root).includes('待写教学反思'));
    await aria(staff.root, '回应问题：22').props.onClick(); await settle();
    assert.equal(field(staff.root, 'daily_session').props.value, '22');
    await button(staff.root, '回应问题').props.onClick(); await nextTick();
    field(staff.root, 'question_reply').props.onInput({ target: { value: '下次用完整案例演示。' } }); await nextTick();
    await button(staff.root, '学习指引').props.onClick(); await nextTick();
    assert(text(staff.root).includes('本节课堂有未保存'));
    await button(staff.root, '教学工作台').props.onClick(); await nextTick();
    assert(text(staff.root).includes('课堂中有未保存'));
    field(staff.root, 'question_resolved').props.onChange({ target: { checked: true } });
    await form(staff.root, 'question-answer').props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(question.status, 'RESOLVED');
    await button(staff.root, '学习指引').props.onClick(); await settle();
    for (const [name, value] of [['title', '设计实践'], ['content', '从需求走向设计'], ['practice', '画出自己的用例图']]) field(staff.root, `guide_${name}`).props.onInput({ target: { value } }); await nextTick();
    await button(staff.root, '我的课程').props.onClick(); await nextTick(); assert(text(staff.root).includes('课堂中有未保存'));
    await form(staff.root, 'guide-editor').props.onSubmit({ preventDefault() {} }); await settle();
    assert(!guides.get(22).published && guides.get(22).draft.title === '设计实践');
    activeRole = 'STUDENT'; learner = mount(Workspace, { user: student }); await settle();
    assert(!text(learner.root).includes('从需求走向设计'));
    await button(learner.root, '我的课程').props.onClick(); await settle();
    await aria(learner.root, '查看课程详情：软件工程').props.onClick(); await settle();
    assert(!walk(learner.root).some(n => n.props['aria-label'] === '学习指引：22'));
    activeRole = 'TEACHER'; await button(staff.root, '发布到学生课堂').props.onClick(); await settle();
    activeRole = 'STUDENT'; await button(learner.root, '刷新').props.onClick(); await settle();
    await aria(learner.root, '学习指引：22').props.onClick(); await settle();
    assert(text(learner.root).includes('从需求走向设计') && text(learner.root).includes('画出自己的用例图'));
    assert(!walk(learner.root).some(n => n.props.name === 'guide_content'), 'student sees published content, not editor');
    await button(learner.root, '写课堂笔记').props.onClick(); await settle();
    assert.equal(field(learner.root, 'notes_session_filter').props.value, '22');
    learner.app.unmount(); learner = null;
    activeRole = 'TEACHER'; field(staff.root, 'guide_content').props.onInput({ target: { value: '第二版未发布内容' } }); await nextTick();
    await form(staff.root, 'guide-editor').props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(guides.get(22).published.content, '从需求走向设计');
    field(staff.root, 'guide_content').props.onInput({ target: { value: '冲突时保留我的内容' } }); await nextTick();
    conflict = true; await form(staff.root, 'guide-editor').props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(field(staff.root, 'guide_content').props.value, '冲突时保留我的内容');
    assert(text(staff.root).includes('学习指引已被更新'));
    conflict = false; await button(staff.root, '放弃修改并刷新指引').props.onClick(); await settle();
    await button(staff.root, '撤下已发布指引').props.onClick(); await nextTick(); assert(guides.get(22).published);
    await button(staff.root, '确认撤下学习指引').props.onClick(); await settle(); assert(!guides.get(22).published);
    await button(staff.root, '课后小结').props.onClick(); await settle();
    field(staff.root, 'classroom_reflection').props.onInput({ target: { value: '下一节增加练习与示例。' } }); await nextTick();
    await button(staff.root, '教学工作台').props.onClick(); await nextTick(); assert(text(staff.root).includes('课堂中有未保存'));
    await form(staff.root, 'reflection-form').props.onSubmit({ preventDefault() {} }); await settle();
    await button(staff.root, '教学工作台').props.onClick(); await settle(); assert(text(staff.root).includes('暂时没有待跟进事项'));
    await button(staff.root, '我的课程').props.onClick(); await settle(); await aria(staff.root, '查看课程详情：软件工程').props.onClick(); await settle();
    await button(staff.root, '安排新课堂').props.onClick(); await nextTick();
    field(staff.root, 'schedule_classroom').props.onInput({ target: { value: 'B202' } }); field(staff.root, 'schedule_class_name').props.onInput({ target: { value: '软件一班' } }); await nextTick();
    await button(staff.root, '返回我的课程').props.onClick(); await nextTick(); assert(text(staff.root).includes('新课堂安排尚未保存'));
    await button(staff.root, '教学工作台').props.onClick(); await nextTick(); assert(field(staff.root, 'schedule_classroom'));
    const scheduleForm = find(staff.root, n => n.type === 'form' && walk(n).some(child => child.props.name === 'schedule_classroom'));
    await scheduleForm.props.onSubmit({ preventDefault() {} }); await settle(); assert(text(staff.root).includes('连接失败'));
    await scheduleForm.props.onSubmit({ preventDefault() {} }); await settle();
    const scheduleRequests = requests.filter(item => item.path === '/api/teaching/sessions');
    assert.equal(scheduleRequests.length, 2); assert.equal(scheduleRequests[0].body.request_id, scheduleRequests[1].body.request_id); assert.equal(sessions.length, 3);
    assert(text(staff.root).includes('B202'));
    await aria(staff.root, '实时看板：22').props.onClick(); await settle();
    assert.equal(requests.filter(item => item.path === '/api/dashboard/realtime').at(-1).params.session_id, '22');
    await button(staff.root, '打开对应课堂').props.onClick(); await settle();
    await button(staff.root, '查看课程统计').props.onClick(); await settle();
    assert.equal(requests.filter(item => item.path === '/api/reports/statistics').at(-1).params.course_id, '9');
    staff.app.unmount(); staff = null;
    let denied = false;
    global.fetch = async () => denied ? json(null, 403, '已不在课堂名单中') : json({ published: { title: '已发布课堂内容', content: '权限变更后应隐藏', practice: '' } });
    const removed = mount(LearningGuidePanel, { user: student, sessionId: 22 }); await settle();
    assert(text(removed.root).includes('权限变更后应隐藏'));
    denied = true; await button(removed.root, '刷新学习指引').props.onClick(); await settle();
    assert(!text(removed.root).includes('权限变更后应隐藏') && text(removed.root).includes('已不在课堂名单中'));
    removed.app.unmount();
    let aborted = 0;
    global.fetch = (path, options) => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => { aborted++; reject(new DOMException('Aborted', 'AbortError')); }));
    const pendingHome = mount(TeachingPanel, { user: teacher }); await settle(); pendingHome.app.unmount();
    const pendingGuide = mount(LearningGuidePanel, { user: teacher, sessionId: 22 }); await settle(); pendingGuide.app.unmount();
    assert.equal(aborted, 2);
    console.log('Teaching interactions passed: exact classroom actions, question responses, public guide vs drafts, student notes, unsaved/conflict protection, recap follow-up, schedule retry, dashboard/report context and read cancellation.');
  } finally { staff?.app.unmount(); learner?.app.unmount(); global.fetch = originalFetch; global.document = originalDocument; }
})().catch(error => { console.error(error); process.exitCode = 1; });
