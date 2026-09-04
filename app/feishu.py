"""
飞书消息发送与接收
- 发送：飞书互动卡片（情报推送、画像结果）
- 接收：用户 @机器人 发消息，触发画像查询
"""
import os
import json
from typing import Optional, List, Dict
import httpx
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
CHAT_ID = os.getenv("FEISHU_CHAT_ID", "")
WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")

_tenant_access_token = ""


def _get_tenant_access_token() -> str:
    """获取 tenant_access_token（带简易缓存）"""
    global _tenant_access_token
    if _tenant_access_token:
        return _tenant_access_token

    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    with httpx.Client() as client:
        resp = client.post(
            url,
            json={"app_id": APP_ID, "app_secret": APP_SECRET},
        )
        data = resp.json()
        _tenant_access_token = data.get("tenant_access_token", "")
        return _tenant_access_token


def send_webhook_message(title: str, content: str) -> bool:
    """
    通过 webhook 发简单文本消息（最简单的测试方式）
    """
    if not WEBHOOK_URL:
        print("[Feishu] 未配置 WEBHOOK_URL，跳过发送")
        return False

    body = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content,
                }
            ],
        },
    }

    try:
        with httpx.Client() as client:
            resp = client.post(WEBHOOK_URL, json=body, timeout=15)
            return resp.status_code == 200
    except Exception as e:
        print(f"[Feishu] webhook 发送失败: {e}")
        return False


def send_intelligence_card(items: List[Dict]) -> bool:
    """
    发送情报日报卡片（Top N）
    items: [{title, summary_zh, tags, importance, source_url, source_name}]
    """
    if not items:
        return False

    elements = []
    for i, item in enumerate(items, 1):
        stars = "⭐" * item.get("importance", 3)
        tags_str = " ".join(f"【{t}】" for t in item.get("tags", []))
        summary = item.get("summary_zh", "")
        source = item.get("source_name", "")
        url = item.get("source_url", "#")

        elements.append(
            {
                "tag": "markdown",
                "content": f"**{i}. {item.get('title', '')}**\n"
                f"{stars} {tags_str}\n"
                f"{summary}\n"
                f"[原文链接({source})]({url})",
            }
        )
        if i < len(items):
            elements.append({"tag": "hr"})

    # 底部提示
    elements.append({"tag": "hr"})
    elements.append(
        {
            "tag": "markdown",
            "content": "💡 **想了解某家机构？** @情报助手 + 公司名，即可生成客户画像",
        }
    )

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📰 收单&银行IT 情报日报（{len(items)}条）",
                },
                "template": "blue",
            },
            "elements": elements,
        },
    }

    if WEBHOOK_URL:
        try:
            with httpx.Client() as client:
                resp = client.post(WEBHOOK_URL, json=card, timeout=15)
                return resp.status_code == 200
        except Exception as e:
            print(f"[Feishu] 情报卡片发送失败: {e}")
            return False
    return False


def send_profile_card(profile: dict, chat_id: str = "") -> bool:
    """
    发送客户画像卡片
    """
    target_chat = chat_id or CHAT_ID
    if not target_chat and not WEBHOOK_URL:
        return False

    company_name = profile.get("company_name", "未知")
    company_type = profile.get("company_type", "")
    founded = profile.get("founded", "未知")
    hq = profile.get("headquarters", "未知")
    scale = profile.get("scale", "未知")
    core_biz = profile.get("core_business", "")
    acquiring = profile.get("acquiring_business", "")
    it_status = profile.get("it_status", "")
    recent_news = profile.get("recent_news", [])
    sources = profile.get("sources", [])

    news_text = "\n".join(f"• {n}" for n in recent_news) if recent_news else "暂无"
    sources_text = (
        "\n".join(f"[{i+1}] {s}" for i, s in enumerate(sources[:5]))
        if sources
        else "无"
    )

    content = f"""**🏢 {company_name}**
**类型**：{company_type}  |  **成立**：{founded}  |  **总部**：{hq}

**📊 规模**：{scale}

**💼 核心业务**：{core_biz}

**💳 收单业务**：{acquiring}

**🖥️ IT系统现状**：{it_status}

**📰 近期动态**：
{news_text}

**📎 信息来源**：
{sources_text}"""

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"🏢 客户画像：{company_name}"},
                "template": "turquoise",
            },
            "elements": [{"tag": "markdown", "content": content}],
        },
    }

    if WEBHOOK_URL and not chat_id:
        try:
            with httpx.Client() as client:
                resp = client.post(WEBHOOK_URL, json=card, timeout=15)
                return resp.status_code == 200
        except Exception as e:
            print(f"[Feishu] 画像卡片发送失败: {e}")
            return False
    elif target_chat:
        # 通过 API 发送到指定群
        token = _get_tenant_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        params = {"receive_id_type": "chat_id"}
        body = {
            "receive_id": target_chat,
            "msg_type": "interactive",
            "content": json.dumps(card["card"], ensure_ascii=False),
        }
        try:
            with httpx.Client() as client:
                resp = client.post(url, headers=headers, params=params, json=body, timeout=15)
                return resp.status_code == 200
        except Exception as e:
            print(f"[Feishu] 画像卡片API发送失败: {e}")
            return False
    return False


