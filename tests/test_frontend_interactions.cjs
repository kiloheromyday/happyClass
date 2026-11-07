// In-memory Vue interactions. No browser, network, database or physical camera.
const assert = require('node:assert/strict');
const { createRenderer, h, nextTick } = require('../frontend/node_modules/vue');

const node = (type, text = '') => ({ type, text, props: {}, children: [], parent: null });
const detach = child => { if (child.parent) { const siblings = child.parent.children; siblings.splice(siblings.indexOf(child), 1); child.parent = null; } };
const renderer = createRenderer({
  createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text),
  setText: (target, text) => { target.text = text; },
  setElementText: (target, text) => { target.children.forEach(child => child.parent = null); target.children = []; target.text = text; },
  patchProp: (target, key, previous, value) => { target.props[key] = value; },
  insert(child, parent, anchor = null) { detach(child); const index = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(index < 0 ? parent.children.length : index, 0, child); child.parent = parent; },
  remove: detach, parentNode: target => target.parent,
  nextSibling: target => target.parent?.children[target.parent.children.indexOf(target) + 1] || null,
});
const text = target => (target.type === '#comment' ? '' : target.text) + target.children.map(text).join('');
const walk = target => [target, ...target.children.flatMap(walk)];
const find = (root, predicate) => { const found = walk(root).find(predicate); assert(found, 'Expected component control not found'); return found; };
const button = (root, label) => find(root, target => target.type === 'button' && text(target) === label);
const field = (root, name) => find(root, target => target.type === 'input' && target.props.name === name);
const hasClass = (target, name) => String(target.props.class || '').split(' ').includes(name);
const settle = async () => { for (let i = 0; i < 8; i++) { await new Promise(setImmediate); await nextTick(); } };
const mount = (component, props = {}) => { const root = node('root'); const app = renderer.createApp({ render: () => h(component, props) }); app.mount(root); return { root, unmount: () => app.unmount() }; };

