# 指导书 2.3 四项扩展验收

最新补充：用户完成 Docker Desktop 4.98.0 / WSL 安装后，本机 Linux 容器实际部署已通过，详见下方“Docker 实际运行补充”。第四项目前仅剩 GitHub CI 远程运行待验收。

日期：2026-11-09。认领成员：Lccccc679。代码基于本分支 2d2d31c，另含本轮 Compose 来源校验修复及真实 Redis 恢复测试扩充。采用 AI 辅助执行；不代替成员本人讲解和课程最终验收。

## 结论

| 项目 | 结论 | 依据与边界 |
| --- | --- | --- |
| 匿名与聚合模式 | 本机功能验收通过 | 隔离数据库 + 真实 HTTP：标准明细、匿名历史与 CSV、聚合隐藏明细且保留统计、学生本人历史保留、权限和版本冲突、防止降低保护等级；前端隐私交互检查通过 |
| 消息队列异步处理 | 本机功能验收通过 | 真实 Redis + HTTP 接收 + 独立 worker：先接收后入库、置信度筛选、批次重复不重复入库、管理员积压及心跳；另通过真实 Redis 消费组恢复、提交后确认前中断、三次失败入失败列表及重放检查 |
| MCP 工具服务 | 本机功能验收通过 | 官方 SDK 以 stdio 握手，发现两个工具、读取能力资源；model_status 访问实际 AI 服务；analyze_emotion 实际调用模型分析内存生成的无脸 JPEG；拒绝 URL 输入 |
| Docker Compose 与 CI | Docker 实际部署通过，CI 待远程运行 | 后续已构建并启动网页、Redis、worker 和 AI 容器，12 项容器检查通过；GitHub CI 仍未触发 |

前三项为功能链路验收，不包含 AI 模型准确率、课堂多人并发性能或正式生产部署验收。匿名模式是展示保护，不是不可逆匿名；MCP 测试未使用真人图片，没有给出识别准确率结论。

## 执行记录

- 四项扩展定向回归：13 passed，0 skipped，17.20 秒；含实际 Redis 消费恢复，1 条 Starlette/httpx 弃用提示。
- 扩充提交后确认前中断、真实 Redis 失败/重放后，恢复与交付检查再次执行：3 passed，0 skipped，2.80 秒。
- 隔离数据库的真实 HTTP、worker、MCP 联合验收：17 个检查点全部通过。临时主服务使用 18090，AI 服务复用 18081；真实账号与课堂所在的 18080 服务及数据库未被验收脚本修改。
- 前端：node tests/test_privacy_interactions.cjs 通过。检查保存、版本冲突保留草稿、放弃、失败重试与学生只读权限。
- 官方 Docker Compose v5.7.0：全部 profile 配置有效；默认 18090 和自定义 18123 的发布端口、允许来源一致。
- actionlint v1.7.12：.github/workflows/ci.yml 检查退出码 0。该检查不等于 GitHub 上执行工作流。
- PowerShell 启动脚本语法解析无错误。
- Docker API 连接检查失败：本机 //./pipe/docker_engine 不存在。没有将这项环境缺失写成部署通过。
- GitHub API 查询 kiloheromyday/happyClass/actions/runs：HTTP 200，total_count=0。当前分支尚未上传，无法验收其远程 CI。

## 本轮修复

Compose 网页默认发布到宿主机 18090，但原请求来源校验默认只允许 18080/15173，浏览器登录会被拒绝。现已在 compose.yaml 设置 EMOJI_ALLOWED_ORIGINS，随 EMOJI_WEB_PORT 同步变化，并增加配置回归检查。隔离 HTTP 服务以修复后的默认来源成功登录，官方 Compose 也验证了默认和自定义端口插值。

## 测试依赖与隔离

临时 Redis 8.10.3 使用 redis-windows 社区 Windows 构建，仅监听 127.0.0.1:16379，没有安装系统服务。它不是 Redis Ltd 的官方 Windows 发行，也不能代替 Compose 中 redis:8.2-alpine 的 Linux 容器验收。下载后已对照 GitHub release 元数据校验 SHA256：8000848c48668c8cd32f21386ce951d0e02c1aefae39443ab9d3de11ff8ebf9e。

来源：https://github.com/redis-windows/redis-windows （该项目声明仅推荐本地开发）；Compose 工具来自 https://github.com/docker/compose/releases/tag/v5.7.0 ；actionlint 来自 https://github.com/rhysd/actionlint/releases/tag/v1.7.12 。三份下载文件均按 release digest 校验。

联合验收使用临时 SQLite 和合成情绪标签，不将其写入用户的真实课堂。13 项定向测试使用 Redis 15 号库及唯一键前缀；联合验收使用 14 号库。后台写入的两个合成标签为 HAPPY 0.94、ANGRY 0.88，SAD 0.40 被过滤。这验证队列的筛选与入库，不是模型对图片的分类准确率。临时 Web、worker、MCP 和 Redis 在验收结束后停止；日常 18080 页仍保持原同步识别方式，未配置 EMOJI_REDIS_URL 时显示“异步处理尚未启用”属于实际状态。

## 第四项还差什么

1. 在已安装并运行 Docker 的 Linux 容器环境执行 scripts/start-extensions.ps1 -WithAI，验收网页登录、真实 Redis/worker、模型健康、数据卷持久化与重启恢复。
2. 使用 Git 命令行认证上传本分支，查看 GitHub Actions 的 tests 和 containers 两个任务实际运行结果，修复失败后保留绿灯链接。

缺少以上两类运行证据前，不能对老师宣称四项全部完成验收。

## Docker 实际运行补充

上述“Docker 引擎缺失”是安装前记录，现已补验：Docker Desktop 4.98.0、Engine 29.9.2、Compose v5.6.1，linux/amd64。已有 start-extensions.ps1 -WithAI 脚本成功构建镜像并启动四个服务。Windows 命令行首次获取 Docker Hub token 超时，使用电脑现有系统代理设置到本次命令的 HTTP_PROXY/HTTPS_PROXY 后下载成功，没有修改全局代理设置。

实际验收发现并修复了第二个部署问题：全部服务仅连接 internal 网络时，此 Docker 环境没有实际发布网页端口。现仅让 web 额外连接 web_access 桥接网络，继续只将 127.0.0.1:18090 发布到宿主机；Redis、worker、AI、MCP 均不连接该访问网络、不发布宿主机端口。增加了对应回归检查，2 项交付检查通过。

容器运行验收共 12 项通过：四服务运行健康、宿主机首页、18090 Origin 登录、AI 健康、队列重复批次识别、真实 worker 入库、队列心跳、容器内 MCP 工具发现、MCP 模型状态、MCP 调用实际模型、四服务重启后登录及数据库记录保留、重启后模型恢复。MCP 使用官方 SDK 通过 docker compose exec -T web python -m ai_service.mcp_server 测试容器内 stdio 与 ai 服务通信；未额外启动独立 mcp profile 容器。

Docker 使用独立 happyclass_app_data 与 happyclass_queue_data 卷，没有迁移或覆盖原本 18080 服务的数据库。创建的演示课程标记为 is_demo=1，异步测试记录 device_id 为 deployment-self-test，属于合成标签，不是模型精度样本。验收后四个服务保留运行，网址 http://127.0.0.1:18090/ ，可用本轮准备的 demo_admin 或 demo_teacher 演示账号登录；密码未写入仓库或验收报告。

因此上面的待办第 1 项已完成，接下来只需完成 GitHub 认证、上传分支与远程 tests/containers 两项 CI 运行记录。不能把本机容器通过写成 GitHub CI 已通过。
