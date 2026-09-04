# AWS 常驻部署交接单（交互机器人）

每日情报管道跑在 GitHub Actions（cron 08:00 CST），**无需部署**；
本单只针对交互机器人（影分身一号长连接），它需要一台 7×24 在线的常驻主机。

## 镜像与启动
- 仓库根目录已有 `Dockerfile`（python:3.11-slim, uvicorn app.main:app, 端口 8000）
- 启动命令：`docker run -d --restart=always --env-file .env -p 8000:8000 <image>`
- 健康检查：`GET /` 返回 200 即服务存活；日志出现「长连接已启动」即机器人在线

## 环境变量（.env 全集）
| 变量 | 说明 |
|---|---|
| LLM_API_KEY | Agenzo 网关密钥（与 GH secrets 同值） |
| LLM_BASE_URL | https://llm-gw.agenzo.com/v1 |
| LLM_MODEL | kiro/claude-opus-5（摘要） |
| LLM_SCORING_MODEL | kiro/gpt-5.6-sol（打分） |
| FEISHU_APP_ID / FEISHU_APP_SECRET | 自建应用「市场情报助手」凭据 |
| BITABLE_APP_TOKEN / BITABLE_TABLE_ID | 情报库定位（代码有默认值，可不配） |

注意：**不要**设置 ENABLE_LOCAL_SCHEDULER（保持为空可防止与 GH Actions 双份推送）。

## 出网白名单（仅 outbound，无入站要求）
- `open.feishu.cn`、`msg-frontier.feishu.cn`（飞书 API + 长连接 WebSocket）
- `llm-gw.agenzo.com`（LLM 网关）
- `news.google.com`（Google News 采集）

## 前置条件（已就绪，勿重复操作）
- 应用已开通 `bitable:app` 权限并发布版本
- 应用已被加为多维表格协作者（可编辑）
- 可用范围已包含使用者（审批 202609030063 已通过）
