#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""editorial_manager.py — 编辑团队状态管理器（纯标准库，无第三方依赖）。

管理多 Agent 协作写作流程中的状态快照、审核记录、状态查询和人工介入检测。
对应 editorial-spawn.md 的 Step 1（快照）与 Step 7（记录），以及防死循环检测。

四个子命令：
  snapshot       — 生成上下文快照 JSON，供编辑团队启动时使用
  record-review  — 记录单次审核结果，追加到 review_history.json
  status          — 查看最近 N 章的审核历史，输出表格格式状态报告
  need-human      — 检测是否需要人工介入（防死循环）

用法：
  python scripts/editorial_manager.py snapshot "{书名目录}" --chapter 37
  python scripts/editorial_manager.py record-review "{书名目录}" --chapter 37 --stage final --agent consistency-reviewer --verdict pass --p0 0 --p1 2 --p2 1
  python scripts/editorial_manager.py status "{书名目录}" --last 10
  python scripts/editorial_manager.py need-human "{书名目录}"

退出码：0 = 成功；1 = 检测到问题（need-human 判定为 true）；2 = 参数/文件错误。
"""

import argparse
import datetime
import glob
import json
import os
import re
import sys

CHAPTER_FILE_RE = re.compile(r"第\s*(\d+)\s*章")

# ── 防死循环阈值（与 editorial-spawn.md 一致） ──────────────────────────
MAX_REWRITE_ROUNDS = 2          # 单章返工上限（第 3 轮仍有 P0 → 人工）
MAX_CONDITIONAL_CHAPTERS = 3    # 连续条件通过章数上限


# ── 工具函数 ────────────────────────────────────────────────────────────────

def _read(path):
    """读取文本文件，返回内容字符串。文件不存在返回 None。"""
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def _read_json(path, default=None):
    """读取 JSON 文件，解析失败返回 default。"""
    text = _read(path)
    if text is None:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def _write_json(path, data):
    """写入 JSON 文件，自动创建父目录。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _ensure_editorial_dir(book_root):
    """确保 追踪/editorial/ 目录存在，返回路径。"""
    d = os.path.join(book_root, "追踪", "editorial")
    os.makedirs(d, exist_ok=True)
    return d


def find_last_chapter(book_root):
    """返回 (章号, 文件相对路径) 或 (None, None)。"""
    prose_dir = os.path.join(book_root, "正文")
    chapters = []
    for path in glob.glob(os.path.join(prose_dir, "*.md")):
        m = CHAPTER_FILE_RE.search(os.path.basename(path))
        if m:
            chapters.append((int(m.group(1)), os.path.relpath(path, book_root)))
    if not chapters:
        return None, None
    chapters.sort(key=lambda x: x[0])
    return chapters[-1]


def find_chapter_file(book_root, chapter_no):
    """按章号查找章节文件，返回相对路径或 None。"""
    prose_dir = os.path.join(book_root, "正文")
    target = f"第{chapter_no:03d}章"
    for path in glob.glob(os.path.join(prose_dir, f"*第*{chapter_no}章*.md")):
        return os.path.relpath(path, book_root)
    # 也试补零格式
    for path in glob.glob(os.path.join(prose_dir, "*.md")):
        m = CHAPTER_FILE_RE.search(os.path.basename(path))
        if m and int(m.group(1)) == chapter_no:
            return os.path.relpath(path, book_root)
    return None


def _count_foreshadow(book_root):
    """解析伏笔台账，返回 {"active": int, "overdue": int}。"""
    result = {"active": 0, "overdue": 0}
    ledger_path = os.path.join(book_root, "追踪", "伏笔台账.md")
    text = _read(ledger_path)
    if text is None:
        return result
    section = None
    for line in text.splitlines():
        h = re.match(r"^#{1,4}\s*(.+)", line)
        if h:
            t = h.group(1)
            if "🔴" in t or "超期" in t:
                section = "overdue"
            elif "🟡" in t or "活跃" in t:
                section = "active"
            else:
                section = None
            continue
        if section and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0] and cells[0] not in ("ID", "") and not set(cells[0]) <= set("-: "):
                if section == "overdue":
                    result["overdue"] += 1
                elif section == "active":
                    result["active"] += 1
    return result


