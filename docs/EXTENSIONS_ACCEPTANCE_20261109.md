# 选做扩展验收

Lccccc679 在 2026 年 11 月 9 日用隔离数据做的本机验收。Docker 和 GitHub 检查是在后面补跑的。

| 功能 | 当时怎么测 |
| --- | --- |
| 匿名与聚合 | 走真实 HTTP 看明细、看板和 CSV，确认匿名模式隐藏账号，聚合模式只显示统计，学生还能看自己的历史。保存冲突和权限也测了 |
| 异步队列 | 用真实 Redis 和独立 worker 走接收、过滤和入库。试过重复提交、入库后还没确认就中断、连续失败三次，以及管理员重试 |
| MCP | 用 SDK 客户端连 stdio，查到两个工具和能力资源。状态工具连到了实际 AI 服务，分析工具处理了一张合成的无脸 JPEG，也试了拒绝 URL 输入 |
| Docker Compose | 本机构建并启动网页、Redis、worker、AI 四个服务。重启后能登录，SQLite 记录仍在，模型也重新就绪 |

## 本机记录

- 四项功能的定向测试 13 项通过。追加真实 Redis 恢复和失败重试的检查后，又单跑了 3 项，全部通过。
- 临时 SQLite 上的 HTTP、worker、MCP 共 17 个检查点通过。Redis 测试用了 14、15 号库，结果是合成标签。队列入库和筛选检查用 HAPPY 0.94、ANGRY 0.88 和 SAD 0.40，前两条入库，后一条被过滤。
- 隐私页面交互、PowerShell 脚本语法、Compose 配置和 actionlint 检查通过。试过默认端口 18090 和自定义端口 18123。
- Docker Desktop 4.98.0、Engine 29.9.2、Compose v5.6.1（Linux 容器）上共 12 项运行检查通过。MCP 在 web 容器内用 SDK 连 stdio，调用 ai 服务成功。这一轮没单独启动 MCP profile 的容器。

安装 Docker 前，本机曾没有可用的引擎。装好后发现了两个问题。登录检查只认 18080 和 15173，于是让 Compose 的允许来源跟随网页端口。只用内部网络时，宿主机也连不上页面，于是给 web 单独接了 `web_access` 网络，仍只把网页发布到本机回环地址。Redis、worker、AI 和 MCP 不占宿主机端口。

最早的 Redis 试验用的是 [redis-windows](https://github.com/redis-windows/redis-windows) 社区构建，只监听 127.0.0.1:16379，没有注册系统服务。Docker 里另测了 Linux Redis。Compose 配置检查和 actionlint 使用的是各自的 [Compose](https://github.com/docker/compose/releases/tag/v5.7.0) 与 [actionlint](https://github.com/rhysd/actionlint/releases/tag/v1.7.12) 发布版本。三个下载文件都核过 release 的校验值。

Docker 用自己的数据库和队列卷，18080 上的原库不参与测试。上面的图片和标签都是测试数据，没有拿来评估模型对真人表情的准确率。

## GitHub 上的结果

扩展合入后已经跑过[扩展分支检查](https://github.com/kiloheromyday/happyClass/actions/runs/42764849798)和[主分支检查](https://github.com/kiloheromyday/happyClass/actions/runs/43003503852)。主分支的测试和容器任务都通过。真实 Redis 和 ONNX 也在 CI 里运行了。
