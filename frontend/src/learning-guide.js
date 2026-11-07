import { h, ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api } from './api.js';
import { icon } from './ui.js';

export const LearningGuidePanel = {
  props: ['sessionId', 'courseId', 'user'], emits: ['expired', 'navigate', 'dirty-change'],
  setup(props, { emit }) {
    const student = props.user.role === 'STUDENT';
    const data = ref(null), draft = reactive({ title: '', content: '', practice: '' }), baseline = ref('');
    const busy = ref(false), error = ref(''), message = ref(''), confirm = ref(false);
    const dirty = computed(() => !student && data.value !== null && JSON.stringify(draft) !== baseline.value);
    let alive = true, abort, timer;
    const fail = failure => { if (failure.status === 401) emit('expired'); else { error.value = failure.message; if (student && [403, 404].includes(failure.status)) data.value = null; } };
    watch(dirty, value => emit('dirty-change', value), { flush: 'sync' });
    function apply(value) { data.value = value; if (!student) { Object.assign(draft, value.draft); baseline.value = JSON.stringify(draft); } }
    async function load(quiet = false) {
      if (busy.value || dirty.value) return;
      const controller = new AbortController(); abort = controller;
      busy.value = true; if (!quiet) { error.value = ''; message.value = ''; }
      try { const result = await api(`/api/sessions/${props.sessionId}/learning-guide`, { signal: controller.signal }); if (alive && !controller.signal.aborted) { apply(result.data); error.value = ''; } }
      catch (failure) { if (alive && !controller.signal.aborted) fail(failure); }
      finally { if (alive && abort === controller) busy.value = false; }
    }
    async function save(action) {
      if (busy.value || !data.value) return;
      if (action === 'UNPUBLISH' && !confirm.value) { confirm.value = true; return; }
      busy.value = true; error.value = ''; message.value = '';
      const controller = new AbortController(); abort = controller;
      try {
        const result = await api(`/api/sessions/${props.sessionId}/learning-guide`, { method: 'PUT', signal: controller.signal, body: { ...draft, version: data.value.version, action } });
        if (alive) { apply(result.data); confirm.value = false; message.value = result.message; }
      } catch (failure) { if (alive && !controller.signal.aborted) fail(failure); }
      finally { if (alive) busy.value = false; }
    }
    function discard() { Object.assign(draft, JSON.parse(baseline.value)); confirm.value = false; load(); }
    onMounted(() => { load(); if (student) timer = setInterval(() => { if (!document.hidden) load(true); }, 30000); });
    onBeforeUnmount(() => { alive = false; abort?.abort(); clearInterval(timer); emit('dirty-change', false); });
    const published = () => data.value?.published ? h('article', { class: 'published-guide' }, [h('p', { class: 'guide-published-label' }, '老师发布的学习指引'), h('h4', data.value.published.title), h('p', { class: 'guide-copy' }, data.value.published.content), data.value.published.practice ? h('div', { class: 'guide-practice' }, [h('h4', '课后练习与思考'), h('p', { class: 'guide-copy' }, data.value.published.practice)]) : null]) : h('p', { class: 'empty-note' }, '老师还没有发布本节学习指引。');
    const field = (label, key, limit, rows) => h('label', { class: 'field' }, [h('span', label), h(key === 'title' ? 'input' : 'textarea', { name: `guide_${key}`, value: draft[key], maxlength: limit, rows, disabled: busy.value, onInput: event => { draft[key] = event.target.value; confirm.value = false; } })]);
    return () => h('section', { class: 'learning-guide-panel', 'aria-busy': busy.value }, [
      h('div', { class: 'section-title' }, [h('h3', '学习指引'), h('button', { class: 'quiet-button', disabled: busy.value, onClick: () => dirty.value ? discard() : load() }, [icon('refresh', 15), dirty.value ? '放弃修改并刷新指引' : '刷新学习指引'])]),
      error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null,
      message.value ? h('p', { class: 'form-notice success', role: 'status' }, message.value) : null,
      !data.value && busy.value ? h('p', { class: 'data-note', role: 'status' }, '正在读取学习指引…') : null,
      data.value ? student ? h('div', [published(), data.value.published ? h('div', { class: 'guide-actions' }, [h('button', { class: 'secondary-button', onClick: () => emit('navigate', { tab: 'notes', view: 'notes', sessionId: props.sessionId, courseId: props.courseId }) }, '写课堂笔记'), h('button', { class: 'quiet-button', onClick: () => emit('navigate', { tab: 'notes', view: 'review', sessionId: props.sessionId, courseId: props.courseId }) }, '回顾本节收获')]) : null]) : h('div', [
        h('p', { class: 'data-note' }, data.value.published ? '已发布到学生课堂。保存草稿不会替换已发布内容。' : '草稿仅教师可见，发布后本节名单内学生可读。'),
        h('form', { class: 'guide-editor', onSubmit: event => { event.preventDefault(); save('SAVE'); } }, [field('指引标题', 'title', 80), field('学习要点', 'content', 3000, 7), field('练习与思考（选填）', 'practice', 1500, 4),
          h('div', { class: 'guide-actions' }, [h('span', { class: 'data-note' }, dirty.value ? '有未保存的修改' : '草稿已同步'), h('button', { type: 'submit', class: 'secondary-button', disabled: busy.value || !dirty.value }, '保存指引草稿'), h('button', { type: 'button', class: 'primary-button', disabled: busy.value || !draft.title.trim() || !draft.content.trim(), onClick: () => save('PUBLISH') }, data.value.published ? '更新发布' : '发布到学生课堂')]),
        ]),
        data.value.published ? h('details', { class: 'guide-preview' }, [h('summary', '查看学生当前可见版本'), published()]) : null,
        data.value.published ? h('div', { class: 'guide-withdraw' }, [h('button', { class: 'quiet-button', disabled: busy.value || dirty.value, onClick: () => save('UNPUBLISH') }, confirm.value ? '确认撤下学习指引' : '撤下已发布指引'), confirm.value ? h('button', { class: 'quiet-button', onClick: () => confirm.value = false }, '保留发布') : null]) : null,
      ]) : null,
    ]);
  },
};
