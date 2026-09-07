"""
Railway 部署的轻量 API 服务
- 仪表盘「立即推送」按钮的后端代理
- 从飞书多维表格读取高价值情报 → 飞书 webhook 推送
"""
import os
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

# ==========================================
# 配置
# ==========================================
FEISHU_HOST = "https://open.feishu.cn"
APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
BITABLE_APP_TOKEN = os.getenv("BITABLE_APP_TOKEN", "")
BITABLE_TABLE_ID = os.getenv("BITABLE_TABLE_ID", "")
WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")

# API Key 认证（简单保护，防止滥用）
API_KEY = os.getenv("PUSH_API_KEY", "")

# 推送阈值与上限
PUSH_THRESHOLD = float(os.getenv("PUSH_THRESHOLD", "5.0"))
PUSH_MAX = int(os.getenv("PUSH_MAX", "10"))
# 兜底：没有达标时，泰国相关度≥5的TOP5
FALLBACK_TH_RELEVANCE = int(os.getenv("FALLBACK_TH_RELEVANCE", "5"))
FALLBACK_MAX = int(os.getenv("FALLBACK_MAX", "5"))

_token_cache = {"token": "", "expire_at": 0}

app = FastAPI(title="Market Intel Push API", version="1.0.0")

# CORS：允许 GitHub Pages 和本地开发
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ==========================================
# 飞书工具函数
# ==========================================
def get_tenant_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expire_at"]:
        return _token_cache["token"]
    resp = requests.post(
        f"{FEISHU_HOST}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=15,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败: {data.get('msg')}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expire_at"] = time.time() + int(data.get("expire", 7200)) - 60
    return _token_cache["token"]


def _field_val(fields: dict, key: str, default=None):
    """安全读取多维表格字段值"""
    v = fields.get(key, default)
    if v is None:
        return default
    return v


def _weighted_score(th: float, op: float, ti: float) -> float:
    return round(0.4 * th + 0.4 * op + 0.2 * ti, 1)


def fetch_top_intelligence(limit: int = 20) -> List[Dict]:
    """
    从多维表格读取最近的高价值情报
    按采集时间倒序，返回 limit 条，本地再按权重分排序取 TOP
    """
    if not BITABLE_APP_TOKEN or not BITABLE_TABLE_ID:
        raise RuntimeError("未配置 BITABLE_APP_TOKEN / BITABLE_TABLE_ID")

    items = []
    page_token = ""
    while True:
        params = {"page_size": 500, "sort": '[{"field_name":"采集时间","desc":true}]'}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{FEISHU_HOST}/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}"
            f"/tables/{BITABLE_TABLE_ID}/records",
            headers={"Authorization": f"Bearer {get_tenant_token()}"},
            params=params,
            timeout=20,
        )
        body = resp.json()
        if body.get("code") != 0:
            raise RuntimeError(f"读取多维表格失败: {body.get('msg')}")
        data = body.get("data", {})
        for rec in data.get("items", []) or []:
            fields = rec.get("fields", {})
            th = float(_field_val(fields, "泰国相关度", 0) or 0)
            op = float(_field_val(fields, "商机强度", 0) or 0)
            ti = float(_field_val(fields, "时效性", 0) or 0)
            score = _weighted_score(th, op, ti)

            link_obj = fields.get("原文链接", {})
            if isinstance(link_obj, dict):
                link = link_obj.get("link", "")
                link_text = link_obj.get("text", link)
            else:
                link = str(link_obj or "")
                link_text = link

            tags_field = fields.get("标签", [])
            if isinstance(tags_field, list):
                tags = tags_field
            elif isinstance(tags_field, str):
                tags = [tags_field]
            else:
                tags = []

            items.append({
                "title": _field_val(fields, "标题", ""),
                "summary_zh": _field_val(fields, "内容摘要", ""),
                "thailand_relevance": th,
                "opportunity_strength": op,
                "timeliness": ti,
                "weight_score": score,
                "section": _field_val(fields, "板块", ""),
                "subsection": _field_val(fields, "二级菜单", ""),
                "tags": tags,
                "source_name": _field_val(fields, "信息来源", ""),
                "source_url": link,
                "collected_at": _field_val(fields, "采集时间", 0),
            })
        if len(items) >= limit * 3 or not data.get("has_more"):
            break
        page_token = data.get("page_token", "")

    # 按权重分排序
    items.sort(key=lambda x: x["weight_score"], reverse=True)
    return items[:limit * 2]


