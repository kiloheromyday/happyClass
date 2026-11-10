# 情绪分析后端服务

本目录统一说明新增的课堂情绪回放、教学洞察和多课堂分析服务。本次交付不包含本地新增前端：小组仓库的登录页、导航、页面与样式保持不变，新增接口可在登录后通过现有 `/docs` API 文档或接口客户端调用。

## 目录

| 目录 | 内容 |
| --- | --- |
| `backend/app/emotion/replay/` | 课堂情绪时间轴聚合 |
| `backend/app/emotion/insights/` | 关注时段规则、教学环节、教学调整与前后对比 |
| `backend/app/emotion/lab/` | 多课堂方案、对齐、质量核对、后台任务、固定报告和导出 |
| `tests/emotion/` | 服务行为、权限、边界、数据库升级与兼容性测试 |
| `scripts/emotion/` | 显式合成演示生成、隔离容器运行检查 |
| `docs/emotion/` | 后端安装、接口与限制说明 |

原有认证、课堂、AI、数据库访问及旧接口保留原位置，避免大范围移动影响组员工作。数据库只新增表和索引；没有改名或删除原表，也不重置现有账号、课堂与反馈。

## 接口入口

| 功能 | 路径 | 说明 |
| --- | --- | --- |
| 回放 | `GET /api/sessions/{id}/emotion-replay` | 只返回时间段、来源和分类数量 |
| 洞察 | `GET /api/sessions/{id}/insights` | 规则、关注区间、教学记录与描述性前后对比 |
| 洞察规则 | `PUT /api/sessions/{id}/insights/rules` | 版本校验 |
| 教学记录 | `/api/sessions/{id}/insights/entries` | 带幂等请求键与编辑版本 |
| 分析实验室 | `/api/emotion-lab/` | 方案、任务、报告、批注与导出 |

完整字段和全部路径以运行服务的 `/docs` 和 `/openapi.json` 为准。登录沿用原有会话 Cookie；写操作沿用 `X-Requested-With: EmojiClassroom` 和来源校验。

课堂内容仅任课教师或管理员可访问。实验室资源另外要求属于当前创建账号，并在读取和运行时重新检查课堂权限；管理员不能直接打开其他账号的分析报告。所有新增结果均为聚合数据，不返回学生账号、姓名、采集设备或人脸图片。

## 运行

Compose 的 web 服务设置 `EMOJI_LAB_WORKER=1`，启动后可处理持久化分析任务。直接运行 Python 主服务时，在启动前显式设置该环境变量即可；未启用时原有业务正常，分析任务会保留在队列。

```powershell
$env:EMOJI_LAB_WORKER='1'
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

测试：`python -m pytest -q tests/emotion`。完整回归仍为 `python -m pytest -q`，前端原有检查和构建继续执行。

独立、明确标记的演示数据只能由操作者显式生成，不会随启动自动写入：

```powershell
docker compose exec web python scripts/emotion/seed_insights_demo.py --teacher demo_teacher --confirm-demo-data
docker compose exec web python scripts/emotion/seed_lab_demo.py --teacher demo_teacher --confirm-demo-data
```

教师账号需事先存在；命令不提供默认密码。演示数据和账号属于操作者数据库，不随代码上传。

## 方法与容量

统计单位为记录次数，不是人数。主动反馈和 AI 分类分别分析；两来源差异不是模型准确率，前后差异不是因果结论。

- [回放接口](replay.md)：时间边界、空白时段和自动分段。
- [教学洞察](insights.md)：规则、教学环节、调整与对比。
- [分析实验室](lab.md)：多课堂对齐、任务、报告与资源管理。

`smoke_runtime.py` 仅供隔离、可销毁的验收数据库使用，会显式创建合成账号与记录。CI 在临时容器中执行它，并在结束时清理临时卷；不要将该命令用于真实业务数据库。
