#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""benchmark.py -- 章节质量基线评测脚本 v1.0.0（纯标准库，无第三方依赖）。

建立和比较章节质量基线，帮助作者量化跟踪写作质量变化趋势。

五维评测：
  1. ai_score       -- AI 味分数（0-100，越低越好）
  2. avg_sent_len   -- 平均句长（字数）
  3. dialogue_ratio -- 对话占比（引号内字数/总字数，百分比）
  4. rhythm_balance -- 节奏均衡度（段落长度标准差归一化到 0-100，越小越均衡）
  5. gate_pass_rate -- 门禁通过率（1.0=全通过，0.0=未通过）

子命令：
  eval     单章评测
  book     全书评测
  save     评测并保存为基线
  compare  与已存基线对比
  trend    最近 N 章趋势

用法：
  python scripts/benchmark.py eval "{章节文件}"
  python scripts/benchmark.py book "{书名目录}"
  python scripts/benchmark.py save "{书名目录}"
  python scripts/benchmark.py compare "{书名目录}"
  python scripts/benchmark.py trend "{书名目录}" --chapters 5

退出码：0 = 成功；1 = 评测异常/基线对比有退化；2 = 参数/文件错误。
"""

import argparse
import datetime
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# 模块导入（带 ImportError 回退）
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import config
    BENCHMARK_METRICS = getattr(config, "BENCHMARK_METRICS", None) or [
        "ai_score", "gate_pass_rate", "avg_sent_len", "dialogue_ratio", "rhythm_balance"
    ]
except ImportError:
    config = None
    BENCHMARK_METRICS = [
        "ai_score", "gate_pass_rate", "avg_sent_len", "dialogue_ratio", "rhythm_balance"
    ]

try:
    import check_text as ct
    _HAS_CHECK_TEXT = True
except ImportError:
    ct = None
    _HAS_CHECK_TEXT = False

try:
    import style_fingerprint as sf
    _HAS_SF = True
except ImportError:
    sf = None
    _HAS_SF = False


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def _cjk_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _find_chapter_files(book_dir: Path) -> List[Tuple[int, Path]]:
    """返回 (章节号, 路径) 列表，按章号排序。"""
    text_dir = book_dir / "正文"
    if not text_dir.exists():
        return []
    results = []
    for f in text_dir.glob("*.md"):
        m = re.search(r"第\s*(\d+)\s*章", f.name)
        if m:
            results.append((int(m.group(1)), f))
    results.sort(key=lambda x: x[0])
    return results


# ---------------------------------------------------------------------------
# 单章评测
# ---------------------------------------------------------------------------

def evaluate_chapter(chapter_path: Path) -> Dict[str, Any]:
    """五维评测单章，返回评分字典。"""
    text = _read_file(chapter_path)
    non_ws = len(re.sub(r"\s", "", text))
    cjk = _cjk_chars(text)
    if non_ws == 0:
        return {"error": "文件为空或无法读取"}

    # 1. ai_score：优先用 check_text 计算，失败时回退到简单启发式
    ai_score = 0.0
    if _HAS_CHECK_TEXT:
        try:
            lines = text.splitlines()
            words = list(ct.BANNED_WORDS)
            _, toxic = ct.scan_lines(lines, words)
            blocking_hits = ct.scan_blocking_patterns(lines)
            trailer_hits = ct.scan_trailer(text)
            n_blocking = len([h for h in _ if h[5] == "blocking" for _ in [toxic]])
            n_blocking += len(blocking_hits) + len(trailer_hits)
            kilo = max(non_ws / 1000.0, 0.001)
            ai_score = min(100.0, n_blocking * 5 / kilo)
        except Exception:
            ai_score = 0.0
    else:
        # 回退：统计禁用词密度
        banned = ["仿佛", "似乎", "不禁", "一丝", "嘴角", "眼底"]
        count = sum(text.count(w) for w in banned)
        ai_score = min(100.0, count * 3 / max(non_ws / 1000.0, 0.001))

    # 2. avg_sent_len：平均句长
    sents = [s for s in re.split(r"[。！？!?…]+", text) if s.strip()]
    avg_sent_len = cjk / max(len(sents), 1)

    # 3. dialogue_ratio：对话占比
    quotes = re.findall(r"「[^」]*」|\"[^\"]*\"", text)
    dialogue_chars = sum(len(re.sub(r"\s", "", q)) for q in quotes)
    dialogue_ratio = dialogue_chars / non_ws * 100 if non_ws else 0

    # 4. rhythm_balance：段落长度标准差归一化
    paras = [len(re.sub(r"\s", "", p)) for p in text.splitlines() if p.strip()]
    if len(paras) >= 2:
        para_std = statistics.stdev(paras)
        # 归一化：标准差 0-300 映射到 0-100
        rhythm_balance = min(100.0, para_std / 3.0)
    else:
        rhythm_balance = 0.0

    # 5. gate_pass_rate：简单估算（无 check_text 时默认 1.0）
    gate_pass_rate = 1.0 if ai_score < 30 else (0.5 if ai_score < 60 else 0.0)

    return {
        "file": str(chapter_path.name),
        "chars": non_ws,
        "cjk": cjk,
        "ai_score": round(ai_score, 1),
        "avg_sent_len": round(avg_sent_len, 1),
        "dialogue_ratio": round(dialogue_ratio, 1),
        "rhythm_balance": round(rhythm_balance, 1),
        "gate_pass_rate": round(gate_pass_rate, 2),
    }


# ---------------------------------------------------------------------------
# 全书评测
# ---------------------------------------------------------------------------

def evaluate_book(book_dir: Path) -> Dict[str, Any]:
    chapters = _find_chapter_files(book_dir)
    if not chapters:
        return {"error": "未找到正文章节"}

    results = []
    for ch_num, ch_path in chapters:
        score = evaluate_chapter(ch_path)
        if "error" not in score:
            score["chapter"] = ch_num
            results.append(score)

    if not results:
        return {"error": "所有章节评测失败"}

    # 汇总统计
    summary = {}
    for metric in BENCHMARK_METRICS:
        vals = [r[metric] for r in results if metric in r]
        if vals:
            summary[f"avg_{metric}"] = round(sum(vals) / len(vals), 2)
            summary[f"min_{metric}"] = round(min(vals), 2)
            summary[f"max_{metric}"] = round(max(vals), 2)
            if len(vals) >= 2:
                summary[f"std_{metric}"] = round(statistics.stdev(vals), 2)

    # 趋势：后1/3 vs 前1/3
    n = len(results)
    if n >= 6:
        split = max(1, n // 3)
        front = results[:split]
        back = results[-split:]
        for metric in BENCHMARK_METRICS:
            fvals = [r[metric] for r in front if metric in r]
            bvals = [r[metric] for r in back if metric in r]
            if fvals and bvals:
                summary[f"trend_{metric}"] = round(
                    sum(bvals) / len(bvals) - sum(fvals) / len(fvals), 2
                )

    return {
        "version": VERSION,
        "evaluated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "total_chapters": n,
        "chapters": results,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 基线管理
# ---------------------------------------------------------------------------

def baseline_path(book_dir: Path) -> Path:
    return book_dir / "追踪" / "benchmark_baseline.json"


def save_baseline(book_dir: Path) -> Dict[str, Any]:
    result = evaluate_book(book_dir)
    if "error" in result:
        return result
    path = baseline_path(book_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except OSError as e:
        return {"error": f"无法写入基线文件: {e}"}
    result["saved_to"] = str(path)
    return result


def load_baseline(book_dir: Path) -> Optional[Dict[str, Any]]:
    path = baseline_path(book_dir)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def compare_baseline(book_dir: Path) -> Dict[str, Any]:
    current = evaluate_book(book_dir)
    baseline = load_baseline(book_dir)
    if "error" in current:
        return current
    if not baseline:
        return {"error": "未找到基线文件，请先运行 save 命令"}

    comparison = {}
    for metric in BENCHMARK_METRICS:
        ckey = f"avg_{metric}"
        cval = current.get("summary", {}).get(ckey)
        bval = baseline.get("summary", {}).get(ckey)
        if cval is not None and bval is not None:
            diff = round(cval - bval, 2)
            pct = round(diff / bval * 100, 1) if bval != 0 else 0.0
            comparison[metric] = {
                "current": cval,
                "baseline": bval,
                "diff": diff,
                "pct": pct,
            }

    # 判定退化
    degraded = []
    for metric, data in comparison.items():
        if metric == "ai_score" and data["diff"] > 5:
            degraded.append(f"{metric} 上升 {data['diff']:.1f}（AI 味加重）")
        elif metric == "gate_pass_rate" and data["diff"] < -0.1:
            degraded.append(f"{metric} 下降 {abs(data['diff']):.2f}（门禁通过率下降）")
        elif metric == "avg_sent_len" and abs(data["diff"]) > 5:
            degraded.append(f"{metric} 变化 {data['diff']:.1f}（句长波动）")

    return {
        "version": VERSION,
        "compared_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "comparison": comparison,
        "degraded": degraded,
        "has_degradation": len(degraded) > 0,
    }


# ---------------------------------------------------------------------------
# 趋势分析
# ---------------------------------------------------------------------------

def trend_analysis(book_dir: Path, last_n: int = 5) -> Dict[str, Any]:
    result = evaluate_book(book_dir)
    if "error" in result:
        return result

    chapters = result.get("chapters", [])
    if len(chapters) < last_n:
        return {"error": f"章节数不足 {last_n}，无法分析趋势"}

    recent = chapters[-last_n:]
    trend = {"chapters": [r["chapter"] for r in recent]}
    for metric in BENCHMARK_METRICS:
        vals = [r[metric] for r in recent if metric in r]
        if vals:
            trend[metric] = {
                "values": vals,
                "avg": round(sum(vals) / len(vals), 2),
                "trend": "上升" if vals[-1] > vals[0] else ("下降" if vals[-1] < vals[0] else "持平"),
            }

    return {
        "version": VERSION,
        "last_n": last_n,
        "total_chapters": len(chapters),
        "trend": trend,
    }


# ---------------------------------------------------------------------------
# 输出格式
# ---------------------------------------------------------------------------

def print_eval_report(score: Dict[str, Any]) -> None:
    if "error" in score:
        print(f"评测失败: {score['error']}")
        return
    print(f"\n=== 单章评测: {score['file']} ===")
    print(f"  字数: {score['chars']} (汉字 {score['cjk']})")
    print(f"  AI 味分数: {score['ai_score']}/100")
    print(f"  平均句长: {score['avg_sent_len']:.1f} 字")
    print(f"  对话占比: {score['dialogue_ratio']:.1f}%")
    print(f"  节奏均衡度: {score['rhythm_balance']:.1f} (越小越均衡)")
    print(f"  门禁通过率: {score['gate_pass_rate']:.0%}")


def print_book_report(result: Dict[str, Any]) -> None:
    if "error" in result:
        print(f"评测失败: {result['error']}")
        return
    print(f"\n=== 全书评测 ({result['total_chapters']} 章) ===")
    print(f"  评测时间: {result['evaluated_at']}")
    print(f"\n  {'指标':<20} {'平均':>8} {'最低':>8} {'最高':>8}")
    print("  " + "-" * 50)
    for metric in BENCHMARK_METRICS:
        avg = result.get("summary", {}).get(f"avg_{metric}", "N/A")
        mn = result.get("summary", {}).get(f"min_{metric}", "N/A")
        mx = result.get("summary", {}).get(f"max_{metric}", "N/A")
        print(f"  {metric:<20} {avg:>8} {mn:>8} {mx:>8}")

    # 趋势
    trends = {k: v for k, v in result.get("summary", {}).items() if k.startswith("trend_")}
    if trends:
        print(f"\n  趋势 (后1/3 vs 前1/3):")
        for k, v in trends.items():
            metric = k.replace("trend_", "")
            direction = "↑" if v > 0 else ("↓" if v < 0 else "→")
            print(f"    {metric}: {v:+.2f} {direction}")


def print_compare_report(result: Dict[str, Any]) -> None:
    if "error" in result:
        print(f"对比失败: {result['error']}")
        return
    print(f"\n=== 基线对比 ===")
    print(f"  对比时间: {result['compared_at']}")
    print(f"\n  {'指标':<18} {'当前':>10} {'基线':>10} {'差值':>10} {'变化%':>10}")
    print("  " + "-" * 62)
    for metric, data in result.get("comparison", {}).items():
        print(f"  {metric:<18} {data['current']:>10.2f} {data['baseline']:>10.2f} "
              f"{data['diff']:>+10.2f} {data['pct']:>+9.1f}%")
    if result["has_degradation"]:
        print(f"\n  ⚠ 检测到退化:")
        for d in result["degraded"]:
            print(f"    - {d}")
    else:
        print(f"\n  ✓ 无明显退化")


def print_trend_report(result: Dict[str, Any]) -> None:
    if "error" in result:
        print(f"趋势分析失败: {result['error']}")
        return
    print(f"\n=== 最近 {result['last_n']} 章趋势 ===")
    trend = result.get("trend", {})
    chs = trend.get("chapters", [])
    print(f"  章节: {chs}")
    for metric in BENCHMARK_METRICS:
        data = trend.get(metric)
        if data:
            vals = ", ".join(str(v) for v in data["values"])
            print(f"  {metric:<18} [{vals}]  平均={data['avg']:.1f}  趋势={data['trend']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(
        description="章节质量基线评测脚本 v1.0.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    p_eval = sub.add_parser("eval", help="单章评测")
    p_eval.add_argument("file", help="章节文件路径")
    p_eval.add_argument("--json", action="store_true", help="JSON 输出")

    p_book = sub.add_parser("book", help="全书评测")
    p_book.add_argument("book_dir", help="书籍工程目录")
    p_book.add_argument("--json", action="store_true", help="JSON 输出")

    p_save = sub.add_parser("save", help="评测并保存为基线")
    p_save.add_argument("book_dir", help="书籍工程目录")

    p_compare = sub.add_parser("compare", help="与已存基线对比")
    p_compare.add_argument("book_dir", help="书籍工程目录")
    p_compare.add_argument("--json", action="store_true", help="JSON 输出")

    p_trend = sub.add_parser("trend", help="最近 N 章趋势")
    p_trend.add_argument("book_dir", help="书籍工程目录")
    p_trend.add_argument("--chapters", type=int, default=5, help="最近 N 章")
    p_trend.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 2

    if args.command == "eval":
        score = evaluate_chapter(Path(args.file))
        if args.json:
            print(json.dumps(score, ensure_ascii=False, indent=2))
        else:
            print_eval_report(score)
        return 0 if "error" not in score else 1

    if args.command in ("book", "save", "compare", "trend"):
        book_dir = Path(args.book_dir).expanduser().resolve()
        if not book_dir.exists():
            print(f"错误: 目录不存在 {book_dir}", file=sys.stderr)
            return 2

        if args.command == "book":
            result = evaluate_book(book_dir)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_book_report(result)
            return 0 if "error" not in result else 1

        if args.command == "save":
            result = save_baseline(book_dir)
            if "error" in result:
                print(f"保存失败: {result['error']}", file=sys.stderr)
                return 1
            print(f"基线已保存: {result['saved_to']}")
            print_book_report(result)
            return 0

        if args.command == "compare":
            result = compare_baseline(book_dir)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_compare_report(result)
            if "error" in result:
                return 1
            return 1 if result["has_degradation"] else 0

        if args.command == "trend":
            result = trend_analysis(book_dir, args.chapters)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_trend_report(result)
            return 0 if "error" not in result else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