def reply_text(message_id: str, text: str) -> bool:
    """
    回复某条消息（用于接收用户查询后回执）
    """
    token = _get_tenant_access_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    try:
        with httpx.Client() as client:
            resp = client.post(url, headers=headers, json=body, timeout=15)
            return resp.status_code == 200
    except Exception as e:
        print(f"[Feishu] 回复失败: {e}")
        return False


def parse_command(text: str) -> dict:
    """
    解析用户消息，识别指令
    返回: {"command": "profile"|"today"|"intel"|"help"|"unknown", "company"/"query": "xxx"}
    """
    text = text.strip()

    # 去掉 @提及
    import re
    text = re.sub(r"<at[^>]*>[^<]*</at>", "", text).strip()

    if not text:
        return {"command": "help", "company": ""}

    # /profile 公司名
    m = re.match(r"^/profile\s+(.+)$", text, re.IGNORECASE)
    if m:
        return {"command": "profile", "company": m.group(1).strip()}

    # 今日情报：/today、/今日、今日情报
    if text.lower() in ("/today", "/今日") or text in ("今日情报", "今天情报", "今日高分情报"):
        return {"command": "today", "query": ""}

    # 关键词检索：/intel 关键词、/检索 关键词、检索 X、查一下 X
    m = re.match(r"^/(?:intel|检索|情报)\s+(.+)$", text, re.IGNORECASE)
    if m:
        return {"command": "intel", "query": m.group(1).strip()}
    m = re.match(r"^(?:检索|查一下|搜索)\s+(.+)$", text)
    if m:
        return {"command": "intel", "query": m.group(1).strip()}

    # /help（放在裸文本回退前，让「帮助」不带斜杠也生效）
    if text.lower() in ("/help", "/帮助", "帮助", "help"):
        return {"command": "help", "company": ""}

    # 打招呼不当作公司名查画像
    if text.lower() in ("hi", "hello", "你好", "在吗", "在"):
        return {"command": "help", "company": ""}

    # 直接发公司名（@机器人 + 公司名）
    # 排除以 / 开头的指令
    if not text.startswith("/"):
        return {"command": "profile", "company": text}

    return {"command": "unknown", "company": ""}


def build_intel_reply_card(items: List[Dict], title: str) -> dict:
    """
    构造情报查询结果卡片（供机器人 im API 回复用，非 webhook）
    items: intel_query 归一化记录 [{title, weight, link, section, subsection, summary, tags, source}]
    """
    elements = []
    for i, r in enumerate(items, 1):
        tags = " ".join(f"【{t}】" for t in r.get("tags", []))
        sec = f"{r.get('section', '')}/{r.get('subsection', '')}".strip("/")
        summary = (r.get("summary") or "")[:100]
        elements.append(
            {
                "tag": "markdown",
                "content": f"**{i}. [{r.get('weight', 0)}分] {r.get('title', '')}**\n"
                f"{sec} {tags}\n{summary}\n"
                f"[原文({r.get('source', '')})]({r.get('link', '#')})",
            }
        )
        if i < len(items):
            elements.append({"tag": "hr"})
    if not elements:
        elements = [{"tag": "markdown", "content": "没有匹配的情报 🤔 换个关键词试试？"}]
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
        "elements": elements,
    }


def get_help_text() -> str:
    """帮助信息"""
    return """🤖 **情报助手使用指南**

**情报查询**：
  • /today 或「今日情报」— 今日高分情报 Top5
  • /intel 关键词 或「检索 SCB」— 全库检索
  • 例如：/intel 虚拟银行

**查询客户画像**：
  • @情报助手 + 公司名
  • 例如：@情报助手 星展银行
  • 或直接发：/profile 招商银行

**其他指令**：
  • /help — 显示帮助信息

每天早上 8:00 自动推送收单&银行IT情报日报 ✉️"""
