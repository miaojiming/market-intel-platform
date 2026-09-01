"""
飞书长连接模式客户端
- 使用 lark-oapi SDK 的 WebSocket 长连接接收消息
- 不需要公网域名，部署更简单
"""
import os
import json
import threading
import asyncio
from typing import Dict, Any
from dotenv import load_dotenv

# 在 import lark_oapi 之前，先给 asyncio.get_event_loop 打补丁
# 原因：lark_oapi.ws 模块级代码会调用 asyncio.get_event_loop()
# 如果此时已有运行中的事件循环（如 FastAPI/uvicorn），会拿到那个 loop
# 导致后续 client.start() 报 "This event loop is already running"
# 解决方案：在 import lark_oapi 前，让 get_event_loop 总是返回新 loop
_original_get_event_loop = asyncio.get_event_loop
_patched_loop = asyncio.new_event_loop()

def _patched_get_event_loop():
    return _patched_loop

asyncio.get_event_loop = _patched_get_event_loop

# 现在 import lark_oapi，ws 模块会拿到我们创建的新 loop
import lark_oapi as lark
from lark_oapi import ws
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    P2ImMessageReceiveV1Data,
    Message,
)

# 恢复原来的 get_event_loop
asyncio.get_event_loop = _original_get_event_loop

# 同时需要确保 ws 模块的 loop 变量是我们创建的那个
# 这样 client.start() 会用这个独立的 loop
import lark_oapi.ws.client as _ws_client
_ws_client.loop = _patched_loop

from app.profile import generate_profile
from app.feishu import (
    send_profile_card,
    parse_command,
    get_help_text,
    _get_tenant_access_token,
)

load_dotenv()

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")


def _reply_with_api(message_id: str, text: str) -> bool:
    """通过 API 回复消息（长连接模式下，用 token 调 API 回复）"""
    token = _get_tenant_access_token()
    if not token:
        print("[Feishu WS] 没有 tenant_access_token，无法回复")
        return False

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
        import httpx
        with httpx.Client() as client:
            resp = client.post(url, headers=headers, json=body, timeout=15)
            return resp.status_code == 200
    except Exception as e:
        print(f"[Feishu WS] 回复失败: {e}")
        return False


def _send_card_with_api(chat_id: str, profile: dict) -> bool:
    """通过 API 发送画像卡片到指定群"""
    token = _get_tenant_access_token()
    if not token:
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

    card_content = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🏢 客户画像：{company_name}"},
            "template": "turquoise",
        },
        "elements": [
            {"tag": "markdown", "content": content},
        ],
    }

    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    params = {"receive_id_type": "chat_id"}
    body = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card_content, ensure_ascii=False),
    }
    try:
        import httpx
        with httpx.Client() as client:
            resp = client.post(url, headers=headers, params=params, json=body, timeout=15)
            return resp.status_code == 200
    except Exception as e:
        print(f"[Feishu WS] 卡片发送失败: {e}")
        return False


def handle_message(event: P2ImMessageReceiveV1):
    """处理接收消息事件"""
    try:
        data: P2ImMessageReceiveV1Data = event.data
        message: Message = data.message

        message_id = message.message_id
        chat_id = message.chat_id
        msg_type = message.message_type

        # 只处理文本消息
        if msg_type != "text":
            return

        content_str = message.content
        try:
            content = json.loads(content_str)
        except Exception:
            content = {}

        text = content.get("text", "").strip()

        # 解析指令
        cmd = parse_command(text)

        # 后台线程处理（避免阻塞长连接）
        def _handle():
            try:
                if cmd["command"] == "help":
                    _reply_with_api(message_id, get_help_text())
                    return

                if cmd["command"] == "profile":
                    company = cmd["company"]
                    if not company:
                        _reply_with_api(
                            message_id, "请告诉我要查询的公司名称，例如：@情报助手 星展银行"
                        )
                        return

                    # 回复"正在生成"的提示
                    _reply_with_api(message_id, f"🔍 正在查询「{company}」的画像，请稍候...")

                    # 生成画像
                    profile = generate_profile(company)

                    # 发送画像卡片
                    _send_card_with_api(chat_id, profile)
                    return

                # 未知指令
                _reply_with_api(message_id, "我不太明白你的意思，发送 /help 查看使用方法")

            except Exception as e:
                print(f"[Feishu WS] 处理消息失败: {e}")
                _reply_with_api(message_id, "❌ 画像生成失败，请稍后重试")

        threading.Thread(target=_handle, daemon=True).start()

    except Exception as e:
        print(f"[Feishu WS] 事件处理异常: {e}")


def start_ws_client():
    """启动长连接客户端（在独立线程中运行专用事件循环）"""
    if not APP_ID or not APP_SECRET:
        print("[Feishu WS] 未配置 FEISHU_APP_ID 或 FEISHU_APP_SECRET，跳过长连接")
        return None

    print(f"[Feishu WS] 正在建立长连接... (app_id: {APP_ID})")

    # 创建事件处理器
    builder = lark.EventDispatcherHandler.builder("", "")
    builder.register_p2_im_message_receive_v1(handle_message)
    event_handler = builder.build()

    # 创建长连接客户端
    client = ws.Client(
        app_id=APP_ID,
        app_secret=APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
        auto_reconnect=True,
    )

    # 在独立线程中运行长连接
    # ws 模块的事件循环是我们创建的独立 loop（_patched_loop）
    # 与 FastAPI 的事件循环完全隔离
    def _run_ws():
        try:
            print("[Feishu WS] 长连接客户端启动中...")
            asyncio.set_event_loop(_patched_loop)
            client.start()
        except Exception as e:
            print(f"[Feishu WS] 长连接异常退出: {e}")

    t = threading.Thread(target=_run_ws, daemon=True)
    t.start()

    print("[Feishu WS] 长连接已启动（后台线程）")
    return None


if __name__ == "__main__":
    # 测试长连接
    start_ws_client()
    import time

    # 保持主线程运行
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n[Feishu WS] 已停止")
