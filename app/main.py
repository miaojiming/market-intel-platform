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
from fastapi.middleware.cors import CORSMiddleware
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

# CORS：允许仪表盘跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# 飞书验证 token（可选）
FEISHU_VERIFICATION_TOKEN = os.getenv("FEISHU_VERIFICATION_TOKEN", "")

# 定时任务
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


# ================ 健康检查 ================
@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

# 仪表盘测试连接用
@app.get("/api/health")
def api_health():
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


# ================ 立即推送（仪表盘用） ================
@app.post("/api/push-now")
def api_push_now():
    """
    仪表盘「立即推送」按钮的后端接口
    从多维表格读取最新高价值情报，直接推送到飞书群
    不重新采集，响应快
    """
    try:
        return _do_push_now()
    except Exception as e:
        import traceback
        print(f"[push-now] ERROR: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


def _do_push_now():
    from app.bitable import (
        BITABLE_APP_TOKEN, BITABLE_TABLE_ID,
        get_tenant_token,
    )
    import requests

    PUSH_THRESHOLD = float(os.getenv("PUSH_THRESHOLD", "5.0"))
    PUSH_MAX = int(os.getenv("PUSH_MAX", "10"))
    FALLBACK_TH_RELEVANCE = int(os.getenv("FALLBACK_TH_RELEVANCE", "5"))
    FALLBACK_MAX = int(os.getenv("FALLBACK_MAX", "5"))

    FEISHU_HOST = "https://open.feishu.cn"
    token = get_tenant_token()

    # 1. 从多维表格读取最新情报
    items = []
    page_token = ""
    while True:
        params = {"page_size": 200}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{FEISHU_HOST}/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}"
            f"/tables/{BITABLE_TABLE_ID}/records",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=20,
        )
        body = resp.json()
        if body.get("code") != 0:
            raise RuntimeError(f"读取多维表格失败: {body.get('msg')} (code={body.get('code')})")
        data = body.get("data", {})
        for rec in data.get("items", []) or []:
            fields = rec.get("fields", {})
            th = float(fields.get("泰国相关度") or 0)
            op = float(fields.get("商机强度") or 0)
            ti = float(fields.get("时效性") or 0)
            score = round(0.4 * th + 0.4 * op + 0.2 * ti, 1)

            link_obj = fields.get("原文链接", {})
            if isinstance(link_obj, dict):
                link = link_obj.get("link", "")
            else:
                link = str(link_obj or "")

            tags_field = fields.get("标签", [])
            if isinstance(tags_field, list):
                tags = tags_field
            elif isinstance(tags_field, str):
                tags = [tags_field]
            else:
                tags = []

            items.append({
                "title": fields.get("标题", ""),
                "summary_zh": fields.get("内容摘要", ""),
                "thailand_relevance": th,
                "opportunity_strength": op,
                "timeliness": ti,
                "weight_score": score,
                "section": fields.get("板块", ""),
                "subsection": fields.get("二级菜单", ""),
                "tags": tags,
                "source_name": fields.get("信息来源", ""),
                "source_url": link,
                "collected_at": fields.get("采集时间", 0),
            })
        if len(items) >= 200 or not data.get("has_more"):
            break
        page_token = data.get("page_token", "")

    # 2. 按权重分排序
    items.sort(key=lambda x: x["weight_score"], reverse=True)

    # 3. 筛选达标
    qualified = [i for i in items if i["weight_score"] >= PUSH_THRESHOLD]
    is_fallback = False

    if qualified:
        to_push = qualified[:PUSH_MAX]
    else:
        # 兜底
        fallback_items = [i for i in items if i["thailand_relevance"] >= FALLBACK_TH_RELEVANCE]
        to_push = fallback_items[:FALLBACK_MAX]
        is_fallback = True

    if not to_push:
        return {"success": False, "count": 0, "is_fallback": False,
                "message": "没有符合条件的情报可推送"}

    # 4. 发送飞书卡片
    ok = send_intelligence_card(to_push)

    mode = "高价值情报" if not is_fallback else "兜底精选"
    return {
        "success": ok,
        "count": len(to_push),
        "is_fallback": is_fallback,
        "message": f"推送成功（{mode}，{len(to_push)}条）" if ok else "推送失败",
    }


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
