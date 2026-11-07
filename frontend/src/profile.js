import { h, reactive, ref, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api } from './api.js';
import { icon, learningStyles } from './ui.js';
import { Avatar } from './avatar.js';

export const ProfilePanel = {
  props: ['user'], emits: ['updated', 'expired', 'navigate', 'dirty-change'],
  setup(props, { emit }) {
    const initial = () => ({ nickname: props.user.nickname || '', email: props.user.email || '', bio: props.user.bio || '', interests: props.user.interests || '', avatar_color: props.user.avatar_color || 'sage', major: props.user.major || '', grade: props.user.grade || '', study_goal: props.user.study_goal || '', learning_style: props.user.learning_style || '' });
    const form = reactive(initial()), saved = ref(JSON.stringify(initial()));
    const busy = ref(false), error = ref(''), message = ref('');
    const overview = ref(null), overviewError = ref(''), overviewLoading = ref(false);
    const picked = ref(null), preview = ref(''), dimensions = ref(null), confirmRemove = ref(false);
    const crop = reactive({ zoom: 1, x: 50, y: 50 });
    const changed = computed(() => JSON.stringify(form) !== saved.value);
    const controller = new AbortController(); let disposed = false;
    const dirty = computed(() => busy.value || changed.value || !!picked.value);
    watch(dirty, value => emit('dirty-change', value), { flush: 'sync' });
    const beforeUnload = event => { if (dirty.value) { event.preventDefault(); event.returnValue = ''; } };
    function cancelPhoto() {
      if (preview.value) URL.revokeObjectURL(preview.value);
      preview.value = ''; picked.value = null; dimensions.value = null;
    }
    onMounted(() => { loadOverview(); if (typeof window !== 'undefined') window.addEventListener('beforeunload', beforeUnload); });
    onBeforeUnmount(() => { disposed = true; controller.abort(); cancelPhoto(); emit('dirty-change', false); if (typeof window !== 'undefined') window.removeEventListener('beforeunload', beforeUnload); });
    async function loadOverview() {
      overviewLoading.value = true; overviewError.value = '';
      try { const result = await api('/api/users/me/overview', { signal: controller.signal }); if (!disposed) overview.value = result.data; }
      catch (failure) { if (!disposed) { if (failure.status === 401) emit('expired'); else overviewError.value = failure.message; } }
      finally { if (!disposed) overviewLoading.value = false; }
    }
    function choosePhoto(event) {
      const file = event.target.files?.[0]; event.target.value = '';
      if (!file || busy.value) return;
      error.value = message.value = '';
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { error.value = '请选择 JPG、PNG 或 WebP 静态图片'; return; }
      if (!file.size || file.size > 2 * 1024 * 1024) { error.value = '头像图片应在 2 MB 以内'; return; }
      cancelPhoto(); picked.value = file; preview.value = URL.createObjectURL(file); confirmRemove.value = false;
      Object.assign(crop, { zoom: 1, x: 50, y: 50 });
    }
    async function savePhoto(remove = false) {
      if (busy.value || (!remove && (!picked.value || !dimensions.value))) return;
      busy.value = true; error.value = message.value = '';
      try {
        const query = new URLSearchParams({ zoom: crop.zoom, x: crop.x / 100, y: crop.y / 100 });
        const result = await api(`/api/users/me/avatar${remove ? '' : '?' + query}`, { method: remove ? 'DELETE' : 'PUT', ...(remove ? {} : { body: picked.value, headers: { 'Content-Type': picked.value.type } }), signal: controller.signal, timeoutMs: 20000 });
        if (!disposed) { cancelPhoto(); confirmRemove.value = false; message.value = result.message; emit('updated', result.data); }
      } catch (failure) { if (!disposed) { if (failure.status === 401) emit('expired'); else error.value = failure.message; } }
      finally { if (!disposed) busy.value = false; }
    }
    const cropStyle = computed(() => {
      if (!dimensions.value) return { width: '100%', height: '100%', objectFit: 'cover' };
      const { width, height } = dimensions.value, scale = 160 * crop.zoom / Math.min(width, height);
      return { width: `${width * scale}px`, height: `${height * scale}px`, left: `${-(width * scale - 160) * crop.x / 100}px`, top: `${-(height * scale - 160) * crop.y / 100}px` };
    });
    async function submit(event) {
      event.preventDefault(); if (busy.value || !changed.value) return;
      busy.value = true; error.value = message.value = '';
      try {
        const result = await api('/api/users/me', { method: 'PUT', body: { ...form, email: form.email || null }, signal: controller.signal });
        if (disposed) return;
        for (const key of Object.keys(form)) form[key] = result.data[key] || (key === 'avatar_color' ? 'sage' : '');
        saved.value = JSON.stringify(form); message.value = result.message;
        emit('updated', result.data);
      } catch (failure) { if (!disposed) { if (failure.status === 401) emit('expired'); else error.value = failure.message; } }
      finally { if (!disposed) busy.value = false; }
    }
    const input = (label, key, options = {}) => h('label', { class: 'field' }, [h('span', label), h('input', { name: key, value: form[key], disabled: busy.value, onInput: event => { form[key] = event.target.value; message.value = ''; }, ...options })]);
    return () => h('section', { class: 'profile-panel' }, [
      h('div', { class: 'section-title' }, [h('div', [h('h2', '个人主页'), h('p', { class: 'profile-page-subtitle' }, '关于你，也关于这段学习时光。')]), h('button', { class: 'quiet-button', disabled: overviewLoading.value, onClick: loadOverview }, [icon('refresh', 15), '刷新概览'])]),
      overview.value ? h('div', { class: 'profile-metrics' }, overview.value.metrics.map(item => h('button', { class: 'profile-metric', onClick: () => emit('navigate', item.target) }, [h('strong', String(item.value)), h('span', item.label), icon('arrow', 14)]))) : null,
      overviewError.value ? h('p', { class: 'form-notice', role: 'alert' }, overviewError.value) : null,
      error.value ? h('div', { class: 'form-notice', role: 'alert' }, error.value) : null,
      message.value ? h('div', { class: 'form-notice success', role: 'status' }, message.value) : null,
      h('div', { class: 'profile-layout' }, [
        h('div', { class: 'profile-preview' }, [
          preview.value ? h('div', { class: 'profile-avatar-crop', 'aria-label': '新头像预览' }, h('img', { src: preview.value, alt: '待保存的头像', style: cropStyle.value, onLoad: event => { dimensions.value = { width: event.target.naturalWidth, height: event.target.naturalHeight }; }, onError: () => { cancelPhoto(); error.value = '图片无法预览，请重新选择'; } })) : h(Avatar, { person: { ...props.user, nickname: form.nickname, avatar_color: form.avatar_color }, variant: 'profile-avatar' }),
          h('div', { class: 'avatar-upload-actions' }, [h('label', { class: ['secondary-button', { disabled: busy.value }], 'aria-label': '选择头像图片' }, [icon('camera', 14), props.user.avatar_url ? '更换头像' : '上传头像', h('input', { name: 'avatar_file', type: 'file', accept: 'image/jpeg,image/png,image/webp', disabled: busy.value, onChange: choosePhoto })]), props.user.avatar_url && !picked.value ? h('button', { type: 'button', class: 'quiet-button', disabled: busy.value, onClick: () => confirmRemove.value = !confirmRemove.value }, '恢复默认头像') : null]),
          picked.value ? h('div', { class: 'avatar-crop-controls' }, [
            ...[['zoom', '大小', 1, 3, .1], ['x', '左右', 0, 100, 1], ['y', '上下', 0, 100, 1]].map(([key, label, min, max, step]) => h('label', [h('span', label), h('input', { type: 'range', name: `avatar_${key}`, min, max, step, value: crop[key], disabled: busy.value, onInput: event => crop[key] = Number(event.target.value) })])),
            h('div', [h('button', { type: 'button', class: 'secondary-button', disabled: busy.value || !dimensions.value, onClick: () => savePhoto() }, busy.value ? '正在保存…' : '保存头像'), h('button', { type: 'button', class: 'quiet-button', disabled: busy.value, onClick: cancelPhoto }, '取消预览')]),
          ]) : h('p', { class: 'avatar-upload-hint' }, 'JPG / PNG / WebP · 2 MB 以内'),
          confirmRemove.value ? h('div', { class: 'avatar-remove-confirm' }, [h('p', '恢复默认的文字头像？'), h('button', { type: 'button', class: 'quiet-button', disabled: busy.value, onClick: () => savePhoto(true) }, '确认恢复默认'), h('button', { type: 'button', class: 'quiet-button', disabled: busy.value, onClick: () => confirmRemove.value = false }, '保留头像')]) : null,
          h('strong', form.nickname || props.user.username), h('span', { class: 'profile-handle' }, `@${props.user.username}`),
          h('p', form.bio || '留一句介绍，让学伴更了解你。'),
          form.interests ? h('span', { class: 'interest-tag' }, [icon('book', 14), form.interests]) : null,
          form.major || form.grade ? h('p', { class: 'profile-study-summary' }, [form.major, form.grade].filter(Boolean).join(' · ')) : null,
          form.study_goal ? h('p', { class: 'profile-study-summary' }, `想一起：${form.study_goal}`) : null,
          form.learning_style ? h('span', { class: 'profile-style-tag' }, learningStyles[form.learning_style]) : null,
          overview.value?.pending_notes !== null && overview.value?.pending_notes !== undefined ? h('button', { class: 'profile-review-link', onClick: () => emit('navigate', 'notes') }, [h('strong', String(overview.value.pending_notes)), ' 篇笔记，等待再看一眼', icon('arrow', 14)]) : null,
          h('div', { class: 'profile-shortcuts' }, [h('button', { class: 'quiet-button', onClick: () => emit('navigate', 'courses') }, [icon('book', 14), '我的课程']), h('button', { class: 'quiet-button', onClick: () => emit('navigate', 'password') }, [icon('lock', 14), '账号安全'])]),
        ]),
        h('form', { class: 'profile-edit-form', onSubmit: submit }, [
          h('h3', '编辑个人资料'),
          h('div', { class: 'form-pair' }, [input('昵称', 'nickname', { maxlength: 32, placeholder: '希望大家怎么称呼你', autocomplete: 'nickname' }), input('联系邮箱', 'email', { type: 'email', maxlength: 254, placeholder: '选填，仅自己和管理员可见', autocomplete: 'email' })]),
          input('学习兴趣', 'interests', { maxlength: 80, placeholder: '例如：设计、编程、英语', autocomplete: 'off' }),
          h('label', { class: 'field' }, [h('span', '个人简介'), h('input', { name: 'bio', value: form.bio, maxlength: 160, placeholder: '一句话介绍自己', disabled: busy.value, onInput: event => { form.bio = event.target.value; message.value = ''; } })]),
          h('div', { class: 'profile-study-fields' }, [
            h('h3', '学习偏好'),
            h('div', { class: 'form-pair' }, [input('专业 / 方向', 'major', { maxlength: 60, placeholder: '例如：数字媒体、计算机' }), input('年级', 'grade', { maxlength: 20, placeholder: '例如：大二、研一' })]),
            input('学习目标', 'study_goal', { maxlength: 100, placeholder: '例如：一起完成课程项目、准备英语四级' }),
            h('label', { class: 'field' }, [h('span', '偏好方式'), h('select', { name: 'learning_style', value: form.learning_style, disabled: busy.value, onChange: event => { form.learning_style = event.target.value; message.value = ''; } }, Object.entries(learningStyles).map(([value, label]) => h('option', { value }, label)))]),
          ]),
          h('fieldset', { class: 'avatar-colors', disabled: busy.value }, [h('legend', '头像配色'), ...[['sage', '鼠尾草'], ['sand', '暖杏'], ['sky', '雾蓝'], ['lilac', '淡紫'], ['rose', '浅玫瑰']].map(([color, label]) => h('label', { class: ['avatar-color-option', `avatar-${color}`, { selected: form.avatar_color === color }], title: label }, [h('input', { type: 'radio', name: 'avatar_color', value: color, checked: form.avatar_color === color, 'aria-label': label, onChange: () => { form.avatar_color = color; message.value = ''; } }), form.avatar_color === color ? h('span', { 'aria-hidden': 'true' }, '✓') : null]))]),
          h('p', { class: 'data-note' }, '学习资料均可选填，会展示在学伴卡片并用于查找。邮箱不公开，登录用户名保持不变。'),
          h('div', { class: 'profile-actions' }, [h('button', { class: 'primary-button', disabled: busy.value || !changed.value }, busy.value ? '正在保存…' : '保存资料'), changed.value ? h('button', { type: 'button', class: 'secondary-button', disabled: busy.value, onClick: () => { Object.assign(form, JSON.parse(saved.value)); error.value = message.value = ''; } }, '撤销修改') : null]),
          h('dl', { class: 'profile-account-info' }, [h('div', [h('dt', '账号身份'), h('dd', { 'data-profile-role': true }, { STUDENT: '学生', TEACHER: '教师', ADMIN: '管理员' }[props.user.role])]), h('div', [h('dt', '注册时间'), h('dd', new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(props.user.created_at)))])]),
        ]),
      ]),
    ]);
  },
};
