#!/usr/bin/env python3
"""
每日情报管道（全链路，ADR 0001 + 四轮共识）
采集(7渠道) → Google News 链接解码 → 去重(内存+多维表格) → 摘要(opus) →
独立打分(gpt-5.6-sol) → 写入多维表格 → 权重分≥6 TOP10 推送飞书群

用法:
  python scripts/daily_pipeline.py                # 全链路
  python scripts/daily_pipeline.py --dry-run      # 不写表不推送（本地联调）
  python scripts/daily_pipeline.py --hours 48     # 回看窗口
GH Actions 入口（.github/workflows/daily-intelligence.yml）。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feedparser

from app.channels import FIXED_FEEDS, GOOGLE_NEWS_CHANNEL, GOOGLE_NEWS_QUERIES, VALID_CHANNELS, google_news_feed_url
from app.gnews import decode_google_news_url
from app.intelligence import fetch_article_content, summarize_article
from app.scoring import parse_published, score_intel
from app import bitable

# 每日全渠道采集上限（控制 LLM 成本与表格增量）
DAILY_MAX = int(os.getenv("PIPELINE_DAILY_MAX", "40"))
# 每渠道条数上限
PER_CHANNEL_MAX = 10
# 推送阈值与上限（共识：权重分≥6 且 TOP10/日）
PUSH_THRESHOLD = 6.0
PUSH_TOP_N = 10


def collect(hours: int) -> list:
    """从 7 个渠道采集 + 解码链接 + 本地去重"""
    cutoff = datetime.now() - timedelta(hours=hours)
    seen = set()
    articles = []

    def _add(title, link, source_name, published, summary, channel, query, language):
        if not title or not link or link in seen:
            return
        seen.add(link)
        articles.append({
            "title": title.strip(),
            "link": link.strip(),
            "source_name": source_name,
            "published": published,
            "summary_rss": (summary or "")[:500],
            "channel": channel if channel in VALID_CHANNELS else "手工录入",
            "query": query,
            "language": language,
        })

    # 1) Google News RSS 检索式 ×11
    for query in GOOGLE_NEWS_QUERIES:
        try:
            feed = feedparser.parse(google_news_feed_url(query, when="2d"))
            count = 0
            for entry in feed.entries:
                if count >= PER_CHANNEL_MAX:
                    break
                link = decode_google_news_url(entry.get("link", ""))
                _add(
                    entry.get("title", ""), link,
                    entry.get("source", {}).get("title", "Google News"),
                    _iso(entry), entry.get("summary", ""),
                    GOOGLE_NEWS_CHANNEL, query, "英语",
                )
                count += 1
            print(f"[Collect] GoogleNews[{query[:40]}…] +{count}")
        except Exception as e:
            print(f"[Collect] GoogleNews 查询失败 [{query[:40]}]: {e}")
        time.sleep(0.5)

    # 2) 固定源 RSS ×5（含关键词过滤）
    for feed_cfg in FIXED_FEEDS:
        try:
            feed = feedparser.parse(feed_cfg["url"])
            count = 0
            for entry in feed.entries[:PER_CHANNEL_MAX * 2]:
                kws = feed_cfg.get("filter_keywords")
                text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
                if kws and not any(k.lower() in text for k in kws):
                    continue
                if count >= PER_CHANNEL_MAX:
                    break
                _add(
                    entry.get("title", ""), entry.get("link", ""),
                    feed_cfg["name"], _iso(entry), entry.get("summary", ""),
                    feed_cfg["channel"], feed_cfg["url"], feed_cfg.get("language", "英语"),
                )
                count += 1
            print(f"[Collect] {feed_cfg['name']} +{count}")
        except Exception as e:
            print(f"[Collect] {feed_cfg['name']} 失败: {e}")

    print(f"[Collect] 采集完成，本地去重后 {len(articles)} 条")
    return articles


def _iso(entry) -> str:
    for f in ("published_parsed", "updated_parsed"):
        t = entry.get(f)
        if t:
            return datetime(*t[:6]).isoformat()
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=26)
    parser.add_argument("--dry-run", action="store_true", help="不写表不推送")
    parser.add_argument("--no-push", action="store_true", help="写表但不推送")
    args = parser.parse_args()

    print(f"\n{'='*56}\n[Pipeline] 泰国支付市场情报管道启动 {datetime.now():%Y-%m-%d %H:%M}\n{'='*56}")

    # 1. 采集
    articles = collect(args.hours)
    if not articles:
        print("[Pipeline] 无新情报，结束")
        return

    # 2. 对比多维表格存量链接去重
    if args.dry_run:
        existing = set()
        print("[Pipeline] dry-run: 跳过表格去重与写入")
    else:
        existing = bitable.fetch_existing_links()
        print(f"[Pipeline] 表内存量链接 {len(existing)} 条")
    fresh = [a for a in articles if a["link"] not in existing][:DAILY_MAX]
    print(f"[Pipeline] 待处理新情报 {len(fresh)} 条（上限 {DAILY_MAX}）")

    # 3. 逐条: 正文 → 摘要(opus) → 独立打分(gpt-5.6-sol) → 写入
    pushed_candidates = []
    written = 0
    for i, item in enumerate(fresh, 1):
        print(f"  [{i}/{len(fresh)}] {item['title'][:50]}…")
        content = fetch_article_content(item["link"])
        summary = summarize_article(item["title"], content or item["summary_rss"])
        item.update(summary)  # summary_zh / tags / importance(卡片兼容)

        score = score_intel(item)
        if not score or score.get("thailand_relevance") is None:
            print("      打分失败，跳过该条")
            continue
        item.update(score)
        item["published_ts"] = parse_published(item.get("published"))
        item["collected_ts"] = time.time()
        weight = bitable.weighted_score(item)
        item["weight_score"] = weight

        if not args.dry_run:
            rid = bitable.create_record(item)
            if rid:
                written += 1
            else:
                continue
        if weight >= PUSH_THRESHOLD:
            pushed_candidates.append(item)
        time.sleep(0.3)

    # 4. 推送（权重分≥6，TOP10；卡片沿用 importance 星级 → weight 映射）
    pushed_candidates.sort(key=lambda x: x["weight_score"], reverse=True)
    top = pushed_candidates[:PUSH_TOP_N]
    for t in top:
        t["importance"] = max(1, min(5, round(t["weight_score"] / 2)))
        t["source_url"] = t["link"]

    if not args.dry_run and not args.no_push and top:
        from app.feishu import send_intelligence_card
        ok = send_intelligence_card(top)
        print(f"[Pipeline] 推送 {'成功' if ok else '失败'}: {len(top)} 条（≥{PUSH_THRESHOLD} 分）")

    # 5. 本地留档（与 daily_report 输出保持同目录）
    out = Path("output")
    out.mkdir(exist_ok=True)
    report = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "collected": len(articles),
        "fresh": len(fresh),
        "written": written if not args.dry_run else 0,
        "push_candidates": len(pushed_candidates),
        "pushed": len(top),
        "dry_run": args.dry_run,
        "items": [
            {k: it.get(k) for k in ("title", "link", "weight_score", "section", "subsection", "score_reason")}
            for it in fresh
        ],
    }
    (out / f"pipeline_{datetime.now():%Y-%m-%d}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\n[Pipeline] 完成: 采集 {len(articles)} / 新增 {len(fresh)} / 写入 {written} / 推送 {len(top)}")
    print(f"[Pipeline] 报告: output/pipeline_{datetime.now():%Y-%m-%d}.json")


if __name__ == "__main__":
    main()
