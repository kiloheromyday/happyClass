const assert = require('node:assert/strict');
const { createSSRApp, h } = require('../../frontend/node_modules/vue');
const { renderToString } = require('../../frontend/node_modules/vue/server-renderer');

(async () => {
  const { Workspace } = await import('../../frontend/src/accounts.js');
  for (const role of ['TEACHER', 'ADMIN', 'STUDENT']) {
    const html = await renderToString(createSSRApp({
      render: () => h(Workspace, { user: { id: 1, username: 'role_check', role } }),
    }));
    if (role === 'STUDENT') {
      assert(!html.includes('情绪回放'));
      assert(!html.includes('情绪洞察'));
    } else {
      assert(html.includes('情绪回放'));
      assert(html.includes('情绪洞察'));
    }
    assert(!html.includes('workspace-welcome'));
    assert(!html.includes('assistant-toggle'));
    assert(!html.includes('/art/'));
  }
  console.log('Emotion page roles passed: teacher/admin entries, no student entry and no visual redesign components.');
})().catch(error => { console.error(error); process.exitCode = 1; });
