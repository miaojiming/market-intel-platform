"""
简化版 AI Evals 评测脚本
（Python 3.8 兼容，MVP 阶段验证 AI 工程化核心思想）

功能：
1. 加载 golden dataset
2. 跑 LLM 生成结果
3. 多维度评测（格式合规、真实性、综合质量）
4. 输出分数 + 判断是否通过阈值
5. 支持基线对比（回归检测）

用法：
  python eval/run_eval.py                    # 跑评测
  python eval/run_eval.py --save-baseline    # 存为基线
  python eval/run_eval.py --baseline         # 和基线对比
  python eval/run_eval.py --fail-under 0.8   # 低于阈值失败（非零退出码）
"""
import os
import sys
import json
import argparse
from pathlib import Path

# 确保能 import app
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.llm import chat_json, chat

# ============ 配置 ============
EVAL_DIR = Path(__file__).parent
GOLDENS_FILE = EVAL_DIR / "goldens.jsonl"
PROMPT_FILE = EVAL_DIR / "prompts" / "summarize.txt"
BASELINE_FILE = EVAL_DIR / ".evals" / "baseline.json"

# 阈值配置
THRESHOLDS = {
    "schema_validation": 1.0,   # 格式必须100%正确
    "faithfulness": 0.85,       # 真实性 ≥ 85%
    "geval": 0.7,               # 综合质量 ≥ 70%
}

# 评委模型
JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL", "gpt-4o")
# 生成模型
TARGET_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")


# ============ 评测指标 ============

# 字段名映射（兼容中英文）
FIELD_MAP = {
    "summary_zh": ["summary_zh", "摘要", "summary", "内容", "中文摘要"],
    "tags": ["tags", "关键词", "标签", "关键词标签", "keywords"],
    "importance": ["importance", "重要性", "重要性评分", "重要程度", "score"],
    "source_name": ["source_name", "来源", "来源名称", "信息来源", "source"],
    "source_url": ["source_url", "链接", "原始链接", "url", "link", "原文链接"],
}


def _normalize_output(output: dict) -> dict:
    """标准化输出字段名（兼容中英文）"""
    if not isinstance(output, dict):
        return output
    normalized = {}
    for std_field, aliases in FIELD_MAP.items():
        for alias in aliases:
            if alias in output:
                normalized[std_field] = output[alias]
                break
    # 保留其他字段
    for k, v in output.items():
        if k not in normalized:
            normalized[k] = v
    return normalized


def eval_schema_validation(output: dict, expected: dict = None) -> float:
    """格式合规检查：是否包含必填字段"""
    output = _normalize_output(output)
    required_fields = ["summary_zh", "tags", "importance", "source_name", "source_url"]
    if not isinstance(output, dict):
        return 0.0
    passed = all(field in output for field in required_fields)
    # tags 必须是数组，importance 必须是整数
    if not isinstance(output.get("tags"), list):
        passed = False
    if not isinstance(output.get("importance"), int):
        passed = False
    return 1.0 if passed else 0.0


def eval_faithfulness(output: dict, input_text: str) -> float:
    """真实性检查：摘要是否有原文未提及的信息（LLM-as-judge）"""
    output = _normalize_output(output)
    summary = output.get("summary_zh", "")
    if not summary:
        return 0.0

    prompt = f"""请判断以下摘要是否真实反映原文，即摘要中的所有信息是否都能在原文中找到依据，没有编造或幻觉。

原文：
{input_text[:4000]}

摘要：
{summary}

请评分（0.0 到 1.0）：
- 1.0 = 完全真实，所有信息都有原文依据
- 0.8 = 基本真实，个别细节表述有偏差但核心信息正确
- 0.5 = 部分内容缺乏依据，或存在明显夸大
- 0.0 = 严重偏离原文，大量编造信息

只输出一个数字（0.0-1.0），不要解释。"""

    try:
        result = chat(prompt, system_prompt="你是一个严谨的评测评委。", model=JUDGE_MODEL, temperature=0, max_tokens=300)
        # 提取数字
        result = result.strip()
        import re
        match = re.search(r'0?\.\d+|1\.0|[01](?![0-9])', result)
        if match:
            score = float(match.group())
            return max(0.0, min(1.0, score))
    except Exception as e:
        print(f"    [真实性评测失败] {e}")

    return 0.5  # 失败时给中间分


