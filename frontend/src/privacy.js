import { h, ref, computed, watch, onMounted, onBeforeUnmount } from 'vue';
import { api, downloadCsv } from './api.js';

const names = { STANDARD: '标准模式', ANONYMOUS: '匿名展示', AGGREGATE: '仅聚合展示' };
const explanations = {
  STANDARD: '任课教师和管理员可查看反馈明细及账号。AI 记录始终不关联学生身份。',
  ANONYMOUS: '教师和管理员的表情历史、看板明细与 CSV 隐藏账号和设备标识。',
  AGGREGATE: '教师和管理员仅查看统计，不提供逐条反馈历史或明细 CSV。学生仍能查看自己的历史。',
};

export const PrivacyPanel = {
  props: ['user'], emits: ['expired', 'dirty-change'],
  setup(props, { emit }) {
    const sessions = ref([]), selected = ref(''), policy = ref(null), draft = ref('STANDARD');
    const loading = ref(false), saving = ref(false), exporting = ref(false), error = ref(''), message = ref('');
    const queue = ref(null), queueBusy = ref(false);
    const staff = props.user.role !== 'STUDENT', admin = props.user.role === 'ADMIN';
    const dirty = computed(() => Boolean(policy.value) && draft.value !== policy.value.mode);
    watch(dirty, value => emit('dirty-change', value), { flush: 'sync' });
    let alive = true, controller;
    const fail = failure => { if (failure.status === 401) emit('expired'); else error.value = failure.message; };
    async function loadPolicy() {
      controller?.abort(); controller = new AbortController();
      const request = controller;
      policy.value = null; loading.value = true; error.value = ''; message.value = '';
      try {
        if (!selected.value) return;
        const result = await api(`/api/privacy/sessions/${selected.value}`, { signal: request.signal });
        if (alive && !request.signal.aborted) { draft.value = result.data.mode; policy.value = result.data; }
      } catch (failure) { if (alive && !request.signal.aborted) fail(failure); }
      finally { if (controller === request) loading.value = false; }
    }
    async function save(event) {
      event.preventDefault();
      if (saving.value || !policy.value || !dirty.value) return;
      saving.value = true; error.value = ''; message.value = '';
      try {
        const result = await api(`/api/privacy/sessions/${selected.value}`, { method: 'PUT', body: { mode: draft.value, version: policy.value.version }, signal: controller.signal });
        if (alive) { policy.value = result.data; message.value = result.message; }
      } catch (failure) { if (alive) fail(failure); }
      finally { saving.value = false; }
    }
    async function exportAggregate() {
      if (!selected.value || exporting.value) return;
      exporting.value = true; error.value = '';
      try { const count = await downloadCsv(`/api/privacy/sessions/${selected.value}/export`, controller.signal); if (alive) message.value = `已导出 ${count} 个情绪与来源分组。`; }
      catch (failure) { if (alive) fail(failure); }
      finally { exporting.value = false; }
    }
    async function queueStatus() {
      if (queueBusy.value) return;
      queueBusy.value = true; error.value = '';
      try { const result = await api('/api/ai/queue/status', { signal: controller?.signal }); if (alive) queue.value = result.data; }
      catch (failure) { if (alive) fail(failure); }
      finally { queueBusy.value = false; }
    }
    async function retry(jobId) {
      if (queueBusy.value) return;
      queueBusy.value = true; error.value = '';
      try { await api(`/api/ai/queue/jobs/${jobId}/retry`, { method: 'POST', signal: controller?.signal }); if (alive) message.value = '任务已重新排队，实际入库结果请刷新查看。'; }
      catch (failure) { if (alive) fail(failure); }
      finally { queueBusy.value = false; }
      if (alive) await queueStatus();
    }
    onMounted(async () => {
      controller = new AbortController(); loading.value = true;
      try {
        const result = await api('/api/sessions', { signal: controller.signal });
        if (!alive) return;
        sessions.value = result.data.items; selected.value = String(sessions.value[0]?.id || '');
        await loadPolicy();
        if (admin && alive) await queueStatus();
      } catch (failure) { if (alive) fail(failure); }
      finally { loading.value = false; }
    });
    onBeforeUnmount(() => { alive = false; controller?.abort(); emit('dirty-change', false); });
    return () => h('div', { class: 'privacy-panel' }, [
      h('h2', '反馈隐私'), h('p', { class: 'muted' }, '按课堂设置反馈的展示范围，兼顾个人回顾与教学统计。'),
      error.value ? h('p', { role: 'alert', class: 'form-notice error' }, error.value) : null,
      message.value ? h('p', { role: 'status', class: 'form-notice success' }, message.value) : null,
      h('label', { class: 'field' }, [h('span', '选择课堂'), h('select', { name: 'privacy_session', value: selected.value, disabled: loading.value || saving.value || exporting.value || dirty.value, onChange: event => { selected.value = event.target.value; loadPolicy(); } }, sessions.value.map(item => h('option', { value: String(item.id) }, `${item.course_name} · ${item.class_name} · ${item.starts_at.slice(0, 10)}`)))]),
      loading.value ? h('p', { role: 'status' }, '正在加载隐私设置…') : !sessions.value.length ? h('p', { class: 'empty-note' }, '还没有可访问的课堂。') : null,
      policy.value ? h('section', { class: 'chart-panel privacy-settings' }, [
        h('h3', `当前：${names[policy.value.mode]}`),
        staff ? h('form', { onSubmit: save }, [
          h('label', { class: 'field' }, [h('span', '课堂反馈模式'), h('select', { name: 'privacy_mode', value: draft.value, disabled: saving.value || exporting.value, onChange: event => draft.value = event.target.value }, Object.entries(names).map(([value, label]) => h('option', { value }, label)))]),
          h('p', explanations[draft.value]), h('p', { class: 'data-note' }, '已有反馈后只能提高保护等级。历史记录不会被删除，隐私设置更新后适用于后续查询。'),
          h('div', { class: 'report-actions' }, [h('button', { class: 'primary-button', disabled: !dirty.value || saving.value || exporting.value }, saving.value ? '正在保存…' : '保存隐私设置'), h('button', { type: 'button', class: 'secondary-button', disabled: !dirty.value || saving.value, onClick: () => draft.value = policy.value.mode }, '放弃隐私草稿')]),
        ]) : h('p', explanations[policy.value.mode]),
        h('p', { class: 'data-note' }, '匿名展示不等于数据库不可关联作者：后台仍保存人工反馈归属，用于本人历史、权限和防重复；模型输出也不能作为心理诊断。'),
        staff ? h('div', [h('button', { class: 'secondary-button', disabled: exporting.value || saving.value || dirty.value, onClick: exportAggregate }, exporting.value ? '正在导出…' : '导出本节聚合 CSV'), h('p', { class: 'data-note' }, '包含本节全部人工与 AI 记录（含演示），仅输出情绪、来源和数量。')]) : null,
      ]) : null,
      admin ? h('section', { class: 'chart-panel privacy-settings' }, [h('h3', 'AI 异步处理'), h('button', { class: 'secondary-button', disabled: queueBusy.value, onClick: queueStatus }, queueBusy.value ? '正在刷新…' : '刷新队列状态'), queue.value ? [
        h('p', !queue.value.enabled ? '异步处理尚未启用，当前仍可使用原有同步识别。' : !queue.value.ready ? '队列暂时不可用，已接收任务将由恢复后的工作进程继续处理。' : `等待或处理中：${queue.value.queued_or_pending} 个任务`),
        queue.value.worker_heartbeat ? h('p', { class: 'data-note' }, `工作进程最近心跳：${queue.value.worker_heartbeat}`) : queue.value.enabled ? h('p', { class: 'data-note' }, '暂未收到有效工作进程心跳。') : null,
        ...(queue.value.failed || []).map(item => h('div', { class: 'queue-failure', key: item.job_id }, [h('code', item.job_id.slice(0, 12)), h('span', item.error_code), h('button', { class: 'quiet-button', disabled: queueBusy.value, onClick: () => retry(item.job_id) }, '重试失败任务')])),
      ] : null]) : null,
    ]);
  },
};
