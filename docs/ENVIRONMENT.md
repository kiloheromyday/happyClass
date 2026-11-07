# 环境检查与第一阶段验证基线

以下保留第一阶段的检查记录。最新功能与测试结果见 REQUIREMENTS.md、TEST_REPORT.md 和 PHASE6.md；文末“尚未完成”描述的是第一阶段结束时的状态，不是当前功能清单。

检查日期：2026 年 11 月 2 日。结论：本机可以进行浏览器客户端、后端和本地数据库开发；第一阶段已实际构建与启动。完整 AI 摄像头推理仍需后续模型和设备验证。

## 本机环境

| 项目 | 检查结果 | 影响 |
| --- | --- | --- |
| Python | 3.13.12 | 已建立项目独立虚拟环境 |
| Node.js / npm | 24.14.0 / 11.9.0 | Vue/Vite 前端已成功构建 |
| Git | 2.53.0.windows.2 | 可用于后续版本管理；当前未创建仓库提交 |
| Java | Temurin 21.0.11 | 已安装，本方案不依赖 Java |
| SQLite | Python 标准库提供 | 六张核心表已初始化，持久化验证通过 |
| PostgreSQL / MySQL | 未发现命令行工具或可直接使用的服务 | 当前使用 SQLite，最终数据库可在业务阶段前调整 |
| Docker | 客户端 29.2.0，Linux 引擎连接失败 | 暂不能直接运行 Docker Compose；本机启动不依赖它 |
| NVIDIA GPU | GeForce RTX 5060 Laptop GPU，8151 MiB | 系统 PyTorch 检测 CUDA 可用；尚未验证具体情绪模型 |
| 系统图像与深度学习库 | OpenCV 4.13.0；PyTorch 2.10.0+cu128 | 仅系统 Python 已有；未复制进项目虚拟环境 |
| DeepFace / FER / TensorFlow | 系统环境未安装 | 本次不安装，优先评估轻量 ONNX 方案 |
| 摄像头 | 未完成设备与授权实测 | AI 阶段需实际读取视频帧再确认 |
| C 盘空间 | 初检约 7.8 GiB 可用 | 足以完成当前基础搭建；后续大型模型或容器镜像下载前需复查空间 |
| 内存与 CPU 详细信息 | 本次系统查询访问受限 | 不据此判断已满足特定大型模型的要求 |

## 已完成的实际检查

- `npm run build` 成功；构建工具 Vite 7.3.7，前端依赖由 `package-lock.json` 锁定。
- Python 依赖装入 `.venv`，未启用系统 site-packages；`pip check` 返回无依赖冲突。
- `python -m pytest -q`：5 项通过。覆盖数据库持久化、故障状态、外键/情绪枚举/AI 置信度约束、未知接口 404，以及 AI 未配置模型的准确状态。
- 实际启动后端，`GET /api/health` 返回 HTTP 200，API 和数据库均为 ready。
- 实际访问网页根路径返回 HTTP 200；`/openapi.json` 可访问，并包含健康检查接口。
- 独立启动 AI 服务，`GET /health` 返回 service=ready、inference=not_configured、model_loaded=false。
- 自动浏览器工具初始化失败，因此本次未完成浏览器截图与交互核验；网页构建和 HTTP 连通性已验证。

测试依赖目前有一条 Starlette 关于 httpx 的弃用提示，不影响测试结果；后续升级测试客户端时处理。

## 安装问题与处理

本次受限 Windows 执行会话中，Python 的 ensurepip/pip 创建临时目录后发生写入拒绝。已使用官方 uv Windows 工具将依赖安装到项目独立虚拟环境，随后补齐 pip 并通过依赖检查；没有切换成系统共享依赖环境。uv 工具和缓存留在工作区的 `work` 目录，不是项目运行依赖。

Python 精确依赖版本记录在 `requirements-lock.txt`。项目支持标准 pip 安装，也在 `scripts/setup.ps1` 中提供 `-UvPath` 参数供同类环境使用。

## 当前可访问地址

- 网页：http://127.0.0.1:18080/
- 后端接口文档：http://127.0.0.1:18080/docs
- AI 服务状态：http://127.0.0.1:18081/health

地址只绑定本机。后台进程关闭或电脑重启后，按 README 的脚本重新启动即可。

## 尚未完成

业务功能、用户认证与授权、AI 模型下载与推理、摄像头采集、正式数据库部署及完整端到端测试。第一阶段完成不代表整个大作业已经完成。
