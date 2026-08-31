#!/usr/bin/env python3
"""
数据飞轮 - 持续进化流水线
每次运行：采集新文章 → 生成摘要 → 跑评测 → 对比基线 → 输出报告
用法: python scripts/eval_pipeline.py
"""

import json
import os
import sys
import time
import shutil
from datetime import datetime
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

EVAL_DIR = ROOT / "eval"
EVALS_DIR = EVAL_DIR / ".evals"
BASELINE_FILE = EVALS_DIR / "baseline.json"
GOLDENS_FILE = EVAL_DIR / "goldens.jsonl"
PROMPTS_DIR = EVAL_DIR / "prompts"
HISTORY_DIR = EVALS_DIR / "history"


def load_baseline():
    """加载当前基线"""
    if not BASELINE_FILE.exists():
        return None
    with open(BASELINE_FILE) as f:
        return json.load(f)


def load_goldens():
    """加载评测集"""
    with open(GOLDENS_FILE) as f:
        return [json.loads(line) for line in f if line.strip()]


def run_evaluation(goldens, prompt_tpl, model="z-ai/glm-5.3-flash"):
    """对评测集跑一轮评测，返回逐条结果和汇总"""
    from app.llm import chat_json
    from eval.run_eval import (
        eval_schema_validation, eval_faithfulness, eval_geval,
        _normalize_output, THRESHOLDS
    )

    results = []
    for i, golden in enumerate(goldens, 1):
        time.sleep(2)
        case_id = golden.get("id", f"case-{i}")
        ctx = golden.get("context", {})
        prompt = prompt_tpl.format(
            article=golden["input"],
            source_name=ctx.get("source", "未知来源"),
            source_url=ctx.get("source_url", ""),
        )

        try:
            output = chat_json(prompt, temperature=0.3, max_tokens=4000, use_json_mode=False)
            norm = _normalize_output(output)
            s_schema = eval_schema_validation(output)
            s_faith = eval_faithfulness(output, golden["input"])
            s_ge = eval_geval(output, golden["input"], golden.get("expected", ""))
        except Exception as e:
            norm = {"summary_zh": f"(失败: {e})", "tags": [], "importance": 0}
            s_schema, s_faith, s_ge = 0, 0, 0.5

        results.append({
            "id": case_id,
            "source_name": ctx.get("source", ""),
            "source_url": ctx.get("source_url", ""),
            "summary_zh": norm.get("summary_zh", ""),
            "tags": norm.get("tags", []),
            "importance": norm.get("importance", ""),
            "scores": {
                "schema_validation": s_schema,
                "faithfulness": s_faith,
                "geval": s_ge,
            },
        })
        print(f"  [{i}/{len(goldens)}] {case_id}: 格式={s_schema:.0f} 真实={s_faith:.2f} 综合={s_ge:.2f}")

    total = len(results)
    avg_schema = sum(r["scores"]["schema_validation"] for r in results) / total
    avg_faith = sum(r["scores"]["faithfulness"] for r in results) / total
    avg_ge = sum(r["scores"]["geval"] for r in results) / total
    overall = avg_schema * 0.2 + avg_faith * 0.4 + avg_ge * 0.4

    return {
        "model": model,
        "total_cases": total,
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "schema_validation": round(avg_schema, 4),
            "faithfulness": round(avg_faith, 4),
            "geval": round(avg_ge, 4),
            "overall_weighted": round(overall, 4),
        },
        "cases": results,
    }


def compare_with_baseline(current, baseline):
    """对比当前结果与基线，输出变化"""
    if not baseline:
        return {"status": "no_baseline", "message": "无基线可对比"}

    b = baseline["metrics"]
    c = current["summary"]
    diffs = {}
    for metric in ["schema_validation", "faithfulness", "geval", "overall_weighted"]:
        old = b.get(metric, 0)
        new = c.get(metric, 0)
        diff = new - old
        diffs[metric] = {
            "old": old,
            "new": new,
            "diff": round(diff, 4),
            "trend": "↑" if diff > 0.01 else ("↓" if diff < -0.01 else "→"),
        }

    # 回归检测
    regressions = []
    for metric, info in diffs.items():
        if info["diff"] < -0.05:
            regressions.append(f"{metric}: {info['old']:.2f} → {info['new']:.2f} (↓{abs(info['diff']):.2f})")

    return {
        "status": "regression" if regressions else "improved_or_stable",
        "diffs": diffs,
        "regressions": regressions,
        "message": "检测到回归!" if regressions else "无回归，质量稳定或提升",
    }


