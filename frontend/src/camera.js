import { h, ref, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { api } from './api.js';
import { createCameraController } from './camera-controller.js';
import { icon } from './ui.js';

const emotionNames = { NEUTRAL: '平静', HAPPY: '开心', SURPRISED: '惊讶', SAD: '低落', ANGRY: '生气', DISGUST: '反感', FEAR: '担忧', CONTEMPT: '轻蔑（不纳入课堂统计）' };
const scoreText = score => `${(score * 100).toFixed(1)}%`;
const outcomeNames = { SAVED: '已保存到课堂统计', LOW_CONFIDENCE: '低于保存阈值，未计入统计', UNSUPPORTED_CLASS: '不属于课堂统计类别，未计入统计' };

export const CameraPanel = {
  props: ['sessionId', 'ongoing'], emits: ['expired', 'saved'],
  setup(props, { emit }) {
    const video = ref(null), state = ref('stopped'), error = ref(''), result = ref(null), ready = ref(null), uploading = ref(false);
    const interval = ref(3);
    let disposed = false, uploadAbort = null;
    const statusAbort = new AbortController();
    function fail(failure) {
      if (failure.status === 401) emit('expired');
      const cameraErrors = {
        NotAllowedError: '摄像头权限未获允许。请在 Windows「隐私和安全性 → 摄像头」和浏览器中允许访问，或选择 JPEG 图片试用。',
        NotFoundError: '当前浏览器没有找到可用的摄像头。请确认摄像头已连接并启用；若在内置浏览器中出现此提示，可用 Edge 打开本机同一地址重试，或选择 JPEG 图片试用。',
        DevicesNotFoundError: '当前浏览器没有找到摄像头。请检查设备连接，或选择 JPEG 图片试用。',
        NotReadableError: '摄像头暂时无法读取。请关闭可能占用摄像头的会议或相机应用，再重试；也可以选择 JPEG 图片。',
        OverconstrainedError: '摄像头无法提供所需画面，请换用其他摄像头或选择 JPEG 图片试用。',
      };
      error.value = cameraErrors[failure.name] || failure.message || '摄像头暂不可用，请检查设备。';
    }
    function received(data) { result.value = data; error.value = ''; if (data.saved) emit('saved'); }
    async function send(blob, id, signal) {
      return (await api(`/api/sessions/${props.sessionId}/ai-frame`, { method: 'POST', body: blob, headers: { 'X-Frame-ID': id }, signal, timeoutMs: 20000 })).data;
    }
    const camera = createCameraController({
      getMedia: () => {
        error.value = '';
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('浏览器不支持摄像头，请使用本机地址或 HTTPS，或选择图片试用。');
        return navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
      },
      attach: async stream => { await nextTick(); video.value.srcObject = stream; await video.value.play(); },
      capture: () => new Promise((resolve, reject) => {
        const preview = video.value;
        if (!preview?.videoWidth || !preview?.videoHeight) { reject(new Error('未获得摄像头画面，请重新开启。')); return; }
        const scale = Math.min(1, 960 / preview.videoWidth, 720 / preview.videoHeight);
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(preview.videoWidth * scale); canvas.height = Math.round(preview.videoHeight * scale);
        canvas.getContext('2d').drawImage(preview, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('无法读取摄像头画面')), 'image/jpeg', 0.8);
      }),
      send, getInterval: () => interval.value * 1000, onState: value => state.value = value, onResult: received, onError: fail,
    });
    function stop() { camera.stop(); if (video.value) video.value.srcObject = null; }
    function hidden() { if (document.hidden) { stop(); uploadAbort?.abort(); } }
    async function upload(event) {
      const file = event.target.files?.[0]; event.target.value = '';
      if (!file || uploading.value || state.value !== 'stopped') return;
      if (file.type !== 'image/jpeg' || file.size > 1000000) { error.value = '请选择不超过 1 MB 的 JPEG 图片。'; return; }
      uploading.value = true; error.value = ''; uploadAbort = new AbortController();
      try { const data = await send(file, crypto.randomUUID(), uploadAbort.signal); if (!disposed) received(data); }
      catch (failure) { if (!disposed && !uploadAbort.signal.aborted) fail(failure); }
      finally { uploading.value = false; }
    }
    onMounted(async () => {
      document.addEventListener('visibilitychange', hidden);
      try { const data = (await api('/api/ai/status', { signal: statusAbort.signal })).data; if (!disposed) ready.value = data; }
      catch (failure) { if (!disposed) fail(failure); }
    });
    onBeforeUnmount(() => { disposed = true; stop(); statusAbort.abort(); uploadAbort?.abort(); document.removeEventListener('visibilitychange', hidden); });
    return () => h('details', { class: 'camera-panel', onToggle: event => { if (!event.target.open) { stop(); uploadAbort?.abort(); } } }, [
      h('summary', [h('span', { class: 'camera-summary-title' }, [icon('camera', 19), '课堂表情识别']), h('span', { class: 'camera-summary-note' }, '摄像头 / 图片'), icon('chevron', 15)]),
      h('div', { class: 'camera-body' }, [
        h('p', { class: 'muted' }, '由你主动开启，仅保存匿名结果，不保存图片或视频。'),
        h('div', { class: 'camera-settings' }, [
          h('label', { class: 'field' }, [h('span', '采样间隔'), h('select', { value: interval.value, disabled: state.value !== 'stopped' || uploading.value, onChange: event => interval.value = Number(event.target.value) }, [3, 5, 10, 30].map(seconds => h('option', { value: seconds }, `${seconds} 秒`)))]),
          h('p', { class: 'data-note', role: 'status' }, ready.value ? ready.value.ready ? `服务就绪 · 置信度 ≥ ${Math.round(ready.value.min_confidence * 100)}%` : '识别服务未就绪，请启动 AI 服务后刷新。' : '正在连接识别服务…'),
        ]),
        h('video', { ref: video, muted: true, playsinline: true, 'aria-label': '本机摄像头预览', class: 'camera-preview', style: { display: state.value === 'stopped' ? 'none' : 'block' } }),
        h('div', { class: 'camera-actions' }, [
          h('button', { type: 'button', class: 'primary-button', disabled: !props.ongoing || !ready.value?.ready || state.value !== 'stopped' || uploading.value, onClick: () => camera.start() }, state.value === 'starting' ? '等待摄像头权限…' : state.value === 'running' ? '正在识别' : '开启识别'),
          h('button', { type: 'button', class: 'secondary-button', disabled: state.value === 'stopped', onClick: stop }, '停止识别'),
          h('label', { class: ['upload-button', { disabled: !props.ongoing || !ready.value?.ready || state.value !== 'stopped' || uploading.value }] }, [icon('upload', 16), h('span', '上传 JPEG'), h('input', { type: 'file', accept: 'image/jpeg', 'aria-label': '上传 JPEG 图片，不超过 1 MB', disabled: !props.ongoing || !ready.value?.ready || state.value !== 'stopped' || uploading.value, onChange: upload })]),
        ]),
        !props.ongoing ? h('p', { class: 'data-note' }, '课堂进行中可使用表情识别。') : null,
        uploading.value ? h('p', { class: 'data-note', role: 'status' }, '正在识别图片…') : null,
        error.value ? h('div', { class: 'form-notice', role: 'alert' }, error.value) : null,
        result.value ? h('p', { class: 'camera-result', role: 'status' }, `检测 ${result.value.detected} · 分析 ${result.value.processed} · 保存 ${result.value.saved} · 过滤 ${result.value.filtered}`) : null,
        result.value?.processed === 0 ? h('p', { class: 'data-note', role: 'status' }, result.value.detected ? '本次检测到人脸，但没有完成表情分析。' : '本次未检测到人脸，请正对镜头并保持光线充足。') : null,
        result.value?.predictions?.length ? h('section', { class: 'chart-panel', 'aria-label': '本次模型判断' }, [
          h('h3', '本次模型判断'),
          ...result.value.predictions.map((face, index) => h('div', { key: index }, [
            h('p', [h('strong', `人脸 ${index + 1}：${emotionNames[face.emotion] || face.emotion} · 模型分数 ${scoreText(face.confidence)}`)]),
            h('p', { class: 'data-note' }, outcomeNames[face.reason] || '请查看课堂统计确认保存结果'),
            face.candidates?.length ? h('p', { class: 'data-note' }, `前三候选：${face.candidates.map(candidate => `${emotionNames[candidate.emotion] || candidate.emotion} ${scoreText(candidate.confidence)}`).join(' / ')}`) : null,
          ])),
          h('p', { class: 'data-note' }, '模型分数不是识别准确率。显示的是本次画面的分类结果，不代表同一人连续追踪。'),
        ]) : null,
        h('details', { class: 'camera-capabilities' }, [h('summary', '可识别类别与结果说明'), h('p', { class: 'data-note' }, '模型输出开心、平静、惊讶、低落、生气、反感、担忧和轻蔑；轻蔑不计入课堂统计。当前模型没有“疑惑”类别。低分结果会显示在本次判断中，但不会计入统计；高分也可能判断错误。')]),
        h('p', { class: 'data-note camera-privacy' }, '离开或收起后停止识别。模型估计仅供参考，不代表真实心理状态。'),
      ]),
    ]);
  },
};
