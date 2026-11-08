import { Avatar } from './avatar.js';
import { h, ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api } from './api.js';
import { ClassroomPanel } from './classroom.js';
import { AnalyticsPanel } from './analytics.js';
import { AdminUserForm } from './admin-users.js';
import { icon } from './ui.js';
import { ProfilePanel } from './profile.js';
import { BuddiesPanel } from './buddies.js';
import { PersonalNotesPanel } from './notes.js';
import { CoursesPanel } from './courses.js';
import { TeachingPanel } from './teaching.js';
import { CampusPanel } from './campus.js';
import { LeavesPanel } from './leaves.js';
import { EvaluationsPanel } from './evaluations.js';
import { MessagesPanel } from './messages.js';
import { CatalogPanel } from './catalog.js';
import { createPoller } from './polling.js';

export const roleNames = { STUDENT: '学生', TEACHER: '教师', ADMIN: '管理员' };
const field = (label, name, value, setter, options = {}) => h('label', { class: 'field' }, [h('span', label), h('input', { name, value, onInput: event => setter(event.target.value), ...options })]);
const notice = (message, type = 'error') => message ? h('div', { class: ['form-notice', type], role: type === 'error' ? 'alert' : 'status' }, message) : null;
const dateText = value => new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(value));

export const AuthPanel = {
  props: ['initialMessage', 'demoBusy', 'demoDirty'], emits: ['authenticated', 'busy-change'],
  setup(props, { emit, slots }) {
    const mode = ref('login'), busy = ref(false), error = ref('');
    const values = reactive({ username: '', password: '', email: '', confirm: '' });
    watch(busy, value => emit('busy-change', value), { flush: 'sync' });
    function switchMode(next) { mode.value = next; values.password = values.confirm = ''; error.value = ''; }
    async function submit(event) {
      event.preventDefault();
      if (busy.value || props.demoBusy) return;
      if (props.demoDirty) { error.value = '成员修改尚未保存，请保存或放弃修改后登录。'; return; }
      error.value = '';
      if (mode.value === 'register' && values.password !== values.confirm) { error.value = '两次输入的密码不一致。'; return; }
      busy.value = true;
      try {
        const body = { username: values.username, password: values.password };
        if (mode.value === 'register') body.email = values.email || null;
        const result = await api(`/api/auth/${mode.value}`, { method: 'POST', body });
        values.password = values.confirm = '';
        emit('authenticated', result.data);
      } catch (failure) { error.value = failure.message; }
      finally { busy.value = false; }
    }
    return () => h('section', { class: 'auth-card', 'aria-label': '账号入口' }, [
      h('div', { class: 'auth-tabs', 'aria-label': '登录或注册' }, ['login', 'register'].map(item => h('button', { type: 'button', class: { active: mode.value === item }, 'aria-pressed': mode.value === item, disabled: busy.value, onClick: () => switchMode(item) }, item === 'login' ? '登录' : '学生注册'))),
      h('h2', mode.value === 'login' ? '欢迎回到课堂' : '开启你的课堂记录'),
      h('p', { class: 'form-intro' }, mode.value === 'login' ? '留一点时间，听听此刻的自己。' : '从今天开始，留下自己的课堂感受。'), notice(props.initialMessage, 'success'),
      h('form', { onSubmit: submit }, [
        field('用户名', 'username', values.username, value => values.username = value, { required: true, minlength: 3, maxlength: 254, pattern: '[A-Za-z0-9_][A-Za-z0-9_.@+\\-]*', autocomplete: 'username', placeholder: mode.value === 'register' ? '3～254 位，支持邮箱式用户名' : '请输入用户名', autocapitalize: 'none', spellcheck: false }),
        mode.value === 'register' ? field('邮箱（可选）', 'email', values.email, value => values.email = value, { type: 'email', maxlength: 254, autocomplete: 'email' }) : null,
        field('密码', 'password', values.password, value => values.password = value, { type: 'password', required: true, minlength: mode.value === 'register' ? 10 : 1, maxlength: 128, autocomplete: mode.value === 'register' ? 'new-password' : 'current-password', placeholder: mode.value === 'register' ? '至少 10 位，包含字母和数字' : '请输入密码' }),
        mode.value === 'register' ? field('确认密码', 'confirm', values.confirm, value => values.confirm = value, { type: 'password', required: true, maxlength: 128, autocomplete: 'new-password' }) : null,
        notice(error.value), h('button', { class: 'primary-button auth-submit', type: 'submit', disabled: busy.value }, [h('span', busy.value ? '正在处理…' : mode.value === 'login' ? '进入课堂' : '注册并进入'), busy.value ? null : icon('arrow', 18)]),
      ]), mode.value === 'register' ? h('p', { class: 'form-footnote' }, '教师账号请联系管理员。') : null,
      slots.developer?.(),
    ]);
  },
};

