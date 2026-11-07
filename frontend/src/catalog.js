import { h, ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api } from './api.js';
import { DataScope, matchesScope } from './data-scope.js';
import { departmentStyle } from './timetable.js';

const colors = ['#668572', '#6b8eb2', '#9a83ac', '#b58b65', '#b57783', '#78969b', '#a19455', '#7c88ad'];
export const CatalogPanel = {
  emits: ['expired', 'dirty-change', 'navigate'],
  setup(_, { emit }) {
    const view = ref('courses'), departments = ref([]), courses = ref([]), teachers = ref([]), loading = ref(false), saving = ref(false), error = ref(''), message = ref('');
    const q = ref(''), scope = ref('ALL'), archive = ref('ACTIVE'), selected = ref(null), editing = ref(false), baseline = ref(''), confirm = ref(false);
    const form = reactive({}), signature = () => JSON.stringify(form), dirty = computed(() => editing.value && signature() !== baseline.value), locked = computed(() => loading.value || saving.value);
    const visible = computed(() => (view.value === 'courses' ? courses.value : departments.value).filter(item => `${item.name} ${item.teacher_name || ''} ${item.short_name || ''}`.toLowerCase().includes(q.value.trim().toLowerCase()) && (view.value !== 'courses' || matchesScope(item, scope.value) && (archive.value === 'ALL' || Boolean(item.archived) === (archive.value === 'ARCHIVED')))));
    let alive = true, readAbort, writeAbort, createRetry;
    watch(() => dirty.value || saving.value, value => emit('dirty-change', value), { flush: 'sync' });
    function fail(e) { if (e.status === 401) emit('expired'); else error.value = e.message; }
    async function load() {
      if (locked.value || dirty.value) return;
      readAbort?.abort(); const controller = new AbortController(); readAbort = controller; loading.value = true; error.value = '';
      try {
        const r = await Promise.all([api('/api/departments', { signal: controller.signal }), api('/api/courses', { signal: controller.signal }), api('/api/admin/people', { signal: controller.signal })]);
        if (!alive || controller.signal.aborted) return;
        departments.value = r[0].data.items; courses.value = r[1].data.items; teachers.value = r[2].data.items.filter(item => item.role === 'TEACHER');
      } catch (e) { if (alive && !controller.signal.aborted) fail(e); }
      finally { if (alive && readAbort === controller) loading.value = false; }
    }
    function open(item = null) {
      if (locked.value || dirty.value) return;
      Object.keys(form).forEach(key => delete form[key]); selected.value = item; confirm.value = false; createRetry = null;
      Object.assign(form, view.value === 'courses' ? { name: item?.name || '', teacher_id: String(item?.teacher_id || ''), department_id: item?.department_id || '', archived: Boolean(item?.archived) } : { id: item?.id || '', name: item?.name || '', short_name: item?.short_name || '', color: item?.color || colors[0] });
      baseline.value = signature(); editing.value = true; error.value = message.value = '';
    }
    function close() { if (saving.value) return; editing.value = false; confirm.value = false; error.value = ''; }
    async function save(event) {
      event.preventDefault(); if (locked.value) return;
      saving.value = true; error.value = message.value = ''; writeAbort = new AbortController();
      const isCourse = view.value === 'courses', base = isCourse ? '/api/admin/courses' : '/api/admin/departments';
      const body = isCourse ? { name: form.name, teacher_id: Number(form.teacher_id), department_id: form.department_id || null, ...(selected.value ? { archived: form.archived, version: selected.value.version } : {}) } : { ...form, version: selected.value?.version || 0 };
      if (isCourse && !selected.value) {
        body.name = body.name.trim();
        const key = JSON.stringify(body);
        if (createRetry?.key !== key) createRetry = { key, request_id: crypto.randomUUID() };
        body.request_id = createRetry.request_id;
      }
      try {
        const r = await api(base + (selected.value ? '/' + selected.value.id : ''), { method: selected.value ? 'PUT' : 'POST', body, signal: writeAbort.signal });
        if (alive) { createRetry = null; editing.value = false; confirm.value = false; message.value = r.message; }
      } catch (e) { if (alive && !writeAbort.signal.aborted) fail(e); }
      finally { if (alive) saving.value = false; }
      if (alive && !error.value) await load();
    }
    async function remove() {
      if (locked.value || dirty.value || !selected.value || view.value !== 'departments') return;
      if (!confirm.value) { confirm.value = true; return; }
      saving.value = true; error.value = ''; writeAbort = new AbortController();
      try { await api(`/api/admin/departments/${selected.value.id}?version=${selected.value.version}`, { method: 'DELETE', signal: writeAbort.signal }); if (alive) { editing.value = false; message.value = '院系已移除。'; } }
      catch (e) { if (alive && !writeAbort.signal.aborted) fail(e); }
      finally { if (alive) saving.value = false; }
      if (alive && !error.value) await load();
    }
    const field = (label, key, options = {}) => h('label', { class: 'field' }, [h('span', label), h('input', { name: `catalog_${key}`, required: true, maxlength: 80, disabled: saving.value, value: form[key], onInput: e => form[key] = e.target.value, ...options })]);
    function editor() {
      const isCourse = view.value === 'courses';
      return h('section', { class: 'catalog-editor' }, [h('h3', `${selected.value ? '编辑' : '新增'}${isCourse ? '课程' : '院系'}`), h('form', { onSubmit: save }, [
        field(isCourse ? '课程名称' : '院系名称', 'name', { maxlength: isCourse ? 120 : 80 }),
        isCourse ? h('div', { class: 'form-pair' }, [h('label', { class: 'field' }, [h('span', '开课院系'), h('select', { name: 'catalog_department', value: form.department_id, disabled: saving.value, onChange: e => form.department_id = e.target.value }, [h('option', { value: '' }, '综合课程 / 未分配'), ...departments.value.map(item => h('option', { value: item.id }, item.name))])]), h('label', { class: 'field' }, [h('span', '任课教师'), h('select', { name: 'catalog_teacher', required: true, value: form.teacher_id, disabled: saving.value, onChange: e => form.teacher_id = e.target.value }, [h('option', { value: '' }, '请选择教师'), ...teachers.value.map(item => h('option', { value: String(item.id) }, item.username))])])]) : h('div', { class: 'form-pair' }, [field('院系编号', 'id', { maxlength: 32, pattern: '[a-z][a-z0-9_-]{1,31}', placeholder: '如 math、physics', disabled: saving.value || Boolean(selected.value) }), field('显示简称', 'short_name', { maxlength: 12 })]),
        !isCourse ? h('div', { class: 'catalog-color-section' }, [field('院系代表色', 'color', { type: 'color' }), h('div', { class: 'catalog-palette' }, colors.map(color => h('button', { type: 'button', style: { background: color }, 'aria-label': `配色 ${color}`, 'aria-pressed': form.color === color, disabled: saving.value, onClick: () => form.color = color }))), h('span', { class: 'department-badge', style: { '--dept-color': form.color, '--dept-bg': form.color + '18' } }, form.short_name || '配色预览')]) : selected.value ? h('label', { class: 'message-unread-toggle' }, [h('input', { type: 'checkbox', checked: form.archived, disabled: saving.value, onChange: e => form.archived = e.target.checked }), '归档课程（保留记录，停止新增课堂与加入）']) : null,
        h('div', { class: 'guide-actions' }, [h('button', { type: 'button', class: 'quiet-button', disabled: saving.value, onClick: close }, dirty.value ? '放弃维护草稿' : '取消编辑'), !isCourse && selected.value ? h('button', { type: 'button', class: 'quiet-button', disabled: saving.value || dirty.value, onClick: remove }, confirm.value ? '确认移除空院系' : '移除空院系') : null, h('button', { class: 'primary-button', disabled: saving.value }, saving.value ? '正在保存…' : '保存信息')]),
      ])]);
    }
    onMounted(load); onBeforeUnmount(() => { alive = false; readAbort?.abort(); writeAbort?.abort(); emit('dirty-change', false); });
    return () => h('section', { class: 'catalog-panel', 'aria-busy': locked.value }, [
      h('div', { class: 'section-title' }, [h('div', [h('p', { class: 'campus-eyebrow' }, 'CATALOG / 教学资料'), h('h2', '院系与课程维护')]), h('div', { class: 'guide-actions' }, [h('button', { class: 'quiet-button', disabled: locked.value || dirty.value, onClick: load }, '刷新资料'), h('button', { class: 'secondary-button', disabled: locked.value || dirty.value, onClick: () => open() }, view.value === 'courses' ? '新增课程' : '新增院系')])]),
      h('div', { class: 'campus-view-switch' }, [['courses', '课程维护'], ['departments', '院系与配色']].map(([value, label]) => h('button', { class: { active: view.value === value }, disabled: locked.value || dirty.value, 'aria-pressed': view.value === value, onClick: () => { view.value = value; editing.value = false; q.value = ''; error.value = message.value = ''; } }, label))),
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null, message.value ? h('p', { class: 'form-notice success', role: 'status' }, message.value) : null,
      editing.value ? editor() : null,
      h('div', { class: 'extension-filters' }, [h('input', { name: 'catalog_query', 'aria-label': '查找维护资料', placeholder: '查找名称、教师或简称', value: q.value, onInput: e => q.value = e.target.value }), view.value === 'courses' ? h(DataScope, { modelValue: scope.value, 'onUpdate:modelValue': value => scope.value = value }) : null, view.value === 'courses' ? h('select', { 'aria-label': '课程归档状态', value: archive.value, onChange: e => archive.value = e.target.value }, [['ACTIVE', '当前课程'], ['ARCHIVED', '已归档课程'], ['ALL', '全部课程']].map(([value, text]) => h('option', { value }, text))) : null]),
      loading.value ? h('p', { role: 'status' }, '正在读取资料…') : h('div', { class: 'catalog-list' }, visible.value.map(item => h('article', { style: view.value === 'courses' ? departmentStyle(item) : { '--dept-color': item.color, '--dept-bg': item.background }, key: item.id }, [h('div', [h('span', { class: 'department-badge' }, view.value === 'courses' ? item.department_name || '综合课程' : item.short_name), h('h3', item.name), h('p', { class: 'data-note' }, view.value === 'courses' ? `${item.teacher_name}${item.is_demo ? ' · 演示' : ''}${item.archived ? ' · 已归档' : ''}` : `${item.id} · ${item.color}`)]), h('div', { class: 'guide-actions' }, [view.value === 'courses' ? h('button', { class: 'quiet-button', disabled: dirty.value || locked.value, onClick: () => emit('navigate', { tab: 'courses', courseId: item.id }) }, '课程详情') : null, h('button', { class: 'secondary-button', disabled: dirty.value || locked.value, onClick: () => open(item) }, '编辑信息')])]))),
      !loading.value && !visible.value.length ? h('p', { class: 'empty-note' }, '没有符合条件的资料。') : null,
    ]);
  },
};
