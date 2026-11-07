import { h, reactive, ref, onBeforeUnmount } from 'vue';
import { api } from './api.js';

export const AdminUserForm = {
  emits: ['created', 'expired'],
  setup(_, { emit }) {
    const form = reactive({ username: '', email: '', password: '', confirm: '', role: 'TEACHER' });
    const busy = ref(false), error = ref(''), message = ref('');
    const abort = new AbortController();
    let disposed = false;
    onBeforeUnmount(() => { disposed = true; abort.abort(); form.password = form.confirm = ''; });
    async function submit(event) {
      event.preventDefault(); if (busy.value) return;
      error.value = message.value = '';
      if (form.password !== form.confirm) { error.value = '两次输入的密码不一致。'; return; }
      busy.value = true;
      try {
        const result = await api('/api/admin/users', { method: 'POST', body: { username: form.username, email: form.email || null, password: form.password, role: form.role }, signal: abort.signal });
        if (!disposed) { form.password = form.confirm = ''; form.username = form.email = ''; message.value = result.message; emit('created'); }
      } catch (failure) { if (!disposed) { if (failure.status === 401) emit('expired'); else error.value = failure.message; } }
      finally { busy.value = false; }
    }
    const field = (label, name, options) => h('label', { class: 'field' }, [h('span', label), h('input', { name, value: form[name], onInput: event => form[name] = event.target.value, ...options })]);
    return () => h('details', { class: 'management-tools' }, [h('summary', '创建教师或学生账号'), h('form', { class: 'password-form', onSubmit: submit }, [
      h('label', { class: 'field' }, [h('span', '账号角色'), h('select', { value: form.role, onChange: event => form.role = event.target.value }, [h('option', { value: 'TEACHER' }, '教师'), h('option', { value: 'STUDENT' }, '学生')])]),
      field('用户名', 'username', { required: true, minlength: 3, maxlength: 254, pattern: '[A-Za-z0-9_][A-Za-z0-9_.@+\\-]*', autocomplete: 'off' }),
      field('邮箱（可选）', 'email', { type: 'email', maxlength: 254 }),
      field('初始密码', 'password', { type: 'password', required: true, minlength: 10, maxlength: 128, autocomplete: 'new-password', placeholder: '至少 10 位，包含字母和数字' }),
      field('确认密码', 'confirm', { type: 'password', required: true, maxlength: 128, autocomplete: 'new-password' }),
      h('p', { class: 'muted' }, '请将账号交给对应使用者，首次登录后可在“账号安全”修改密码。'),
      error.value ? h('div', { class: 'form-notice', role: 'alert' }, error.value) : null,
      message.value ? h('div', { class: 'form-notice success', role: 'status' }, message.value) : null,
      h('button', { class: 'primary-button', disabled: busy.value }, busy.value ? '正在创建…' : '创建账号'),
    ])]);
  },
};
