"""
飞书多维表格 v1 HTTP 写入客户端（ADR 0001）
GH Actions 无 CLI 环境，agent 通过 tenant_access_token + 开放平台 HTTP API 写入。
实测踩坑（2026-09-03 全链路验证）：
- 单选字段必须传纯字符串，传数组报 SingleSelectFieldConvFail
- url 文本字段必须传 {"text":..., "link":...} 对象，裸字符串报 URLFieldConvFail
- 日期字段传 Unix 毫秒时间戳，不是日期字符串
"""
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Set

import requests

FEISHU_HOST = "https://open.feishu.cn"
APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
BITABLE_APP_TOKEN = os.getenv("BITABLE_APP_TOKEN", "IjRjbhMNZaCR3YsvenrcIyk2nXg")
BITABLE_TABLE_ID = os.getenv("BITABLE_TABLE_ID", "tblHfzfRCBqjAfVD")

_token_cache = {"token": "", "expire_at": 0}


def get_tenant_token() -> str:
    """获取 tenant_access_token，进程内缓存，过期前 60s 刷新"""
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


def _headers() -> dict:
    return {"Authorization": f"Bearer {get_tenant_token()}", "Content-Type": "application/json"}


def to_v1_fields(item: Dict) -> Dict:
    """把管道内部 item 转成 v1 API 的 fields 格式（见模块头踩坑说明）"""
    fields: Dict = {
        "标题": item.get("title", ""),
        "内容摘要": item.get("summary_zh", ""),
        "泰国相关度": item.get("thailand_relevance"),
        "商机强度": item.get("opportunity_strength"),
        "时效性": item.get("timeliness"),
        "打分理由": item.get("score_reason", ""),
        "信息来源": item.get("source_name", ""),
        "标签": item.get("tags_v1", []),
        "原文语种": item.get("language", "英语"),
        "采集渠道": item.get("channel"),
        "查询式": item.get("query", ""),
        "状态": item.get("status", "待处理"),
    }
    # 单选：纯字符串，缺失时不下发该键（避免 ConvFail）
    for key, src in (("板块", "section"), ("二级菜单", "subsection")):
        val = item.get(src)
        if val:
            fields[key] = val
    # url 字段：必须对象
    link = item.get("link", "")
    if link:
        fields["原文链接"] = {"text": link, "link": link}
    # 日期：毫秒时间戳
    pub = item.get("published_ts")
    if pub:
        fields["发布日期"] = int(pub * 1000)
    ctime = item.get("collected_ts") or time.time()
    fields["采集时间"] = int(ctime * 1000)
    # 过滤 None 值，避免覆盖失败
    return {k: v for k, v in fields.items() if v is not None}


def fetch_existing_links() -> Set[str]:
    """拉取主表全部原文链接，作为去重键集合；API 报错时抛异常（不静默当空表）"""
    links: Set[str] = set()
    page_token = ""
    while True:
        params = {"page_size": 500}
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
            raise RuntimeError(
                f"读取多维表格失败 code={body.get('code')}: {body.get('msg')}"
            )
        data = body.get("data", {})
        for rec in data.get("items", []) or []:
            f = rec.get("fields", {}).get("原文链接")
            if isinstance(f, dict):
                links.add(f.get("link", ""))
            elif isinstance(f, str):
                links.add(f)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    return {l for l in links if l}


def create_record(item: Dict) -> Optional[str]:
    """写入一条情报记录，返回 record_id；失败返回 None"""
    try:
        resp = requests.post(
            f"{FEISHU_HOST}/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}"
            f"/tables/{BITABLE_TABLE_ID}/records",
            headers=_headers(),
            json={"fields": to_v1_fields(item)},
            timeout=20,
        )
        data = resp.json()
        if data.get("code") == 0:
            return data["data"]["record"]["record_id"]
        print(f"[Bitable] 写入失败 code={data.get('code')}: {data.get('msg')} | 标题={item.get('title','')[:40]}")
        return None
    except Exception as e:
        print(f"[Bitable] 写入异常: {e}")
        return None


def update_record_fields(record_id: str, fields: Dict) -> bool:
    """更新指定记录的部分字段（v1 PUT，格式约定同 to_v1_fields）"""
    try:
        resp = requests.put(
            f"{FEISHU_HOST}/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}"
            f"/tables/{BITABLE_TABLE_ID}/records/{record_id}",
            headers=_headers(),
            json={"fields": fields},
            timeout=20,
        )
        data = resp.json()
        if data.get("code") == 0:
            return True
        print(f"[Bitable] 更新失败 code={data.get('code')}: {data.get('msg')} | rid={record_id}")
        return False
    except Exception as e:
        print(f"[Bitable] 更新异常: {e}")
        return False