def _get_rhythm_recent(book_root, chapter_no, count=3):
    """获取近 N 章的节奏配额记录，返回 [配额字母/档位, ...]。"""
    quota_path = os.path.join(book_root, "追踪", "节奏配额.md")
    text = _read(quota_path)
    if text is None:
        return []
    records = []
    section = None
    for line in text.splitlines():
        h = re.match(r"^#{1,6}\s*(.+)", line)
        if h:
            t = h.group(1)
            if ("A/B/C" in t or "ABC" in t) and "配额" in t:
                section = "quota"
            else:
                section = None
            continue
        if section == "quota" and line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not cells or set(cells[0]) <= set("-: ") or cells[0] in ("章节", "章"):
                continue
            chap_m = re.search(r"\d+", cells[0])
            if chap_m:
                chap = int(chap_m.group())
                if chap <= chapter_no:
                    quota_val = cells[1] if len(cells) > 1 else "none"
                    records.append((chap, quota_val))
    # 按章号排序，取最近 count 条
    records.sort(key=lambda x: x[0], reverse=True)
    recent = records[:count]
    recent.sort(key=lambda x: x[0])
    return [q for _, q in recent]


def _get_character_summary(book_root):
    """读取角色状态文件，生成摘要字符串。"""
    char_path = os.path.join(book_root, "追踪", "角色状态.md")
    text = _read(char_path)
    if text is None:
        return "（角色状态文件不存在）"
    roles = re.findall(r"^##\s*(.+?)\s*$", text, re.M)
    if not roles:
        return "（角色状态文件无角色条目）"
    if len(roles) > 10:
        return f"共 {len(roles)} 个角色已建档：" + "、".join(roles[:10]) + f" 等（共 {len(roles)} 个）"
    return f"共 {len(roles)} 个角色已建档：" + "、".join(roles)


def _get_rhythm_violations(book_root):
    """检查节奏配额是否有连续越界，返回最近3章是否全部越界。"""
    # 简化检测：读取最近的门禁状态，看 rhythm.passed
    prose_dir = os.path.join(book_root, "正文")
    chapters = []
    for path in glob.glob(os.path.join(prose_dir, "*.md")):
        m = CHAPTER_FILE_RE.search(os.path.basename(path))
        if m:
            chapters.append(int(m.group(1)))
    chapters.sort(reverse=True)
    recent = chapters[:3]
    violations = 0
    for ch in recent:
        gate_path = os.path.join(book_root, "追踪", "门禁", f"gate_ch{ch}.json")
        state = _read_json(gate_path)
        if state and isinstance(state.get("rhythm"), dict):
            if not state["rhythm"].get("passed", True):
                violations += 1
    return violations


# ── 子命令：snapshot ──────────────────────────────────────────────────────

def cmd_snapshot(book_root, chapter_no):
    """生成上下文快照，输出到 追踪/editorial/snapshot_ch{N}.json。"""
    # 查找最新章节文件
    chapter_file = find_chapter_file(book_root, chapter_no)
    if chapter_file is None:
        # 用最新章
        last_no, last_file = find_last_chapter(book_root)
        if last_file:
            chapter_file = last_file
            if chapter_no != last_no:
                print(f"提示：第{chapter_no}章文件未找到，使用最新章节 第{last_no}章", file=sys.stderr)
        else:
            chapter_file = "（无章节文件）"

    # 伏笔状态
    foreshadow = _count_foreshadow(book_root)

    # 节奏配额近3章
    rhythm_recent = _get_rhythm_recent(book_root, chapter_no, count=3)

    # 角色状态摘要
    char_summary = _get_character_summary(book_root)

    # 文风锚路径
    style_anchor = "设定/文风锚.md"
    if not os.path.isfile(os.path.join(book_root, style_anchor)):
        style_anchor = "（文风锚文件不存在）"

    snapshot = {
        "chapter": chapter_no,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "latest_chapter_file": chapter_file,
        "character_state_summary": char_summary,
        "foreshadow_status": foreshadow,
        "rhythm_quota_recent": rhythm_recent,
        "style_anchor_path": style_anchor,
    }

    out_dir = _ensure_editorial_dir(book_root)
    out_path = os.path.join(out_dir, f"snapshot_ch{chapter_no}.json")
    _write_json(out_path, snapshot)

    print(f"上下文快照已生成：{out_path}")
    print(f"  章节：第{chapter_no}章")
    print(f"  最新章节文件：{chapter_file}")
    print(f"  角色状态：{char_summary}")
    print(f"  伏笔状态：活跃 {foreshadow['active']}，超期 {foreshadow['overdue']}")
    print(f"  节奏配额近3章：{rhythm_recent}")
    print(f"  文风锚：{style_anchor}")
    return 0


