# 部署与使用手册

0.21.1 修复全面测试发现的重试、时钟、筛选和分页问题；启动自动新增 course_creation_keys，不修改旧业务记录，无新增依赖。更新前备份数据库，重新构建前端并重启主服务；AI 服务可保持运行。

0.21.0 增加完整课程评价、站内消息中心、院系与课程维护和演示数据筛选。启动兼容补表/补列，原记录保留。可在备份后显式运行 `.\.venv\Scripts\python.exe scripts/seed_evaluations.py` 补充带标记的校园演示评分；不会随启动自动生成。使用及接口见 COURSE_EVALUATIONS_AND_MESSAGES.md。

0.20.0 增加学生请假窗口、任课教师审批、管理员全校请假记录与课堂名单标记；启动自动增加 leave_requests 表，保留已有数据。使用与权限见 LEAVE_REQUESTS.md。

0.19.0 新增管理员全校开课总览、院系统一配色、可点击周课表及四周演示数据生成。每天六时段包含晚课；公开参考与数据补充方式见 CAMPUS_DEMO.md。启动迁移保留旧数据，演示数据须显式运行生成脚本，不会随普通启动自动写入。

当前版本 0.21.1：开发者模式提供“演示学生”“演示教师”“演示管理员”身份切换。管理员默认进入全校开课总览，可管理院系、课程、课堂及用户，并只读查看全校请假记录。学生提交具体课堂的请假申请，由任课教师审批。学伴是学生之间的好友关系，位于学生端“好友学伴”；原 demo_buddy 账号仍作为普通学生保留，可在成员管理中查找。

本说明面向 Windows 本机课程演示。需要 Python 3.13、Node.js 22.12 以上、可下载依赖的网络以及可用磁盘空间。已验证 Python 3.13.12、Node 24.14。AI 使用 CPU，不要求 GPU。当前未验证 Linux、容器或公网部署。

## 从源码包开始

解压后在 emoji-classroom 目录打开 PowerShell。执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\setup-ai.ps1
```

受限环境下 pip 临时目录报错时，可分别给脚本传入 `-UvPath <uv.exe完整路径>`。AI 模型约 35 MB，准备脚本检查 SHA256；模型和依赖不随源码包重复分发。requirements-lock.txt、ai_service/requirements-ai-lock.txt 和 frontend/package-lock.json 记录验证版本。

创建第一个管理员，密码在终端隐藏输入：

```powershell
.\.venv\Scripts\python.exe -m backend.manage create-user --username admin --role ADMIN
```

分别在两个终端运行，按 Ctrl+C 停止：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-ai.ps1
```

打开 http://127.0.0.1:18080/ ，API 文档 http://127.0.0.1:18080/docs ，AI 状态 http://127.0.0.1:18081/health 。业务健康应显示数据库 ready，AI 应显示 `data.ready=true`。更改 Python 源码后重启相应服务；更改页面源码后在 frontend 运行 `npm.cmd run build` 并刷新网页。

## 三个角色的操作

管理员在“用户列表”创建教师或学生，在“课程与课堂”创建课程并指定教师，创建时间段和班级，再勾选课堂学生名单保存。名单保存为整体替换，结束后不能修改。密码至少 10 位且包含字母和数字，用户名 3～254 位，支持邮箱式用户名。

学生也可自行注册，进入“我的课堂”选择正在进行且已安排的课堂，选择表情并提交。“情绪历史”显示本人记录，“账号安全”可改密。教师进入“课堂反馈”查看本人所授课堂，通过“实时看板”查看约 5 秒更新的数据，通过“统计与导出”组合筛选并下载 CSV。管理员可以查看全部课程。

“个人资料”可编辑昵称、邮箱、简介、兴趣、专业、年级、学习目标、偏好方式与头像配色，学习信息均可选填。学生进入“好友学伴”输入关键词即可模糊查找，多个词用空格分开；展开“更多筛选”可限定字段、兴趣、专业、年级、偏好方式、关系与共同课程，条件组合生效。搜索结果分页显示。可发送申请、同意或婉拒、撤回和移除。邮箱和个人情绪不向学伴开放。详情见 PROFILE_AND_BUDDIES.md。

教师选择进行中的课堂，展开“课堂表情识别”，设置采样间隔后主动点击“开启识别”。摄像头权限由浏览器询问，只有获准才开始。停止按钮、收起识别区、切换课堂、离开页面和隐藏标签页均会释放摄像头。也可上传不超过 1 MB、最大 1920×1080 的 JPEG。模型输出低于阈值或不支持的类别会过滤；无人脸或全部过滤是合法结果。

## 独立采集程序

只在显式选择 `--camera` 时才会打开设备。下面命令仅为使用说明，本阶段验证没有运行物理摄像头：

```powershell
.\.venv\Scripts\python.exe -m ai_service.capture --camera 0 --session-id 1 --device-id classroom-a --interval 5
```

课堂 ID 可从接口文档的已授权课堂列表响应查看。ID 1 只是示例，应替换成真实的进行中课堂。程序使用本机两个独立凭据，不需要学生 Cookie。默认连续运行，Ctrl+C 结束；`--max-frames 10` 限制采样数量。

已有授权的本地视频或单张图片可以使用：

```powershell
.\.venv\Scripts\python.exe -m ai_service.capture --video .\lesson.mp4 --session-id 1 --device-id video-a --interval 3 --max-frames 5
.\.venv\Scripts\python.exe -m ai_service.capture --image .\sample.jpg --session-id 1 --device-id image-a
```