def send_intelligence_card(items: List[Dict], is_fallback: bool = False) -> bool:
    """发送情报卡片到飞书 webhook"""
    if not WEBHOOK_URL:
        return False
    if not items:
        return False

    elements = []
    for i, item in enumerate(items[:PUSH_MAX], 1):
        th = item.get("thailand_relevance", "-")
        op = item.get("opportunity_strength", "-")
        ti = item.get("timeliness", "-")
        sec = f"{item.get('section', '')}/{item.get('subsection', '')}".strip("/")
        tags_str = " ".join(f"【{t}】" for t in (item.get("tags") or []))
        summary = item.get("summary_zh", "")
        source = item.get("source_name", "")
        url = item.get("source_url", "#")

        head = f"**{i}. [{item['weight_score']}分] {item.get('title', '')}**"
        metrics = f"🎯 泰国相关 {th} · 💼 商机 {op} · ⏱ 时效 {ti}" + (f"\n📂 {sec}" if sec else "")
        elements.append({
            "tag": "markdown",
            "content": f"{head}\n{metrics}\n{tags_str}\n{summary}\n[原文链接({source})]({url})",
        })
        if i < min(len(items), PUSH_MAX):
            elements.append({"tag": "hr"})

    elements.append({"tag": "hr"})
    elements.append({
        "tag": "markdown",
        "content": "💡 **想了解某家机构？** @情报助手 + 公司名，即可生成客户画像",
    })

    flag = "⭐ 高价值情报" if not is_fallback else "📋 精选情报（兜底）"
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📰 {flag}（{min(len(items), PUSH_MAX)}条）",
                },
                "template": "blue",
            },
            "elements": elements,
        },
    }

    try:
        resp = requests.post(WEBHOOK_URL, json=card, timeout=15)
        return resp.status_code == 200
    except Exception as e:
        print(f"[Feishu] 情报卡片发送失败: {e}")
        return False


# ==========================================
# API 路由
# ==========================================
class PushResponse(BaseModel):
    success: bool
    count: int
    is_fallback: bool
    message: str


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now().isoformat()}


@app.post("/api/push-now", response_model=PushResponse)
async def push_now(x_api_key: str = ""):
    """
    触发一次飞书推送
    Header: X-API-Key（如果配置了 PUSH_API_KEY）
    """
    # API Key 校验
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="无效的 API Key")

    if not WEBHOOK_URL:
        raise HTTPException(status_code=500, detail="未配置 FEISHU_WEBHOOK_URL")

    try:
        # 1. 读取最新情报
        all_items = fetch_top_intelligence(limit=50)

        # 2. 筛选达标
        qualified = [i for i in all_items if i["weight_score"] >= PUSH_THRESHOLD]
        is_fallback = False

        if qualified:
            to_push = qualified[:PUSH_MAX]
        else:
            # 3. 兜底：泰国相关度≥5 的 TOP N
            fallback_items = [i for i in all_items if i["thailand_relevance"] >= FALLBACK_TH_RELEVANCE]
            to_push = fallback_items[:FALLBACK_MAX]
            is_fallback = True

        if not to_push:
            return PushResponse(
                success=False,
                count=0,
                is_fallback=False,
                message="没有符合条件的情报可推送",
            )

        # 4. 发送
        ok = send_intelligence_card(to_push, is_fallback=is_fallback)

        mode = "高价值情报" if not is_fallback else "兜底精选"
        return PushResponse(
            success=ok,
            count=len(to_push),
            is_fallback=is_fallback,
            message=f"推送成功（{mode}，{len(to_push)}条）" if ok else "推送失败",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    return {
        "name": "Market Intel Push API",
        "version": "1.0.0",
        "endpoints": ["/api/health", "/api/push-now"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