# ── 子命令：record-review ──────────────────────────────────────────────────

VALID_STAGES = ("planning", "writing", "anti-ai", "consistency", "final")
VALID_VERDICTS = ("pass", "conditional", "rewrite")


def cmd_record_review(book_root, args):
    """记录审核结果，追加到 追踪/editorial/review_history.json。"""
    if args.stage not in VALID_STAGES:
        print(f"错误：--stage 须为 {VALID_STAGES} 之一，收到：{args.stage}", file=sys.stderr)
        return 2
    if args.verdict not in VALID_VERDICTS:
        print(f"错误：--verdict 须为 {VALID_VERDICTS} 之一，收到：{args.verdict}", file=sys.stderr)
        return 2
    if args.p0 < 0 or args.p1 < 0 or args.p2 < 0:
        print("错误：P0/P1/P2 计数不可为负数", file=sys.stderr)
        return 2

    # 解析问题描述（--issues 参数，逗号分隔）
    issues = []
    if args.issues:
        issues = [s.strip() for s in args.issues.split(",") if s.strip()]

    record = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "chapter": args.chapter,
        "stage": args.stage,
        "agent": args.agent,
        "verdict": args.verdict,
        "p0_count": args.p0,
        "p1_count": args.p1,
        "p2_count": args.p2,
        "issues": issues,
    }

    # 读取已有历史
    out_dir = _ensure_editorial_dir(book_root)
    history_path = os.path.join(out_dir, "review_history.json")
    history = _read_json(history_path, {"reviews": []})
    if "reviews" not in history:
        history["reviews"] = []
    history["reviews"].append(record)

    _write_json(history_path, history)

    print(f"审核记录已追加：{history_path}")
    print(f"  章节：第{args.chapter}章  阶段：{args.stage}  审核：{args.agent}")
    print(f"  结论：{args.verdict}  P0:{args.p0}  P1:{args.p1}  P2:{args.p2}")
    if issues:
        for iss in issues:
            print(f"    - {iss}")
    return 0


# ── 子命令：status ─────────────────────────────────────────────────────────

def cmd_status(book_root, last_n):
    """查看最近 N 章的审核历史，输出表格格式状态报告。"""
    out_dir = os.path.join(book_root, "追踪", "editorial")
    history_path = os.path.join(out_dir, "review_history.json")
    history = _read_json(history_path)
    if not history or "reviews" not in history or not history["reviews"]:
        print("（无审核历史记录）")
        return 0

    reviews = history["reviews"]

    # 按章节分组，取最近 last_n 章
    chapter_set = sorted(set(r["chapter"] for r in reviews), reverse=True)[:last_n]
    chapter_set.sort()

    # 统计
    total_reviews = len(reviews)
    total_pass = sum(1 for r in reviews if r["verdict"] == "pass")
    total_conditional = sum(1 for r in reviews if r["verdict"] == "conditional")
    total_rewrite = sum(1 for r in reviews if r["verdict"] == "rewrite")

    print("=" * 60)
    print("  编辑团队审核状态报告")
    print("=" * 60)
    print()

    # 汇总统计
    print(f"总审核记录数：{total_reviews}")
    if total_reviews > 0:
        print(f"  通过：{total_pass}  有条件通过：{total_conditional}  返工：{total_rewrite}")
    print()

    # 各章节明细
    print(f"最近 {len(chapter_set)} 章审核明细：")
    print()
    # 表头
    header = f"{'章节':<8}{'轮数':<6}{'阶段':<14}{'审核Agent':<24}{'结论':<14}{'P0':<5}{'P1':<5}{'P2':<5}"
    print(header)
    print("-" * len(header))

    for ch in chapter_set:
        ch_reviews = [r for r in reviews if r["chapter"] == ch]
        ch_reviews.sort(key=lambda x: x.get("timestamp", ""))
        for i, r in enumerate(ch_reviews):
            stage = r.get("stage", "-")
            agent = r.get("agent", "-")
            verdict = r.get("verdict", "-")
            p0 = r.get("p0_count", 0)
            p1 = r.get("p1_count", 0)
            p2 = r.get("p2_count", 0)
            round_label = f"R{i + 1}" if len(ch_reviews) > 1 else "-"
            line = f"第{ch}章  {round_label:<6}{stage:<14}{agent:<24}{verdict:<14}{p0:<5}{p1:<5}{p2:<5}"
            print(line)
        # 章节汇总
        rounds = len(ch_reviews)
        final_verdicts = [r["verdict"] for r in ch_reviews]
        has_pass = "pass" in final_verdicts
        if has_pass:
            final = "pass"
        elif "conditional" in final_verdicts:
            final = "conditional"
        else:
            final = "rewrite"
        print(f"         └─ 共{rounds}轮，最终结论：{final}")
        print()

    # 常见问题类型统计
    all_issues = []
    for r in reviews:
        for iss in r.get("issues", []):
            all_issues.append(iss)
    if all_issues:
        print("常见问题类型：")
        issue_counts = {}
        for iss in all_issues:
            issue_counts[iss] = issue_counts.get(iss, 0) + 1
        sorted_issues = sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)
        for iss, count in sorted_issues[:10]:
            print(f"  [{count}次] {iss}")
        print()

    print("=" * 60)
    return 0


