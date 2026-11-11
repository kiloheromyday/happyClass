# HappyClass 课堂情绪检查器

让课堂感受被看见，让师生沟通有回应。支持学生、教师、管理员三种身份，覆盖课堂反馈、学习记录、教学跟进和校园课程维护。

## 📖 [点击阅读：完整功能使用说明 · 真实截图版](docs/manual/README.md)

**35 个功能场景 · 56 幅带编号框的配图 · 入口、步骤、结果完整说明。点击上方标题即可在 GitHub 直接阅读，不用下载 Word。**

[学生功能](docs/manual/README.md#student) · [教师功能](docs/manual/README.md#teacher) · [管理员功能](docs/manual/README.md#admin) · [下载 Word 版（49 页）](docs/manual/课堂情绪检查器功能使用说明_真实截图版_20261109.docx)

[安装与组员交接](docs/GETTING_STARTED.md) · [三人演示路线](docs/manual/README.md#walkthrough) · [常见问题](docs/manual/README.md#faq)

## 界面实拍

### 学生：从已加入的课程开始

搜索课程、查看详情，在课程卡片与彩色周课表之间切换；日常直接选择正在进行或刚结束的课堂提交感受和评价。

![学生端真实课程卡片，带操作编号框](docs/manual/images/04-course-cards-focus.png)

[查看课程操作步骤](docs/manual/README.md#scene-04) · [查看课堂评价](docs/manual/README.md#scene-08) · [查看可点击的日期回顾](docs/manual/README.md#scene-13)

### 教师：把学生反馈接入教学流程

在工作台定位当前课堂和待办，回应匿名问题、发布学习指引、审批请假，再查看统计和教学反思。

![教师端真实教学工作台，带操作编号框](docs/manual/images/22-teaching-top.png)

[查看教学工作台](docs/manual/README.md#scene-21) · [查看统计与导出](docs/manual/README.md#scene-27)

### 管理员：全校开课与院系配色

同一院系使用统一颜色，支持全校课表、课程评价、院系课程维护及成员管理。

![管理员端真实全校开课总览，带操作编号框](docs/manual/images/32-campus-overview.png)

[查看全校课表](docs/manual/README.md#scene-30) · [查看院系维护](docs/manual/README.md#scene-31) · [查看账号与名单管理](docs/manual/README.md#scene-33)

截图来自同一应用的独立测试环境，人物与排课为合成演示内容，不代表学校官方课表。完整手册包含每张图的编号说明和实际操作结果。

## 已有功能

| 身份 | 主要功能 | 图文入口 |
| --- | --- | --- |
| 学生 | 课程与周课表、加入课程、表情反馈、四项评价、匿名提问、学习指引、提交情绪反馈、填写回访、课堂卡点书签与课后复习 | [课程与课堂](docs/manual/README.md#scene-04) · [提交反馈](docs/emotion/guide/submit-feedback.md) · [填写回访](docs/emotion/guide/review-feedback.md) · [记书签与复习](docs/emotion/guide/student-bookmarks.md) |
| 学生个人空间 | 私人笔记、查询与 CSV 导出、日期回顾、资料与头像裁剪、好友学伴、留言墙、请假、站内消息 | [笔记与回顾](docs/manual/README.md#scene-11) · [学伴与留言](docs/manual/README.md#scene-16) |
| 教师 | 课堂安排、课程邀请、问题回应、指引草稿与发布、请假审批、实时看板、统计导出、评价汇总、教学反思、追问反馈、批量回应、发起回访、卡点统计与补学资料 | [教师完整流程](docs/manual/README.md#teacher) · [处理反馈](docs/emotion/guide/ask-student.md) · [分组与批量回应](docs/emotion/guide/batch-feedback.md) · [查看卡点与发资料](docs/emotion/guide/teacher-bookmarks.md) |
| 管理员 | 全校开课与评价、院系配色、课程归档恢复、教师分配、账号创建、课堂名单、演示数据筛选 | [管理员完整流程](docs/manual/README.md#admin) |
| 通用 | 登录与账号安全、角色权限、消息已读与跳转、本地演示身份切换 | [首次使用](docs/manual/README.md#common) |
| 教师和管理员 | 情绪回放、教学调整前后对比、课堂反馈隐私 | [情绪回放](docs/emotion/guide/replay-emotion.md) · [情绪洞察](docs/emotion/guide/teaching-insights.md) · [反馈隐私](docs/emotion/guide/feedback-privacy.md) |

加入码只在添加课程时使用；个人笔记和回顾由本人查看；好友学伴是普通学生之间的关系。表情反馈条数、参与人数和四项评分份数分别统计。

## 本地启动

已验证 Windows PowerShell、Python 3.13、Node.js 22.12 及以上。后端使用 FastAPI，前端使用 Vue 3 / Vite，数据库为 SQLite，无需另装数据库服务。

```powershell
git clone https://github.com/kiloheromyday/happyClass.git
cd happyClass
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\.venv\Scripts\python.exe -m backend.manage create-user --username admin --role ADMIN
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

创建管理员时，按提示自行设置密码。启动后访问 **<http://127.0.0.1:18080/>**。

新克隆的仓库不包含原电脑数据库、账号和历史数据。需要丰富课表和可切换的演示身份，请按 [本地演示配置步骤](docs/GETTING_STARTED.md#3-建立可切换角色的本地演示) 创建账号、生成数据并启动演示模式。完整安装、开发、备份和测试命令均在 [安装与组员交接](docs/GETTING_STARTED.md)。

## 交接与后续工作

选做扩展为 **0.22.0**，原交接版本为 **0.21.1**。图文手册与界面完善日期 **2026-11-09**。已补充管理员账号草稿保护、统计筛选后的重新查询提示和导出限制，并统一“表情反馈”数量名称，详见 [本次完善](docs/manual/README.md#walkthrough)。

可选 AI 已验证服务就绪及 JPEG 请求链路；**物理摄像头预览、连续识别、设备释放和另一台电脑部署仍待实机验收**。手动反馈及其他业务不依赖 AI 服务。当前数据库实现为 SQLite，MySQL / PostgreSQL 适配和公网部署尚未完成。Docker Compose 在本机跑过，主分支的测试和容器检查也通过了。[主分支 CI](https://github.com/kiloheromyday/happyClass/actions/runs/43003503852)

## 指导书 2.3 选做扩展

- **反馈隐私。** 任课老师可以按课设置匿名或只显示统计。学生仍能看自己的记录。
- **AI 结果队列。** 独立采集脚本带上 `--delivery queue`，结果先送进 Redis，再由后台写入数据库。管理员在「反馈隐私」里能看到积压和失败记录，也能重试。
- **MCP。** 可以在 MCP 客户端查模型状态，或传一张 JPEG 看识别结果。由使用者提供图片，工具不会打开摄像头。
- **Docker 和 CI。** 用 Compose 启动网页、Redis 和后台进程，需要识别时再加上 AI 服务。GitHub Actions 会跑测试和容器检查。

教师和管理员还能从侧栏打开「情绪回放」和「情绪洞察」。回放可以拖时间轴看某段反馈，洞察可以记教学调整，再对照前后的统计。多课堂分析目前在 `/docs` 里调用。

具体操作见[选做扩展](docs/OPTIONAL_EXTENSIONS.md)和[情绪分析说明](docs/emotion/README.md)。

| 资料 | 用途 |
| --- | --- |
| [安装与组员交接](docs/GETTING_STARTED.md) | 环境、演示数据、开发命令、测试、三人分工 |
| [需求](docs/REQUIREMENTS.md) · [设计与 ER 图](docs/DESIGN.md) · [数据库脚本](database/schema.sql) | 报告与代码结构依据 |
| [部署说明](docs/DEPLOYMENT.md) · [数据库要求核对](docs/DATABASE_REQUIREMENTS.md) | 新电脑运行及选型说明 |
| [全面测试报告](docs/COMPREHENSIVE_TEST_20261104.md) · [交接复验](docs/HANDOFF_20261107.md) | 已执行的检查及时间范围 |
| [浏览器验收](docs/BROWSER_ACCEPTANCE.md) · [最终清单](docs/FINAL_CHECKLIST.md) · [摄像头记录](docs/CAMERA_TEST_20261104.md) | 后续验收 |
| [三人分工](docs/TEAM_HANDOFF.md) · [演示与报告](docs/DEMO_AND_REPORT.md) | 组员接手与答辩准备 |
