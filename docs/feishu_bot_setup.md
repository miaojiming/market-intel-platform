# 飞书机器人配置指南

## 前置条件
- 已部署 FastAPI 服务，有公网 URL（如 `https://your-app.example.com`）
- 有飞书开发者后台权限

## 步骤 1：创建飞书企业自建应用

1. 打开 https://open.feishu.cn/app
2. 点击 **"创建企业自建应用"**
3. 填写：
   - 应用名称：市场情报助手
   - 应用描述：收单&银行IT行业情报 + 客户画像查询
4. 点击 **"创建"**

## 步骤 2：获取凭证

在应用详情页 → **"凭证与基础信息"**：
- 复制 **App ID**（如 `cli_xxxxxxxxxx`）
- 复制 **App Secret**（如 `xxxxxxxxxxxxxxxxxxxx`）

配置到环境变量：
```
FEISHU_APP_ID=cli_xxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxx
```

## 步骤 3：添加权限

左侧菜单 → **"权限管理"** → 搜索并添加以下权限：

| 权限名称 | 权限码 | 用途 |
|---------|--------|------|
| 获取与发送单聊、群组消息 | `im:message` | 发消息/卡片 |
| 读取群消息 | `im:message.group_at_msg` | 接收群里@机器人的消息 |
| 获取群组信息 | `im:chat` | 获取群信息 |

添加后点 **"批量申请"**，提交审批（管理员审批后生效）。

## 步骤 4：配置事件订阅

左侧菜单 → **"事件与回调"** → **"事件配置"**

1. **请求网址（URL）** 填：
   ```
   https://your-app.example.com/feishu/webhook
   ```
   （替换成你的服务地址）

2. 页面会发送一个 `url_verification` 请求验证，我们的服务已自动处理

3. 点击 **"添加事件"**，搜索并添加：
   - **接收消息**（`im.message.receive_v1`）

4. 保存配置

## 步骤 5：创建版本并发布

左侧菜单 → **"版本管理与发布"** → **"创建版本"**

- 版本号：1.0.0
- 更新说明：初始版本
- 可用性：全员可用 / 指定群组

提交发布，等待管理员审批。

## 步骤 6：把机器人拉进群

1. 在飞书里打开目标群
2. 群设置 → 群机器人 → 添加机器人
3. 搜索"市场情报助手"添加

## 使用方式

在群里 @机器人 + 公司名：

```
@情报助手 星展银行
```

或者直接发指令：

```
/profile 招商银行
```

几秒后会收到客户画像卡片。

## 环境变量清单

| 变量 | 必填 | 说明 |
|------|------|------|
| `FEISHU_APP_ID` | ✅ | 飞书应用 App ID |
| `FEISHU_APP_SECRET` | ✅ | 飞书应用 App Secret |
| `FEISHU_WEBHOOK_URL` | ❌ | 群机器人 Webhook（用于每日情报推送，可选） |
| `FEISHU_VERIFICATION_TOKEN` | ❌ | 事件验证 token（可选，增强安全性） |
| `LLM_API_KEY` | ✅ | LLM Gateway API Key |
| `LLM_BASE_URL` | ✅ | `https://llm-gw.agenzo.com/v1` |
| `LLM_MODEL` | ✅ | `kiro/claude-opus-5` |
