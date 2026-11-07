export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

export async function request(path, { method = 'GET', body, signal, timeoutMs = 10000, headers: extraHeaders = {} } = {}) {
  const headers = { ...extraHeaders };
  const binary = typeof Blob !== 'undefined' && body instanceof Blob;
  if (method !== 'GET') headers['X-Requested-With'] = 'EmojiClassroom';
  if (body !== undefined && !headers['Content-Type']) headers['Content-Type'] = binary ? 'image/jpeg' : 'application/json';
  let response;
  try {
    response = await fetch(path, { method, headers, credentials: 'same-origin', body: body === undefined ? undefined : binary ? body : JSON.stringify(body), signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs) });
  } catch (error) { if (signal?.aborted) throw error; throw new ApiError('连接失败，请确认服务已启动后重试。', 0); }
  if (!response.ok) {
    let result;
    try { result = await response.json(); } catch { result = {}; }
    const fields = { username: '用户名需为 3～254 位，以字母、数字或下划线开头，可包含 .、@、+ 和 -', password: '密码需为 10～128 位，包含字母和数字', email: '邮箱格式不正确', new_password: '新密码需为 10～128 位，包含字母和数字', name: '请填写课程名称（不超过 120 字）', teacher_id: '请选择任课教师', course_id: '请选择所属课程', starts_at: '请填写有效的开始时间', ends_at: '请填写有效的结束时间', classroom: '请填写教室（不超过 120 字）', class_name: '请填写班级（不超过 120 字）' };
    const field = result.data?.errors?.[0]?.field?.split('.').at(-1);
    const communityFields = { nickname: '昵称最多 32 字，请勿包含换行或控制字符', bio: '简介最多 160 字，请使用一行普通文字', interests: '学习兴趣最多 80 字', major: '专业方向最多 60 字', grade: '年级最多 20 字', study_goal: '学习目标最多 100 字', learning_style: '请选择提供的学习方式', q: '关键词最多 120 字、5 组，请使用普通文字', avatar_color: '请选择提供的头像配色', user_id: '请选择有效的学生账号' };
    const engagementFields = { title: '请填写 1～80 字的单行笔记标题', content: '请填写 1～5000 字的笔记正文', takeaway: '收获最多 300 字', next_step: '下一步最多 300 字', reviewed: '请选择有效的回顾状态', days: '请选择近 7、30 或 90 天', text: '问题内容最多 300 字，请使用普通文字', reply: '教师回应最多 1000 字，请使用普通文字', reflection: '教学反思最多 2000 字，请使用普通文字', category: '请选择问题类型', version: '内容版本已变化，请刷新后重试' };
    const wallField = path.startsWith('/api/buddy-wall') ? { content: '请填写 1～600 字的普通文字留言', visibility: '请选择匿名或允许查看来源' }[field] : undefined;
    const joinField = { code: '请填写 8 位加入码，可包含字母和数字 2～9', ttl_minutes: '加入码有效时长应为 15～1440 分钟' }[field];
    const leaveField = path.startsWith('/api/leaves') ? { reason: '请填写 2～500 字的普通文字请假原因', category: '请选择病假、事假或其他', reply: '审批回复最多 500 字', version: '申请状态已变化，请刷新后查看' }[field] : undefined;
    throw new ApiError(leaveField || wallField || joinField || engagementFields[field] || communityFields[field] || fields[field] || result.message || '操作未成功，请重试。', response.status);
  }
  return response;
}

export async function api(path, options) {
  const response = await request(path, options);
  try { return await response.json(); }
  catch { throw new ApiError('服务返回了无效响应，请稍后重试。', 502); }
}

export async function downloadCsv(path, signal) {
  const response = await request(path, { signal, timeoutMs: 60000 });
  const blob = await response.blob();
  if (signal?.aborted) throw new DOMException('已取消下载', 'AbortError');
  const filename = response.headers.get('Content-Disposition')?.match(/filename="([A-Za-z0-9_.-]+)"/)?.[1] || 'emoji-feedback.csv';
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return Number(response.headers.get('X-Export-Count') || 0);
}
