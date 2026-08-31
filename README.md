# 市场智能情报与获客平台（MVP）

AI 驱动的收单 & 银行 IT 行业情报与客户画像平台。

## 功能模块

### 1. 行业情报日报

* 自动抓取 Finextra、The Paypers 等行业媒体最新文章

* AI 中文摘要 + 重要性评分 + 标签分类

* 每天早上 8:00 推送到飞书群

* Top 5 高价值情报精选

### 2. 客户画像

* 飞书 @机器人 + 公司名，自动生成画像卡片

* 画像字段：公司类型、成立时间、规模、核心业务、收单业务、IT系统现状、近期动态、信息来源

* 全部基于公开互联网信息

### 3. AI 工程化验证

* 基于 harness-evals 的 AI Evals 质量门禁

* 评测指标：格式合规、忠实度、综合质量

* 支持基线对比和回归检测

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 API Key 和飞书配置
```

### 3. 启动服务

```bash
python -m app.main
```

服务默认运行在 `http://localhost:8000`

### 4. 测试接口

```bash
# 健康检查
curl http://localhost:8000/health

# 手动触发情报日报
curl -X POST http://localhost:8000/api/intelligence/run?hours=48&top_n=5

# 手动生成画像
curl "http://localhost:8000/api/profile?company=Adyen"
```

### 5. 飞书配置

1. 在飞书开放平台创建自建应用
2. 添加"机器人"能力
3. 配置事件订阅：

   * 请求地址：`https://your-domain/feishu/webhook`

   * 订阅事件：`im.message.receive_v1`（接收消息）
4. 配置 Webhook 群机器人（用于情报推送）
5. 在 `.env` 中填入相关配置

### 6. 运行 AI 评测

```bash
cd eval

# 跑一次评测
harness-evals run intelligence.eval.yaml

# 存为基线
harness-evals run intelligence.eval.yaml --save-baseline

# 和基线对比（检查回归）
harness-evals run intelligence.eval.yaml --baseline

# 门禁：低于 0.8 失败
harness-evals run intelligence.eval.yaml --fail-under 0.8
```

## 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── main.py           # 主入口 + API + 定时任务
│   ├── llm.py            # LLM 调用封装
│   ├── feishu.py         # 飞书消息发送/接收
│   ├── intelligence.py   # 行业情报采集 + 摘要
│   ├── profile.py        # 客户画像生成
│   └── prompts.py        # Prompt 模板
├── eval/
│   ├── goldens.jsonl     # 评测数据集（13 条）
│   ├── intelligence.eval.yaml  # 评测配置
│   └── prompts/
│       └── summarize.txt # 评测用 Prompt
├── requirements.txt
├── .env.example
└── README.md
```

## 信息源

当前配置的 RSS 源：

* Finextra Headlines

* The Paypers News

可在 `app/intelligence.py` 的 `RSS_SOURCES` 中添加更多源。

## 技术栈

* **后端**：FastAPI + Python

* **LLM**：OpenAI GPT-4o-mini（可替换）

* **消息推送**：飞书机器人

* **定时任务**：APScheduler

* **AI 评测**：harness-evals（开源版）

* **数据采集**：feedparser + BeautifulSoup + DuckDuckGo HTML 搜索

## 后续扩展

* [ ] 增加更多信息源（监管网站、中文行业媒体）

* [ ] 招标信息监控模块

* [ ] 峰会商机挖掘模块

* [ ] 知识图谱（实体归一化、公司关系）

* [ ] Harness AI Configs（Prompt 灰度发布）

* [ ] Harness AgentTrace（Agent 链路追踪）

* [ ] 在线评测 + 反馈闭环

