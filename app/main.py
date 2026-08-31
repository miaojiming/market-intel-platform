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
from app.feishu import send_intelligence_card, send_profile_card, reply_text

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
    if msg_type != "text" or not text:
        return {"code": 0}

    # 去掉 @机器人 的提及
    # 飞书的文本消息里 @ 会以 <at user_id="xxx">名字</at> 形式出现
    import re
    text = re.sub(r"<at[^>]*>[^<]*</at>", "", text).strip()

    if not text:
        return {"code": 0}

    # 后台线程处理（避免飞书重试）
    def _handle():
        try:
            # 回复"正在生成"的提示
            reply_text(message_id, f"🔍 正在查询「{text}」的画像，请稍候...")

            # 生成画像
            profile = generate_profile(text)

            # 发送画像卡片
            send_profile_card(profile, chat_id=chat_id)
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
    """启动定时任务"""
    # 每天早上 8:00 推送情报日报
    scheduler.add_job(
        scheduled_intelligence,
        "cron",
        hour=8,
        minute=0,
        id="daily_intelligence",
        replace_existing=True,
    )
    scheduler.start()
    print("[Scheduler] 定时任务已启动，每天 8:00 推送情报日报")


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
