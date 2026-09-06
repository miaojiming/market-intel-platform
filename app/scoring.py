"""
独立打分模型（ADR 共识：打分与摘要模型分离）
- 摘要模型（LLM_MODEL, kiro/claude-opus-5）负责中文摘要 + 翻译
- 打分模型（LLM_SCORING_MODEL, kiro/gpt-5.6-sol）独立第二遍调用，负责：
  三维权重打分（泰国相关度/商机强度/时效性 0-10）+ 板块/二级菜单分类 + 标签

Prompt 单一真相在 eval/prompts/scoring.txt（eval-gate CI 对其变更做金标准回归），
本模块运行时读取该文件，读不到时用内置副本兜底（保持部署健壮性）。
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

from app.llm import chat_json

SCORING_MODEL = os.getenv("LLM_SCORING_MODEL", "kiro/gpt-5.6-sol")

SECTIONS = ["行业新闻", "招标机会"]
SUBSECTIONS = [
    "行业会议", "行业新闻", "技术趋势动态", "政策与监管新闻",
    "政府/银行招标公告", "数字化转型规划", "合约到期与更换窗口预测", "在网系统现状摸底",
]
# 多维表格「标签」多选的全部合法选项（写入前过滤，防 ConvFail）
TAG_OPTIONS = [
    "收单费率", "招标公告", "核心系统", "监管政策", "数字钱包", "跨境支付",
    "稳定币", "会议展会", "银行动态", "投融资", "反洗钱", "AI应用",
]

_FALLBACK_PROMPT = """你是支付行业情报打分器。对一条情报完成分类与三维打分(0-10整数)。

当前日期: {today}  （判断时效性时以此为基准，越近越高）

业务聚焦点：收单 SaaS（Adyen/Opn/2C2P/Worldpay 等以 SaaS 模式提供收单服务）与收单独立部署（泰国银行自建或采购收单系统）。

分类:
- section 板块，二选一: 行业新闻, 招标机会
- subsection 二级菜单，八选一: 行业会议, 行业新闻, 技术趋势动态, 政策与监管新闻, 政府/银行招标公告, 数字化转型规划, 合约到期与更换窗口预测, 在网系统现状摸底

打分维度:
- thailand_relevance 泰国相关度:与泰国收单/支付市场的相关程度。非泰国=0-3;提及泰国但主题非收单/支付=4-7;泰国收单/支付为核心主题=8-10
- opportunity_strength 商机强度:对收单独立部署服务商(SI)的销售线索价值。
  8-10分(直接项目): 银行收单系统正式招标RFP/核心系统更换含收单模块/合约到期启动选型/大客户收单系统部署
  5-7分(间接机会): 银行核心系统改造可能延伸收单/SaaS厂商进入泰国可能需本地集成/监管政策变化引发系统改造需求/RFI需求征询(非正式招标)
  2-4分(微弱信号): SaaS厂商获牌/产品发布/一般合作/框架性政策/试点概念验证
  1分(无价值): 非收单/纯背景分析/会议花絮/一般行业动态
- timeliness 时效性:基于当前日期({today})与发布日期的时间差。
  8-10分: 1个月内发布/进行中的招标/即将到期的投标截止
  5-7分: 1-3个月内发布/近期动态但非紧急
  1-4分: 3个月前发布/历史背景/多年前事件/已完成项目

分类消歧:
- 以新闻形式报道但实质是供应商选定/系统替换/采购窗口信号的(如'银行选定X厂商升级收单系统'),归 招标机会
- 与泰国无关的一般国际采购/融资/监管动态,归 行业新闻
- 非收单的泰国新闻(如电子烟打击、AI峰会),归 行业新闻且商机≤2
- SaaS厂商获牌/产品发布≠招标机会,归行业新闻且商机≤4
- 监管政策/框架/意见征询≠招标机会,归行业新闻的政策类
- RFI(需求征询)≠正式招标,归数字化转型规划且商机≤7

再从这些标签里选0-3个最贴切的: 收单费率, 招标公告, 核心系统, 监管政策, 数字钱包, 跨境支付, 稳定币, 会议展会, 银行动态, 投融资, 反洗钱, AI应用

只输出JSON,不要多余文本:
{"section":"...","subsection":"...","thailand_relevance":n,"opportunity_strength":n,"timeliness":n,"reason":"一句话中文理由不超过40字","tags":["..."]}"""


def _load_score_prompt_template() -> str:
    """优先读 eval/prompts/scoring.txt（单一真相），失败用内置兜底"""
    p = Path(__file__).resolve().parent.parent / "eval" / "prompts" / "scoring.txt"
    try:
        text = p.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    return _FALLBACK_PROMPT


_PROMPT_TEMPLATE = _load_score_prompt_template()


def get_score_system_prompt(today_str: str = None) -> str:
    """获取注入了当前日期的打分 system prompt"""
    if today_str is None:
        today_str = datetime.now().strftime("%Y-%m-%d")
    return _PROMPT_TEMPLATE.replace("{today}", today_str)


# 保留向后兼容：默认用当天日期
SCORE_SYSTEM_PROMPT = get_score_system_prompt()


def score_intel(item: Dict, today_str: str = None) -> Dict:
    """
    对单条情报独立打分。
    输入 item 需含: title, summary_zh(或空), source_name, published
    可选 today_str: 覆盖当前日期(YYYY-MM-DD)，用于评测或调试
    返回: {section, subsection, thailand_relevance, opportunity_strength,
           timeliness, score_reason, tags_v1}
    """
    if today_str is None:
        today_str = datetime.now().strftime("%Y-%m-%d")
    system_prompt = get_score_system_prompt(today_str)

    user_prompt = (
        f"标题: {item.get('title', '')}\n"
        f"来源: {item.get('source_name', '')} 发布: {item.get('published') or '未知'}\n"
        f"摘要: {item.get('summary_zh') or item.get('summary_rss') or '（无摘要,仅标题）'}"
    )
    try:
        result = chat_json(
            user_prompt,
            system_prompt=system_prompt,
            model=SCORING_MODEL,
            temperature=0,
            max_tokens=300,
        )
        return _normalize(result)
    except Exception as e:
        print(f"[Scoring] 打分失败: {e}")
        return {}


def _normalize(r: Dict) -> Dict:
    """钳制取值范围并过滤非法选项，保证 v1 写入不被 ConvFail 拒绝"""
    def clamp(v):
        try:
            return max(0, min(10, int(v)))
        except (TypeError, ValueError):
            return None

    section = r.get("section") if r.get("section") in SECTIONS else None
    subsection = r.get("subsection") if r.get("subsection") in SUBSECTIONS else None
    tags = [t for t in (r.get("tags") or []) if t in TAG_OPTIONS][:3]
    out = {
        "thailand_relevance": clamp(r.get("thailand_relevance")),
        "opportunity_strength": clamp(r.get("opportunity_strength")),
        "timeliness": clamp(r.get("timeliness")),
        "score_reason": str(r.get("reason", ""))[:80],
        "tags_v1": tags,
    }
    if section:
        out["section"] = section
    if subsection:
        out["subsection"] = subsection
    return out


def parse_published(published: str):
    """把 ISO 日期串转 epoch 秒；失败返回 None"""
    if not published:
        return None
    try:
        return datetime.fromisoformat(published).timestamp()
    except ValueError:
        return None