export const Workspace = {
  props: ['user', 'demoBusy', 'memberDirty'], emits: ['session-ended', 'profile-updated', 'dirty-change'],
  setup(props, { emit, slots }) {
    const tab = ref(props.user.role === 'ADMIN' ? 'campus' : props.user.role === 'TEACHER' ? 'teaching' : 'classroom'), error = ref(''), loading = ref(false), changing = ref(false), logoutBusy = ref(false);
    const users = ref([]), total = ref(0), offset = ref(0);
    const password = reactive({ current: '', next: '', confirm: '' });
    const notebookDirty = ref(false), leaveDirty = ref(false), extensionDirty = ref(false), unreadCount = ref(0);
    let unreadRevision = 0;
    const messagePoller = createPoller({ interval: 30000, load: async (_, signal) => { const revision = unreadRevision; return { ...(await api('/api/messages?limit=1', { signal })).data, revision }; }, onData: data => { if (data.revision === unreadRevision) unreadCount.value = data.unread_count; }, onError: () => {} });
    onMounted(() => messagePoller.start('inbox'));
    onBeforeUnmount(() => messagePoller.stop());
    const wallDirty = ref(false);
    const profileDirty = ref(false);
    const navigation = ref({});
    const classroomDirty = ref(false), scheduleDirty = ref(false);
    const editing = computed(() => extensionDirty.value || leaveDirty.value || notebookDirty.value || wallDirty.value || profileDirty.value || classroomDirty.value || scheduleDirty.value || changing.value || loading.value || logoutBusy.value);
    watch(editing, value => emit('dirty-change', value), { flush: 'sync' });
    const dirtyClass = value => { classroomDirty.value = value; if (!value) error.value = ''; };
    const dirtySchedule = value => { scheduleDirty.value = value; if (!value) error.value = ''; };
    const beforeUnload = event => { if (extensionDirty.value || leaveDirty.value || classroomDirty.value || scheduleDirty.value) { event.preventDefault(); event.returnValue = ''; } };
    onMounted(() => { if (typeof window !== 'undefined') window.addEventListener('beforeunload', beforeUnload); });
    onBeforeUnmount(() => { if (typeof window !== 'undefined') window.removeEventListener('beforeunload', beforeUnload); });
    function handleError(failure) {
      if (failure.status === 401) emit('session-ended', '登录已过期，请重新登录。');
      else error.value = failure.message;
    }
    async function loadUsers(nextOffset = 0) {
      loading.value = true; error.value = '';
      try {
        const result = await api(`/api/admin/users?limit=10&offset=${nextOffset}`);
        users.value = result.data.items; total.value = result.data.total; offset.value = nextOffset;
      } catch (failure) { handleError(failure); }
      finally { loading.value = false; }
    }
    async function selectTab(target) {
      if (props.demoBusy) return;
      if (props.memberDirty) { error.value = '成员修改尚未保存，请先保存或放弃成员修改。'; return; }
      const next = typeof target === 'string' ? target : target.tab;
      if (extensionDirty.value) { error.value = '表单内容尚未保存，请先保存或清空草稿。'; return; }
      if (leaveDirty.value) { error.value = '请假申请或审批尚未保存，请先完成或放弃草稿。'; return; }
      if (classroomDirty.value) { error.value = '课堂中有未保存的内容，请先保存或放弃修改后离开。'; return; }
      if (scheduleDirty.value) { error.value = '新课堂安排尚未保存，请先保存或放弃安排。'; return; }
      if (profileDirty.value && next !== tab.value) { error.value = '头像预览或个人资料尚未保存，请先保存，或取消预览、撤销修改。'; return; }
      if (wallDirty.value && next !== tab.value) { error.value = '留言草稿尚未发送或保存，请先完成，或在留言墙选择放弃草稿并返回。'; return; }
      if (notebookDirty.value && next !== tab.value) { error.value = '笔记尚未保存，请先保存，或在笔记中选择放弃修改并返回。'; return; }
      if (changing.value || loading.value) return;
      navigation.value = typeof target === 'string' ? {} : target;
      tab.value = next; error.value = ''; password.current = password.next = password.confirm = '';
      if (next === 'users') await loadUsers();
    }
    async function changePassword(event) {
      event.preventDefault();
      if (props.demoBusy) return;
      if (props.memberDirty) { error.value = '成员修改尚未保存，请先保存或放弃成员修改。'; return; }
      if (changing.value) return;
      error.value = '';
      if (password.next !== password.confirm) { error.value = '两次输入的新密码不一致。'; return; }
      changing.value = true;
      try {
        const result = await api('/api/auth/password', { method: 'PUT', body: { current_password: password.current, new_password: password.next } });
        password.current = password.next = password.confirm = ''; emit('session-ended', result.message);
      } catch (failure) { handleError(failure); }
      finally { changing.value = false; }
    }
    async function logout() {
      if (props.demoBusy) return;
      if (props.memberDirty) { error.value = '成员修改尚未保存，请先保存或放弃成员修改。'; return; }
      if (extensionDirty.value) { error.value = '表单内容尚未保存，请先保存或清空草稿。'; return; }
      if (leaveDirty.value) { error.value = '请假申请或审批尚未保存，请先完成或放弃草稿。'; return; }
      if (classroomDirty.value || scheduleDirty.value) { error.value = '教学或课堂内容尚未保存，请先保存或放弃修改。'; return; }
      if (profileDirty.value) { error.value = '头像预览或个人资料尚未保存，请先保存，或取消预览、撤销修改。'; return; }
      if (wallDirty.value) { error.value = '留言草稿尚未发送或保存，请先完成，或在留言墙选择放弃草稿并返回。'; return; }
      if (notebookDirty.value) { error.value = '笔记尚未保存，请先保存，或在笔记中选择放弃修改并返回。'; return; }
      if (logoutBusy.value) return;
      logoutBusy.value = true;
      try { await api('/api/auth/logout', { method: 'POST' }); emit('session-ended', '已安全退出登录。'); }
      catch (failure) { handleError(failure); }
      finally { logoutBusy.value = false; }
    }
    const navIcons = { evaluations: 'chart', messages: 'history', catalog: 'book', leaves: 'book', campus: 'dashboard', teaching: 'book', notes: 'book', overview: 'profile', buddies: 'users', classroom: 'classroom', dashboard: 'dashboard', reports: 'chart', history: 'history', users: 'users', courses: 'book', password: 'lock' };
    const navItem = (id, text) => h('button', { type: 'button', class: { selected: tab.value === id }, 'aria-current': tab.value === id ? 'page' : undefined, onClick: () => selectTab(id), disabled: changing.value || loading.value }, [icon(navIcons[id], 18), h('span', text), id === 'messages' && unreadCount.value ? h('span', { class: 'nav-unread', 'aria-label': `${unreadCount.value}条未读消息` }, unreadCount.value > 99 ? '99+' : String(unreadCount.value)) : null, tab.value === id ? h('span', { class: 'nav-current', 'aria-hidden': 'true' }) : null]);
    function content() {
      if (tab.value === 'evaluations') return h(EvaluationsPanel, { key: `evaluations:${navigation.value.sessionId || ''}:${navigation.value.courseId || ''}`, user: props.user, initialSessionId: navigation.value.sessionId, initialCourseId: navigation.value.courseId, initialDataScope: navigation.value.dataScope, onDirtyChange: value => { extensionDirty.value = value; if (!value) error.value = ''; }, onNavigate: selectTab, onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'messages') return h(MessagesPanel, { onNavigate: selectTab, onUnreadChange: value => { unreadRevision += 1; unreadCount.value = value; }, onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'catalog' && props.user.role === 'ADMIN') return h(CatalogPanel, { onDirtyChange: value => { extensionDirty.value = value; if (!value) error.value = ''; }, onNavigate: selectTab, onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'leaves') return h(LeavesPanel, { key: `leaves:${navigation.value.sessionId || ''}`, user: props.user, initialSessionId: navigation.value.sessionId, onDirtyChange: value => { leaveDirty.value = value; if (!value) error.value = ''; }, onNavigate: selectTab, onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'campus') return h(CampusPanel, { onNavigate: selectTab, onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'teaching') return h(TeachingPanel, { user: props.user, onNavigate: selectTab, onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'courses') return h(CoursesPanel, { user: props.user, initialCourseId: navigation.value.courseId, onDirtyChange: dirtySchedule, onNavigate: selectTab, onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'notes') return h(PersonalNotesPanel, { initialSessionId: navigation.value.sessionId, initialView: navigation.value.view, initialCourseId: navigation.value.courseId, onNavigate: selectTab, onDirtyChange: value => { notebookDirty.value = value; if (!value) error.value = ''; }, onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'overview') return h(ProfilePanel, { user: props.user, onNavigate: selectTab, onDirtyChange: value => { profileDirty.value = value; if (!value) error.value = ''; }, onUpdated: account => emit('profile-updated', account), onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'buddies') return h(BuddiesPanel, { user: props.user, onDirtyChange: value => { wallDirty.value = value; if (!value) error.value = ''; }, onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'dashboard' || tab.value === 'reports') return h(AnalyticsPanel, { key: `${tab.value}:${navigation.value.sessionId || ''}:${navigation.value.courseId || ''}`, user: props.user, initialSessionId: navigation.value.sessionId, initialCourseId: navigation.value.courseId, initialDataScope: navigation.value.dataScope, onNavigate: selectTab, realtime: tab.value === 'dashboard', onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'classroom' || tab.value === 'history') return h(ClassroomPanel, { key: `${tab.value}:${navigation.value.sessionId || ''}`, user: props.user, initialSessionId: navigation.value.sessionId, initialCourseId: navigation.value.courseId, initialDataScope: navigation.value.dataScope, initialView: navigation.value.view, onDirtyChange: dirtyClass, onNavigate: selectTab, historyOnly: tab.value === 'history', onExpired: () => emit('session-ended', '登录已过期，请重新登录。') });
      if (tab.value === 'password') return [h('h2', '修改登录密码'), h('p', { class: 'muted' }, '修改后所有设备都会退出登录，请使用新密码重新进入。'), h('form', { class: 'password-form', onSubmit: changePassword }, [
        field('当前密码', 'current_password', password.current, value => password.current = value, { type: 'password', required: true, maxlength: 128, autocomplete: 'current-password' }),
        field('新密码', 'new_password', password.next, value => password.next = value, { type: 'password', required: true, minlength: 10, maxlength: 128, autocomplete: 'new-password', placeholder: '至少 10 位，包含字母和数字' }),
        field('确认新密码', 'confirm_password', password.confirm, value => password.confirm = value, { type: 'password', required: true, maxlength: 128, autocomplete: 'new-password' }),
        notice(error.value), h('button', { class: 'primary-button', disabled: changing.value }, changing.value ? '正在保存…' : '保存新密码'),
      ])];
      if (tab.value === 'users') return [
        h('div', { class: 'section-title' }, [h('h2', '用户列表'), h('span', { class: 'count' }, `共 ${total.value} 位`)]), h(AdminUserForm, { onDirtyChange: value => { extensionDirty.value = value; if (!value) error.value = ''; }, onCreated: () => loadUsers(), onExpired: () => emit('session-ended', '登录已过期，请重新登录。') }), notice(error.value),
        loading.value ? h('p', { role: 'status' }, '正在加载用户…') : h('div', { class: 'table-wrap' }, [h('table', [
          h('thead', h('tr', ['用户名', '角色', '邮箱', '状态', '注册时间'].map(text => h('th', { scope: 'col' }, text)))),
          h('tbody', users.value.map(user => h('tr', { key: user.id }, [h('td', { title: user.username }, user.username), h('td', h('span', { class: 'table-badge' }, roleNames[user.role])), h('td', { title: user.email || undefined }, user.email || '—'), h('td', h('span', { class: ['status-text', { active: user.status === 'ACTIVE' }] }, user.status === 'ACTIVE' ? '正常' : '已停用')), h('td', dateText(user.created_at))]))),
        ])]),
        total.value > 10 || offset.value > 0 ? h('div', { class: 'pagination' }, [h('button', { disabled: loading.value || offset.value === 0, onClick: () => loadUsers(offset.value - 10) }, '上一页'), h('span', `第 ${Math.floor(offset.value / 10) + 1} 页`), h('button', { disabled: loading.value || offset.value + 10 >= total.value, onClick: () => loadUsers(offset.value + 10) }, '下一页')]) : null,
      ];
      return null;
    }
    return () => h('section', { class: 'workspace' }, [h('aside', { class: 'workspace-nav' }, [
      h('div', { class: 'workspace-identity' }, [h(Avatar, { person: props.user, variant: 'avatar' }), h('div', { class: 'identity-text' }, [h('strong', { title: props.user.username }, props.user.nickname || props.user.username), h('span', { class: 'role-badge' }, roleNames[props.user.role])])]),
      h('nav', { 'aria-label': '工作台导航' }, [h('span', { class: 'nav-label' }, '课堂空间'), navItem('messages', '消息中心'), navItem('evaluations', '课程评价'), props.user.role === 'ADMIN' ? navItem('campus', '开课总览') : null, props.user.role !== 'STUDENT' ? navItem('teaching', '教学工作台') : null, navItem('leaves', props.user.role === 'STUDENT' ? '请假申请' : props.user.role === 'TEACHER' ? '请假审批' : '请假记录'), navItem('classroom', props.user.role === 'ADMIN' ? '课程与课堂' : props.user.role === 'TEACHER' ? '课堂反馈' : '我的课堂'), props.user.role !== 'STUDENT' ? navItem('dashboard', '实时看板') : null, props.user.role !== 'STUDENT' ? navItem('reports', '统计与导出') : null, props.user.role === 'STUDENT' ? navItem('history', '情绪历史') : null, props.user.role === 'STUDENT' ? navItem('notes', '笔记与回顾') : null, props.user.role === 'STUDENT' ? navItem('buddies', '好友学伴') : null, props.user.role === 'ADMIN' ? navItem('users', '用户列表') : null, props.user.role === 'ADMIN' ? navItem('catalog', '院系与课程维护') : null, navItem('courses', props.user.role === 'ADMIN' ? '全校课程' : '我的课程'), h('span', { class: 'nav-label nav-label-account' }, '我的账户'), navItem('overview', '个人资料'), navItem('password', '账号安全')]),
      h('button', { type: 'button', class: 'logout-button', onClick: logout, disabled: logoutBusy.value || changing.value }, [icon('logout', 17), h('span', logoutBusy.value ? '正在退出…' : '退出登录')]),
    ]), h('div', { class: 'workspace-content', 'aria-busy': loading.value }, [
      slots.developer?.(),
      ['evaluations', 'messages', 'catalog', 'leaves', 'campus', 'teaching', 'classroom', 'history', 'dashboard', 'reports', 'notes', 'buddies', 'overview', 'courses'].includes(tab.value) ? notice(error.value) : null,
      content(),
    ])]);
  },
};
