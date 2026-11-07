import { h, ref, reactive, computed, watch, onBeforeUnmount } from 'vue';
import { api } from './api.js';

const local = value => new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
export const SchedulePanel = {
  props: ['courseId'], emits: ['expired', 'created', 'dirty-change'],
  setup(props, { emit }) {
    const opened = ref(false), busy = ref(false), error = ref('');
    const draft = reactive({ starts_at: '', ends_at: '', classroom: '', class_name: '' }), baseline = ref('');
    const dirty = computed(() => opened.value && JSON.stringify(draft) !== baseline.value);
    let alive = true, abort, retry;
    watch(dirty, value => emit('dirty-change', value), { flush: 'sync' });
    function open() { Object.assign(draft, { starts_at: local(new Date(Date.now() + 3600000)), ends_at: local(new Date(Date.now() + 7200000)), classroom: '', class_name: '' }); baseline.value = JSON.stringify(draft); opened.value = true; error.value = ''; }
    async function submit(event) {
      event.preventDefault(); if (busy.value) return;
      if (Date.parse(draft.ends_at) <= Date.parse(draft.starts_at)) { error.value = '结束时间必须晚于开始时间。'; return; }
      busy.value = true; error.value = ''; abort = new AbortController();
      try {
        const body = { ...draft, course_id: props.courseId, starts_at: new Date(draft.starts_at).toISOString(), ends_at: new Date(draft.ends_at).toISOString() };
        const signature = JSON.stringify(body);
        if (retry?.signature !== signature) retry = { signature, request_id: crypto.randomUUID() };
        const result = await api('/api/teaching/sessions', { method: 'POST', signal: abort.signal, body: { ...body, request_id: retry.request_id } });
        if (alive) { opened.value = false; emit('created', result.data, result.message); }
      } catch (failure) { if (alive && !abort.signal.aborted) { if (failure.status === 401) emit('expired'); else error.value = failure.message; } }
      finally { if (alive) busy.value = false; }
    }
    onBeforeUnmount(() => { alive = false; abort?.abort(); emit('dirty-change', false); });
    const field = (label, key, type = 'text') => h('label', { class: 'field' }, [h('span', label), h('input', { name: `schedule_${key}`, type, required: true, maxlength: 120, value: draft[key], disabled: busy.value, onInput: event => draft[key] = event.target.value })]);
    return () => h('section', { class: 'teacher-schedule' }, [
      opened.value ? h('form', { onSubmit: submit }, [h('h3', '安排新课堂'), h('p', { class: 'data-note' }, '使用本地时间。保存后，课程内有效学生会自动出现在新课堂名单中。'), h('div', { class: 'form-pair' }, [field('开始时间', 'starts_at', 'datetime-local'), field('结束时间', 'ends_at', 'datetime-local')]), h('div', { class: 'form-pair' }, [field('教室', 'classroom'), field('班级', 'class_name')]), error.value ? h('p', { class: 'form-notice', role: 'alert' }, error.value) : null, h('div', { class: 'guide-actions' }, [h('button', { type: 'button', class: 'quiet-button', disabled: busy.value, onClick: () => opened.value = false }, dirty.value ? '放弃安排并收起' : '取消安排'), h('button', { class: 'primary-button', disabled: busy.value }, busy.value ? '正在安排…' : '保存课堂安排')])]) : h('button', { class: 'secondary-button', onClick: open }, '安排新课堂'),
    ]);
  },
};
