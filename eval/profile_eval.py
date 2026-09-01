"""
客户画像模块评测脚本
验证画像生成质量：格式合规、信息完整性、业务相关性
"""
import sys
import os
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.profile import generate_profile
from app.llm import chat_json


# ===== 评测指标定义 =====
# 1. 格式合规：必须包含所有必要字段
REQUIRED_FIELDS = [
    "company_name",
    "company_type",
    "founded",
    "headquarters",
    "scale",
    "core_business",
    "acquiring_business",
    "it_status",
    "recent_news",
    "sources",
]

# 2. 信息完整性：关键字段不为空且不是"未知/未找到"
INFORMATIVE_FIELDS = [
    "company_type",
    "core_business",
    "acquiring_business",
]

# 3. 业务相关性：收单业务描述是否到位（LLM 评分 0-1）
RELEVANCE_PROMPT = """你是一名支付行业评委。请评估客户画像中"收单业务"描述的质量。

公司：{company}
预期类型：{expected_type}
收单业务描述：
{acquiring_text}

【评分标准】只看描述本身的质量，不用做事实核查：
- 1.0：描述具体，包含收单业务的产品、规模、牌照或特色等信息
- 0.5：提到了收单相关业务，但描述较笼统
- 0.0：完全没有收单业务内容，或显示"暂无/未知"

【要求】直接输出 JSON，不要分析过程。
格式：{{"score": 0.5, "reason": "简短理由"}}"""


def evaluate_format(profile: dict) -> float:
    """格式合规评分：字段齐全度"""
    missing = [f for f in REQUIRED_FIELDS if f not in profile]
    if missing:
        print(f"    ❌ 缺失字段: {missing}")
        return 0.0
    return 1.0


def evaluate_informativeness(profile: dict) -> float:
    """信息完整性评分：关键字段是否有实质内容（非空值占位符）"""
    empty_markers = [
        "未知", "未找到足够信息", "未找到", "暂无公开信息",
        "暂无", "无公开信息", "画像生成失败", "未找到足够",
        "N/A", "n/a",
    ]
    filled = 0
    for field in INFORMATIVE_FIELDS:
        val = str(profile.get(field, "")).strip()
        # 检查是否是空值占位符
        is_empty = any(val.strip() == m or val.strip().startswith(m) for m in empty_markers)
        # 至少 2 个字符以上才算有实质内容
        if not is_empty and len(val.strip()) >= 2:
            filled += 1
        else:
            print(f"    ⚠️  {field} 信息不足: '{val[:60]}'")
    return filled / len(INFORMATIVE_FIELDS)


def evaluate_relevance(profile: dict, expected: dict) -> float:
    """业务相关性评分：收单业务描述质量"""
    acquiring_text = str(profile.get("acquiring_business", ""))

    prompt = RELEVANCE_PROMPT.format(
        company=expected.get("company_cn", expected["company"]),
        expected_type=expected.get("expected_type", ""),
        acquiring_text=acquiring_text[:1000],
    )

    try:
        from app.llm import chat as _chat
        raw_output = _chat(prompt, temperature=0, max_tokens=800)

        # 先尝试标准 JSON 提取
        from app.llm import _extract_json
        try:
            result = _extract_json(raw_output)
            score = float(result.get("score", 0))
            reason = result.get("reason", "")
        except Exception:
            # 兜底：正则提取 score 字段
            score_match = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', raw_output)
            if score_match:
                score = float(score_match.group(1))
                reason = "正则提取"
            else:
                print(f"    ❌ 无法提取评分")
                return 0.0
    except Exception as e:
        print(f"    ❌ 相关性评分失败: {e}")
        return 0.0

    print(f"    📊 收单相关性: {score:.1f} - {reason}")
    return score


def run_profile_eval(goldens_file: str = "eval/profile_goldens.jsonl") -> dict:
    """运行客户画像评测"""
    # 读取评测集
    goldens = []
    with open(goldens_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                goldens.append(json.loads(line))

    print(f"\n{'='*60}")
    print(f"客户画像评测 - {len(goldens)} 家机构")
    print(f"模型: {os.environ.get('LLM_MODEL', 'default')}")
    print(f"{'='*60}\n")

    results = []
    format_scores = []
    info_scores = []
    relevance_scores = []

    for i, golden in enumerate(goldens, 1):
        company = golden["company"]
        company_cn = golden.get("company_cn", company)
        print(f"[{i}/{len(goldens)}] {company_cn} ({company})")

        # 生成画像
        try:
            profile = generate_profile(company)
        except Exception as e:
            print(f"  ❌ 生成失败: {e}")
            results.append(
                {
                    "id": golden["id"],
                    "company": company,
                    "error": str(e),
                    "format_score": 0,
                    "info_score": 0,
                    "relevance_score": 0,
                }
            )
            format_scores.append(0)
            info_scores.append(0)
            relevance_scores.append(0)
            continue

        # 评测
        fmt_score = evaluate_format(profile)
        info_score = evaluate_informativeness(profile)
        rel_score = evaluate_relevance(profile, golden)

        format_scores.append(fmt_score)
        info_scores.append(info_score)
        relevance_scores.append(rel_score)

        # 保存结果
        results.append(
            {
                "id": golden["id"],
                "company": company,
                "company_cn": company_cn,
                "profile": profile,
                "format_score": fmt_score,
                "info_score": info_score,
                "relevance_score": rel_score,
            }
        )

        # 礼貌延迟
        time.sleep(1)
        print()

    # 计算汇总
    avg_format = sum(format_scores) / len(format_scores) if format_scores else 0
    avg_info = sum(info_scores) / len(info_scores) if info_scores else 0
    avg_relevance = sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0

    # 加权综合分：格式20% + 完整性30% + 相关性50%
    overall = avg_format * 0.2 + avg_info * 0.3 + avg_relevance * 0.5

    summary = {
        "timestamp": datetime.now().isoformat(),
        "model": os.environ.get("LLM_MODEL", "default"),
        "total_cases": len(goldens),
        "metrics": {
            "format_compliance": round(avg_format, 3),
            "informativeness": round(avg_info, 3),
            "business_relevance": round(avg_relevance, 3),
            "overall_weighted": round(overall, 3),
        },
        "results": results,
    }

    # 输出汇总
    print("=" * 60)
    print("评测汇总")
    print("=" * 60)
    print(f"  格式合规:   {avg_format:.2f}")
    print(f"  信息完整:   {avg_info:.2f}")
    print(f"  业务相关:   {avg_relevance:.2f}")
    print(f"  综合加权:   {overall:.2f}")
    print()

    # 逐条简表
    print(f"{'ID':<12} {'公司':<16} {'格式':<6} {'完整':<6} {'相关':<6}")
    print("-" * 50)
    for r in results:
        name = r.get("company_cn", r["company"])[:14]
        print(
            f"{r['id']:<12} {name:<16} "
            f"{r['format_score']:<6.1f} {r['info_score']:<6.1f} {r['relevance_score']:<6.1f}"
        )

    # 保存结果
    os.makedirs("eval/.evals", exist_ok=True)
    out_file = f"eval/.evals/profile_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存: {out_file}")

    return summary


if __name__ == "__main__":
    result = run_profile_eval()
    overall = result["metrics"]["overall_weighted"]
    # 综合分低于 0.7 退出码非零（用于 CI 门禁）
    sys.exit(0 if overall >= 0.7 else 1)
