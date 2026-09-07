#!/usr/bin/env python3
"""
导出多维表格数据为 JSON，供静态仪表盘使用
用法: python scripts/export_dashboard_data.py
输出: dashboard/data.json
"""
import json
import os
import sys
from pathlib import Path

# 加项目根到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.bitable import (
    BITABLE_APP_TOKEN, BITABLE_TABLE_ID, FEISHU_HOST,
    get_tenant_token, weighted_score
)
import requests


def fetch_all_records() -> list:
    """拉取全部记录"""
    items = []
    page_token = ""
    headers = {
        "Authorization": f"Bearer {get_tenant_token()}",
        "Content-Type": "application/json",
    }
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{FEISHU_HOST}/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}"
            f"/tables/{BITABLE_TABLE_ID}/records",
            headers=headers,
            params=params,
            timeout=20,
        )
        body = resp.json()
        if body.get("code") != 0:
            raise RuntimeError(f"读取多维表格失败 code={body.get('code')}: {body.get('msg')}")
        data = body.get("data", {})
        items.extend(data.get("items", []) or [])
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    return items


def transform_record(rec: dict) -> dict:
    """把多维表格记录转成前端需要的格式"""
    f = rec.get("fields", {})
    link = f.get("原文链接")
    if isinstance(link, dict):
        link_url = link.get("link", "")
    else:
        link_url = link or ""

    pub_ts = f.get("发布日期")
    pub_str = ""
    if pub_ts:
        from datetime import datetime
        pub_str = datetime.fromtimestamp(pub_ts / 1000).strftime("%Y-%m-%d")

    item = {
        "id": rec.get("record_id", ""),
        "title": f.get("标题", ""),
        "summary_zh": f.get("内容摘要", ""),
        "thailand_relevance": f.get("泰国相关度", 0) or 0,
        "opportunity_strength": f.get("商机强度", 0) or 0,
        "timeliness": f.get("时效性", 0) or 0,
        "section": f.get("板块", "") or "",
        "subsection": f.get("二级菜单", "") or "",
        "tags": f.get("标签", []) or [],
        "source": f.get("信息来源", "") or "",
        "published": pub_str,
        "link": link_url,
    }
    item["weight_score"] = weighted_score(item)
    return item


def main():
    print("正在从多维表格拉取数据...")
    records = fetch_all_records()
    print(f"共 {len(records)} 条记录")

    items = [transform_record(r) for r in records]
    # 按权重分降序
    items.sort(key=lambda x: x["weight_score"], reverse=True)

    # 计算统计数据
    stats = {
        "total": len(items),
        "high_value": sum(1 for i in items if i["weight_score"] >= 5),
        "tender": sum(1 for i in items if i.get("section") == "招标机会"),
        "sources": len(set(i["source"] for i in items if i["source"])),
    }
    print(f"统计: {stats}")

    # 输出
    out_path = Path(__file__).parent.parent / "dashboard" / "data.json"
    out_path.write_text(json.dumps({
        "items": items,
        "stats": stats,
        "exported_at": __import__("datetime").datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已导出到: {out_path}")


if __name__ == "__main__":
    main()
