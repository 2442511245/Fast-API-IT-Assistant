#!/usr/bin/env python3
"""
evaluate_rag.py — RAG 检索增强生成评估脚本

功能：
  1. 加载 eval_qa.json 评估数据集
  2. 使用项目现有 RAG 流水线逐条回答问题
  3. 基于 expected_keywords 计算关键词匹配指标
  4. 区分知识库内/外问题，分别统计
  5. 输出控制台报告 + 保存详细结果 JSON

用法：
  # 使用默认参数运行完整评估
  python evaluate_rag.py

  # 指定 ChromaDB 和评估集路径
  python evaluate_rag.py --db-dir ./chroma_db --eval-file data/eval_qa.json

  # 仅评估前 N 条（快速验证）
  python evaluate_rag.py --limit 10

  # 输出 JSON 报告到指定路径
  python evaluate_rag.py --output results/eval_report.json

  # 静默模式（仅输出 JSON，适合 CI）
  python evaluate_rag.py --quiet

依赖：
  - DASHSCOPE_API_KEY 环境变量或 config.txt（LLM 调用需要）
  - ChromaDB 已构建（先运行 scripts/seed_knowledge_base.py）
  - bge-small-zh 嵌入模型（首次自动下载）

指标说明：
  - keyword_precision：回答中包含的期望关键词数 / 回答中检测到的总词数
  - keyword_recall：回答中包含的期望关键词数 / 期望关键词总数
  - keyword_f1：precision 和 recall 的调和平均
  - hit_rate：至少命中 1 个关键词的问题比例
  - out_of_kb_detect_rate：知识库外问题被正确识别（说"无法找到"）的比例
  - source_rate：检索到来源文档的问题比例
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# 将项目根目录加入 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 评估指标计算
# ============================================================

def keyword_match_score(answer: str, expected_keywords: List[str]) -> Dict:
    """
    计算答案与期望关键词的匹配分数

    返回:
      {
        "matched": ["关键词1", ...],      # 命中的关键词
        "missed": ["关键词2", ...],        # 未命中的关键词
        "precision": float,               # 命中数 / 期望数（简化 precision）
        "recall": float,                  # 命中数 / 期望数
        "f1": float,
      }
    """
    if not expected_keywords:
        return {
            "matched": [],
            "missed": [],
            "precision": 1.0,  # 无期望关键词视为通过
            "recall": 1.0,
            "f1": 1.0,
        }

    answer_lower = answer.lower()
    matched = []
    missed = []

    for kw in expected_keywords:
        if kw.lower() in answer_lower:
            matched.append(kw)
        else:
            missed.append(kw)

    recall = len(matched) / len(expected_keywords)
    # precision 简化：命中数 / 期望数（与 recall 相同，因为分母是固定的 expected）
    precision = recall
    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0

    return {
        "matched": matched,
        "missed": missed,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def is_out_of_kb_response(answer: str) -> bool:
    """
    判断回答是否表明知识库中未找到答案
    匹配多种"无法回答"的表述
    """
    refusal_patterns = [
        "无法从知识库中找到",
        "无法找到相关",
        "已自动创建工单",
        "知识库中没有",
        "未找到相关",
        "无法回答",
        "没有找到",
    ]
    answer_lower = answer.lower()
    return any(p.lower() in answer_lower for p in refusal_patterns)


# ============================================================
# 评估主流程
# ============================================================

def load_eval_dataset(file_path: str) -> List[Dict]:
    """加载评估数据集"""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def run_evaluation(
    eval_file: str,
    db_dir: str = "./chroma_db",
    limit: Optional[int] = None,
    verbose: bool = True,
) -> Dict:
    """
    运行完整 RAG 评估

    参数:
      eval_file: 评估数据集 JSON 路径
      db_dir: ChromaDB 向量库目录
      limit: 仅评估前 N 条（用于快速验证）
      verbose: 是否打印进度

    返回:
      包含 summary 和 details 的评估报告 dict
    """
    from langchain_community.vectorstores import Chroma
    from rag.core.rag import get_embedding, build_rag_chain, ask_question

    # 1. 加载数据
    dataset = load_eval_dataset(eval_file)
    if limit:
        dataset = dataset[:limit]

    in_kb_items = [d for d in dataset if d["answer_type"] == "in_kb"]
    out_kb_items = [d for d in dataset if d["answer_type"] == "out_of_kb"]

    if verbose:
        print("=" * 60)
        print("  RAG 检索增强生成 — 自动化评估")
        print("=" * 60)
        print(f"  评估集：{eval_file}")
        print(f"  向量库：{db_dir}")
        print(f"  总条目：{len(dataset)}（库内 {len(in_kb_items)} + 库外 {len(out_kb_items)}）")
        print()

    # 2. 加载向量库 + 构建 RAG 链
    if verbose:
        print("[..] 加载向量库和嵌入模型...")
    t0 = time.time()

    try:
        embedding = get_embedding()
        db = Chroma(
            persist_directory=db_dir,
            embedding_function=embedding,
        )
        chain, retriever = build_rag_chain(db)
        if verbose:
            print(f"[OK] 向量库加载完成，耗时 {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"[FAIL] 向量库加载失败：{e}")
        print(f"     请先运行 scripts/seed_knowledge_base.py 构建知识库")
        raise

    # 3. 逐条评估
    if verbose:
        print(f"\n[..] 开始评估（共 {len(dataset)} 条）...\n")

    details = []
    for i, item in enumerate(dataset):
        qid = item["id"]
        question = item["question"]
        expected_kw = item.get("expected_keywords", [])
        answer_type = item["answer_type"]
        category = item["category"]
        difficulty = item["difficulty"]

        if verbose:
            print(f"  [{i + 1}/{len(dataset)}] #{qid} [{category}] {question[:50]}...", end=" ")

        try:
            t_start = time.time()
            answer, sources = ask_question(chain, retriever, question)
            elapsed = time.time() - t_start

            # 关键词匹配
            kw_result = keyword_match_score(answer, expected_kw)

            # 是否命中来源
            has_sources = len(sources) > 0

            # 知识库外检测
            is_refused = is_out_of_kb_response(answer)

            # 判断对错
            if answer_type == "out_of_kb":
                # 期望：拒绝回答
                correct = is_refused
            else:
                # 期望：命中至少一半关键词
                correct = kw_result["recall"] >= 0.5

            detail = {
                "id": qid,
                "question": question,
                "category": category,
                "difficulty": difficulty,
                "answer_type": answer_type,
                "answer": answer,
                "source_count": len(sources),
                "source_previews": [s.page_content[:150] for s in sources[:2]],
                "expected_keywords": expected_kw,
                "matched_keywords": kw_result["matched"],
                "missed_keywords": kw_result["missed"],
                "keyword_precision": kw_result["precision"],
                "keyword_recall": kw_result["recall"],
                "keyword_f1": kw_result["f1"],
                "has_sources": has_sources,
                "is_refused": is_refused,
                "correct": correct,
                "elapsed_sec": round(elapsed, 2),
            }
            details.append(detail)

            status = "OK" if correct else "MISS"
            if verbose:
                print(f"{status} (recall={kw_result['recall']:.2f}, srcs={len(sources)}, {elapsed:.1f}s)")

        except Exception as e:
            detail = {
                "id": qid,
                "question": question,
                "category": category,
                "difficulty": difficulty,
                "answer_type": answer_type,
                "answer": f"ERROR: {str(e)}",
                "source_count": 0,
                "source_previews": [],
                "expected_keywords": expected_kw,
                "matched_keywords": [],
                "missed_keywords": expected_kw,
                "keyword_precision": 0.0,
                "keyword_recall": 0.0,
                "keyword_f1": 0.0,
                "has_sources": False,
                "is_refused": False,
                "correct": False,
                "elapsed_sec": 0.0,
            }
            details.append(detail)
            if verbose:
                print(f"ERROR: {e}")

    # 4. 汇总统计
    in_kb_details = [d for d in details if d["answer_type"] == "in_kb"]
    out_kb_details = [d for d in details if d["answer_type"] == "out_of_kb"]

    def avg(values: List[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    summary = {
        "total": len(details),
        "correct": sum(1 for d in details if d["correct"]),
        "accuracy": round(sum(1 for d in details if d["correct"]) / len(details), 4)
        if details
        else 0.0,

        # 知识库内指标
        "in_kb": {
            "total": len(in_kb_details),
            "correct": sum(1 for d in in_kb_details if d["correct"]),
            "avg_keyword_recall": round(avg([d["keyword_recall"] for d in in_kb_details]), 4),
            "avg_keyword_f1": round(avg([d["keyword_f1"] for d in in_kb_details]), 4),
            "hit_rate": round(
                sum(1 for d in in_kb_details if d["keyword_recall"] > 0) / len(in_kb_details), 4
            )
            if in_kb_details
            else 0.0,
            "source_rate": round(
                sum(1 for d in in_kb_details if d["has_sources"]) / len(in_kb_details), 4
            )
            if in_kb_details
            else 0.0,
            "avg_elapsed_sec": round(avg([d["elapsed_sec"] for d in in_kb_details]), 2),
        },

        # 知识库外指标
        "out_of_kb": {
            "total": len(out_kb_details),
            "correct": sum(1 for d in out_kb_details if d["correct"]),
            "detect_rate": round(
                sum(1 for d in out_kb_details if d["is_refused"]) / len(out_kb_details), 4
            )
            if out_kb_details
            else 0.0,
        },

        # 按难度汇总
        "by_difficulty": {},
        "by_category": {},
    }

    # 按难度
    for diff in ["easy", "medium", "hard"]:
        items = [d for d in details if d["difficulty"] == diff]
        if items:
            summary["by_difficulty"][diff] = {
                "total": len(items),
                "correct": sum(1 for d in items if d["correct"]),
                "accuracy": round(sum(1 for d in items if d["correct"]) / len(items), 4),
            }

    # 按分类
    for cat in sorted(set(d["category"] for d in details)):
        items = [d for d in details if d["category"] == cat]
        if items:
            summary["by_category"][cat] = {
                "total": len(items),
                "correct": sum(1 for d in items if d["correct"]),
                "accuracy": round(sum(1 for d in items if d["correct"]) / len(items), 4),
            }

    return {"summary": summary, "details": details}


# ============================================================
# 报告输出
# ============================================================

def print_report(report: Dict) -> None:
    """打印控制台评估报告"""
    s = report["summary"]

    print("\n" + "=" * 60)
    print("  评估结果汇总")
    print("=" * 60)

    print(f"\n  整体指标：")
    print(f"    总问题数：{s['total']}")
    print(f"    正确数：  {s['correct']}")
    print(f"    准确率：  {s['accuracy']:.1%}")

    print(f"\n  知识库内问题 ({s['in_kb']['total']} 条)：")
    print(f"    关键词命中率：  {s['in_kb']['hit_rate']:.1%}")
    print(f"    平均关键词召回：{s['in_kb']['avg_keyword_recall']:.3f}")
    print(f"    平均 F1：        {s['in_kb']['avg_keyword_f1']:.3f}")
    print(f"    来源命中率：    {s['in_kb']['source_rate']:.1%}")
    print(f"    平均耗时：      {s['in_kb']['avg_elapsed_sec']}s")

    print(f"\n  知识库外问题 ({s['out_of_kb']['total']} 条)：")
    print(f"    拒答检测率：    {s['out_of_kb']['detect_rate']:.1%}")

    if s["by_difficulty"]:
        print(f"\n  按难度分布：")
        for diff, stats in s["by_difficulty"].items():
            bar = "█" * int(stats["accuracy"] * 20)
            print(f"    {diff:<8} {stats['accuracy']:.1%} {bar} ({stats['correct']}/{stats['total']})")

    if s["by_category"]:
        print(f"\n  按分类分布：")
        for cat, stats in s["by_category"].items():
            bar = "█" * int(stats["accuracy"] * 20)
            print(f"    {cat:<16} {stats['accuracy']:.1%} {bar} ({stats['correct']}/{stats['total']})")

    print(f"\n{'=' * 60}")


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="RAG 检索增强生成评估脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  %(prog)s                                       # 默认评估
  %(prog)s --limit 10                            # 仅评估前 10 条
  %(prog)s --db-dir ./chroma_db                   # 指定向量库
  %(prog)s --output results/report.json           # 保存报告
  %(prog)s --quiet --output results/ci_report.json # CI 模式
        """,
    )
    parser.add_argument(
        "--eval-file",
        type=str,
        default="data/eval_qa.json",
        help="评估数据集 JSON 路径（默认：data/eval_qa.json）",
    )
    parser.add_argument(
        "--db-dir",
        type=str,
        default="./chroma_db",
        help="ChromaDB 向量库目录（默认：./chroma_db）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="仅评估前 N 条（用于快速验证）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="评估结果 JSON 输出路径（不指定则不保存文件）",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="静默模式（不打印进度，仅输出最终报告或 JSON）",
    )

    args = parser.parse_args()

    # 检查前置条件
    if not Path(args.eval_file).exists():
        print(f"[FAIL] 评估集不存在：{args.eval_file}")
        sys.exit(1)

    if not Path(args.db_dir).exists():
        print(f"[FAIL] 向量库不存在：{args.db_dir}")
        print(f"     请先运行 scripts/seed_knowledge_base.py 构建知识库")
        sys.exit(1)

    # 检查 API Key
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        config_path = PROJECT_ROOT / "config.txt"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                api_key = f.read().strip()
        if not api_key:
            print("[FAIL] 未设置 DASHSCOPE_API_KEY 环境变量，且 config.txt 为空")
            print("     请设置 export DASHSCOPE_API_KEY='your-key'")
            sys.exit(1)

    # 运行评估
    report = run_evaluation(
        eval_file=args.eval_file,
        db_dir=args.db_dir,
        limit=args.limit,
        verbose=not args.quiet,
    )

    # 输出
    if not args.quiet:
        print_report(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[OK] 评估报告已保存：{output_path}")
    elif args.quiet:
        # 静默模式输出 JSON 到 stdout
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
