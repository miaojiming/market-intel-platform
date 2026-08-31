#!/usr/bin/env python3
"""
数据飞轮 - 新用例添加工具
将新采集的文章添加到评测集，持续扩充黄金标准

用法:
  python scripts/add_golden.py --id case-011 --input "文章内容" --source "来源" --url "链接"
  python scripts/add_golden.py --from-article-url "https://example.com/article"
"""

import argparse
import json
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
GOLDENS_FILE = ROOT / "eval" / "goldens.jsonl"


def add_golden(case_id, article_text, source_name, source_url, expected_summary=None, importance=None):
    """添加一条新用例到评测集"""
    entry = {
        "id": case_id,
        "input": article_text,
        "context": {
            "source": source_name,
            "source_url": source_url,
        },
    }

    if expected_summary:
        expected = {"summary_zh": expected_summary}
        if importance is not None:
            expected["importance"] = importance
        entry["expected"] = json.dumps(expected, ensure_ascii=False)
    else:
        entry["expected"] = ""

    with open(GOLDENS_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"✅ 已添加 {case_id} 到评测集")
    print(f"   来源: {source_name}")
    print(f"   链接: {source_url}")
    print(f"   文章长度: {len(article_text)} 字符")
    if expected_summary:
        print(f"   预期摘要: {expected_summary[:100]}...")
    print(f"   当前评测集总量: {count_goldens()} 条")


def count_goldens():
    """统计当前评测集数量"""
    if not GOLDENS_FILE.exists():
        return 0
    with open(GOLDENS_FILE) as f:
        return sum(1 for line in f if line.strip())


def main():
    parser = argparse.ArgumentParser(description="添加新用例到评测集")
    parser.add_argument("--id", required=True, help="用例ID，如 case-011")
    parser.add_argument("--input", required=True, help="文章内容")
    parser.add_argument("--source", required=True, help="来源名称")
    parser.add_argument("--url", required=True, help="来源链接")
    parser.add_argument("--expected", help="预期摘要（可选）")
    parser.add_argument("--importance", type=int, help="预期重要性 1-5（可选）")

    args = parser.parse_args()

    add_golden(
        case_id=args.id,
        article_text=args.input,
        source_name=args.source,
        source_url=args.url,
        expected_summary=args.expected,
        importance=args.importance,
    )


if __name__ == "__main__":
    main()
