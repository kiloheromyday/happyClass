# Lccccc679 的工作记录

我先做了指导书 2.3 的选做功能，后来加了情绪回放、教学洞察和反馈处理中心。开发时用了 AI 辅助编程。

| PR | 我加的部分 | 在哪里试 |
| --- | --- | --- |
| [#1](https://github.com/kiloheromyday/happyClass/pull/1) | 课堂匿名与聚合、AI 结果队列、MCP、Compose 和 CI | 从「反馈隐私」试匿名和聚合。队列、MCP 和启动命令见[选做扩展](OPTIONAL_EXTENSIONS.md) |
| [#2](https://github.com/kiloheromyday/happyClass/pull/2) | 回放数据、教学洞察、多课堂分析的后端 | 在 `/docs` 查接口。多课堂分析可以排队生成报告 |
| [#3](https://github.com/kiloheromyday/happyClass/pull/3) | 情绪回放和情绪洞察的页面 | 教师或管理员登录后，从左侧打开「情绪回放」或「情绪洞察」 |
| [#4](https://github.com/kiloheromyday/happyClass/pull/4) | 情绪反馈处理中心 | 学生提交原因，老师回应并发回访。同一节课的相似反馈可以放到一组处理 |

队列验收用过真实 Redis，检查了后台中途退出后还能接着处理，以及同一批结果不会存两遍。Compose 在本机运行过网页、Redis、后台进程和 AI 服务。[本机验收记录](EXTENSIONS_ACCEPTANCE_20261109.md)

反馈中心用学生和教师账号在浏览器里走过完整流程，也试过两位学生各自收到批量回应。PR #4 合入后，`main` 的自动测试和容器检查都通过了。[主分支 CI](https://github.com/kiloheromyday/happyClass/actions/runs/43003503852)
