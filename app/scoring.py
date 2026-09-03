"""
独立打分模型（ADR 共识：打分与摘要模型分离）
- 摘要模型（LLM_MODEL, kiro/claude-opus-5）负责中文摘要 + 翻译
- 打分模型（LLM_SCORING_MODEL, kiro/gpt-5.6-sol）独立第二遍调用，负责：
  三维权重打分（泰国相关度/商机强度/时效性 0-10）+ 板块/二级菜单分类 + 标签
prompt 已在 76 条存量情报上验证（2026-09-03，76/76 成功）。
"""
import os
from datetime import datetime
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

SCORE_SYSTEM_PROMPT = f"""你是支付行业情报打分器。对一条情报完成分类与三维打分(0-10整数)。

分类:
- section 板块，二选一: {", ".join(SECTIONS)}
- subsection 二级菜单，八选一: {", ".join(SUBSECTIONS)}

打分维度:
- thailand_relevance 泰国相关度:与泰国支付/收单市场的相关程度。仅泛东南亚或全球=1-4;提及泰国但非主角=5-7;泰国为核心主题=8-10
- opportunity_strength 商机强度:对收单/卡支付/银行IT服务商的销售线索价值。招标公告/费率变动/核心系统更换/大客户进泰国=8-10;产品发布/重要合作/影响市场的监管变化=4-7;一般行业动态/会议花絮/背景分析=1-3
- timeliness 时效性:价值窗口。进行中的招标/即将召开的会议/新发布政策=8-10;近期动态=4-7;历史背景/多年前事件/已结束=1-3

再从这些标签里选0-3个最贴切的: {", ".join(TAG_OPTIONS)}

只输出JSON,不要多余文本:
{{"section":"...","subsection":"...","thailand_relevance":n,"opportunity_strength":n,"timeliness":n,"reason":"一句话中文理由不超过40字","tags":["..."]}}"""


def score_intel(item: Dict) -> Dict:
    """
    对单条情报独立打分。
    输入 item 需含: title, summary_zh(或空), source_name, published
    返回: {section, subsection, thailand_relevance, opportunity_strength,
           timeliness, score_reason, tags_v1}
    """
    user_prompt = (
        f"标题: {item.get('title', '')}\n"
        f"来源: {item.get('source_name', '')} 发布: {item.get('published') or '未知'}\n"
        f"摘要: {item.get('summary_zh') or item.get('summary_rss') or '（无摘要,仅标题）'}"
    )
    try:
        result = chat_json(
            user_prompt,
            system_prompt=SCORE_SYSTEM_PROMPT,
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