(async () => {
  const { App } = await import('../frontend/src/app.js');
  const { Workspace } = await import('../frontend/src/accounts.js');
  const { CameraPanel } = await import('../frontend/src/camera.js');
  const { QuestionsPanel, RecapPanel } = await import('../frontend/src/engagement.js');
  const { PersonalNotesPanel } = await import('../frontend/src/notes.js');
  const { BuddyWallPanel } = await import('../frontend/src/wall.js');
  const { JoinClassPanel, JoinCodePanel } = await import('../frontend/src/join-codes.js');
  const originalFetch = global.fetch, originalDocument = global.document;
  const originalSetInterval = global.setInterval, originalClearInterval = global.clearInterval;
  const originalWindow = global.window;
  const originalNavigator = Object.getOwnPropertyDescriptor(global, 'navigator');
  const listeners = new Set();
  global.document = { hidden: false, visibilityState: 'visible', addEventListener: (name, fn) => listeners.add(fn), removeEventListener: (name, fn) => listeners.delete(fn) };
  const student = { id: 1, username: 'student01', role: 'STUDENT', email: null, status: 'ACTIVE', created_at: '2026-11-03T00:00:00Z' };
  const teacher = { ...student, id: 2, username: 'teacher01', role: 'TEACHER' };
  const session = { id: 1, course_id: 1, course_name: '测试课程', class_name: '测试班', classroom: 'A101', teacher_name: 'teacher01', status: 'ONGOING', can_feedback: true, feedback_closes_at: '2099-11-03T12:30:00Z', starts_at: new Date(Date.now() - 60000).toISOString(), ends_at: new Date(Date.now() + 60000).toISOString(), scheduled_count: 1 };
  const records = [], requests = [], mounted = [];
  const questions = [];
  const personalNotes = [];
  const wallMessages = [], wallKeys = new Map();
  let joinCode = { code: null, version: 0, expires_at: null, status: 'NONE', updated_at: null };
  let reflection = { reflection: '', version: 0, updated_at: null };
  const peer = { id: 90, username: 'buddy01', nickname: '同桌', bio: '一起学习', interests: '设计 / Python', avatar_color: 'sky', major: '计算机', grade: '大二', study_goal: '项目实践', learning_style: 'project' };
  const invitation = { id: 91, username: 'buddy02', nickname: '小北', bio: '', interests: '', avatar_color: 'sand', request_id: 41 };
  const buddies = { friends: [], incoming: [invitation], outgoing: [] };
  let currentUser = null, pendingUpload = false, uploadCancelled = false;
  const json = (data, status = 200) => new Response(JSON.stringify({ code: status === 200 ? 'OK' : 'UNAUTHORIZED', message: status === 200 ? '已保存' : '请登录', data }), { status, headers: { 'Content-Type': 'application/json' } });
  const emotions = () => ['HAPPY', 'NEUTRAL', 'SAD', 'ANGRY', 'SURPRISED', 'FEAR', 'DISGUST'].map(emotion => ({ emotion, count: records.filter(record => record.emotion === emotion).length }));
  const summary = () => ({ total: records.length, responding_students: records.length ? 1 : 0, session_count: 1, ai_count: 0, manual_count: records.length });
  const questionSummary = () => ({ total: questions.length, open: questions.filter(item => item.status === 'OPEN').length, resolved: questions.filter(item => item.status === 'RESOLVED').length, categories: ['PACE', 'EXAMPLE', 'REPEAT', 'OTHER'].map(category => ({ category, count: questions.filter(item => item.category === category).length })) });
  global.fetch = async (path, options = {}) => {
    const url = new URL(path, 'http://component.test'); requests.push({ path: url.pathname, params: Object.fromEntries(url.searchParams), method: options.method || 'GET' });
    if (url.pathname === '/api/health') return json({ status: 'ok' });
    if (url.pathname === '/api/users/me' && options.method === 'PUT') { currentUser = { ...currentUser, ...JSON.parse(options.body) }; return json(currentUser); }
    if (url.pathname === '/api/users/me') return json(currentUser, currentUser ? 200 : 401);
    if (url.pathname === '/api/users/me/overview') return json({ metrics: [{ label: '已加入课程', value: 1, target: 'courses' }, { label: '累计反馈', value: records.length, target: 'history' }, { label: '个人笔记', value: personalNotes.length, target: 'notes' }, { label: '好友学伴', value: buddies.friends.length, target: 'buddies' }], pending_notes: 1 });
    if (url.pathname === '/api/users/me/avatar') {
      currentUser = { ...currentUser, avatar_url: options.method === 'DELETE' ? null : '/api/avatars/1/' + 'a'.repeat(64) };
      return json(currentUser);
    }
    if (url.pathname === '/api/buddies') return json(buddies);
    if (url.pathname === '/api/buddy-wall/sent') return json({ items: wallMessages.map(item => ({ ...item, owner_username: 'student01', owner_nickname: '' })), total: wallMessages.length });
    if (/^\/api\/buddy-wall\/\d+$/.test(url.pathname)) {
      const ownerId = Number(url.pathname.split('/').at(-1));
      if (options.method === 'POST') {
        const payload = JSON.parse(options.body);
        if (wallKeys.has(payload.request_id)) return json(wallKeys.get(payload.request_id));
        const item = { id: wallMessages.length + 1, owner_id: ownerId, content: payload.content, visibility: payload.visibility, version: 1, created_at: '2026-11-03T09:00:00Z', updated_at: '2026-11-03T09:00:00Z', is_mine: true, can_delete: true };
        wallMessages.push(item); wallKeys.set(payload.request_id, item); return json(item);
      }
      const matching = wallMessages.filter(item => item.owner_id === ownerId);
      return json({ owner: ownerId === 1 ? student : invitation, items: matching, total: matching.length });
    }
    if (/^\/api\/buddy-wall\/\d+\/\d+\/source$/.test(url.pathname)) return json({ username: student.username, nickname: '小林', bio: '一起学习', avatar_color: 'sage', interests: '设计', major: '计算机', grade: '大二', study_goal: '项目实践', learning_style: 'pair' });
    if (/^\/api\/buddy-wall\/\d+\/\d+$/.test(url.pathname)) {
      const item = wallMessages.find(item => item.id === Number(url.pathname.split('/').at(-1)));
      if (options.method === 'PUT') { Object.assign(item, JSON.parse(options.body), { version: item.version + 1 }); return json(item); }
      if (options.method === 'DELETE') { wallMessages.splice(wallMessages.indexOf(item), 1); return json(null); }
    }
    if (url.pathname === '/api/buddies/search') {
      if (url.searchParams.get('major') === '计算机') return json({ total: 13, items: [{ ...peer, id: url.searchParams.get('offset') === '12' ? 95 : peer.id, nickname: url.searchParams.get('offset') === '12' ? '下一页同学' : peer.nickname, relationship: 'NONE', request_id: null }] });
      return json({ items: [{ ...peer, relationship: buddies.outgoing.length ? 'OUTGOING' : 'NONE', request_id: buddies.outgoing.length ? 42 : null }] });
    }
    if (url.pathname === '/api/buddies/requests' && options.method === 'POST') { buddies.outgoing = [{ ...peer, request_id: 42 }]; return json({ request_id: 42, relationship: 'OUTGOING' }); }
    if (url.pathname === '/api/buddies/requests/41/accept') { buddies.incoming = []; buddies.friends = [invitation]; return json(null); }
    if (url.pathname === '/api/buddies/requests/42' && options.method === 'DELETE') { buddies.outgoing = []; return json(null); }
    if (url.pathname === '/api/buddies/91' && options.method === 'DELETE') { buddies.friends = []; return json(null); }
    if (url.pathname === '/api/auth/login') { currentUser = student; return json(student); }
    if (url.pathname === '/api/auth/logout') { currentUser = null; return json(null); }
    if (url.pathname === '/api/sessions') return json({ items: [session] });
    if (url.pathname === '/api/sessions/1/learning-guide') return json(currentUser?.role === 'STUDENT' ? { published: null } : { published: null, draft: { title: '', content: '', practice: '' }, version: 0 });
    if (url.pathname === '/api/teaching/overview') return json({ summary: { courses: 1, sessions: 1, ongoing: 1, upcoming: 0, open_questions: questions.filter(item => item.status === 'OPEN').length, pending_reflections: 0 }, sessions: [{ ...session, record_count: records.length, open_questions: questions.filter(item => item.status === 'OPEN').length, has_reflection: false, guide_published: false }] });
    if (url.pathname === '/api/sessions/join') return json({ session, joined: true });
    if (url.pathname === '/api/sessions/1/join-code') {
      if (options.method === 'POST') joinCode = { code: joinCode.code === 'ABCD2345' ? 'EFGH6789' : 'ABCD2345', version: joinCode.version + 1, expires_at: '2026-11-03T12:00:00Z', status: 'ACTIVE', updated_at: '2026-11-03T09:00:00Z' };
      if (options.method === 'DELETE') joinCode = { ...joinCode, status: 'DISABLED', version: joinCode.version + 1 };
      return json(joinCode);
    }
    if (url.pathname === '/api/courses' || url.pathname === '/api/teacher/courses') return json({ items: [{ id: 1, name: '测试课程' }] });
    if (url.pathname === '/api/courses/1') return json({ course: { id: 1, name: '测试课程', teacher_name: 'teacher01' }, sessions: [{ ...session, record_count: records.length, personal: { feedback_count: records.length, note_count: personalNotes.length, pending_count: 0 } }], summary: { total: 1, ended: 0, ongoing: 1, upcoming: 0, feedback_count: records.length, note_count: personalNotes.length, pending_count: 0, participated_sessions: records.length ? 1 : 0 } });
    if (url.pathname === '/api/admin/people') return json({ items: [student, teacher] });
    if (url.pathname === '/api/admin/campus') return json({ courses: [], sessions: [], summary: { demo_feedback_count: 0 } });
    if (url.pathname === '/api/departments') return json({ items: [] });
    if (url.pathname === '/api/admin/users') return json({ items: [student, teacher], total: 2 });
    if (url.pathname === '/api/sessions/1/roster') return json({ items: [student] });
    if (url.pathname === '/api/sessions/1/statistics') return json({ ...summary(), emotions: emotions(), session });
    if (url.pathname === '/api/sessions/1/questions' && options.method === 'POST') {
      const payload = JSON.parse(options.body);
      questions.push({ id: questions.length + 1, category: payload.category, text: payload.text, reply: '', status: 'OPEN', version: 1, created_at: '2026-11-03T09:00:00Z', updated_at: '2026-11-03T09:00:00Z', is_mine: true });
      return json(questions.at(-1));
    }
    if (url.pathname === '/api/sessions/1/questions') {
      const status = url.searchParams.get('status');
      const items = questions.filter(item => status === 'ALL' || status === item.status);
      return json({ items, total: items.length, summary: questionSummary() });
    }
    if (url.pathname === '/api/sessions/1/questions/1' && options.method === 'PUT') { Object.assign(questions[0], JSON.parse(options.body), { version: questions[0].version + 1 }); return json(questions[0]); }
    if (url.pathname === '/api/sessions/1/recap' && options.method === 'PUT') { reflection = { ...JSON.parse(options.body), version: reflection.version + 1, updated_at: '2026-11-03T09:01:00Z' }; return json(reflection); }
    if (url.pathname === '/api/sessions/1/recap') return json({ session, summary: summary(), emotions: emotions(), periods: ['前半节', '后半节'].map(label => ({ label, total: records.length, emotions: emotions() })), outside_period_count: 0, questions: questionSummary(), reflection, generated_at: '2026-11-03T09:01:00Z' });
    if (url.pathname === '/api/sessions/1/recap/export') return new Response('\ufeff课堂小结,测试课程\r\n', { headers: { 'Content-Disposition': 'attachment; filename="classroom-recap-1.csv"', 'Content-Type': 'text/csv' } });
    if (url.pathname === '/api/personal/notes/sessions') return json({ items: [session] });
    if (url.pathname === '/api/personal/notes' && options.method === 'POST') {
      const { request_id, ...payload } = JSON.parse(options.body);
      personalNotes.push({ ...payload, id: personalNotes.length + 1, version: 1, course_name: payload.session_id ? session.course_name : null, class_name: payload.session_id ? session.class_name : null, reviewed_at: payload.reviewed ? '2026-11-03T09:00:00Z' : null, created_at: '2026-11-03T09:00:00Z', updated_at: '2026-11-03T09:00:00Z' });
      return json(personalNotes.at(-1));
    }
    if (url.pathname === '/api/personal/notes' || url.pathname === '/api/personal/notes/export') {
      const review = url.searchParams.get('review'), q = url.searchParams.get('q') || '', sessionId = url.searchParams.get('session_id');
      const matching = personalNotes.filter(item => (review === 'ALL' || item.reviewed === (review === 'DONE')) && (!sessionId || item.session_id === Number(sessionId)) && [item.title, item.content, item.takeaway, item.next_step].some(value => value.includes(q)));
      if (url.pathname.endsWith('/export')) return new Response('\ufeff标题,笔记正文\r\n', { headers: { 'Content-Disposition': 'attachment; filename="my-classroom-notes.csv"', 'X-Export-Count': String(matching.length) } });
      return json({ items: matching.slice(Number(url.searchParams.get('offset')), Number(url.searchParams.get('offset')) + 12), total: matching.length });
    }
    if (/^\/api\/personal\/notes\/\d+$/.test(url.pathname)) {
      const item = personalNotes.find(item => item.id === Number(url.pathname.split('/').at(-1)));
      if (options.method === 'PUT') { Object.assign(item, JSON.parse(options.body), { version: item.version + 1 }); return json(item); }
      if (options.method === 'DELETE') { personalNotes.splice(personalNotes.indexOf(item), 1); return json(null); }
      return json(item);
    }
    if (url.pathname === '/api/personal/review') {
      const sessionId = Number(url.searchParams.get('session_id')) || null;
      const notes = personalNotes.filter(item => !sessionId || item.session_id === sessionId);
      return json({ days: Number(url.searchParams.get('days')), session_id: sessionId, starts_at: '2026-10-27T12:00:00Z', ends_at: '2026-11-03T12:00:00Z', summary: { feedback_count: records.length, active_days: 1, note_count: notes.length, reviewed_count: notes.filter(item => item.reviewed).length, pending_count: notes.filter(item => !item.reviewed).length }, emotions: emotions(), trend: [{ timestamp: '2026-11-02T00:00:00Z', total: 0 }, { timestamp: '2026-11-03T00:00:00Z', total: records.length }], sessions: [{ ...session, feedback_count: records.length, note_count: notes.length }], recent_notes: notes });
    }
    if (url.pathname === '/api/personal/review/day') {
      const day = url.searchParams.get('day'), sessionId = Number(url.searchParams.get('session_id')) || null;
      const notes = personalNotes.filter(item => item.created_at.startsWith(day) && (!sessionId || item.session_id === sessionId));
      const feedback = records.filter(item => item.recorded_at.startsWith(day));
      return json({ day, session_id: sessionId, feedback: { items: feedback, total: feedback.length, offset: 0, limit: 12 }, notes: { items: notes, total: notes.length, offset: 0, limit: 12 }, emotions: emotions() });
    }
    if (url.pathname === '/api/personal/review/export') return new Response('\ufeff学生个人回顾\r\n', { headers: { 'Content-Disposition': 'attachment; filename="my-learning-review.csv"' } });
    if (url.pathname === '/api/emoji/history') return json({ items: records, total: records.length });
    if (url.pathname === '/api/emoji') {
      const payload = JSON.parse(options.body);
      records.push({ id: records.length + 1, ...payload, username: student.username, course_name: session.course_name, class_name: session.class_name, source: 'MANUAL', recorded_at: '2026-11-03T09:00:00Z' });
      return json(records.at(-1));
    }
    if (url.pathname === '/api/dashboard/realtime' || url.pathname === '/api/reports/statistics') return json({ session, summary: summary(), emotions: emotions(), trend: [{ timestamp: '2026-11-03T09:00:00Z', total: records.length }], latest: records, updated_at: '2026-11-03T09:00:01Z', filters: { bucket: 'day' }, by_course: [], by_class: [] });
    if (url.pathname === '/api/ai/status') return json({ ready: true, min_confidence: .7 });
    if (url.pathname === '/api/sessions/1/ai-frame' && pendingUpload) return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => { uploadCancelled = true; reject(new DOMException('Aborted', 'AbortError')); }, { once: true }));
    throw new Error(`Unexpected mocked request: ${url.pathname}`);
  };
  try {
    const guest = mount(App); mounted.push(guest); await settle();
    assert(text(guest.root).includes('每一种感受，') && text(guest.root).includes('连接正常'));
    assert(!text(guest.root).includes('已开放') && !text(guest.root).includes('本地开发环境'));
    assert(!walk(guest.root).some(target => hasClass(target, 'roles') || target.props.href === '/docs'));
    await button(guest.root, '学生注册').props.onClick(); await nextTick();
    assert(field(guest.root, 'email') && field(guest.root, 'confirm'));
    await button(guest.root, '登录').props.onClick(); await nextTick();
    field(guest.root, 'username').props.onInput({ target: { value: 'student01' } });
    field(guest.root, 'password').props.onInput({ target: { value: 'ComponentOnly123' } });
    await find(guest.root, target => target.type === 'form').props.onSubmit({ preventDefault() {} }); await settle();
    assert(text(guest.root).includes('此刻，你感觉如何？'), 'student opens directly into the classroom');
    assert(!walk(guest.root).some(target => hasClass(target, 'hero-auth')), 'login introduction disappears in the workspace');
    assert(!walk(guest.root).some(target => target.props.name === 'class_join_code'), 'daily feedback never asks for a join code');
    await button(guest.root, '我的课程').props.onClick(); await settle();
    assert(!walk(guest.root).some(target => target.props.name === 'class_join_code'), 'course addition is collapsed by default');
    await button(guest.root, '添加课程').props.onClick(); await settle();
    field(guest.root, 'class_join_code').props.onInput({ target: { value: 'abcd2345' } });
    await find(guest.root, target => target.type === 'form' && hasClass(target, 'join-class-form')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(requests.some(request => request.path === '/api/sessions/join' && request.method === 'POST'));
    assert(!walk(guest.root).some(target => target.props.name === 'class_join_code'), 'successful addition closes the form');
    await button(guest.root, '我的课堂').props.onClick(); await settle();
    await button(guest.root, '开心').props.onClick(); await nextTick();
    assert.equal(button(guest.root, '开心').props['aria-pressed'], true);
    await button(guest.root, '提交本次感受').props.onClick(); await settle();
    assert.equal(records.length, 1); assert(text(guest.root).includes('我的反馈历史'));
    const originalTimes = { status: session.status, ends_at: session.ends_at, feedback_closes_at: session.feedback_closes_at };
    session.status = 'ENDED'; session.ends_at = new Date(Date.now() - 1000).toISOString();
    await button(guest.root, '刷新').props.onClick(); await settle();
    assert(text(guest.root).includes('回想刚才的课堂') && !button(guest.root, '开心').props.disabled, 'recently ended class stays available for feedback');
    session.can_feedback = false; session.feedback_closes_at = new Date(Date.now() - 3600000).toISOString();
    await button(guest.root, '刷新').props.onClick(); await settle();
    assert(!walk(guest.root).some(target => target.props['data-emotion']), 'expired classes are absent from daily evaluation');
    find(guest.root, target => target.props.name === 'daily_session_scope').props.onChange({ target: { value: 'ALL' } }); await settle();
    assert(button(guest.root, '开心').props.disabled, 'viewing older classes never enables late feedback');
    session.can_feedback = true; Object.assign(session, originalTimes);
    await button(guest.root, '刷新').props.onClick(); await settle();
    find(guest.root, target => target.props.name === 'daily_session_scope').props.onChange({ target: { value: 'AVAILABLE' } }); await settle();
    assert(!walk(guest.root).some(target => hasClass(target, 'pagination')), 'single-page history has no redundant pager');
    assert(text(guest.root).includes('匿名问题卡'));
    find(guest.root, target => target.type === 'textarea' && target.props.name === 'question_text').props.onInput({ target: { value: '能用一个生活中的例子解释吗？' } });
    await find(guest.root, target => target.type === 'form' && hasClass(target, 'question-compose')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(questions.length === 1 && text(guest.root).includes('我提出的') && text(guest.root).includes('能用一个生活中的例子解释吗？'));
    assert(!text(guest.root).includes('回应问题') && !text(guest.root).includes('课堂小结'), 'students cannot edit teacher responses or read staff recaps');
    const unloadListeners = new Set();
    global.window = { addEventListener: (name, listener) => unloadListeners.add(listener), removeEventListener: (name, listener) => unloadListeners.delete(listener) };
    await button(guest.root, '笔记与回顾').props.onClick(); await settle();
    assert(text(guest.root).includes('仅自己可见') && unloadListeners.size === 1);
    await button(guest.root, '新建笔记').props.onClick(); await nextTick();
    field(guest.root, 'note_title').props.onInput({ target: { value: '信息层级随记' } });
    find(guest.root, target => target.type === 'textarea' && target.props.name === 'note_content').props.onInput({ target: { value: '先明确主要信息，再安排细节。' } });
    find(guest.root, target => target.type === 'textarea' && target.props.name === 'note_takeaway').props.onInput({ target: { value: '理解了内容的优先次序' } });
    find(guest.root, target => target.type === 'textarea' && target.props.name === 'note_next_step').props.onInput({ target: { value: '画一个校园导览页' } });
    find(guest.root, target => target.type === 'select' && target.props.name === 'note_session').props.onChange({ target: { value: '1' } }); await nextTick();
    await button(guest.root, '个人资料').props.onClick(); await nextTick();
    assert(text(guest.root).includes('笔记尚未保存') && field(guest.root, 'note_title').props.value === '信息层级随记');
    let preventedReload = false;
    [...unloadListeners][0]({ preventDefault() { preventedReload = true; }, returnValue: undefined });
    assert(preventedReload, 'unsaved drafts request the browser reload guard');
    await find(guest.root, target => target.type === 'form' && hasClass(target, 'note-editor')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(personalNotes.length === 1 && personalNotes[0].session_id === 1 && button(guest.root, '保存笔记').props.disabled);
    await button(guest.root, '返回笔记').props.onClick(); await settle();
    await button(guest.root, '打开笔记').props.onClick(); await settle();
    field(guest.root, 'note_reviewed').props.onChange({ target: { checked: true } }); await nextTick();
    await find(guest.root, target => target.type === 'form' && hasClass(target, 'note-editor')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(personalNotes[0].reviewed && personalNotes[0].version === 2);
    await button(guest.root, '返回笔记').props.onClick(); await settle();
    await button(guest.root, '新建笔记').props.onClick(); await nextTick();
    field(guest.root, 'note_title').props.onInput({ target: { value: '练习计划' } });
    find(guest.root, target => target.type === 'textarea' && target.props.name === 'note_content').props.onInput({ target: { value: '明天做一个版式练习' } });
    await find(guest.root, target => target.type === 'form' && hasClass(target, 'note-editor')).props.onSubmit({ preventDefault() {} }); await settle();
    await button(guest.root, '返回笔记').props.onClick(); await settle();
    find(guest.root, target => target.type === 'select' && target.props.name === 'notes_review_filter').props.onChange({ target: { value: 'DONE' } });
    await find(guest.root, target => target.type === 'form' && hasClass(target, 'note-search')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(text(guest.root).includes('信息层级随记') && !text(guest.root).includes('练习计划'));
    let notesFilename = '';
    Object.assign(global.document, { createElement: () => ({ click() { notesFilename = this.download; }, remove() {} }), body: { appendChild() {} } });
    await button(guest.root, '导出笔记').props.onClick(); await settle();
    assert.equal(notesFilename, 'my-classroom-notes.csv');
    field(guest.root, 'note_query').props.onInput({ target: { value: '改了搜索条件' } }); await nextTick();
    assert(button(guest.root, '导出笔记').props.disabled, 'export cannot silently use an unapplied search');
    await button(guest.root, '个人回顾').props.onClick(); await settle();
    assert(text(guest.root).includes('你有 1 篇笔记待回顾') && text(guest.root).includes('这些日子的感受'));
    find(guest.root, target => target.type === 'select' && target.props.name === 'personal_review_days').props.onChange({ target: { value: '30' } }); await settle();
    assert.equal(requests.filter(request => request.path === '/api/personal/review').at(-1).params.days, '30');
    find(guest.root, target => target.type === 'select' && target.props.name === 'personal_review_session').props.onChange({ target: { value: '1' } }); await settle();
    assert.equal(requests.filter(request => request.path === '/api/personal/review').at(-1).params.session_id, '1');
    assert(text(guest.root).includes('留给下一次的想法') && text(guest.root).includes('画一个校园导览页'));
    let dayPoint = find(guest.root, target => target.type === 'g' && target.props['data-day'] === '2026-11-03');
    dayPoint.props.onClick(); await settle();
    assert(text(guest.root).includes('2026/11/03 的记录') && text(guest.root).includes('1 条反馈 · 1 篇新笔记'));
    const dayRequest = requests.filter(request => request.path === '/api/personal/review/day').at(-1);
    assert.equal(dayRequest.params.session_id, '1'); assert.equal(dayRequest.params.starts_at, '2026-10-27T12:00:00Z');
    assert(find(guest.root, target => target.props['data-day'] === '2026-11-03').props['aria-pressed']);
    dayPoint = find(guest.root, target => target.props['data-day'] === '2026-11-03');
    dayPoint.props.onKeydown({ key: 'ArrowLeft', preventDefault() {} }); await settle();
    assert(text(guest.root).includes('2026/11/02 的记录') && text(guest.root).includes('这一天没有手动反馈记录。'));
    field(guest.root, 'review_day').props.onChange({ target: { value: '2026-11-03' } }); await settle();
    await button(guest.root, '打开当天笔记').props.onClick(); await settle();
    assert.equal(field(guest.root, 'note_title').props.value, '信息层级随记');
    await button(guest.root, '返回笔记').props.onClick(); await settle();
    await button(guest.root, '个人回顾').props.onClick(); await settle();
    assert(!text(guest.root).includes('2026/11/03 的记录'), 'changing review resets the selected day');
    await button(guest.root, '导出个人回顾').props.onClick(); await settle();
    assert.equal(notesFilename, 'my-learning-review.csv');
    assert.equal(requests.filter(request => request.path === '/api/personal/review/export').at(-1).params.session_id, '1');
    await button(guest.root, '打开这篇笔记').props.onClick(); await settle();
    assert.equal(field(guest.root, 'note_title').props.value, '信息层级随记');
    await button(guest.root, '返回笔记').props.onClick(); await settle();
    await button(guest.root, '个人回顾').props.onClick(); await settle();
    find(guest.root, target => target.type === 'select' && target.props.name === 'personal_review_session').props.onChange({ target: { value: '' } }); await settle();
    await button(guest.root, '查看待回顾笔记').props.onClick(); await settle();
    assert(text(guest.root).includes('练习计划') && !text(guest.root).includes('信息层级随记'));
    await button(guest.root, '打开笔记').props.onClick(); await settle();
    await button(guest.root, '删除这篇笔记').props.onClick(); await nextTick();
    assert.equal(personalNotes.length, 2, 'delete requires the second explicit action');
    await button(guest.root, '确认删除笔记').props.onClick(); await settle();
    assert.equal(personalNotes.length, 1);
    await button(guest.root, '情绪历史').props.onClick(); await settle(); assert(text(guest.root).includes('测试课程 / 测试班'));
    await button(guest.root, '个人资料').props.onClick(); await settle(); assert(text(guest.root).includes('账号身份'));
    assert.equal(unloadListeners.size, 1, 'profile replaces the notebook reload guard');
    assert(text(guest.root).includes('个人主页') && text(guest.root).includes('累计反馈'));
    const avatarFile = new Blob(['image'], { type: 'image/png' });
    field(guest.root, 'avatar_file').props.onChange({ target: { files: [avatarFile], value: '' } }); await nextTick();
    assert(!requests.some(request => request.path === '/api/users/me/avatar'), 'choosing an image does not upload it');
    find(guest.root, target => target.type === 'img' && target.props.alt === '待保存的头像').props.onLoad({ target: { naturalWidth: 640, naturalHeight: 480 } }); await nextTick();
    field(guest.root, 'avatar_zoom').props.onInput({ target: { value: '2' } });
    field(guest.root, 'avatar_x').props.onInput({ target: { value: '25' } }); await nextTick();
    await button(guest.root, '好友学伴').props.onClick(); await nextTick();
    assert(text(guest.root).includes('头像预览或个人资料尚未保存'));
    await button(guest.root, '保存头像').props.onClick(); await settle();
    assert(currentUser.avatar_url && requests.filter(request => request.path === '/api/users/me/avatar').at(-1).params.zoom === '2');
    assert(walk(find(guest.root, target => hasClass(target, 'workspace-identity'))).some(target => target.type === 'img' && target.props.src === currentUser.avatar_url), 'saved avatar synchronizes to sidebar');
    await button(guest.root, '恢复默认头像').props.onClick(); await nextTick();
    assert(currentUser.avatar_url, 'restoring avatar requires confirmation');
    await button(guest.root, '确认恢复默认').props.onClick(); await settle();
    assert.equal(currentUser.avatar_url, null);
    field(guest.root, 'avatar_file').props.onChange({ target: { files: [new Blob(['<svg/>'], { type: 'image/svg+xml' })], value: '' } }); await nextTick();
    assert(text(guest.root).includes('请选择 JPG、PNG 或 WebP'));
    field(guest.root, 'avatar_file').props.onChange({ target: { files: [avatarFile], value: '' } }); await nextTick();
    await button(guest.root, '取消预览').props.onClick(); await nextTick();
    assert(!walk(guest.root).some(target => target.props.alt === '待保存的头像'));
    field(guest.root, 'nickname').props.onInput({ target: { value: '小林' } });
    field(guest.root, 'bio').props.onInput({ target: { value: '一起学设计' } }); await nextTick();
    field(guest.root, 'major').props.onInput({ target: { value: '计算机' } });
    field(guest.root, 'grade').props.onInput({ target: { value: '大二' } });
    field(guest.root, 'study_goal').props.onInput({ target: { value: '项目实践' } }); await nextTick();
    const profileForm = find(guest.root, target => target.type === 'form' && hasClass(target, 'profile-edit-form'));
    await profileForm.props.onSubmit({ preventDefault() {} }); await settle();
    assert(currentUser.nickname === '小林' && currentUser.major === '计算机' && currentUser.study_goal === '项目实践' && text(guest.root).includes('已保存'));
    assert(text(find(guest.root, target => hasClass(target, 'workspace-identity'))).includes('小林'), 'saved nickname updates workspace identity immediately');
    assert.equal(button(guest.root, '保存资料').props.disabled, true);
    await find(guest.root, target => hasClass(target, 'profile-metric') && text(target).includes('累计反馈')).props.onClick(); await settle();
    assert(text(guest.root).includes('我的反馈历史'), 'profile overview cards open the corresponding real page');
    await button(guest.root, '个人资料').props.onClick(); await settle();
    await button(guest.root, '好友学伴').props.onClick(); await settle();
    field(guest.root, 'buddy_username').props.onInput({ target: { value: 'buddy01' } });
    await find(guest.root, target => target.type === 'form' && hasClass(target, 'buddy-search-form')).props.onSubmit({ preventDefault() {} }); await settle();
    await button(guest.root, '添加学伴').props.onClick(); await settle();
    assert(buddies.outgoing.length === 1 && text(guest.root).includes('等待对方回应'));
    const buddyTab = label => find(guest.root, target => target.type === 'button' && text(target).startsWith(label));
    await buddyTab('发出的申请').props.onClick(); await nextTick();
    await button(guest.root, '撤回申请').props.onClick(); await settle(); assert.equal(buddies.outgoing.length, 0);
    await buddyTab('收到的申请').props.onClick(); await nextTick();
    await button(guest.root, '同意').props.onClick(); await settle(); assert.equal(buddies.friends.length, 1);
    await buddyTab('我的学伴').props.onClick(); await nextTick();
    await button(guest.root, '去留言').props.onClick(); await settle();
    assert(text(guest.root).includes('学伴留言墙') && text(guest.root).includes('已确认学伴可见'));
    const wallInput = () => find(guest.root, target => target.type === 'textarea' && target.props.name === 'wall_content');
    wallInput().props.onInput({ target: { value: '一起把这个课程项目完成！' } }); await nextTick();
    await button(guest.root, '个人资料').props.onClick(); await nextTick();
    assert(text(guest.root).includes('留言草稿尚未发送') && wallInput().props.value.includes('课程项目'));
    await find(guest.root, target => target.type === 'form' && hasClass(target, 'wall-compose')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(wallMessages.length === 1 && wallMessages[0].visibility === 'ANONYMOUS');
    assert(text(guest.root).includes('来源保密') && !walk(guest.root).some(target => target.type === 'button' && text(target) === '点击查看来源'));
    assert(!requests.some(request => request.path.endsWith('/source')), 'anonymous cards never request author identity');
    wallInput().props.onInput({ target: { value: '欢迎来问我版式练习的问题。' } });
    find(guest.root, target => target.type === 'input' && target.props.name === 'wall_visibility' && target.props.value === 'REVEALABLE').props.onChange(); await nextTick();
    assert(text(guest.root).includes('发布后不能更改此项'));
    await find(guest.root, target => target.type === 'form' && hasClass(target, 'wall-compose')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(wallMessages[1].visibility === 'REVEALABLE' && !text(guest.root).includes('@student01'));
    assert(!requests.some(request => request.path.endsWith('/source')), 'revealable list does not prefetch public source');
    await button(guest.root, '点击查看来源').props.onClick(); await settle();
    assert(text(guest.root).includes('@student01') && text(guest.root).includes('结对练习'));
    await button(guest.root, '收起来源').props.onClick(); await nextTick();
    assert(!text(guest.root).includes('@student01'));
    await button(guest.root, '编辑留言').props.onClick(); await nextTick();
    find(guest.root, target => target.type === 'textarea' && target.props.name === 'wall_edit_content').props.onInput({ target: { value: '一起把这个项目做得更好！' } });
    await find(guest.root, target => target.type === 'form' && hasClass(target, 'wall-edit-form')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(wallMessages[0].version === 2 && wallMessages[0].visibility === 'ANONYMOUS');
    await button(guest.root, '我发出的留言').props.onClick(); await settle();
    assert(text(guest.root).includes('解除学伴关系后仍可删除'));
    await button(guest.root, '删除留言').props.onClick(); await nextTick();
    assert.equal(wallMessages.length, 2);
    await button(guest.root, '确认删除留言').props.onClick(); await settle();
    assert.equal(wallMessages.length, 1);
    await button(guest.root, '返回学伴').props.onClick(); await settle();
    await button(guest.root, '我的留言墙').props.onClick(); await settle();
    assert(text(guest.root).includes('我的留言墙'));
    await button(guest.root, '返回学伴').props.onClick(); await settle();
    await button(guest.root, '移除学伴').props.onClick(); await nextTick(); assert.equal(buddies.friends.length, 1);
    await button(guest.root, '确认移除').props.onClick(); await settle(); assert.equal(buddies.friends.length, 0);
    field(guest.root, 'buddy_username').props.onInput({ target: { value: '设计 Python' } });
    field(guest.root, 'buddy_major').props.onInput({ target: { value: '计算机' } });
    field(guest.root, 'buddy_grade').props.onInput({ target: { value: '大二' } });
    field(guest.root, 'buddy_interests').props.onInput({ target: { value: 'Python' } });
    find(guest.root, target => target.type === 'select' && target.props.name === 'buddy_style').props.onChange({ target: { value: 'project' } });
    find(guest.root, target => target.type === 'select' && target.props.name === 'buddy_relationship').props.onChange({ target: { value: 'new' } });
    field(guest.root, 'buddy_common_course').props.onChange({ target: { checked: true } }); await nextTick();
    await find(guest.root, target => target.type === 'form' && hasClass(target, 'buddy-search-form')).props.onSubmit({ preventDefault() {} }); await settle();
    const searchRequest = requests.filter(request => request.path === '/api/buddies/search').at(-1).params;
    assert(searchRequest.q === '设计 Python' && searchRequest.major === '计算机' && searchRequest.grade === '大二' && searchRequest.interests === 'Python' && searchRequest.learning_style === 'project' && searchRequest.common_course === 'true' && searchRequest.relationship === 'new');
    assert(text(guest.root).includes('共 13 位') && text(guest.root).includes('项目协作'));
    await button(guest.root, '下一页').props.onClick(); await settle();
    assert(text(guest.root).includes('下一页同学'));
    assert.equal(requests.filter(request => request.path === '/api/buddies/search').at(-1).params.offset, '12');
    await button(guest.root, '清空条件').props.onClick(); await nextTick(); assert.equal(button(guest.root, '查找').props.disabled, true);
    await button(guest.root, '退出登录').props.onClick(); await settle(); assert(text(guest.root).includes('欢迎回到课堂'));
    guest.unmount(); mounted.pop();

    const staff = mount(Workspace, { user: teacher }); mounted.push(staff); await settle();
    assert(text(staff.root).includes('课堂与跟进'), 'teacher opens into the teaching workspace');
    assert(!text(staff.root).includes('AI 识别尚未接入'));
    await button(staff.root, '我的课程').props.onClick(); await settle();
    await find(staff.root, target => target.props['aria-label'] === '查看课程详情：测试课程').props.onClick(); await settle();
    await button(staff.root, '生成加入码').props.onClick(); await settle();
    assert(text(staff.root).includes('ABCD 2345'));
    await button(staff.root, '重新生成').props.onClick(); await nextTick();
    assert(text(staff.root).includes('旧码立即失效') && joinCode.version === 1);
    await button(staff.root, '确认更换加入码').props.onClick(); await settle();
    assert(text(staff.root).includes('EFGH 6789') && joinCode.version === 2);
    await button(staff.root, '停用加入码').props.onClick(); await settle();
    assert.equal(joinCode.status, 'DISABLED');
    await button(staff.root, '课堂反馈').props.onClick(); await settle();
    assert(!text(staff.root).includes('生成加入码'), 'teacher daily feedback has no code management');
    await button(staff.root, '问题回应').props.onClick(); await settle();
    await button(staff.root, '回应问题').props.onClick(); await nextTick();
    find(staff.root, target => target.type === 'textarea' && target.props.name === 'question_reply').props.onInput({ target: { value: '下一段用图书馆的例子解释。' } });
    field(staff.root, 'question_resolved').props.onChange({ target: { checked: true } });
    await find(staff.root, target => target.type === 'form' && hasClass(target, 'question-answer')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(questions[0].status === 'RESOLVED' && questions[0].reply.includes('图书馆') && text(staff.root).includes('老师回应'));
    await button(staff.root, '课后小结').props.onClick(); await settle();
    const recap = find(staff.root, target => target.type === 'details' && hasClass(target, 'recap-panel'));
    recap.props.onToggle({ target: { open: true } }); await settle();
    assert(text(staff.root).includes('前半节') && text(staff.root).includes('后半节'));
    find(staff.root, target => target.type === 'textarea' && target.props.name === 'classroom_reflection').props.onInput({ target: { value: '下节课多用实例，并留出提问时间。' } }); await nextTick();
    assert.equal(button(staff.root, '导出课堂小结').props.disabled, true, 'unsaved reflection must not be silently omitted from export');
    await find(staff.root, target => target.type === 'form' && hasClass(target, 'reflection-form')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(reflection.version === 1 && reflection.reflection.includes('实例') && button(staff.root, '保存教学反思').props.disabled);
    let downloaded = '';
    Object.assign(global.document, { createElement: () => ({ click() { downloaded = this.download; }, remove() {} }), body: { appendChild() {} } });
    await button(staff.root, '导出课堂小结').props.onClick(); await settle();
    assert.equal(downloaded, 'classroom-recap-1.csv');
    await button(staff.root, '统计与导出').props.onClick(); await settle();
    assert(button(staff.root, '导出 CSV') && walk(staff.root).some(target => hasClass(target, 'chart-x-axis')));
    await button(staff.root, '我的课程').props.onClick(); await settle(); assert(text(staff.root).includes('测试课程'));
    await button(staff.root, '账号安全').props.onClick(); await nextTick(); assert(field(staff.root, 'current_password'));
    staff.unmount(); mounted.pop();

    const admin = mount(Workspace, { user: { ...teacher, role: 'ADMIN' } }); mounted.push(admin); await settle();
    await button(admin.root, '用户列表').props.onClick(); await settle();
    assert(text(admin.root).includes('student01') && text(admin.root).includes('teacher01'));
    assert(!walk(admin.root).some(target => hasClass(target, 'pagination')));
    admin.unmount(); mounted.pop();

    let releasePermission, stopped = 0;
    Object.defineProperty(global, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia: () => new Promise(resolve => { releasePermission = resolve; }) } } });
    const camera = mount(CameraPanel, { sessionId: 1, ongoing: true }); mounted.push(camera); await settle();
    const permission = button(camera.root, '开启识别').props.onClick(); await nextTick();
    const details = find(camera.root, target => target.type === 'details');
    details.props.onToggle({ target: { open: false } });
    releasePermission({ getTracks: () => [{ stop: () => stopped++ }] }); await permission; await settle();
    assert.equal(stopped, 1, 'collapsing while permission is pending releases the later stream');
    pendingUpload = true;
    const upload = find(camera.root, target => target.type === 'input' && target.props.type === 'file');
    const uploading = upload.props.onChange({ target: { files: [new Blob(['jpeg'], { type: 'image/jpeg' })], value: 'sample.jpg' } });
    await settle(); details.props.onToggle({ target: { open: false } }); await uploading; await settle();
    assert(uploadCancelled, 'collapsing cancels the pending upload');
    camera.unmount(); mounted.pop();
    const readyFetch = global.fetch;
    const cards = Array.from({ length: 13 }, (_, index) => ({ id: index + 1, category: 'EXAMPLE', text: `分页问题 ${index + 1}`, reply: '', status: 'OPEN', version: 1, created_at: '2026-11-03T09:00:00Z', updated_at: '2026-11-03T09:00:00Z' }));
    let scheduledQuestionPoll, questionOffline = false, answerConflict = false;
    global.setInterval = callback => { scheduledQuestionPoll = callback; return 999; };
    global.clearInterval = () => { scheduledQuestionPoll = null; };
    global.fetch = async (path, options = {}) => {
      const url = new URL(path, 'http://component.test');
      if (options.method === 'PUT') {
        if (answerConflict) return new Response(JSON.stringify({ message: '问题卡已被更新，请刷新后再保存' }), { status: 409 });
        Object.assign(cards.at(-1), JSON.parse(options.body), { version: 2 });
        return json(cards.at(-1));
      }
      if (questionOffline) throw new Error('offline');
      const status = url.searchParams.get('status'), offset = Number(url.searchParams.get('offset'));
      const matching = cards.filter(item => status === 'ALL' || item.status === status);
      return json({ items: matching.slice(offset, offset + 12), total: matching.length, summary: { total: cards.length, open: cards.filter(item => item.status === 'OPEN').length, resolved: cards.filter(item => item.status === 'RESOLVED').length } });
    };
    const questionEdges = mount(QuestionsPanel, { sessionId: 1, ongoing: true, user: teacher }); mounted.push(questionEdges); await settle();
    await find(questionEdges.root, target => target.type === 'button' && text(target).startsWith('待回应')).props.onClick(); await settle();
    await button(questionEdges.root, '下一页').props.onClick(); await settle();
    assert(text(questionEdges.root).includes('分页问题 13') && text(questionEdges.root).includes('第 2 页'));
    await button(questionEdges.root, '回应问题').props.onClick(); await nextTick();
    assert(button(questionEdges.root, '上一页').props.disabled, 'editing cannot hide a draft by changing pages');
    assert(find(questionEdges.root, target => target.type === 'button' && text(target).startsWith('全部')).props.disabled);
    find(questionEdges.root, target => target.type === 'textarea').props.onInput({ target: { value: '保留这条草稿' } });
    answerConflict = true;
    await find(questionEdges.root, target => target.type === 'form' && hasClass(target, 'question-answer')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(text(questionEdges.root).includes('问题卡已被更新'));
    assert.equal(find(questionEdges.root, target => target.type === 'textarea').props.value, '保留这条草稿');
    await button(questionEdges.root, '放弃修改并刷新').props.onClick(); await settle();
    assert(!walk(questionEdges.root).some(target => target.type === 'form' && hasClass(target, 'question-answer')));
    answerConflict = false;
    await button(questionEdges.root, '回应问题').props.onClick(); await nextTick();
    field(questionEdges.root, 'question_resolved').props.onChange({ target: { checked: true } });
    await find(questionEdges.root, target => target.type === 'form' && hasClass(target, 'question-answer')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(text(questionEdges.root).includes('分页问题 1') && !text(questionEdges.root).includes('第 2 页'), 'resolving the final card returns to the last available page');
    questionOffline = true; scheduledQuestionPoll(); await settle();
    assert(text(questionEdges.root).includes('暂时无法更新问题') && text(questionEdges.root).includes('分页问题 1'), 'failed background updates retain and label the last result');
    questionOffline = false; scheduledQuestionPoll(); await settle();
    assert(!text(questionEdges.root).includes('暂时无法更新问题'));
    questionEdges.unmount(); mounted.pop(); assert.equal(scheduledQuestionPoll, null);
    global.setInterval = originalSetInterval; global.clearInterval = originalClearInterval;
    let releaseDay, staleDayAborted = false;
    global.fetch = async (path, options = {}) => {
      const url = new URL(path, 'http://component.test');
      if (url.pathname === '/api/personal/review/day' && url.searchParams.get('day') === '2026-11-02') {
        options.signal.addEventListener('abort', () => staleDayAborted = true, { once: true });
        return new Promise(resolve => releaseDay = resolve);
      }
      return readyFetch(path, options);
    };
    const dayEdges = mount(PersonalNotesPanel); mounted.push(dayEdges); await settle();
    await button(dayEdges.root, '个人回顾').props.onClick(); await settle();
    find(dayEdges.root, target => target.props['data-day'] === '2026-11-02').props.onClick(); await settle();
    assert(text(dayEdges.root).includes('正在打开这一天'));
    find(dayEdges.root, target => target.props['data-day'] === '2026-11-03').props.onClick(); await settle();
    assert(staleDayAborted && text(dayEdges.root).includes('2026/11/03 的记录'));
    releaseDay(json({ day: '2026-11-02', feedback: { items: [], total: 999 }, notes: { items: [], total: 999 } })); await settle();
    assert(!text(dayEdges.root).includes('999 条反馈'), 'late day responses never replace the currently selected date');
    find(dayEdges.root, target => target.props['data-day'] === '2026-11-02').props.onClick(); await settle();
    staleDayAborted = false;
    find(dayEdges.root, target => target.props.name === 'personal_review_session').props.onChange({ target: { value: '1' } }); await settle();
    assert(staleDayAborted && !text(dayEdges.root).includes('2026/11/02 的记录'), 'classroom changes cancel and clear the old date detail');
    releaseDay(json({ day: '2026-11-02' })); await settle();
    dayEdges.unmount(); mounted.pop(); global.fetch = readyFetch;
    let lostCreateReply = true, firstNoteRequest, noteConflict = false;
    const initialNoteCount = personalNotes.length;
    global.fetch = async (path, options = {}) => {
      if (path === '/api/personal/notes' && options.method === 'POST') {
        const body = JSON.parse(options.body);
        if (lostCreateReply) { firstNoteRequest = body.request_id; lostCreateReply = false; await readyFetch(path, options); throw new Error('reply lost after commit'); }
        assert.equal(body.request_id, firstNoteRequest, 'retrying a new note reuses its request key');
        return json(personalNotes.at(-1));
      }
      if (/^\/api\/personal\/notes\/\d+$/.test(path) && options.method === 'PUT' && noteConflict) return new Response(JSON.stringify({ message: '笔记已被更新，请先复制草稿，再重新打开最新版本' }), { status: 409 });
      return readyFetch(path, options);
    };
    const noteEdges = mount(PersonalNotesPanel); mounted.push(noteEdges); await settle();
    await button(noteEdges.root, '新建笔记').props.onClick(); await nextTick();
    field(noteEdges.root, 'note_title').props.onInput({ target: { value: '重试笔记' } });
    find(noteEdges.root, target => target.type === 'textarea' && target.props.name === 'note_content').props.onInput({ target: { value: '断线后仍然保留' } });
    await find(noteEdges.root, target => target.type === 'form' && hasClass(target, 'note-editor')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(text(noteEdges.root).includes('连接失败') && field(noteEdges.root, 'note_title').props.value === '重试笔记');
    await find(noteEdges.root, target => target.type === 'form' && hasClass(target, 'note-editor')).props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(personalNotes.length, initialNoteCount + 1);
    noteConflict = true;
    field(noteEdges.root, 'note_title').props.onInput({ target: { value: '发生冲突的草稿' } });
    await find(noteEdges.root, target => target.type === 'form' && hasClass(target, 'note-editor')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(text(noteEdges.root).includes('笔记已被更新') && field(noteEdges.root, 'note_title').props.value === '发生冲突的草稿');
    await button(noteEdges.root, '放弃修改并返回').props.onClick(); await settle();
    assert(text(noteEdges.root).includes('重试笔记') && !text(noteEdges.root).includes('发生冲突的草稿'));
    noteEdges.unmount(); mounted.pop();
    let firstWallRequest, lostWallReply = true, releaseSource;
    const initialWallCount = wallMessages.length;
    const sourceResponse = new Promise(resolve => { releaseSource = resolve; });
    global.fetch = async (path, options = {}) => {
      if (path === '/api/buddy-wall/1' && options.method === 'POST') {
        const body = JSON.parse(options.body);
        if (lostWallReply) { firstWallRequest = body.request_id; lostWallReply = false; await readyFetch(path, options); throw new Error('reply lost'); }
        assert.equal(body.request_id, firstWallRequest, 'wall retry retains the original request key');
      }
      if (path.endsWith('/source')) return sourceResponse;
      return readyFetch(path, options);
    };
    const wallEdges = mount(BuddyWallPanel, { ownerId: 1, user: student }); mounted.push(wallEdges); await settle();
    find(wallEdges.root, target => target.type === 'textarea' && target.props.name === 'wall_content').props.onInput({ target: { value: '重试仍然只留一条' } });
    find(wallEdges.root, target => target.type === 'input' && target.props.name === 'wall_visibility' && target.props.value === 'REVEALABLE').props.onChange();
    await find(wallEdges.root, target => target.type === 'form' && hasClass(target, 'wall-compose')).props.onSubmit({ preventDefault() {} }); await settle();
    assert(text(wallEdges.root).includes('连接失败') && find(wallEdges.root, target => target.type === 'textarea').props.value.includes('只留一条'));
    await find(wallEdges.root, target => target.type === 'form' && hasClass(target, 'wall-compose')).props.onSubmit({ preventDefault() {} }); await settle();
    assert.equal(wallMessages.length, initialWallCount + 1);
    const sourceOpening = button(wallEdges.root, '点击查看来源').props.onClick(); await settle();
    assert(text(wallEdges.root).includes('正在读取公开来源'));
    await button(wallEdges.root, '收起来源').props.onClick(); await settle();
    releaseSource(json({ username: 'late_source_must_not_show', nickname: '旧来源', avatar_color: 'sage' }));
    await sourceOpening; await settle();
    assert(!text(wallEdges.root).includes('late_source_must_not_show'), 'closing a source prevents a late response from reopening identity');
    wallEdges.unmount(); mounted.pop();
    let abortedReads = 0;
    global.fetch = (path, options) => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => { abortedReads++; reject(new DOMException('Aborted', 'AbortError')); }, { once: true }));
    const switchingQuestions = mount(QuestionsPanel, { sessionId: 1, ongoing: true, user: student });
    await settle(); switchingQuestions.unmount(); await settle();
    const switchingRecap = mount(RecapPanel, { sessionId: 1 });
    find(switchingRecap.root, target => target.type === 'details').props.onToggle({ target: { open: true } });
    await settle(); switchingRecap.unmount(); await settle();
    assert.equal(abortedReads, 2, 'leaving questions and recap cancels pending reads');
    const switchingNotes = mount(PersonalNotesPanel); await settle(); switchingNotes.unmount(); await settle();
    assert.equal(abortedReads, 4, 'leaving notes cancels list and classroom requests');
    const switchingWall = mount(BuddyWallPanel, { ownerId: 1, user: student }); await settle(); switchingWall.unmount(); await settle();
    assert.equal(abortedReads, 5, 'leaving wall cancels pending reads');
    const switchingCode = mount(JoinCodePanel, { sessionId: 1, ended: false }); await settle(); switchingCode.unmount(); await settle();
    assert.equal(abortedReads, 6, 'leaving classroom cancels code settings reads');
    global.fetch = readyFetch;
    assert.equal(listeners.size, 0, 'navigation and unmount clean up visibility listeners');
    console.log('In-memory Vue interactions passed: login, roles, feedback, notes/review, buddy wall anonymous/revealable source, draft guards, edit/delete, questions/recaps, profile, buddies, reports and cancellation.');
  } finally {
    mounted.forEach(instance => instance.unmount());
    global.fetch = originalFetch; global.document = originalDocument;
    global.setInterval = originalSetInterval; global.clearInterval = originalClearInterval;
    if (originalWindow === undefined) delete global.window; else global.window = originalWindow;
    if (originalNavigator) Object.defineProperty(global, 'navigator', originalNavigator); else delete global.navigator;
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
