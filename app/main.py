"""
主入口：FastAPI 服务 + 定时任务 + 飞书事件回调
- GET /health 健康检查
- POST /feishu/webhook 飞书事件回调（接收用户消息）
- POST /api/intelligence/run 手动触发情报日报
- GET /api/profile?company=xxx 手动触发画像生成
"""
import os
import json
import threading
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from apscheduler.schedulers.background import BackgroundScheduler

from app.intelligence import run_intelligence_daily
from app.profile import generate_profile
from app.feishu import (
    send_intelligence_card,
    send_profile_card,
    reply_text,
    parse_command,
    get_help_text,
)
from app.feishu_ws import start_ws_client

load_dotenv()

app = FastAPI(title="市场智能情报与获客平台 MVP")

# 飞书验证 token（可选）
FEISHU_VERIFICATION_TOKEN = os.getenv("FEISHU_VERIFICATION_TOKEN", "")

# 定时任务
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


# ================ 健康检查 ================
@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


# ================ 飞书事件回调 ================
@app.post("/feishu/webhook")
async def feishu_webhook(request: Request):
    """
    接收飞书事件：
    - URL 验证（challenge）
    - 消息接收（用户 @机器人 发公司名）
    """
    body = await request.json()

    # 1. URL 验证
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    # 2. 事件回调
    header = body.get("header", {})
    event = body.get("event", {})

    # 去重：同一条事件只处理一次（MVP 简易处理）
    event_id = header.get("event_id", "")
    if not event_id:
        return {"code": 0}

    # 只处理接收消息事件
    event_type = header.get("event_type", "")
    if event_type != "im.message.receive_v1":
        return {"code": 0}

    # 提取消息内容
    message = event.get("message", {})
    sender = event.get("sender", {})
    chat_id = message.get("chat_id", "")
    message_id = message.get("message_id", "")
    msg_type = message.get("message_type", "")
    content_str = message.get("content", "{}")

    try:
        content = json.loads(content_str)
    except Exception:
        content = {}

    text = content.get("text", "").strip()

    # 只处理文本消息
    if msg_type != "text":
        return {"code": 0}

    # 解析指令
    cmd = parse_command(text)

    # 后台线程处理（避免飞书重试 3 秒超时）
    def _handle():
        try:
            if cmd["command"] == "help":
                reply_text(message_id, get_help_text())
                return

            if cmd["command"] == "profile":
                company = cmd["company"]
                if not company:
                    reply_text(message_id, "请告诉我要查询的公司名称，例如：@情报助手 星展银行")
                    return

                # 回复"正在生成"的提示
                reply_text(message_id, f"🔍 正在查询「{company}」的画像，请稍候...")

                # 生成画像
                profile = generate_profile(company)

                # 发送画像卡片
                send_profile_card(profile, chat_id=chat_id)
                return

            # 未知指令
            reply_text(message_id, "我不太明白你的意思，发送 /help 查看使用方法")

        except Exception as e:
            print(f"[Webhook] 处理失败: {e}")
            reply_text(message_id, "❌ 画像生成失败，请稍后重试")

    threading.Thread(target=_handle, daemon=True).start()

    return {"code": 0}


# ================ 手动触发接口 ================
@app.post("/api/intelligence/run")
def api_run_intelligence(hours: int = 24, top_n: int = 5):
    """手动触发情报日报生成"""
    items = run_intelligence_daily(hours=hours, top_n=top_n)
    # 同时推送到飞书
    if items:
        send_intelligence_card(items)
    return {"count": len(items), "items": items}


@app.get("/api/profile")
def api_profile(company: str):
    """手动触发画像生成"""
    if not company:
        raise HTTPException(status_code=400, detail="company 参数必填")
    profile = generate_profile(company)
    return profile


# ================ 定时任务 ================
def scheduled_intelligence():
    """定时任务：每天早上 8 点推送情报日报"""
    print(f"\n[Scheduler] 定时触发情报日报 - {datetime.now()}")
    try:
        items = run_intelligence_daily(hours=24, top_n=5)
        if items:
            send_intelligence_card(items)
            print("[Scheduler] 情报日报推送完成")
        else:
            print("[Scheduler] 今日无情报")
    except Exception as e:
        print(f"[Scheduler] 情报日报任务失败: {e}")


@app.on_event("startup")
def start_scheduler():
    """启动定时任务 + 飞书长连接"""
    # 每日情报管道已由 GitHub Actions 定时执行（ADR 0001），
    # 本服务专职交互机器人长连接；旧版本地定时任务默认关闭，
    # 仅在显式设置 ENABLE_LOCAL_SCHEDULER=1 时启用（本地调试用），
    # 否则常驻部署时会在 8:00 与 GH Actions 双份推送旧版日报。
    if os.getenv("ENABLE_LOCAL_SCHEDULER") == "1":
        scheduler.add_job(
            scheduled_intelligence,
            "cron",
            hour=8,
            minute=0,
            id="daily_intelligence",
            replace_existing=True,
        )
        scheduler.start()
        print("[Scheduler] 本地定时任务已启动（ENABLE_LOCAL_SCHEDULER=1）")
    else:
        print("[Scheduler] 每日管道由 GitHub Actions 执行，本地定时任务未启用")

    # 启动飞书长连接（接收消息）
    start_ws_client()


@app.on_event("shutdown")
def stop_scheduler():
    scheduler.shutdown()
    print("[Scheduler] 定时任务已停止")


# ================ 入口 ================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
