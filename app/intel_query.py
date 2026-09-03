"""
情报查询模块：机器人 /today、/intel 背后的多维表格读取
数据源：情报主表（v1 API，tenant_access_token，ADR 0001）
表规模 hackathon 期 < 千行，全量拉取 + 本地过滤即可，无需服务端谓词下推。
"""
from datetime import datetime
from typing import Dict, List

import requests

from app.bitable import BITABLE_APP_TOKEN, BITABLE_TABLE_ID, FEISHU_HOST, _headers

# 查询需要的字段投影（拉小 payload）
_FIELDS = ["标题", "权重分", "原文链接", "板块", "二级菜单", "内容摘要", "标签", "信息来源", "采集时间"]


def fetch_intel_records() -> List[Dict]:
    """全量拉取情报主表并归一化；API 报错时抛异常"""
    records: List[Dict] = []
    page_token = ""
    while True:
        params = {"page_size": 500, "field_names": str(_FIELDS).replace("'", '"')}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{FEISHU_HOST}/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}"
            f"/tables/{BITABLE_TABLE_ID}/records",
            headers=_headers(),
            params=params,
            timeout=20,
        )
        body = resp.json()
        if body.get("code") != 0:
            raise RuntimeError(f"读取多维表格失败 code={body.get('code')}: {body.get('msg')}")
        data = body.get("data", {})
        for rec in data.get("items", []) or []:
            records.append(_normalize(rec.get("fields", {})))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    return records


def _normalize(f: Dict) -> Dict:
    """v1 各字段形态归一化：权重分→float、链接→str、标签→list、空值兜底"""

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def _link(v):
        if isinstance(v, dict):
            return v.get("link", "")
        return str(v or "")

    def _tags(v):
        if isinstance(v, list):
            return [t.get("text", "") if isinstance(t, dict) else str(t) for t in v]
        return []

    def _text(v):
        # 公式/富文本字段可能返回 [{"text": "...", "type": "text"}] 分段数组
        if isinstance(v, list):
            return "".join(seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in v)
        return str(v) if v is not None else ""

    # 采集日期优先从毫秒时间戳本地推导，不依赖公式列
    ts = f.get("采集时间")
    collected_date = (
        datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")
        if isinstance(ts, (int, float))
        else _text(f.get("采集日期"))
    )

    return {
        "title": _text(f.get("标题")),
        "weight": _num(f.get("权重分")),
        "link": _link(f.get("原文链接")),
        "section": _text(f.get("板块")),
        "subsection": _text(f.get("二级菜单")),
        "summary": _text(f.get("内容摘要")),
        "tags": _tags(f.get("标签")),
        "source": _text(f.get("信息来源")),
        "collected_date": collected_date,
    }


def query_today(top_n: int = 5, min_weight: float = 0.0) -> List[Dict]:
    """今日采集的高分情报，按权重分降序"""
    today = datetime.now().strftime("%Y-%m-%d")
    rows = [r for r in fetch_intel_records() if r["collected_date"] == today]
    rows = [r for r in rows if r["weight"] >= min_weight]
    rows.sort(key=lambda r: r["weight"], reverse=True)
    return rows[:top_n]


def query_keyword(keyword: str, top_n: int = 5) -> List[Dict]:
    """关键词检索（标题/摘要/标签/板块），按权重分降序"""
    kw = keyword.strip().lower()
    if not kw:
        return []

    def _hit(r: Dict) -> bool:
        hay = " ".join(
            [r["title"], r["summary"], r["source"], r["section"], r["subsection"]]
            + r["tags"]
        ).lower()
        return kw in hay

    rows = [r for r in fetch_intel_records() if _hit(r)]
    rows.sort(key=lambda r: r["weight"], reverse=True)
    return rows[:top_n]