def eval_geval(output: dict, input_text: str, expected: str) -> float:
    """综合质量评估（LLM-as-judge）"""
    output = _normalize_output(output)
    summary = output.get("summary_zh", "")
    tags = output.get("tags", [])
    importance = output.get("importance", 3)

    prompt = f"""请从以下三个维度评估情报摘要的质量，给出综合评分（0.0-1.0）：

【评估标准】
1. 摘要质量（40%）：是否简洁明了，80字以内，准确概括文章核心内容？
2. 标签质量（30%）：标签是否与收单/银行IT业务相关且贴切？
3. 重要性评分合理性（30%）：重要性评分是否合理？
   - 5分：收单费率变动、监管政策、银行收单系统改造/招标、核心系统替换、重大收单合约
   - 4分：POS/收单产品发布、收单机构动态、跨境收单创新、银行IT合作
   - 3分：行业数据报告、一般性融资动态
   - 1-2分：与收单/银行IT无关的内容

原文：
{input_text[:3000]}

AI生成的摘要：
{summary}

AI生成的标签：{tags}

AI给出的重要性：{importance}分

请输出一个0.0到1.0之间的数字表示综合评分。只输出数字，不要解释。"""

    try:
        result = chat(prompt, system_prompt="你是一个专业的情报质量评测专家。", model=JUDGE_MODEL, temperature=0, max_tokens=300)
        result = result.strip()
        import re
        match = re.search(r'0?\.\d+|1\.0|[01](?![0-9])', result)
        if match:
            score = float(match.group())
            return max(0.0, min(1.0, score))
    except Exception as e:
        print(f"    [综合质量评测失败] {e}")

    return 0.5


# ============ 主流程 ============

