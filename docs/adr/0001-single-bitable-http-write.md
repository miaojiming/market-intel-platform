# 情报存储采用单一多维表格，写入走开放平台 HTTP API

hackathon 泰国市场情报平台的每日采集结果需要结构化存储并支撑看板。生产写入方是 GitHub Actions 里跑的 agent（自定义应用身份），运行环境没有 lark-cli，只能用 tenant_access_token 走 HTTP 调飞书开放平台 API。

**决定**：全部情报追加进一份多维表格（`IjRjbhMNZaCR3YsvenrcIyk2nXg` 的情报主表 `tblHfzfRCBqjAfVD`），不按天分表。时间语义用三个字段区分：`采集时间`（业务时间，管道写入）、`创建时间`/`更新时间`（created_at/updated_at 系统字段，平台自动维护）。写入统一走 bitable v1 HTTP API：`POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records`，`Authorization: Bearer <tenant_access_token>`，去重键 = 原文链接。

**为什么不是每日一份**：看板图表需要跨天连续数据，日表意味着每个图表每天重挂数据源；按链接去重要求单一键空间，分表后跨表查重要么放弃要么额外维护索引；应用权限与 token 只想维护一份。

**后果**：自定义应用必须开通 bitable 相关 scope 并被加为该 Base 的协作者，否则定时任务写入会 403；表会持续增长，hackathon 阶段不做归档。本地调试用的 lark-cli（base/v3 接口）与生产管道（bitable/v1 接口）是同一份数据的两条写入路径，字段 schema 是唯一契约。
