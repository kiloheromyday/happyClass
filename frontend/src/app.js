import { h, ref, onMounted } from 'vue';
import { api } from './api.js';
import { AuthPanel, Workspace } from './accounts.js';
import { icon, welcomeArt } from './ui.js';
import { DeveloperPanel } from './developer.js';

export const App = {
  setup() {
    const user = ref(null), restoring = ref(true), sessionMessage = ref('');
    const state = ref('loading'), checking = ref(false);
    const demo = ref({ enabled: false, active: false, accounts: [] }), demoBusy = ref(false), demoError = ref('');
    const workspaceDirty = ref(false), developerDirty = ref(false), developerBusy = ref(false), authBusy = ref(false);
    async function demoStatus() {
      try { demo.value = (await api('/api/demo/status')).data; }
      catch { demo.value = { enabled: false, active: false, accounts: [] }; }
    }
    async function demoAction(action, username) {
      if (demoBusy.value || authBusy.value || developerBusy.value) return;
      if (action !== 'enable' && (workspaceDirty.value || developerDirty.value)) { demoError.value = '还有未保存的内容，请先保存或放弃修改。'; return; }
      demoBusy.value = true; demoError.value = '';
      try {
        const result = await api(`/api/demo/${action}`, { method: 'POST', body: action === 'login' ? { username } : undefined });
        if (action === 'login') { user.value = result.data; sessionMessage.value = ''; workspaceDirty.value = false; }
        else demo.value = result.data;
      } catch (failure) { demoError.value = failure.message; if (failure.status === 401 || failure.status === 404) await demoStatus(); }
      finally { demoBusy.value = false; }
    }
    const developerSlot = () => demo.value.enabled ? h('div', { class: 'developer-container' }, [
      h(DeveloperPanel, { state: demo.value, user: user.value, busy: demoBusy.value || authBusy.value, blocked: workspaceDirty.value, onEnable: () => demoAction('enable'), onDisable: () => demoAction('disable'), onSwitch: username => demoAction('login', username), onDirtyChange: value => developerDirty.value = value, onBusyChange: value => developerBusy.value = value }),
      demoError.value ? h('p', { class: 'form-notice', role: 'alert' }, demoError.value) : null,
    ]) : null;
    async function check() {
      if (checking.value) return;
      checking.value = true; state.value = 'loading';
      try {
        const response = await fetch('/api/health', { signal: AbortSignal.timeout(5000) });
        const body = await response.json();
        if (!response.ok || body.data?.status !== 'ok') throw new Error('unavailable');
        state.value = 'ready';
      } catch { state.value = 'error'; }
      finally { checking.value = false; }
    }
    onMounted(async () => {
      check();
      demoStatus();
      try { user.value = (await api('/api/users/me')).data; }
      catch (failure) { if (failure.status !== 401) sessionMessage.value = failure.message; }
      finally { restoring.value = false; }
    });
    return () => h('div', { class: ['page', { 'page-workspace': user.value }] }, [
      h('a', { class: 'skip-link', href: '#main-content' }, '跳到主要内容'),
      h('header', { class: 'site-header' }, [
        h('a', { class: 'brand', href: '/', 'aria-label': '课堂情绪检查器首页' }, [h('span', { class: 'brand-icon' }, icon('smile', 25)), h('span', '课堂情绪检查器')]),
        h('div', { class: ['connection', state.value], role: 'status', 'aria-live': 'polite' }, [
          h('span', { class: 'dot', 'aria-hidden': 'true' }), h('span', state.value === 'ready' ? '连接正常' : state.value === 'error' ? '暂时无法连接' : '正在连接'),
          state.value === 'error' ? h('button', { type: 'button', class: 'icon-button', onClick: check, disabled: checking.value, 'aria-label': '重新连接', title: '重新连接' }, icon('refresh', 15)) : null,
        ]),
      ]),
      h('main', { id: 'main-content', tabindex: -1 }, [
        restoring.value ? h('div', { class: 'restore-session', role: 'status' }, [h('span', { class: 'loading-ring', 'aria-hidden': 'true' }), '正在准备你的课堂…'])
          : user.value ? h(Workspace, { key: user.value.id, user: user.value, demoBusy: demoBusy.value || developerBusy.value, memberDirty: developerDirty.value, onDirtyChange: value => workspaceDirty.value = value, onProfileUpdated: account => user.value = account, onSessionEnded: message => { user.value = null; workspaceDirty.value = false; sessionMessage.value = message; } }, { developer: developerSlot })
            : h('section', { class: 'hero hero-auth' }, [
              h('div', { class: 'intro' }, [
                h('p', { class: 'eyebrow' }, [h('span', { class: 'eyebrow-line' }), '让课堂，多一点理解']),
                h('h1', ['每一种感受，', h('br'), h('span', { class: 'heading-accent' }, '都值得被看见。')]),
                h('p', { class: 'lead' }, '用一个表情，记录此刻。\n让表达更轻松，让倾听更贴近。'), welcomeArt(),
              ]),
              h(AuthPanel, { initialMessage: sessionMessage.value, demoBusy: demoBusy.value || developerBusy.value, demoDirty: developerDirty.value, onBusyChange: value => authBusy.value = value, onAuthenticated: account => { user.value = account; sessionMessage.value = ''; } }, { developer: developerSlot }),
            ]),
      ]),
      h('footer', { class: 'site-footer' }, [icon('leaf', 13), h('span', '安心表达 · 从容倾听')]),
    ]);
  },
};