def load_goldens() -> list:
    """加载评测数据"""
    goldens = []
    with open(GOLDENS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                goldens.append(json.loads(line))
    return goldens


def run_target(input_text: str, prompt_template: str, context: dict = None) -> dict:
    """运行目标系统（这里直接调 LLM）"""
    ctx = context or {}
    prompt = prompt_template.format(
        article=input_text,
        source_name=ctx.get("source", "未知来源"),
        source_url=ctx.get("source_url", ctx.get("url", "")),
    )
    try:
        return chat_json(prompt, temperature=0.3, max_tokens=1500, model=TARGET_MODEL, use_json_mode=False)
    except Exception as e:
        print(f"  [生成失败] {e}")
        return {"summary_zh": "", "tags": [], "importance": 0, "source_name": "", "source_url": ""}


def run_eval() -> dict:
    """运行完整评测"""
    goldens = load_goldens()
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    print(f"\n{'='*60}")
    print(f"  AI Evals 评测开始")
    print(f"  测试用例: {len(goldens)} 条")
    print(f"  生成模型: {TARGET_MODEL}")
    print(f"  评委模型: {JUDGE_MODEL}")
    print(f"{'='*60}\n")

    all_scores = {
        "schema_validation": [],
        "faithfulness": [],
        "geval": [],
    }

    for i, golden in enumerate(goldens, 1):
        case_id = golden.get("id", f"case-{i}")
        input_text = golden.get("input", "")
        expected = golden.get("expected", "")

        print(f"[{i}/{len(goldens)}] {case_id}")

        # 1. 运行目标系统
        context = golden.get("context", {})
        output = run_target(input_text, prompt_template, context)

        # 2. 各指标评测
        s_schema = eval_schema_validation(output)
        s_faith = eval_faithfulness(output, input_text)
        s_geval = eval_geval(output, input_text, expected)

        all_scores["schema_validation"].append(s_schema)
        all_scores["faithfulness"].append(s_faith)
        all_scores["geval"].append(s_geval)

        print(f"    格式: {s_schema:.2f} | 真实性: {s_faith:.2f} | 综合: {s_geval:.2f}")

        # 每个 case 间隔 1 秒，避免触发速率限制
        import time
        time.sleep(1)

    # 计算平均分
    avg_scores = {
        metric: sum(scores) / len(scores) if scores else 0
        for metric, scores in all_scores.items()
    }

    # 计算整体通过率（加权）
    weights = {"schema_validation": 0.2, "faithfulness": 0.4, "geval": 0.4}
    overall = sum(avg_scores[m] * weights[m] for m in weights)

    # 判断各指标是否过阈值
    pass_status = {
        metric: avg >= THRESHOLDS[metric]
        for metric, avg in avg_scores.items()
    }
    all_passed = all(pass_status.values())

    print(f"\n{'='*60}")
    print(f"  评测结果")
    print(f"{'='*60}")
    for metric, avg in avg_scores.items():
        threshold = THRESHOLDS[metric]
        status = "✅ 通过" if pass_status[metric] else "❌ 未通过"
        print(f"  {metric:20s} {avg:.2f} / {threshold}  {status}")
    print(f"  {'-'*50}")
    print(f"  综合加权分: {overall:.2f}")
    print(f"  整体状态: {'✅ 全部通过' if all_passed else '❌ 有指标未通过'}")
    print()

    result = {
        "avg_scores": avg_scores,
        "overall": overall,
        "all_passed": all_passed,
        "pass_status": pass_status,
        "thresholds": THRESHOLDS,
        "case_count": len(goldens),
    }
    return result


def save_baseline(result: dict):
    """保存基线"""
    BASELINE_FILE.parent.mkdir(exist_ok=True)
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"💾 基线已保存到: {BASELINE_FILE}")


def compare_baseline(result: dict):
    """和基线对比"""
    if not BASELINE_FILE.exists():
        print("⚠️  未找到基线文件，请先使用 --save-baseline 保存")
        return

    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    print(f"\n{'='*60}")
    print(f"  基线对比")
    print(f"{'='*60}")

    tolerance = 0.03  # 容忍度 3%
    has_regression = False

    for metric, current in result["avg_scores"].items():
        base = baseline["avg_scores"].get(metric, current)
        delta = current - base
        direction = "📈" if delta > 0.01 else ("📉" if delta < -0.01 else "➖")
        status = ""
        if delta < -tolerance:
            status = " ⚠️ 回归"
            has_regression = True
        print(f"  {metric:20s} 基线: {base:.2f}  当前: {current:.2f}  变化: {delta:+.2f} {direction}{status}")

    print()
    if has_regression:
        print("❌ 检测到质量回归！")
    else:
        print("✅ 无明显回归，质量稳定或提升")
    print()

    return has_regression


def main():
    parser = argparse.ArgumentParser(description="AI Evals 评测工具")
    parser.add_argument("--save-baseline", action="store_true", help="保存为基线")
    parser.add_argument("--baseline", action="store_true", help="和基线对比")
    parser.add_argument("--fail-under", type=float, default=0.0, help="综合分低于此值则失败（退出码非零）")
    args = parser.parse_args()

    result = run_eval()

    if args.save_baseline:
        save_baseline(result)

    if args.baseline:
        has_regression = compare_baseline(result)
        if has_regression:
            sys.exit(1)

    if args.fail_under > 0 and result["overall"] < args.fail_under:
        print(f"❌ 综合分 {result['overall']:.2f} 低于阈值 {args.fail_under}，评测失败")
        sys.exit(1)

    if not result["all_passed"]:
        print("❌ 有指标未通过阈值")
        sys.exit(1)

    print("✅ 评测通过")


if __name__ == "__main__":
    main()
