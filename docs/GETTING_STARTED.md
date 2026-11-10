[返回项目首页](../README.md) · [在线截图使用说明](manual/README.md)

# HappyClass 安装、开发与组员交接

面向三人组课程大作业的课堂反馈系统。学生选择已加入课程中的具体课堂，提交感受和完整评价；教师回应问题、发布学习指引、审批请假并查看统计；管理员维护全校开课、院系、课程和账号。

**选做扩展版本：0.22.0；原交接版本：0.21.1；图文手册及界面完善日期：2026-11-09。** 系统版本以 `backend/app/main.py` 的 API 版本为准。已完成三角色真实浏览器操作及截图手册，见 [功能使用说明](manual/README.md)。物理摄像头实时采集和另一台电脑的部署验收仍待完成，不能视为已经通过生产部署验收。

本文是详细安装与交接入口：先完成本地启动，再按角色体验业务，最后核对待办与分工。

## 1. 环境与技术选型

| 部分 | 使用方案 | 接手要求 |
| --- | --- | --- |
| 前端 | Vue 3、Vite 7 | Node.js 22.12 及以上；已验证 Node 24.14 |
| 主服务 | Python、FastAPI、Uvicorn | Python 3.13；已验证 Python 3.13.12 |
| 数据库 | SQLite、SQL 初始化脚本 | 无需另装数据库服务；默认 `data/classroom.db` |
| 可选 AI | OpenCV、ONNX Runtime、FER+ | CPU 可运行；首次下载约 35 MB 模型 |
| 已验证运行方式 | Windows 本机 PowerShell、Docker Desktop 的 Linux 容器 | 另一台电脑与公网部署尚未复现验收；Compose 入口见 [选做扩展](OPTIONAL_EXTENSIONS.md) |

后端按 Controller → Service → Repository 分层。SQLite 是当前实际实现，**未适配 MySQL/PostgreSQL**。参考指导书将这两者列为建议技术栈；若授课教师另有硬性要求，应另行确认，详见 [数据库要求核对](DATABASE_REQUIREMENTS.md)。

## 2. 从 GitHub 克隆并启动

下面命令均在 PowerShell 中执行。安装 Python、Node.js 和 Git 后：

```powershell
git clone https://github.com/kiloheromyday/happyClass.git
cd happyClass
python --version
node --version
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

`setup.ps1` 创建项目自己的 `.venv`、安装基础 Python 依赖，并通过 `npm ci` 安装、构建前端。依赖下载需要网络，失败后应解决网络问题并重试，不能跳过前端构建。依赖快照见 `requirements-lock.txt`、`frontend/package-lock.json` 及可选 AI 的 `ai_service/requirements-ai-lock.txt`。

创建第一个管理员，按终端提示输入两遍自己设置的密码：

```powershell
.\.venv\Scripts\python.exe -m backend.manage create-user --username admin --role ADMIN
```

用户名 3～254 位；密码 10～128 位，至少含字母和数字。仓库不提供默认密码。启动主服务并保持这个终端运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

- 网页：<http://127.0.0.1:18080/>
- 主服务健康：<http://127.0.0.1:18080/api/health>
- API 交互文档：<http://127.0.0.1:18080/docs>
- API 结构：<http://127.0.0.1:18080/openapi.json>

首次启动会初始化数据库。管理员登录后创建教师、课程、课堂和学生名单；学生也可自行注册。Ctrl+C 停止服务。端口占用时先确认是否已有本项目运行。

**克隆后没有原电脑的账号、头像、课程和历史记录是正常现象。** 仓库交付源码及可重复的演示生成脚本，不包含开发者本机数据库、私有资料和服务凭据。需要丰富演示数据时执行下一节。

## 3. 建立可切换角色的本地演示

在项目根目录新开终端，依次创建固定演示身份。密码由操作者自行设置，不要写入 README 或提交仓库：

```powershell
.\.venv\Scripts\python.exe -m backend.manage create-user --username demo_student --role STUDENT
.\.venv\Scripts\python.exe -m backend.manage create-user --username demo_teacher --role TEACHER
.\.venv\Scripts\python.exe -m backend.manage create-user --username demo_admin --role ADMIN
.\.venv\Scripts\python.exe -m backend.manage create-user --username demo_buddy --role STUDENT
```

已有账号不必重复创建。`demo_buddy` 是普通学生，可用于好友功能验收；系统只有学生、教师、管理员三种身份，没有单独的“学伴端”。

在空库或自己控制的演示库中，显式生成课程与评价：

```powershell
.\.venv\Scripts\python.exe scripts/seed_campus.py --confirm-demo-data
.\.venv\Scripts\python.exe scripts/seed_evaluations.py
```

第一条生成 10 个教学单位、20 门合成课程，并按执行日期所在周安排上一周至后两周的四周课堂，每天六个时段，包含晚上及周末。第二条补充已结束演示课堂的四项评分与建议。重复运行按请求键避免重复生成；未来课堂不会凭空生成历史评价。院系和课程取材于公开学科设置，**不是中国科学技术大学当学期的真实课表或真实师生数据**。对已有数据库执行前先备份；脚本不会自动随服务启动执行。

停止普通主服务，再启动本地演示服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-demo.ps1
```

