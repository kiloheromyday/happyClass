const assert = require('node:assert/strict');
const { createRenderer, h, nextTick } = require('../frontend/node_modules/vue');
const node = (type, text = '') => ({ type, text, props: {}, children: [], parent: null });
const detach = child => { if (child.parent) { child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null; } };
const renderer = createRenderer({ createElement: type => node(type), createText: text => node('#text', text), createComment: text => node('#comment', text), setText: (n, value) => n.text = value, setElementText: (n, value) => { n.text = value; n.children = []; }, patchProp: (n, key, old, value) => n.props[key] = value, insert(n, parent, anchor) { detach(n); const i = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(i < 0 ? parent.children.length : i, 0, n); n.parent = parent; }, remove: detach, parentNode: n => n.parent, nextSibling: n => n.parent?.children[n.parent.children.indexOf(n) + 1] || null });
const walk = n => [n, ...n.children.flatMap(walk)], text = n => (n.type === '#comment' ? '' : n.text) + n.children.map(text).join('');
const find = (root, condition) => { const n = walk(root).find(condition); assert(n, 'Control not found'); return n; };
const button = (root, label) => find(root, n => n.type === 'button' && text(n) === label);
const field = (root, name) => find(root, n => n.props.name === name);
const settle = async () => { for (let i = 0; i < 8; i++) { await new Promise(setImmediate); await nextTick(); } };
const mount = (component, props) => { const root = node('root'), app = renderer.createApp({ render: () => h(component, props) }); app.mount(root); return { root, app }; };

(async () => {
  const { PrivacyPanel } = await import('../frontend/src/privacy.js');
  const originalFetch = global.fetch, requests = [], dirty = [];
  let mounted, policy = { session_id: 1, mode: 'STANDARD', version: 0 }, failSave = false, failed = true;
  global.fetch = async (path, options = {}) => {
    requests.push({path, method: options.method || 'GET'});
    let data;
    if (path === '/api/sessions') data = {items: [{id: 1, course_name: '软件工程', class_name: '一班', starts_at: '2026-11-09T00:00:00Z'}]};
    else if (path === '/api/privacy/sessions/1' && options.method === 'PUT') {
      if (failSave) return new Response(JSON.stringify({message: '隐私设置已更新，请刷新后重试'}), {status: 409});
      policy = {...policy, mode: JSON.parse(options.body).mode, version: policy.version + 1}; data = policy;
    } else if (path === '/api/privacy/sessions/1') data = policy;
    else if (path === '/api/ai/queue/status') data = {enabled: true, ready: true, queued_or_pending: 1, failed: failed ? [{job_id: 'f'.repeat(64), error_code: 'OperationalError'}] : []};
    else if (path.endsWith('/retry')) { failed = false; data = {state: 'QUEUED'}; }
    else throw new Error('Unexpected request: ' + path);
    return new Response(JSON.stringify({data, message: '已保存'}), {status: 200});
  };
  try {
    mounted = mount(PrivacyPanel, {user: {role: 'ADMIN'}, onDirtyChange: value => dirty.push(value)}); await settle();
    assert(text(mounted.root).includes('当前：标准模式'));
    field(mounted.root, 'privacy_mode').props.onChange({target: {value: 'ANONYMOUS'}}); await nextTick();
    assert.equal(dirty.at(-1), true); assert(field(mounted.root, 'privacy_session').props.disabled);
    await find(mounted.root, n => n.type === 'form').props.onSubmit({preventDefault() {}}); await settle();
    assert.equal(policy.mode, 'ANONYMOUS'); assert.equal(dirty.at(-1), false);
    field(mounted.root, 'privacy_mode').props.onChange({target: {value: 'AGGREGATE'}}); await nextTick(); failSave = true;
    await find(mounted.root, n => n.type === 'form').props.onSubmit({preventDefault() {}}); await settle();
    assert(text(mounted.root).includes('隐私设置已更新')); assert.equal(field(mounted.root, 'privacy_mode').props.value, 'AGGREGATE');
    await button(mounted.root, '放弃隐私草稿').props.onClick(); await nextTick(); assert.equal(dirty.at(-1), false);
    await button(mounted.root, '重试失败任务').props.onClick(); await settle();
    assert(requests.some(r => r.method === 'POST' && r.path.endsWith('/retry'))); assert(!text(mounted.root).includes('OperationalError'));
    mounted.app.unmount(); assert.equal(dirty.at(-1), false);
    const start = requests.length;
    mounted = mount(PrivacyPanel, {user: {role: 'STUDENT'}}); await settle();
    assert(text(mounted.root).includes('当前：匿名展示')); assert(text(mounted.root).includes('后台仍保存'));
    assert(!walk(mounted.root).some(n => n.type === 'form'));
    assert(!requests.slice(start).some(r => r.path.includes('/queue/')));
    mounted.app.unmount(); mounted = null;
    console.log('Privacy interactions passed: mode save, version conflict retains draft, dirty guard, discard, failed-job retry and student read-only boundaries.');
  } finally { mounted?.app.unmount(); global.fetch = originalFetch; }
})().catch(error => { console.error(error); process.exitCode = 1; });
