// Render the actual Vue components without starting a browser or downloading dependencies.
const assert = require('node:assert/strict');
const { createSSRApp, h } = require('../frontend/node_modules/vue');
const { renderToString } = require('../frontend/node_modules/@vue/server-renderer');

(async () => {
  const { Workspace, AuthPanel } = await import('../frontend/src/accounts.js');
  const { ClassroomPanel } = await import('../frontend/src/classroom.js');
  const { AnalyticsPanel } = await import('../frontend/src/analytics.js');
  const { CameraPanel } = await import('../frontend/src/camera.js');
  const { AdminUserForm } = await import('../frontend/src/admin-users.js');
  const { TrendChart, EmotionDistribution } = await import('../frontend/src/charts.js');
  const render = (component, props) => renderToString(createSSRApp({ render: () => h(component, props) }));
  const login = await render(AuthPanel, {});
  assert(login.includes('欢迎回到课堂') && login.includes('type="password"'));
  assert(/<input[^>]*name="username"[^>]*minlength="3"[^>]*maxlength="254"/.test(login), 'username length limits must match the backend');
  assert(login.includes('pattern="[A-Za-z0-9_][A-Za-z0-9_.@+\\-]*"'));
  const adminForm = await render(AdminUserForm, {});
  assert(adminForm.includes('创建教师或学生账号') && adminForm.includes('value="TEACHER"') && adminForm.includes('maxlength="254"'));
  const camera = await render(CameraPanel, { sessionId: 1, ongoing: true });
  assert(camera.includes('开启识别') && camera.includes('停止识别') && camera.includes('image/jpeg'));
  assert(camera.startsWith('<details') && !/<details[^>]*\sopen(?:=|\s|>)/.test(camera), 'recognition is collapsed until requested');
  for (const length of [0, 1, 12, 49]) {
    const points = Array.from({ length }, (_, index) => ({ timestamp: new Date(Date.UTC(2026, 10, 3, index)).toISOString(), total: length === 12 ? 0 : index }));
    const chart = await render(TrendChart, { points, bucket: 'hour', realtime: false });
    assert(!chart.includes('NaN') && !chart.includes('Infinity'), 'empty, zero and single-point charts must have finite coordinates');
    assert(chart.includes('role="img"') && chart.includes('chart-y-axis'));
    if (length > 0) assert(chart.includes(`${points.at(-1).timestamp} · ${points.at(-1).total} 条`));
    if (length > 48) assert(!chart.includes(`${points[0].timestamp} ·`), 'chart shows only the latest 48 buckets');
  }
  const distribution = await render(EmotionDistribution, { items: ['HAPPY', 'NEUTRAL', 'SAD', 'ANGRY', 'SURPRISED', 'FEAR', 'DISGUST'].map(emotion => ({ emotion, count: 0 })) });
  assert(!distribution.includes('NaN') && distribution.includes('开心 0 条') && distribution.includes('反感 0 条'));
  const sharedScale = await render(EmotionDistribution, { items: [{ emotion: 'HAPPY', count: 2 }], scaleMaximum: 8 });
  assert(sharedScale.includes('width:25%'), 'recap comparisons share one count scale across both periods');
  const longReviewPoints = Array.from({ length: 91 }, (_, index) => ({ timestamp: new Date(Date.UTC(2026, 7, 1 + index)).toISOString(), total: 1 }));
  const longReview = await render(TrendChart, { points: longReviewPoints, maxPoints: 92, bucket: 'day', realtime: false });
  assert(longReview.includes(`${longReviewPoints[0].timestamp} · 1 条`) && longReview.includes(`${longReviewPoints[90].timestamp} · 1 条`), '90-day personal review includes the whole selected period');
  const interactive = await render(TrendChart, { points: longReviewPoints, maxPoints: 92, bucket: 'day', interactive: true, selectedDate: '2026-08-01' });
  assert(interactive.includes('role="button"') && interactive.includes('data-day="2026-08-01"') && interactive.includes('aria-pressed="true"') && interactive.includes('2184px'), 'daily chart exposes selectable dates and scroll space for long periods');
  for (const role of ['STUDENT', 'TEACHER', 'ADMIN']) {
    const user = { username: 'render_check', role, created_at: '2026-11-02T00:00:00Z' };
    const workspace = await render(Workspace, { user });
    assert.equal(workspace.includes('用户列表'), role === 'ADMIN');
    assert.equal(workspace.includes('情绪历史'), role === 'STUDENT');
    assert.equal(workspace.includes('好友学伴'), role === 'STUDENT');
    assert.equal(workspace.includes('笔记与回顾'), role === 'STUDENT');
    assert(workspace.includes(role === 'ADMIN' ? '全校课程' : '我的课程'));
    assert.equal(workspace.includes('开课总览'), role === 'ADMIN');
    assert.equal(workspace.includes('统计与导出'), role !== 'STUDENT');
    const classroom = await render(ClassroomPanel, { user, historyOnly: false });
    assert.equal(classroom.includes('name="course_name"'), role === 'ADMIN');
    assert(classroom.includes('选择课堂'));
    assert(!classroom.includes('class_join_code') && !classroom.includes('join-code-panel'), 'daily feedback has no joining controls');
    assert(!classroom.includes('[object Object]'));
    if (role !== 'STUDENT') {
      const dashboard = await render(AnalyticsPanel, { user, realtime: true });
      assert(dashboard.includes('自动更新（约每 5 秒）'));
      const analytics = await render(AnalyticsPanel, { user, realtime: false });
      assert(analytics.includes('导出 CSV') && analytics.includes('datetime-local'));
    }
  }
  console.log('Vue render checks passed: login, three role workspaces, classroom panels, collapsed recognition and chart boundaries.');
})().catch(error => { console.error(error); process.exitCode = 1; });
