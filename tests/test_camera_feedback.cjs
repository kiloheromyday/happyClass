const assert = require('node:assert/strict');
const { createRenderer, h, nextTick } = require('../frontend/node_modules/vue');
const node = (type, text = '') => ({ type, text, props: {}, children: [], parent: null });
const detach = child => { if (child.parent) { child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null; } };
const renderer = createRenderer({ createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text), setText: (n, value) => n.text = value, setElementText: (n, value) => { n.text = value; n.children = []; }, patchProp: (n, key, old, value) => n.props[key] = value, insert(n, parent, anchor) { detach(n); const i = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(i < 0 ? parent.children.length : i, 0, n); n.parent = parent; }, remove: detach, parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] || null });
const walk = n => [n, ...n.children.flatMap(walk)];
const text = n => (n.type === '#comment' ? '' : n.text) + n.children.map(text).join('');
const settle = async () => { for (let i = 0; i < 5; i++) { await new Promise(setImmediate); await nextTick(); } };

(async () => {
  const { CameraPanel } = await import('../frontend/src/camera.js');
  const originalFetch = global.fetch, originalDocument = global.document;
  let app, result, saves = 0;
  global.document = { addEventListener() {}, removeEventListener() {} };
  global.fetch = async (path, options) => {
    if (path !== '/api/ai/status') {
      assert.equal(path, '/api/sessions/169/ai-frame');
      assert(options.body instanceof Blob, 'image is sent through the existing explicit upload path');
    }
    return new Response(JSON.stringify({ data: path === '/api/ai/status' ? { ready: true, min_confidence: .7 } : result }), { status: 200 });
  };
  try {
    const root = node('root');
    app = renderer.createApp({ render: () => h(CameraPanel, {sessionId: 169, ongoing: true, onSaved: () => saves++}) });
    app.mount(root); await settle();
    const input = () => walk(root).find(n => n.type === 'input' && n.props.type === 'file');
    const upload = async () => { await input().props.onChange({ target: { files: [new Blob(['test JPEG placeholder'], { type: 'image/jpeg' })], value: 'file.jpg' } }); await settle(); };
    result = {detected: 1, processed: 1, saved: 0, filtered: 1, predictions: [{emotion: 'ANGRY', confidence: .56, reason: 'LOW_CONFIDENCE', candidates: [{emotion: 'ANGRY', confidence: .56}, {emotion: 'NEUTRAL', confidence: .3}, {emotion: 'SAD', confidence: .1}]}]};
    await upload();
    assert(text(root).includes('生气 · 模型分数 56.0%'));
    assert(text(root).includes('低于保存阈值，未计入统计'));
    assert(text(root).includes('平静 30.0%'));
    assert.equal(saves, 0, 'a low-score candidate must not trigger a saved-statistics update');
    result = {detected: 1, processed: 1, saved: 1, filtered: 0, predictions: [{emotion: 'NEUTRAL', confidence: .99, reason: 'SAVED', candidates: []}]};
    await upload();
    assert(text(root).includes('平静 · 模型分数 99.0%'));
    assert(text(root).includes('已保存到课堂统计'));
    assert(text(root).includes('模型分数不是识别准确率'));
    assert.equal(saves, 1);
    result = {detected: 0, processed: 0, saved: 0, filtered: 0, predictions: []};
    await upload();
    assert(text(root).includes('本次未检测到人脸'));
    assert(!text(root).includes('本次模型判断'));
    assert(text(root).includes('当前模型没有“疑惑”类别'));
    console.log('Camera feedback checks passed: low-score candidates remain visible without being counted, saved scores, unsupported confusion category and no-face state.');
  } finally { app?.unmount(); global.fetch = originalFetch; global.document = originalDocument; }
})().catch(error => { console.error(error); process.exitCode = 1; });