采集程序按间隔运行；视频按帧率跳过中间帧。它不会保存新的视频或截图。临时网络错误最多尝试三次，批次标识不变；权限、时间或格式错误直接停止。连续失败不会无提示地丢弃数据并继续。待确认结果只保存在内存，进程退出后不恢复，不保证离线缓存。

## 配置与故障处理

`.env.example` 是参考文件，程序不会自动读取 `.env`。PowerShell 通过 `$env:名称 = '值'` 设置进程环境，再启动服务。阈值为 EMOJI_AI_MIN_CONFIDENCE，默认 .70；推理地址为 EMOJI_AI_URL。推理凭据为 data/ai-service.token，结果接收凭据为 data/ai-ingest.token，也分别可由 EMOJI_AI_TOKEN、EMOJI_AI_INGEST_TOKEN 指定。两者不能互换，不应复制到前端或提交仓库。

端口占用时先确认是否已有本项目服务，避免重复启动。登录失败先检查当前真实账号；自动测试账号只存在隔离数据库，网页没有默认测试密码。课堂不可提交时核对开始结束时间、学生名单、教师归属。AI 未就绪时检查独立服务启动输出、模型文件和准备脚本；页面显示旧状态时刷新。摄像头拒绝时检查浏览器权限，也可先用 JPEG 验证链路。

本机业务数据在 data/classroom.db。备份时停止业务服务，再复制数据库到自己保管的位置；恢复也应停止服务后操作。不要把数据库和密钥作为公开作业附件。源码打包脚本自动排除这些本地文件，换电脑时创建新账号和凭据。

远程或正式部署需要补充 HTTPS、备份策略、受控的 AI 服务网络与正式数据库方案，当前说明不能替代生产部署验收。

## 升级至 0.18.0

0.10.0 沿用下列备份与重启步骤，另幂等新增 `personal_notes` 和 `personal_note_keys`，原始业务数据保留。确认 OpenAPI 版本为 0.10.0 后，学生刷新页面即可看到“笔记与回顾”。AI 服务不变。数据库含个人笔记，备份也应按私有数据妥善保管。

0.11.0 幂等新增 `buddy_wall_messages` 与 `buddy_wall_keys`。学生在学伴页访问自己的墙或已确认学伴的墙，匿名方式不会自动揭示来源。备份中包含内部作者关联，应作为私有数据保管。无需重新创建账号或确认既有关系。

0.12.0 幂等新增 `session_join_codes`，个人回顾扩展无需新增统计表。已有名单与加入码共存，更换和停用不会清除名单。数据库备份含可使用的加入码，应妥善保管。

0.13.0 新增 `course_enrollments`，首次升级从旧名单建立课程关系而不修改旧名单；以后新课堂自动安排有效课程成员。添加入口移至“我的课程”，日常评价默认只展示进行中与刚结束课堂，人工评价结束后保留 30 分钟，AI 与问题卡权限不变。

0.14.0 添加个人回顾日期详情接口与图表交互，无新增业务表。更新前端构建并重启主服务即可；保留原数据库。

0.15.0 新增 Pillow 12.0.0 依赖，先安装 requirements.txt，再重建前端、重启主服务。幂等新增 user_avatars 表，不修改原资料；头像存于数据库并随私有备份保存，不纳入源码包。无需重启 AI 服务。详细使用见 PROFILE_HOME.md。

0.16.0 新增课程详情只读接口、课程卡片与课堂/笔记/回顾定位跳转，无新增表或依赖。更新前端构建并重启主服务，刷新网页后进入“我的课程”点击课程卡片。教师加入码入口移至本门课程详情。见 COURSE_DETAILS.md。

0.17.0 教师首页改为教学工作台，新增课堂安排与学习指引发布接口，幂等创建 classroom_guides、teaching_session_keys，不改动旧课堂、名单、账号、笔记与学伴关系。无新增依赖，重新构建前端并重启主服务即可。教师需要由管理员分配课程，学生学习指引只在教师实际发布后出现。见 TEACHER_WORKSPACE.md。

0.18.0 新增本地演示开发者模式与 demo_access_sessions 能力表，无新增依赖。正常启动默认关闭；本机演示以 scripts/start-demo.ps1 启动，再在登录栏主动开启。切换只允许已存在且角色匹配的固定 demo 账号；不会自动创建账号或覆盖原密码。成员管理针对本数据库其他学生教师，须在自己控制的本地环境操作，勿反向代理对外开放。见 DEVELOPER_MODE.md。

升级前停止服务并备份数据库，或使用 SQLite 官方备份 API 得到一致副本。保留原 data 目录，将新源码和前端构建放到同一项目目录后重启主服务。启动时幂等补齐新增表；不删除账号、课程、反馈或学伴关系。AI 服务无需更换模型。确认 `/openapi.json` 版本为 0.18.0、`/api/health` 数据库 ready，然后刷新网页。扩展功能使用见 CLASSROOM_ENGAGEMENT.md、PERSONAL_NOTES.md、BUDDY_WALL.md、JOIN_CODES.md、PROFILE_HOME.md、COURSE_DETAILS.md、TEACHER_WORKSPACE.md 和 DEVELOPER_MODE.md。
## 0.22.0 选做服务部署入口

原本机部署方式继续可用。Redis、独立结果工作进程、MCP 和 Docker Compose 的安装、密钥、端口及验证命令见 [选做扩展](OPTIONAL_EXTENSIONS.md)。Docker 默认网页端口为 18090，使用独立卷，与原本机 18080 服务的数据分开。