def save_history(report, comparison):
    """保存历史记录，用于追踪进化轨迹"""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    record = {
        "timestamp": ts,
        "run_at": report["run_at"],
        "metrics": report["summary"],
        "comparison": comparison,
    }
    history_file = HISTORY_DIR / f"run_{ts}.json"
    with open(history_file, "w") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return history_file


def update_baseline_if_better(report, comparison):
    """如果结果优于基线，自动更新基线"""
    if comparison["status"] == "no_baseline":
        return False

    current = report["summary"]["overall_weighted"]
    baseline_score = comparison["diffs"]["overall_weighted"]["old"]

    if current > baseline_score + 0.01:
        # 更新基线
        baseline = {
            "baseline_name": f"Auto-updated {datetime.now().strftime('%Y-%m-%d')}",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": report["model"],
            "metrics": report["summary"],
            "cases_count": report["total_cases"],
        }
        with open(BASELINE_FILE, "w") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)
        return True
    return False


def generate_evolution_report(report, comparison):
    """生成进化报告"""
    lines = []
    lines.append("=" * 60)
    lines.append("数据飞轮 - 进化报告")
    lines.append("=" * 60)
    lines.append(f"运行时间: {report['run_at']}")
    lines.append(f"模型: {report['model']}")
    lines.append(f"用例数: {report['total_cases']}")
    lines.append("")

    c = report["summary"]
    lines.append("当前得分:")
    lines.append(f"  格式: {c['schema_validation']:.2f}")
    lines.append(f"  真实: {c['faithfulness']:.2f}")
    lines.append(f"  综合: {c['geval']:.2f}")
    lines.append(f"  加权: {c['overall_weighted']:.2f}")
    lines.append("")

    if comparison["status"] != "no_baseline":
        lines.append("基线对比:")
        for metric, info in comparison["diffs"].items():
            icon = "✅" if info["diff"] >= 0 else "❌"
            lines.append(f"  {icon} {metric}: {info['old']:.2f} → {info['new']:.2f} ({info['trend']}{abs(info['diff']):.2f})")
        lines.append("")

        if comparison["regressions"]:
            lines.append("⚠️ 回归告警:")
            for r in comparison["regressions"]:
                lines.append(f"  - {r}")
        else:
            lines.append("✅ 无回归，质量稳定或提升")
    else:
        lines.append("(首次运行，无基线对比)")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    """主入口"""
    print("数据飞轮 - 持续进化流水线")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 1. 加载基线和评测集
    baseline = load_baseline()
    goldens = load_goldens()

    with open(PROMPTS_DIR / "summarize.txt") as f:
        prompt_tpl = f.read()

    print(f"评测集: {len(goldens)} 条用例")
    print(f"基线: {baseline['baseline_name'] if baseline else '无'}")
    print()

    # 2. 跑评测
    print("正在运行评测...")
    report = run_evaluation(goldens, prompt_tpl)

    # 3. 对比基线
    comparison = compare_with_baseline(report, baseline)

    # 4. 输出报告
    evolution_report = generate_evolution_report(report, comparison)
    print()
    print(evolution_report)

    # 5. 保存历史
    history_file = save_history(report, comparison)
    print(f"历史记录: {history_file}")

    # 6. 自动更新基线（如果更好）
    if update_baseline_if_better(report, comparison):
        print("✅ 质量提升，已自动更新基线")
    elif comparison["status"] != "no_baseline":
        print("→ 未超过基线，保持当前基线")

    # 7. 保存详细结果
    result_file = EVALS_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_file, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"详细结果: {result_file}")

    # 8. 回归告警退出码
    if comparison.get("regressions"):
        print("\n❌ 检测到回归，退出码 1（可用于 CI 门禁）")
        sys.exit(1)
    else:
        print("\n✅ 无回归，退出码 0")
        sys.exit(0)


if __name__ == "__main__":
    main()
