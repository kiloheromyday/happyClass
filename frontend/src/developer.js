import { h, ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api } from './api.js';
import { icon } from './ui.js';

export const DeveloperPanel = {
  props: ['state', 'user', 'busy', 'blocked'], emits: ['enable', 'disable', 'switch', 'dirty-change', 'busy-change'],
  setup(props, { emit }) {
    const expanded = ref(false), managing = ref(false), mode = ref(''), selected = ref(null);
    const filters = reactive({ q: '', role: 'ALL', status: 'ALL' });
    const applied = ref(''), items = ref([]), total = ref(0), offset = ref(0), loading = ref(false), saving = ref(false);
    const error = ref(''), message = ref(''), confirm = ref(null);
    const expired = ref(false);
    const form = reactive({ username: '', nickname: '', email: '', role: 'STUDENT', password: '', confirm: '' }), baseline = ref('');
    const dirty = computed(() => Boolean(mode.value) && JSON.stringify(form) !== baseline.value);
    const locked = computed(() => props.busy || props.blocked || loading.value || saving.value);
    const changed = computed(() => applied.value !== JSON.stringify(filters));
    let alive = true, readAbort, writeAbort;
    watch(dirty, value => emit('dirty-change', value), { flush: 'sync' });
    watch(() => loading.value || saving.value, value => emit('busy-change', value), { flush: 'sync' });
    watch(() => props.state, () => expired.value = false);
    watch(() => props.state?.active, active => { if (!active) { managing.value = false; mode.value = ''; items.value = []; } });
    const beforeUnload = event => { if (dirty.value) { event.preventDefault(); event.returnValue = ''; } };
    onMounted(() => { if (typeof window !== 'undefined') window.addEventListener('beforeunload', beforeUnload); });
    onBeforeUnmount(() => { alive = false; readAbort?.abort(); writeAbort?.abort(); emit('dirty-change', false); emit('busy-change', false); form.password = form.confirm = ''; if (typeof window !== 'undefined') window.removeEventListener('beforeunload', beforeUnload); });
    async function load(nextOffset = 0) {
      if (dirty.value || saving.value) return;
      readAbort?.abort(); const abort = new AbortController(); readAbort = abort;
      loading.value = true; error.value = ''; const values = { ...filters };
      try {
        const query = new URLSearchParams({ ...values, limit: '10', offset: String(nextOffset) });
        let result = await api(`/api/demo/members?${query}`, { signal: abort.signal });
        if (!alive || abort.signal.aborted) return;
        const last = Math.max(0, Math.floor((result.data.total - 1) / 10)*10);
        if (nextOffset > last) { nextOffset = last; query.set('offset', String(last)); result = await api(`/api/demo/members?${query}`, { signal: abort.signal }); }
        if (alive && !abort.signal.aborted) { items.value = result.data.items; total.value = result.data.total; offset.value = nextOffset; applied.value = JSON.stringify(values); }
      } catch (failure) { if (alive && !abort.signal.aborted) { error.value = failure.message; expired.value = failure.status === 401; } }
      finally { if (alive && readAbort === abort) loading.value = false; }
    }
    function edit(next, item = null) {
      if (locked.value || dirty.value) return;
      mode.value = next; selected.value = item; confirm.value = null; error.value = message.value = '';
      Object.assign(form, { username: item?.username || '', nickname: item?.nickname || '', email: item?.email || '', role: item?.role || 'STUDENT', password: '', confirm: '' });
      baseline.value = JSON.stringify(form);
    }
    function close() { mode.value = ''; selected.value = null; form.password = form.confirm = ''; confirm.value = null; error.value = ''; }
    async function mutate(operation, notice) {
      if (saving.value || props.busy || props.blocked) return;
      saving.value = true; error.value = message.value = ''; const abort = new AbortController(); writeAbort = abort;
      try { await operation(abort.signal); if (alive) { close(); message.value = notice; } }
      catch (failure) { if (alive && !abort.signal.aborted) { error.value = failure.message; expired.value = failure.status === 401; } }
      finally { if (alive) saving.value = false; }
      if (alive && !error.value) await load(offset.value);
    }
    async function submit(event) {
      event.preventDefault();
      if (mode.value !== 'edit' && form.password !== form.confirm) { error.value = '两次输入的密码不一致。'; return; }
      if (mode.value === 'create') await mutate(signal => api('/api/demo/members', { method: 'POST', signal, body: { username: form.username, email: form.email || null, role: form.role, password: form.password } }), '新成员已创建，可使用填写的账号密码登录。');
      else if (mode.value === 'edit') await mutate(signal => api(`/api/demo/members/${selected.value.id}`, { method: 'PUT', signal, body: { nickname: form.nickname, email: form.email || null, expected_email: selected.value.email, expected_nickname: selected.value.nickname } }), '成员资料已保存。');
      else if (mode.value === 'password') {
        if (confirm.value !== 'PASSWORD') { confirm.value = 'PASSWORD'; return; }
        await mutate(signal => api(`/api/demo/members/${selected.value.id}/password`, { method: 'PUT', signal, body: { new_password: form.password } }), '密码已重设，该成员的旧登录已失效。');
      }
    }
    function changeStatus(item) {
      if (locked.value || dirty.value) return;
      const status = item.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE';
      if (confirm.value !== item.id) { confirm.value = item.id; return; }
      mutate(signal => api(`/api/demo/members/${item.id}/status`, { method: 'PUT', signal, body: { status, expected_status: item.status } }), status === 'DISABLED' ? '成员已停用，历史数据保留。' : '成员已启用。');
    }
    const field = (label, key, options = {}) => h('label', { class: 'field' }, [h('span', label), h('input', { name: `demo_${key}`, value: form[key], disabled: saving.value, onInput: event => { form[key] = event.target.value; if (confirm.value === 'PASSWORD') confirm.value = null; }, ...options })]);
    function editor() {
      return h('form', { class: 'demo-member-form', onSubmit: submit }, [h('h4', mode.value === 'create' ? '新建学生或教师' : `${mode.value === 'edit' ? '编辑资料' : '重设密码'} · ${selected.value.username}`),
        mode.value === 'create' ? h('div', { class: 'form-pair' }, [field('用户名', 'username', { required: true, minlength: 3, maxlength: 254, autocomplete: 'off' }), h('label', { class: 'field' }, [h('span', '成员角色'), h('select', { name: 'demo_role', value: form.role, disabled: saving.value, onChange: event => form.role = event.target.value }, [h('option', { value: 'STUDENT' }, '学生'), h('option', { value: 'TEACHER' }, '教师')])])]) : null,
        mode.value === 'edit' ? field('昵称', 'nickname', { maxlength: 32 }) : null,
        mode.value !== 'password' ? field('邮箱（选填）', 'email', { type: 'email', maxlength: 254 }) : null,
        mode.value !== 'edit' ? h('div', { class: 'form-pair' }, [field('新密码', 'password', { type: 'password', required: true, minlength: 10, maxlength: 128, autocomplete: 'new-password', placeholder: '至少 10 位，包含字母和数字' }), field('确认密码', 'confirm', { type: 'password', required: true, maxlength: 128, autocomplete: 'new-password' })]) : null,
        confirm.value === 'PASSWORD' ? h('p', { class: 'data-note', role: 'status' }, '确认重设后，该成员在其他页面的登录将失效。') : null,
        h('div', { class: 'guide-actions' }, [h('button', { type: 'button', class: 'quiet-button', disabled: saving.value, onClick: close }, dirty.value ? '放弃成员修改' : '取消成员编辑'), h('button', { type: 'submit', class: 'primary-button', disabled: saving.value || !dirty.value }, saving.value ? '正在保存…' : mode.value === 'password' ? confirm.value === 'PASSWORD' ? '确认重设密码' : '重设成员密码' : '保存成员')]),
      ]);
    }
    function members() {
      return h('section', { class: 'demo-members' }, [
        h('div', { class: 'section-title' }, [h('h3', '学生与教师成员'), h('button', { class: 'secondary-button', disabled: locked.value || dirty.value, onClick: () => edit('create') }, '新建成员')]),
        h('form', { class: 'demo-member-filters', onSubmit: event => { event.preventDefault(); if (dirty.value || locked.value) return; close(); message.value = ''; load(); } }, [h('input', { name: 'demo_member_query', 'aria-label': '查找成员', placeholder: '用户名、昵称或邮箱', value: filters.q, maxlength: 120, disabled: locked.value || dirty.value, onInput: event => filters.q = event.target.value }), ...[['role', [['ALL', '全部角色'], ['STUDENT', '学生'], ['TEACHER', '教师']]], ['status', [['ALL', '全部状态'], ['ACTIVE', '正常'], ['DISABLED', '已停用']]]].map(([key, options]) => h('select', { name: `demo_filter_${key}`, 'aria-label': key === 'role' ? '成员角色筛选' : '成员状态筛选', value: filters[key], disabled: locked.value || dirty.value, onChange: event => filters[key] = event.target.value }, options.map(([value, label]) => h('option', { value }, label)))), h('button', { class: 'secondary-button', disabled: locked.value || dirty.value }, '查找成员')]),
        mode.value ? editor() : null,
        changed.value ? h('p', { class: 'data-note' }, '筛选条件已更改，请点击查找成员。') : null,
        loading.value ? h('p', { class: 'data-note', role: 'status' }, '正在读取成员…') : null,
        h('div', { class: 'demo-member-list' }, items.value.map(item => h('article', { class: 'demo-member-row', key: item.id }, [h('div', [h('strong', item.nickname || item.username), h('p', `${item.username} · ${item.role === 'TEACHER' ? '教师' : '学生'} · ${item.status === 'ACTIVE' ? '正常' : '已停用'}`), item.email ? h('p', item.email) : null]), item.protected ? h('span', { class: 'demo-protected' }, '固定演示账号') : h('div', { class: 'demo-member-actions' }, [h('button', { class: 'quiet-button', 'aria-label': `编辑成员：${item.username}`, disabled: locked.value || dirty.value, onClick: () => edit('edit', item) }, '编辑资料'), h('button', { class: 'quiet-button', 'aria-label': `重设密码：${item.username}`, disabled: locked.value || dirty.value, onClick: () => edit('password', item) }, '重设密码'), h('button', { class: 'quiet-button', 'aria-label': `切换成员状态：${item.username}`, disabled: locked.value || dirty.value, onClick: () => changeStatus(item) }, confirm.value === item.id ? item.status === 'ACTIVE' ? '确认停用' : '确认启用' : item.status === 'ACTIVE' ? '停用成员' : '启用成员'), confirm.value === item.id ? h('button', { class: 'quiet-button', onClick: () => confirm.value = null }, '取消状态操作') : null])]))),
        !loading.value && !items.value.length ? h('p', { class: 'empty-note' }, '没有找到符合条件的成员。') : null,
        total.value > 10 || offset.value ? h('div', { class: 'pagination' }, [h('button', { disabled: locked.value || dirty.value || offset.value === 0 || changed.value, onClick: () => load(offset.value-10) }, '上一页成员'), h('span', `共 ${total.value} 位 · 第 ${Math.floor(offset.value/10)+1} 页`), h('button', { disabled: locked.value || dirty.value || offset.value+10 >= total.value || changed.value, onClick: () => load(offset.value+10) }, '下一页成员')]) : null,
      ]);
    }
    return () => props.state?.enabled ? h('section', { class: ['developer-panel', { active: props.state.active }], 'aria-label': '演示开发者模式' }, [
      h('div', { class: 'developer-heading' }, [h('button', { type: 'button', class: 'quiet-button', 'aria-expanded': expanded.value, disabled: props.busy, onClick: () => expanded.value = !expanded.value }, [icon('classroom', 16), props.state.active ? '开发者模式 · 已开启' : '开发者模式']), props.state.active ? h('span', { class: 'demo-local' }, '本地演示') : null]),
      expanded.value || props.state.active ? h('div', { class: 'developer-body' }, [
        !props.state.active ? h('div', [h('p', { class: 'data-note' }, '开启后可切换演示学生、教师、管理员，并管理学生与教师成员。'), h('button', { class: 'secondary-button', disabled: props.busy, onClick: () => emit('enable') }, '开启演示开发者模式')]) : h('div', [
          h('div', { class: 'demo-switches' }, props.state.accounts.map(account => h('button', { type: 'button', class: props.user?.username === account.username ? 'secondary-button selected' : 'secondary-button', 'aria-pressed': props.user?.username === account.username, disabled: locked.value || dirty.value || props.user?.username === account.username, onClick: () => emit('switch', account.username) }, account.label))),
          h('div', { class: 'demo-tools' }, [h('button', { class: 'quiet-button', disabled: locked.value || dirty.value, onClick: () => { managing.value = !managing.value; close(); if (managing.value) load(); } }, managing.value ? '收起成员管理' : '管理学生与教师'), h('button', { class: 'quiet-button', disabled: locked.value || dirty.value, onClick: () => emit('disable') }, '关闭开发者模式')]),
          props.blocked ? h('p', { class: 'data-note', role: 'status' }, '当前页面有未保存的内容，请保存或放弃修改后切换。') : null,
          managing.value ? members() : null,
        ]),
      ]) : null,
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null,
      expired.value ? h('button', { class: 'secondary-button', disabled: props.busy, onClick: () => emit('enable') }, '重新开启开发者模式') : null,
      message.value ? h('p', { class: 'form-notice success', role: 'status' }, message.value) : null,
    ]) : null;
  },
};
