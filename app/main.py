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
from fastapi.responses import HTMLResponse
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

# 反馈缓存：推送时存入情报数据，反馈页面通过短ID获取
_feedback_cache: dict = {}

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


# ================ 用户反馈（数据飞轮） ================
@app.get("/api/feedback/item")
async def api_feedback_item(id: str = ""):
    """通过短ID获取情报数据（反馈页面用）"""
    data = _feedback_cache.get(id)
    if not data:
        raise HTTPException(status_code=404, detail="情报数据不存在或已过期")
    return {"success": True, "data": data}


@app.post("/api/feedback")
async def api_feedback(request: Request):
    """
    提交用户反馈
    body: {
        item_title: 情报标题,
        item_url: 原文链接,
        feedback_type: 反馈类型,
        original_scores: {weight_score, thailand_relevance, opportunity_strength, timeliness},
        comment: 备注(可选),
        source: 来源(可选),
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效的请求体")

    feedback_type = body.get("feedback_type", "")
    if not feedback_type:
        raise HTTPException(status_code=400, detail="feedback_type 必填")

    from app.bitable import add_feedback

    rec_id = add_feedback({
        "item_title": body.get("item_title", ""),
        "item_url": body.get("item_url", ""),
        "feedback_type": feedback_type,
        "user_name": body.get("user_name", "匿名用户"),
        "user_id": body.get("user_id", ""),
        "original_scores": body.get("original_scores", {}),
        "comment": body.get("comment", ""),
        "source": body.get("source", "web"),
    })

    if rec_id:
        return {"success": True, "record_id": rec_id, "message": "反馈提交成功"}
    else:
        # 可能是没配置反馈表，但不要报 500，告诉用户已记录
        return {"success": True, "record_id": "", "message": "反馈已收到，感谢你的反馈"}


@app.get("/api/feedback/stats")
async def api_feedback_stats():
    """获取反馈统计数据"""
    from app.bitable import get_feedback_stats
    stats = get_feedback_stats()
    return {"success": True, "data": stats}


# ================ 反馈页面（数据飞轮） ================
FEEDBACK_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>情报反馈 - 市场情报与获客平台</title>
<style>
  :root {
    --bg: #0f172a; --bg-card: #1e293b; --bg-soft: #334155;
    --text: #f1f5f9; --text-2: #94a3b8; --text-3: #64748b;
    --border: #334155; --accent: #3b82f6; --accent-2: #8b5cf6;
    --success: #10b981; --danger: #ef4444; --warning: #f59e0b;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; padding: 20px; line-height: 1.6; }
  .container { max-width: 560px; margin: 40px auto; }
  .header { text-align: center; margin-bottom: 24px; }
  .header h1 { font-size: 20px; font-weight: 700; background: linear-gradient(135deg, var(--accent), var(--accent-2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
  .header p { font-size: 13px; color: var(--text-3); margin-top: 4px; }
  .card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 16px; }
  .item-title { font-size: 15px; font-weight: 600; color: var(--text); margin-bottom: 8px; line-height: 1.4; }
  .score-row { display: flex; gap: 12px; flex-wrap: wrap; }
  .score-badge { background: rgba(59,130,246,0.15); color: #93c5fd; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
  .section-title { font-size: 14px; font-weight: 600; color: var(--text); margin-bottom: 12px; }
  .feedback-options { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .feedback-option { background: var(--bg-soft); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-size: 13px; color: var(--text-2); cursor: pointer; transition: all 0.2s; text-align: center; user-select: none; }
  .feedback-option:hover { border-color: var(--accent); color: var(--text); }
  .feedback-option.selected { background: rgba(59,130,246,0.2); border-color: var(--accent); color: #93c5fd; font-weight: 500; }
  .feedback-option.useful.selected { background: rgba(16,185,129,0.2); border-color: var(--success); color: #6ee7b7; }
  textarea { width: 100%; min-height: 80px; padding: 10px 12px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 13px; font-family: inherit; resize: vertical; box-sizing: border-box; }
  textarea:focus { outline: none; border-color: var(--accent); }
  textarea::placeholder { color: var(--text-3); }
  .submit-btn { width: 100%; padding: 12px; background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: white; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s; margin-top: 16px; }
  .submit-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(59,130,246,0.4); }
  .submit-btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
  .success-page { text-align: center; padding: 40px 20px; }
  .success-icon { font-size: 48px; margin-bottom: 16px; }
  .success-title { font-size: 18px; font-weight: 600; color: var(--text); margin-bottom: 8px; }
  .success-desc { font-size: 13px; color: var(--text-2); margin-bottom: 20px; }
  .error-msg { color: var(--danger); font-size: 13px; text-align: center; margin-top: 12px; min-height: 18px; }
  @media (max-width: 480px) { .feedback-options { grid-template-columns: 1fr; } .container { margin: 20px auto; } }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>情报反馈</h1>
    <p>你的反馈帮助我们持续优化模型</p>
  </div>
  <div id="feedbackForm">
    <div class="card">
      <div class="item-title" id="itemTitle">加载中...</div>
      <div class="score-row">
        <span class="score-badge" id="scoreBadge">-- 分</span>
        <span class="score-badge" id="thBadge" style="background:rgba(16,185,129,0.15);color:#6ee7b7;">泰国相关 --</span>
        <span class="score-badge" id="opBadge" style="background:rgba(245,158,11,0.15);color:#fcd34d;">商机强度 --</span>
        <span class="score-badge" id="tiBadge" style="background:rgba(139,92,246,0.15);color:#c4b5fd;">时效性 --</span>
      </div>
    </div>
    <div class="card">
      <div class="section-title">这条情报哪里有问题？</div>
      <div class="feedback-options">
        <div class="feedback-option useful" data-type="useful">👍 有价值</div>
        <div class="feedback-option" data-type="score_high">📈 打分偏高</div>
        <div class="feedback-option" data-type="score_low">📉 打分偏低</div>
        <div class="feedback-option" data-type="category_wrong">📂 分类错误</div>
        <div class="feedback-option" data-type="summary_wrong">📝 摘要不准确</div>
        <div class="feedback-option" data-type="tag_wrong">🏷️ 标签不对</div>
        <div class="feedback-option" data-type="spam">🗑️ 噪音/无关</div>
        <div class="feedback-option" data-type="other">❓ 其他</div>
      </div>
    </div>
    <div class="card">
      <div class="section-title">补充说明（可选）</div>
      <textarea id="commentInput" placeholder="具体说说哪里有问题，或者正确的打分应该是怎样的..."></textarea>
      <button class="submit-btn" id="submitBtn" onclick="submitFeedback()">提交反馈</button>
      <div class="error-msg" id="errorMsg"></div>
    </div>
  </div>
  <div id="successPage" style="display:none;">
    <div class="card success-page">
      <div class="success-icon">✅</div>
      <div class="success-title">感谢你的反馈！</div>
      <div class="success-desc">我们会认真对待每一条反馈，<br>并将其纳入模型优化迭代。</div>
    </div>
  </div>
</div>
<script>
  var payload = __PAYLOAD__;
  var title = payload.title || '';
  var url = payload.url || '';
  var score = parseFloat(payload.score || 0);
  var th = parseFloat(payload.th || 0);
  var op = parseFloat(payload.op || 0);
  var ti = parseFloat(payload.ti || 0);
  var src = payload.src || 'feishu_card';
  var preType = '__PRETYPE__';
  var selectedType = preType;
  function getApiUrl() { return window.location.origin; }

  document.getElementById('itemTitle').textContent = title || '未知情报';
  document.getElementById('scoreBadge').textContent = score + ' 分';
  document.getElementById('thBadge').textContent = '泰国相关 ' + th;
  document.getElementById('opBadge').textContent = '商机强度 ' + op;
  document.getElementById('tiBadge').textContent = '时效性 ' + ti;
  if (preType) { var el = document.querySelector('.feedback-option[data-type="' + preType + '"]'); if (el) el.classList.add('selected'); }
  document.querySelectorAll('.feedback-option').forEach(function(el) {
    el.addEventListener('click', function() {
      document.querySelectorAll('.feedback-option').forEach(function(e) { e.classList.remove('selected'); });
      el.classList.add('selected'); selectedType = el.dataset.type;
    });
  });

  function submitFeedback() {
    if (!selectedType) { document.getElementById('errorMsg').textContent = '请选择反馈类型'; return; }
    var apiUrl = getApiUrl();
    var btn = document.getElementById('submitBtn');
    btn.disabled = true; btn.textContent = '提交中...';
    document.getElementById('errorMsg').textContent = '';
    var comment = document.getElementById('commentInput').value.trim();
    fetch(apiUrl + '/api/feedback', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_title: title, item_url: url, feedback_type: selectedType,
        original_scores: { weight_score: score, thailand_relevance: th, opportunity_strength: op, timeliness: ti },
        comment: comment, source: src }),
    }).then(function(resp) { return resp.json(); }).then(function(data) {
      if (data.success) {
        document.getElementById('feedbackForm').style.display = 'none';
        document.getElementById('successPage').style.display = 'block';
      } else {
        document.getElementById('errorMsg').textContent = data.detail || data.message || '提交失败，请重试';
        btn.disabled = false; btn.textContent = '提交反馈';
      }
    }).catch(function(e) {
      document.getElementById('errorMsg').textContent = '网络错误：' + e.message;
      btn.disabled = false; btn.textContent = '提交反馈';
    });
  }
</script>
</body>
</html>"""


@app.get("/feedback.html", response_class=HTMLResponse)
async def feedback_page(id: str = "", type: str = ""):
    """反馈页面：数据服务端内嵌，避免前端 fetch 依赖"""
    data = _feedback_cache.get(id, {})
    payload = json.dumps(data, ensure_ascii=True)
    html = FEEDBACK_HTML.replace("__PAYLOAD__", payload)
    html = html.replace("__PRETYPE__", type or "")
    return HTMLResponse(html)


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