网页登录卡片底部打开“开发者模式”，主动开启后可切换演示学生、教师、管理员，并管理其他学生与教师。启动脚本只开启能力，不会自动创建上述账号或重设密码。随机生成的 `campus_*` 成员没有公开密码，使用固定 demo 身份体验即可。默认普通启动不启用此模式，本地演示服务不应经代理对外开放。详见 [开发者模式](DEVELOPER_MODE.md) 和 [校园演示数据](CAMPUS_DEMO.md)。

## 4. 已完成功能与师生对应关系

| 身份 | 已实现的主要功能 |
| --- | --- |
| 学生 | 课程详情、彩色周课表、添加课程与加入码、课堂表情反馈、四项课程评价、匿名问题、已发布指引、个人笔记、可点击日期的个人回顾、CSV 导出 |
| 学生个人空间 | 资料与头像上传裁剪、多属性好友搜索、好友申请确认、匿名或允许点击来源的留言墙、按节请假、站内消息、账号安全 |
| 教师 | 教学工作台、所授课程与课堂安排、加入码、名单查看、问题回应和解决状态、指引草稿与发布、请假审批、实时看板、完整评价汇总、统计导出、教学反思、可选 AI |
| 管理员 | 全校开课、院系一致配色、全校课表与评价、院系和课程维护、归档恢复与教师调整、账号创建与名单安排、全校请假只读查询、演示数据筛选 |
| 共用能力 | 登录会话与角色权限、消息已读与跳转、写操作来源校验、重复请求保护、事务与审计、CSV 公式注入防护 |

建议使用同一课程、同一课堂完成联合演示：

1. 管理员分配教师并安排课堂；学生加入课程，后续新课堂自动安排课程成员。
2. 学生在“我的课堂”选择进行中课堂，提交感受、四项评分和匿名问题。
3. 教师回应问题并发布指引；学生查看消息、返回对应课堂写笔记。
4. 学生点击个人回顾日期节点查看当天记录；教师查看课堂汇总并保存反思。
5. 另选未结束课堂，学生申请请假，任课教师审批，双方查看结果。

需要区分的规则：

- 加入码只在“我的课程 → 添加课程”使用；日常评价从已经加入的课程选择。
- 手动表情和完整评价从课堂开始开放，到结束后 30 分钟截止；匿名新问题和 AI 仅在课堂进行中开放。
- 感受可多次提交；完整评价每人每节一份，可更新。表情条数、参与人数和评分份数不是同一个量。
- 个人笔记和回顾只有本人有应用读取入口；学伴不等于共享个人情绪或笔记。
- 匿名留言和“允许点击来源”是发布时的不同选择；匿名不等于数据库内部无法关联作者。
- 个人回顾按 UTC 日期分组，校园周课表使用北京时间，跨日时应留意这个差异。
- 演示范围依据每条数据的标记过滤；“排除演示”不代表剩余数据已核实为真实采集。

## 5. 可选摄像头与 AI 服务

不运行 AI 服务也能使用手动反馈、评价、笔记、好友和管理功能。需要 AI 时，先完成基础安装，再执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup-ai.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-ai.ps1
```

AI 在另一个终端持续运行，主服务也须同时运行。状态地址为 <http://127.0.0.1:18081/health>，就绪状态应为 `data.ready=true`。准备脚本下载并校验 FER+ 模型，在 `data` 下生成两份独立服务凭据，不要复制到前端或提交仓库。

教师在自己授课的进行中课堂主动开启识别，由使用者决定摄像头授权，也可上传不超过 1 MB 的 JPEG 验证链路。模型默认过滤低置信度结果，AI 记录匿名保存，默认不保存原始摄像头视频或人脸图像。个人头像则会持久保存，两者处理方式不同。

**已完成公开样例图片推理与入库验证；网页真实摄像头的预览、连续识别和设备释放尚未完成实机验收。** Windows“相机”有画面不能替代网页验收，也没有经过实测的识别准确率结论。详见 [摄像头记录](CAMERA_TEST_20261104.md)。

## 6. 代码目录与修改方法

```text
backend/app/controllers/    HTTP 接口和请求校验
backend/app/services/       业务规则、角色权限与流程
backend/app/repositories/   SQLite 访问与兼容初始化
backend/app/models/         请求和领域数据结构
backend/manage.py           本地创建账号
frontend/src/               Vue 页面、交互与样式
ai_service/                独立推理服务与显式采集程序
database/schema.sql        数据表、约束与索引
scripts/                   安装、启动、演示数据、模型准备与打包
tests/                     Python 回归及前端组件检查
docs/                      需求、设计、功能、部署、测试与交接资料
data/                      运行时数据库与凭据，不纳入 Git
```

改 Python 主服务后重启主服务；改 AI 源码后重启 AI。改前端后执行构建并刷新网页，主服务提供的是 `frontend/dist`，不是即时读取 `src`：

```powershell
Push-Location frontend
npm.cmd run build
Pop-Location
```

前端开发时可在 `frontend` 运行 `npm.cmd run dev`，地址为 <http://127.0.0.1:15173/>，仍需主服务运行。`.env.example` 只是配置说明，程序不会自动读取 `.env`；应在启动前设置进程环境变量。完整配置、升级及备份方法见 [部署说明](DEPLOYMENT.md)。

## 7. 检查与测试

在项目根目录，安装基础及可选 AI 依赖后执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
Get-ChildItem tests/test_*.cjs | ForEach-Object {
    & node $_.FullName
    if ($LASTEXITCODE -ne 0) { throw $_.Name }
}
Push-Location frontend
try {
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally { Pop-Location }
```

