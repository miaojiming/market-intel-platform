# Push API（Railway 部署）

仪表盘「立即推送」功能的后端代理服务。

## 功能

- `POST /api/push-now` — 从飞书多维表格读取高价值情报，推送到飞书群
- `GET /api/health` — 健康检查
- `GET /` — API 信息

## 本地运行

```bash
cd push_api
pip install -r requirements.txt
export FEISHU_APP_ID=xxx
export FEISHU_APP_SECRET=xxx
export BITABLE_APP_TOKEN=xxx
export BITABLE_TABLE_ID=xxx
export FEISHU_WEBHOOK_URL=xxx
export PUSH_API_KEY=your-secret-key  # 可选，用于 API 鉴权
uvicorn main:app --reload --port 8000
```

测试：
```bash
curl -X POST http://localhost:8000/api/push-now \
  -H "X-API-Key: your-secret-key"
```

## Railway 部署

### 方式一：连接 GitHub 自动部署（推荐）

1. 在 Railway 控制台点击 **New Project** → **Deploy from GitHub repo**
2. 选择你的仓库
3. 配置环境变量（见下方）
4. 设置 Root Directory（或用 railway.json 自动识别）
5. 部署完成后，把生成的域名填到仪表盘的「设置」里

### 方式二：CLI 部署

```bash
npm i -g @railway/cli
railway login
railway init
railway up
```

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `FEISHU_APP_ID` | ✅ | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | ✅ | 飞书应用 App Secret |
| `BITABLE_APP_TOKEN` | ✅ | 多维表格 app token |
| `BITABLE_TABLE_ID` | ✅ | 多维表格 table id |
| `FEISHU_WEBHOOK_URL` | ✅ | 飞书群机器人 webhook 地址 |
| `PUSH_API_KEY` | ❌ | API 访问密钥，留空则不校验 |
| `PUSH_THRESHOLD` | ❌ | 推送权重分阈值，默认 5.0 |
| `PUSH_MAX` | ❌ | 最大推送条数，默认 10 |
| `PORT` | ❌ | 服务端口，Railway 自动注入 |

## 推送逻辑

1. 从多维表格读取最新情报（按采集时间倒序）
2. 本地计算权重分（0.4 × 泰国相关度 + 0.4 × 商机强度 + 0.2 × 时效性）
3. 筛选权重分 ≥ 阈值的情报，取 TOP N 推送
4. 如果没有达标情报，走兜底逻辑：泰国相关度 ≥ 5 的 TOP 5
5. 如果连兜底都没有，返回「没有符合条件的情报」

## 仪表盘对接

仪表盘右上角 ⚙️ 设置中填入：
- **Push API 地址**：`https://your-app.up.railway.app`
- **API Key**：和 `PUSH_API_KEY` 一致（如果配置了的话）

设置保存在浏览器 localStorage 中。
