# 部署指南

## 快速部署选项

| 方案 | 难度 | 费用 | 适合 |
|------|------|------|------|
| **Railway** | ⭐ 简单 | 免费额度 / $5/月起 | MVP 快速验证 |
| **Fly.io** | ⭐ 简单 | 免费额度 / $2/月起 | 全球节点多 |
| **阿里云函数计算** | ⭐⭐ 中等 | 几乎免费（首年） | 国内访问快 |
| **自建服务器** | ⭐⭐⭐ 复杂 | ¥50/月起 | 完全可控 |

推荐 **Railway**，一键部署，有免费额度，最快上线。

---

## 方案一：Railway 一键部署（推荐）

### 1. 准备
- 注册 Railway 账号：https://railway.app
- 关联你的 GitHub 仓库

### 2. 部署
1. Railway 控制台 → **"New Project"** → **"Deploy from GitHub repo"**
2. 选择 `market-intel-platform` 仓库
3. 选择 `main` 分支
4. 点击 **"Deploy now"**

### 3. 配置环境变量
部署完成后，在项目 → **Variables** 中添加：

```
LLM_API_KEY=llmgtwy_xxxxxxxxxxxxxxxx
LLM_BASE_URL=https://llm-gw.agenzo.com/v1
LLM_MODEL=kiro/claude-opus-5
LLM_JUDGE_MODEL=kiro/claude-opus-5
FEISHU_APP_ID=cli_xxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxx
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
PORT=8000
```

### 4. 获取公网 URL
部署成功后，Railway 会自动分配一个域名，形如：
```
https://your-project-name.up.railway.app
```

用这个 URL 配置飞书事件订阅的回调地址：
```
https://your-project-name.up.railway.app/feishu/webhook
```

### 5. 验证
访问健康检查：
```
https://your-project-name.up.railway.app/health
```

应该返回 `{"status": "ok", ...}`

---

## 方案二：Docker 部署

### 1. 构建镜像
```bash
docker build -t market-intel .
```

### 2. 运行
```bash
docker run -d \
  --name market-intel \
  -p 8000:8000 \
  -e LLM_API_KEY=your-key \
  -e LLM_BASE_URL=https://llm-gw.agenzo.com/v1 \
  -e LLM_MODEL=kiro/claude-opus-5 \
  -e FEISHU_APP_ID=cli_xxx \
  -e FEISHU_APP_SECRET=xxx \
  market-intel
```

---

## 验证飞书机器人

部署成功并配置好飞书机器人后，按以下步骤验证：

1. **URL 验证**：飞书后台配置事件订阅 URL 时，应该自动验证通过
2. **健康检查**：访问 `/health` 接口确认服务正常
3. **消息测试**：
   - 在飞书群里 @机器人 发送"测试"
   - 应该收到"🔍 正在查询..."的回执
   - 几秒后收到画像卡片
4. **帮助指令**：发送 `/help` 应该收到使用指南
5. **情报日报**：手动调用 `/api/intelligence/run` 触发一次

---

## 监控与维护

### 日志查看
- Railway：项目 → Deployments → 查看日志
- Docker：`docker logs market-intel -f`

### 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 飞书收不到回复 | App ID/Secret 错误 | 检查环境变量 |
| 画像生成失败 | LLM API Key 错误 | 检查 LLM_API_KEY |
| 504 超时 | 画像生成时间太长 | 正常，后台线程处理，飞书会收到回复 |
| 重复回复 | 飞书事件重试 | 代码已用 event_id 去重 |

---

## 成本估算

| 项目 | 月费用 |
|------|--------|
| Railway 部署（Hobby 档） | $5（约 ¥35） |
| Claude Opus 5 API（每日 20 条情报 + 10 次画像） | $10-30（约 ¥70-210） |
| 飞书机器人 | 免费 |
| **合计** | **约 ¥100-250/月** |