Python 测试使用隔离数据库，不要改为指向现有业务数据库。AI 模型检查还需要准备模型。2026-11-04 已记录 Python 320 项、前端 11 组检查通过及生产构建成功，详见 [全面测试报告](COMPREHENSIVE_TEST_20261104.md)。本次交接的复验另记在 [本次交接记录](HANDOFF_20261107.md)，不把历史结果当成本次执行。

## 8. 三人组接手分工

以下为建议任务，不是已经完成的个人贡献证明：

| 成员 | 负责内容 | 应交付的材料 |
| --- | --- | --- |
| 成员一 组长与集成 | 核对教师硬性要求、合并修复、统一版本与答辩流程 | 需求对照、问题关闭记录、最终源码与真实贡献记录 |
| 成员二 页面与设备 | 三角色真实点击、宽窄屏、权限、摄像头、真实截图框注 | 浏览器验收表、实景截图、设备观察与复验记录 |
| 成员三 部署与报告 | 另一台电脑从 Git 克隆复现、架构材料、课程报告及视频 | 实际部署记录、正式报告、5～8 分钟演示视频 |

优先待办：

1. 按 [最终清单](FINAL_CHECKLIST.md) 和 [浏览器验收](BROWSER_ACCEPTANCE.md) 做真实点击，核对问题回应、指引发布、请假审批及消息跳转。
2. 补摄像头实机记录，测试停止、切换课堂和隐藏页面后的设备释放。
3. 按 [真实截图使用说明](manual/README.md) 复现三角色流程；最新版为 49 页、35 个场景、56 幅配图，已标注实际入口及操作结果。更换界面或业务规则后同步更新对应截图。
4. 在另一台电脑按本文复现，补姓名、组号、真实贡献和教师要求，冻结版本后录视频。

排课冲突检测不在当前需求中。MySQL/PostgreSQL 适配、公网部署、邮件或短信通知尚未实现，不能在报告中写成现成功能。Docker Compose 已完成本机运行验证，GitHub Actions 已在小组仓库通过[扩展分支检查](https://github.com/kiloheromyday/happyClass/actions/runs/42764849798)。安装、故障恢复及限制见 [选做扩展](OPTIONAL_EXTENSIONS.md)，详细分工见 [TEAM_HANDOFF](TEAM_HANDOFF.md)。

## 9. 数据与交付约定

- 数据库、令牌、日志、虚拟环境、依赖目录和模型权重不提交，在新电脑重新生成。备份数据库先停服务，或使用 SQLite 一致性备份 API。
- `database/schema.sql` 与启动兼容初始化是实际结构依据；升级前备份，不能为演示直接删除旧库。
- 源码打包可执行 `.\.venv\Scripts\python.exe scripts/package_project.py --output ..\happyclass-source.zip`，输出名须未被占用；Git 仓库不需要提交重复压缩包。
- 截图、测试和贡献记录只写实际发生的内容；流程示意或自动化检查不替代真实浏览器验收。

常用资料：[需求](REQUIREMENTS.md) · [设计与 ER 图](DESIGN.md) · [部署](DEPLOYMENT.md) · [数据库脚本](../database/schema.sql) · [演示与报告](DEMO_AND_REPORT.md) · [个人笔记](PERSONAL_NOTES.md) · [课程详情](COURSE_DETAILS.md) · [教师对应流程](TEACHER_WORKSPACE.md) · [评价与消息](COURSE_EVALUATIONS_AND_MESSAGES.md)。