def mark_pushed(record_ids: List[str]) -> int:
    """把已推送记录的状态改为「已推送」，返回成功条数"""
    ok = 0
    for rid in record_ids:
        if update_record_fields(rid, {"状态": "已推送"}):
            ok += 1
    return ok


def weighted_score(item: Dict) -> float:
    """本地复算权重分（与多维表格公式列同口径 0.4/0.4/0.2），用于推送过滤"""
    th = item.get("thailand_relevance") or 0
    op = item.get("opportunity_strength") or 0
    ti = item.get("timeliness") or 0
    return round(0.4 * th + 0.4 * op + 0.2 * ti, 1)


# ==========================================
# 反馈表（数据飞轮）
# ==========================================
FEEDBACK_TABLE_ID = os.getenv("FEEDBACK_TABLE_ID", "")

# 反馈类型枚举
FEEDBACK_TYPES = {
    "score_high": "打分偏高",
    "score_low": "打分偏低",
    "category_wrong": "分类错误",
    "summary_wrong": "摘要不准确",
    "tag_wrong": "标签不对",
    "spam": "噪音/无关",
    "useful": "有价值",
}


def add_feedback(feedback: Dict) -> Optional[str]:
    """
    写入一条用户反馈到反馈表
    feedback: {
        item_title: 情报标题,
        item_url: 原文链接,
        feedback_type: 反馈类型(见 FEEDBACK_TYPES keys),
        user_name: 用户名,
        user_id: 用户 open_id,
        original_scores: {thailand_relevance, opportunity_strength, timeliness, weight_score},
        comment: 用户备注(可选),
        source: 来源(飞书卡片/仪表盘),
    }
    """
    if not FEEDBACK_TABLE_ID:
        print("[Bitable] 未配置 FEEDBACK_TABLE_ID，跳过反馈写入")
        return None

    try:
        now_ms = int(time.time() * 1000)
        fields = {
            "情报标题": feedback.get("item_title", ""),
            "原文链接": feedback.get("item_url", ""),
            "反馈类型": feedback.get("feedback_type", ""),
            "反馈人": feedback.get("user_name", ""),
            "反馈人ID": feedback.get("user_id", ""),
            "原权重分": feedback.get("original_scores", {}).get("weight_score"),
            "原泰国相关度": feedback.get("original_scores", {}).get("thailand_relevance"),
            "原商机强度": feedback.get("original_scores", {}).get("opportunity_strength"),
            "原时效性": feedback.get("original_scores", {}).get("timeliness"),
            "备注": feedback.get("comment", ""),
            "来源": feedback.get("source", "飞书卡片"),
            "处理状态": "待处理",
            "反馈时间": now_ms,
        }
        # 过滤 None 值
        fields = {k: v for k, v in fields.items() if v is not None}

        resp = requests.post(
            f"{FEISHU_HOST}/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}"
            f"/tables/{FEEDBACK_TABLE_ID}/records",
            headers=_headers(),
            json={"fields": fields},
            timeout=20,
        )
        data = resp.json()
        if data.get("code") == 0:
            rec_id = data.get("data", {}).get("record", {}).get("record_id", "")
            print(f"[Bitable] 反馈已写入: {feedback.get('feedback_type')} - {feedback.get('item_title', '')[:30]}")
            return rec_id
        else:
            print(f"[Bitable] 反馈写入失败: code={data.get('code')}, msg={data.get('msg')}")
            return None
    except Exception as e:
        print(f"[Bitable] 反馈写入异常: {e}")
        return None


def get_feedback_stats() -> Dict:
    """获取反馈统计数据（用于仪表盘展示）"""
    if not FEEDBACK_TABLE_ID:
        return {"total": 0, "by_type": {}, "pending": 0}

    try:
        items = []
        page_token = ""
        while True:
            params = {"page_size": 200}
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(
                f"{FEISHU_HOST}/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}"
                f"/tables/{FEEDBACK_TABLE_ID}/records",
                headers=_headers(),
                params=params,
                timeout=20,
            )
            body = resp.json()
            if body.get("code") != 0:
                return {"total": 0, "by_type": {}, "pending": 0}
            data = body.get("data", {})
            items.extend(data.get("items", []) or [])
            if len(items) >= 500 or not data.get("has_more"):
                break
            page_token = data.get("page_token", "")

        by_type = {}
        pending = 0
        for rec in items:
            fields = rec.get("fields", {})
            ftype = fields.get("反馈类型", "未知")
            by_type[ftype] = by_type.get(ftype, 0) + 1
            if fields.get("处理状态", "待处理") == "待处理":
                pending += 1

        return {
            "total": len(items),
            "by_type": by_type,
            "pending": pending,
        }
    except Exception as e:
        print(f"[Bitable] 反馈统计失败: {e}")
        return {"total": 0, "by_type": {}, "pending": 0}
