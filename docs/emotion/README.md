# 情绪回放、洞察和多课堂分析

教师或管理员登录后，从左侧打开「情绪回放」或「情绪洞察」。在课堂反馈和实时看板里也能直接打开当前课堂的回放。

- **回放。** 拖时间轴看某段反馈，或用播放、倍速和跳转按钮看有记录的时段。可以只看手动反馈或 AI 记录。[回放接口](replay.md)
- **洞察。** 按课设置关注规则，标教学环节，记下什么时候调整了讲法，再看调整前后两段的反馈。可以导出 CSV。默认排除演示数据，要看示例时在「数据范围」选「仅演示数据」。[洞察接口](insights.md)
- **多课堂分析。** 在 `/docs` 选几节课，排队生成一份报告。报告可以做批注和导出。[实验室接口](lab.md)

统计按反馈条数算。手动反馈和 AI 分类分开看。调整前后的变化可以留作复盘。

| 位置 | 放了什么 |
| --- | --- |
| `backend/app/emotion/` | 回放、洞察、多课堂分析及反馈中心的接口和数据处理 |
| `frontend/src/emotion/` | 回放、洞察和反馈中心的页面 |
| `tests/emotion/` | 接口、权限、旧库升级和页面测试 |
| `scripts/emotion/` | 生成演示数据、容器验收 |

各接口的字段可以在 `/docs` 或 `/openapi.json` 查。沿用项目登录会话，写请求要带 `X-Requested-With: EmojiClassroom`。教师只能访问自己授课的课堂。多课堂分析方案和报告归创建账号，打开报告时还会检查当前课堂权限。

## 启动和测试

Compose 已经打开多课堂分析的后台进程。如果直接用 Python 启动，要先设变量。没打开时，任务会在队列里等。

```powershell
$env:EMOJI_LAB_WORKER='1'
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
python -m pytest -q tests/emotion
```

演示数据需要手动生成。先创建自己的教师账号，下面假设用户名是 `demo_teacher`。

```powershell
docker compose exec web python scripts/emotion/seed_insights_demo.py --teacher demo_teacher --confirm-demo-data
docker compose exec web python scripts/emotion/seed_lab_demo.py --teacher demo_teacher --confirm-demo-data
```

`smoke_runtime.py` 会创建测试账号和数据，只在可以清理的测试库里跑。CI 会用临时容器执行。