# ── 子命令：need-human ─────────────────────────────────────────────────────

def cmd_need_human(book_root):
    """检测是否需要人工介入，输出 JSON 判定结果。"""
    reasons = []
    out_dir = os.path.join(book_root, "追踪", "editorial")
    history_path = os.path.join(out_dir, "review_history.json")
    history = _read_json(history_path)

    # ── 检测 1：单章审核轮数 >= 3（防死循环） ──
    if history and "reviews" in history and history["reviews"]:
        reviews = history["reviews"]
        chapter_rounds = {}
        for r in reviews:
            ch = r["chapter"]
            chapter_rounds[ch] = chapter_rounds.get(ch, 0) + 1
        for ch, rounds in sorted(chapter_rounds.items()):
            if rounds >= 3:
                reasons.append(f"第{ch}章审核轮数达 {rounds} 轮（上限 {MAX_REWRITE_ROUNDS + 1}），"
                               f"可能陷入死循环")

    # ── 检测 2：连续 3 章结论为 conditional ──
    if history and "reviews" in history and history["reviews"]:
        reviews = history["reviews"]
        # 每章取最终结论
        chapter_verdicts = {}
        for r in reviews:
            ch = r["chapter"]
            # 后来的记录覆盖前面的
            chapter_verdicts[ch] = r["verdict"]
        # 按章节排序
        sorted_chs = sorted(chapter_verdicts.keys())
        # 找连续 conditional
        consecutive = 0
        for ch in sorted_chs:
            if chapter_verdicts[ch] == "conditional":
                consecutive += 1
                if consecutive >= MAX_CONDITIONAL_CHAPTERS:
                    # 找到连续的起始章节
                    start = sorted_chs[sorted_chs.index(ch) - consecutive + 1]
                    reasons.append(f"连续 {consecutive} 章（第{start}–{ch}章）结论为 conditional，"
                                   f"存在系统性问题")
                    break
            else:
                consecutive = 0

    # ── 检测 3：P0 问题在重写后仍然存在 ──
    if history and "reviews" in history and history["reviews"]:
        reviews = history["reviews"]
        # 按章节分组，检查是否有重写后仍存在 P0 的模式
        chapter_reviews = {}
        for r in reviews:
            ch = r["chapter"]
            chapter_reviews.setdefault(ch, []).append(r)
        for ch, ch_revs in chapter_reviews.items():
            ch_revs.sort(key=lambda x: x.get("timestamp", ""))
            # 查找 rewrite 后仍有 P0 的情况
            for i in range(len(ch_revs) - 1):
                if ch_revs[i]["verdict"] == "rewrite":
                    # 检查后续轮次是否仍有 P0
                    for j in range(i + 1, len(ch_revs)):
                        if ch_revs[j]["p0_count"] > 0:
                            reasons.append(f"第{ch}章重写后仍存在 P0 问题"
                                           f"（R{i + 1}→R{j + 1}，P0={ch_revs[j]['p0_count']}）")
                            break

    # ── 检测 4：伏笔超期未处理 ──
    foreshadow = _count_foreshadow(book_root)
    if foreshadow["overdue"] > 0:
        reasons.append(f"伏笔台账有 {foreshadow['overdue']} 项超期未处理")

    # ── 检测 5：节奏配额连续越界 ──
    rhythm_violations = _get_rhythm_violations(book_root)
    if rhythm_violations >= 3:
        reasons.append(f"节奏配额连续 3 章越界（全部 FAIL）")

    # ── 汇总判定 ──
    need_human = len(reasons) > 0

    # 建议动作
    if need_human:
        # 根据原因给出针对性建议
        has_loop = any("死循环" in r for r in reasons)
        has_conditional = any("系统性" in r for r in reasons)
        has_p0 = any("P0" in r for r in reasons)
        has_foreshadow = any("伏笔" in r for r in reasons)
        has_rhythm = any("节奏" in r for r in reasons)

        suggestions = []
        if has_loop or has_p0:
            suggestions.append("停止自动重写，人工审查 Chapter Brief 和正文，确认是否需要改纲")
        if has_conditional:
            suggestions.append("系统性问题可能出在章纲或角色设定，建议走改纲流程（outline-system.md）")
        if has_foreshadow:
            suggestions.append("先处理超期伏笔（回收/延期/弃坑），再开新章")
        if has_rhythm:
            suggestions.append("调整节奏配额分配策略，检查是否 A/B/C 配额卡太死或太松")
        suggested_action = "；".join(suggestions) if suggestions else "人工审查当前状态，决定后续方向"
    else:
        suggested_action = "无异常，可继续自动流程"

    result = {
        "need_human": need_human,
        "reasons": reasons,
        "suggested_action": suggested_action,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))

    return 1 if need_human else 0


