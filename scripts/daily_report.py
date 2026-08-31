"""
每日情报报告脚本
采集 RSS 文章 → LLM 摘要 → 筛选高价值 → 推送飞书 → 保存结果
"""
import sys
import os
import json
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.intelligence import run_intelligence_daily


def push_feishu(items, webhook_url):
    """推送情报到飞书群"""
    import requests

    if not webhook_url:
        print("[飞书] 未配置 Webhook，跳过推送")
        return

    # 筛选高价值情报
    high_value = [r for r in items if r.get("importance", 0) >= 4]
    if not high_value:
        print("[飞书] 没有高价值情报，跳过推送")
        return

    # 构建飞书卡片消息
    elements = []
    for i, item in enumerate(high_value[:10], 1):
        tags = "、".join(item.get("tags", []))
        summary = item.get("summary_zh", "")
        source_url = item.get("source_url", "")
        source_name = item.get("source_name", "")
        importance = "⭐" * item.get("importance", 0)

        content = (
            f"**{i}. {item.get('title', '')[:50]}**\n"
            f"{importance}\n\n"
            f"{summary}\n\n"
            f"🏷️ 标签：{tags}\n"
            f"📰 来源：[{source_name}]({source_url})"
        )
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})
        elements.append({"tag": "hr"})

    # 移除最后一个 hr
    if elements and elements[-1].get("tag") == "hr":
        elements.pop()

    msg = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📊 每日收单情报（{len(high_value)} 条高价值）",
                },
                "template": "blue",
            },
            "elements": elements,
        },
    }

    try:
        resp = requests.post(webhook_url, json=msg, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0:
                print(f"[飞书] ✅ 推送成功，{len(high_value)} 条情报")
            else:
                print(f"[飞书] ❌ 推送失败: {data}")
        else:
            print(f"[飞书] ❌ HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[飞书] ❌ 推送异常: {e}")


def main():
    print("=" * 60)
    print("每日收单情报报告")
    print(f"日期: {date.today().strftime('%Y-%m-%d')}")
    print("=" * 60)

    # 1. 运行情报采集 + 摘要
    items = run_intelligence_daily(hours=24, top_n=20)
    print(f"\n共生成 {len(items)} 条情报摘要")

    # 2. 推送飞书
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if webhook:
        push_feishu(items, webhook)
    else:
        print("\n[飞书] 未配置 FEISHU_WEBHOOK_URL，跳过推送")

    # 3. 保存结果到文件
    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output"
    )
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"intelligence_{date.today()}.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到: {output_file}")

    # 4. 统计
    high_value_count = sum(1 for r in items if r.get("importance", 0) >= 4)
    print(f"\n📈 统计：")
    print(f"  总情报数：{len(items)}")
    print(f"  高价值（≥4星）：{high_value_count}")
    print(f"  一般价值（<4星）：{len(items) - high_value_count}")


if __name__ == "__main__":
    main()
