# 泰国支付市场情报平台

AI 驱动的泰国支付/收单市场情报平台：每日自动采集 → 独立模型权重打分 → 多维表格存储与看板 → 飞书定时推送 + 对话式机器人查询。公司 Hackathon 项目。

## 系统全链路

```
每天 08:00 (GitHub Actions)
  7 渠道采集（Google News RSS ×11 组查询式 + Bangkok Post/FintechNews SG/Finextra/Techsauce 固定源）
  → Google News 中转链接解码还原原文 URL（batchexecute 协议）
  → 摘要模型 kiro/claude-opus-5（中文摘要 + 翻译，含真实性红线）
  → 打分模型 kiro/gpt-5.6-sol 独立二次调用
     三维打分: 泰国相关度/商机强度/时效性 (0-10) + 板块分类 + 标签
  → 权重分 = 0.4×相关度 + 0.4×商机 + 0.2×时效（多维表格公式列实时计算）
  → 写入飞书多维表格（按原文链接全量去重）
  → 权重分 ≥6 的 TOP10 推送飞书群（三维分版式卡片，推送后状态自动流转「已推送」）
```

**对话机器人**（自建应用长连接，本地/常驻服务器运行）：
- 命令：`/today`（今日高分情报）、`/intel <关键词>`（全库检索）、`/profile <公司>`（客户画像）、`/help`
- 自然语言：说「最近有什么高价值的情报？」「查一下虚拟银行相关的发我」——LLM 意图路由自动分发

## 数据与质量门禁（数据飞轮）

- **多维表格**「泰国支付市场情报库」：情报主表 20 字段（打分五件套 + 系统时间 + 采集日期公式列）、看板「情报总览」8 组件（板块分布/每日采集量/权重分 Top 来源等）、渠道清单 83 条（18 条 v1 在产 + 65 条 v2 候选，含可爬性实爬验证）
- **金标准**：摘要 13 条 + 打分 20 条（人工裁决校准，见 `docs/金标准抽检清单.md`）
- **eval-gate CI**：改 prompt/金标准/评分代码自动触发双评估——摘要质量（格式/忠实度/GEval + 基线回归）与打分金标准（分维 MAE + 板块准确率 + 时效窗口分桶），任一回归阻断合并
- 决策记录：`docs/adr/0001`（单一多维表格 + bitable v1 HTTP 写入）、领域术语表 `CONTEXT.md`

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env   # 填 LLM_API_KEY、FEISHU_APP_ID/SECRET 等

# 情报管道（全链路）
python scripts/daily_pipeline.py --dry-run   # 不写表不推送，本地联调
python scripts/daily_pipeline.py --no-push   # 写表但不推送

# 交互机器人（长连接，需常驻）
python -m uvicorn app.main:app --port 8000

# 打分金标准评估
python eval/scoring_eval.py

# 摘要质量评估 + 基线对比
python scripts/eval_pipeline.py
```

飞书应用前置：开通 `bitable:app` 权限并发布版本；应用加为多维表格协作者（详见 `docs/deployment-aws.md` 交接单）。

## 项目结构

```
app/
├── channels.py        # 7 渠道配置（11 组 Google News 查询式 + 5 固定源）
├── gnews.py           # Google News 链接解码（签名+batchexecute RPC）
├── intelligence.py    # 采集调度 + 正文抓取 + 摘要
├── scoring.py         # 独立打分模型（prompt 单一真相在 eval/prompts/scoring.txt）
├── bitable.py         # 多维表格 v1 HTTP 写入客户端（token/格式转换/去重/状态流转）
├── intel_query.py     # 机器人查询（/today /intel 背后的读表）
├── feishu.py          # 卡片构造 + 命令解析 + LLM 意图路由
├── feishu_ws.py       # 长连接机器人（消息分发）
├── llm.py / prompts.py / profile.py / main.py
scripts/
├── daily_pipeline.py  # 每日管道编排（GH Actions 入口）
└── eval_pipeline.py   # 摘要评估 + 基线
eval/
├── goldens.jsonl / scoring_goldens.jsonl   # 双金标准
├── run_eval.py / scoring_eval.py           # 双评估器
└── prompts/            # Prompt 单一真相
.github/workflows/
├── daily-intelligence.yml   # 每日 08:00 全链路
├── eval-gate.yml             # prompt/金标准变更门禁
└── monitor.yml               # 每 6h LLM 连通性监控
```

## 技术栈

FastAPI · feedparser/BeautifulSoup · Agenzo LLM 网关（kiro/claude-opus-5 + kiro/gpt-5.6-sol）· 飞书开放平台（bitable v1 / im 长连接）· GitHub Actions

## 部署形态

- **每日管道**：GitHub Actions cron（免运维，密钥在 repo secrets）
- **交互机器人**：任意常驻进程/Docker（`docs/deployment-aws.md`）

## 后续扩展

- [ ] v2 渠道接入：65 个已验证黄金源（BOT 官网、律所解读、NITMX/PromptPay 等，见渠道清单 `[v2候选]`）
- [ ] e-GP 政府采购 API（招标板块官方源，待 API key）
- [ ] 知识图谱（实体归一化、公司关系）
