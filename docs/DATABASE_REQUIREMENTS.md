# 参考文档中的数据库要求与本项目对应

核对依据为用户提供的《表情符号课堂情绪检查器系统》实验指导书。参考文档用于确定课程项目范围，用户已说明不要求完全一致；这里区分原文的要求、建议与本项目选择，不把建议自动升级为强制要求。

## 数据库产品与架构

第三部分“总体架构要求”的架构图使用“关系型数据库”。同部分 3.2 的标题是“技术栈建议”，表格的数据库一项为“PostgreSQL / MySQL”。文档没有另外写“必须使用 PostgreSQL”或“只能使用 MySQL”。

因此，本项目选择 SQLite 满足关系型数据存储和持久化方式，但与文档推荐产品有差异。当前无需仅因该建议就强制迁移。如果授课教师另有通知或评分细则指定数据库产品，应以该实际课程要求补充适配；本项目尚未声称兼容 PostgreSQL/MySQL。

文档要求 Repository 访问数据库、Service 实现业务逻辑，且后端提供 REST API 与数据持久化。本项目已采用 Controller → Service → Repository，启用 SQLite 外键校验，使用事务、参数化查询与索引，保存到 data/classroom.db。

## 核心实体与字段

第四部分写明“至少设计以下核心实体，允许合理扩展”。User、Course、ClassSession、ScheduleUser、EmojiRecord 为核心业务实体，AuditLog 标注为“建议”。

| 文档实体 | 主要字段 | 项目表 |
| --- | --- | --- |
| User | ID、用户名、密码哈希、角色、邮箱、状态、创建时间 | users |
| Course | ID、名称、教师 ID | courses |
| ClassSession | ID、课程 ID、开始结束、教室、班级 | class_sessions |
| ScheduleUser | ID、课堂 ID、用户 ID、安排时间 | schedule_users |
| EmojiRecord | ID、用户或匿名、课堂、类型、时间、来源、置信度、设备标记 | emoji_records |
| AuditLog 建议项 | 登录、导出等关键操作 | audit_logs |

本项目另设会话、限流及人工请求、网页帧、AI 批次幂等辅助表，不替代上述实体。可执行字段和约束以 database/schema.sql 为准。

## 数据约束与提交材料

原文约束包括密码加盐哈希且禁止明文、后端角色权限校验、emoji 枚举约束、AI 必须有置信度、CSV 注入防护、默认不保存原始视频和人脸图像。AI 匿名记录允许用户字段为空。项目已在数据库约束与业务层实现这些规则；权限与导出规则不能仅靠数据库产品名称满足。

提交材料要求数据库设计、ER 图和数据库脚本。项目已提供 docs/DESIGN.md 的 ER 图和关系说明、database/schema.sql 初始化脚本以及 docs/DEPLOYMENT.md 的数据位置与备份说明。

文档未额外指定数据库版本、字符集、分库分表、存储过程、主从复制或必须采用特定 ORM。当前也没有这些实现声明。Docker Compose 位于选做扩展，同时出现在建议部署和进度安排中；不能据此认定 PostgreSQL/MySQL 是不可替换的数据库产品要求。