# ── 主入口 ──────────────────────────────────────────────────────────────────

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description="编辑团队状态管理器：快照/审核记录/状态查询/人工介入检测"
    )
    sub = ap.add_subparsers(dest="command", help="子命令")

    # ── snapshot ──
    p_snap = sub.add_parser("snapshot", help="生成上下文快照 JSON")
    p_snap.add_argument("book_root", help="书籍工程目录")
    p_snap.add_argument("--chapter", type=int, required=True, help="当前章节号")

    # ── record-review ──
    p_review = sub.add_parser("record-review", help="记录审核结果")
    p_review.add_argument("book_root", help="书籍工程目录")
    p_review.add_argument("--chapter", type=int, required=True, help="章节号")
    p_review.add_argument("--stage", required=True,
                          help=f"审核阶段：{VALID_STAGES}")
    p_review.add_argument("--agent", required=True, help="审核 Agent 名称")
    p_review.add_argument("--verdict", required=True,
                          help=f"审核结论：{VALID_VERDICTS}")
    p_review.add_argument("--p0", type=int, default=0, help="P0 问题数（默认 0）")
    p_review.add_argument("--p1", type=int, default=0, help="P1 问题数（默认 0）")
    p_review.add_argument("--p2", type=int, default=0, help="P2 问题数（默认 0）")
    p_review.add_argument("--issues", default=None,
                          help="问题描述（逗号分隔）")

    # ── status ──
    p_status = sub.add_parser("status", help="查看审核历史状态报告")
    p_status.add_argument("book_root", help="书籍工程目录")
    p_status.add_argument("--last", type=int, default=10, help="查看最近 N 章（默认 10）")

    # ── need-human ──
    p_human = sub.add_parser("need-human", help="检测是否需要人工介入")
    p_human.add_argument("book_root", help="书籍工程目录")

    args = ap.parse_args()

    if not args.command:
        ap.print_help()
        return 2

    book_root = os.path.abspath(args.book_root)
    if not os.path.isdir(book_root):
        print(f"错误：目录不存在 {book_root}", file=sys.stderr)
        return 2

    if args.command == "snapshot":
        return cmd_snapshot(book_root, args.chapter)
    elif args.command == "record-review":
        return cmd_record_review(book_root, args)
    elif args.command == "status":
        return cmd_status(book_root, args.last)
    elif args.command == "need-human":
        return cmd_need_human(book_root)
    else:
        ap.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
