#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resume.py — 会话恢复报告（纯标准库，无第三方依赖）。

每次开工先跑它，把「写到哪了 / 欠什么账 / 下一章是什么」一次说清，
替代人工逐个翻追踪文件。这就是 chapter-loop 里「欠账门」的机器查验。

检查项：
  1. 进度：正文/ 最新一章是第几章（按文件名「第N章」排序）
  2. 门禁：最新一章的 追踪/门禁/gate_ch{N}.json 是否存在、是否通过、
     正文过闸后是否被改动（mtime 比对）、节奏段是否通过
  3. 追踪同步：章节摘要.md 是否有第 N 章条目；节奏配额.md 是否有第 N 章记录；
     伏笔台账是否有 🔴 超期项
  4. 下一章：第 N+1 章的章纲是否已建（大纲/章纲_第NNN章.md，兼容不补零写法）

用法：
  python3 scripts/resume.py "{书名目录}"
  python3 scripts/resume.py . --json

退出码：0 = 已检查无欠账（empty 仅可准备首章）；1 = 欠账或布局待确认；2 = 参数错误。
"""

import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

CHAPTER_FILE_RE = re.compile(r"第\s*(\d+)\s*章")


def find_last_chapter(book_root):
    """返回 (章号, 文件名) 或 (None, None)。"""
    prose_dir = os.path.join(book_root, "正文")
    chapters = []
    for path in glob.glob(os.path.join(prose_dir, "*.md")):
        m = CHAPTER_FILE_RE.search(os.path.basename(path))
        if m:
            chapters.append((int(m.group(1)), path))
    if not chapters:
        return None, None
    chapters.sort(key=lambda x: x[0])
    return chapters[-1]


def check_gate(book_root, chapter_no, chapter_path):
    """查验最新章门禁，返回 (欠账列表, 备注列表)。"""
    debts, notes = [], []
    gate_path = os.path.join(book_root, "追踪", "门禁", f"gate_ch{chapter_no}.json")
    if not os.path.isfile(gate_path):
        debts.append(f"第{chapter_no}章门禁状态缺失：跑 check_text.py --gate-report --gate-state 补账")
        return debts, notes
    try:
        with open(gate_path, "r", encoding="utf-8-sig") as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        debts.append(f"第{chapter_no}章门禁文件损坏：{e}")
        return debts, notes
    if not state.get("passed"):
        debts.append(f"第{chapter_no}章门禁未通过（blocking={state.get('blocking')}）：先修再写")
    recorded = state.get("chapter_mtime")
    if recorded and chapter_path and os.path.isfile(chapter_path):
        with open(chapter_path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        changed = (digest != state["chapter_sha256"] if state.get("chapter_sha256")
                   else abs(os.stat(chapter_path).st_mtime - float(recorded)) > 1.0)
        if changed:
            debts.append(f"第{chapter_no}章正文在过闸后有改动：重跑门禁")
    rhythm = state.get("rhythm")
    if isinstance(rhythm, dict):
        if rhythm.get("passed") is False:
            debts.append(f"第{chapter_no}章节奏配额检查未通过（fails={rhythm.get('fails')}）")
        else:
            notes.append("节奏配额检查已通过")
    else:
        notes.append("无节奏检查记录（建议跑 rhythm_guard.py --gate-state）")
    return debts, notes


def check_tracking_sync(book_root, chapter_no):
    """检查追踪文件是否已回写最新章，返回 (欠账列表, 备注列表)。"""
    debts, notes = [], []
    tracking = os.path.join(book_root, "追踪")

    summary = os.path.join(tracking, "章节摘要.md")
    if os.path.isfile(summary):
        with open(summary, "r", encoding="utf-8-sig") as f:
            text = f.read()
        if re.search(rf"第\s*0*{chapter_no}\s*章", text):
            notes.append("章节摘要已回写")
        else:
            debts.append(f"章节摘要.md 缺第{chapter_no}章条目：按模板字段补记")
    else:
        notes.append("章节摘要.md 不存在（开书初期可忽略）")

    quota = os.path.join(tracking, "节奏配额.md")
    if os.path.isfile(quota):
        with open(quota, "r", encoding="utf-8-sig") as f:
            text = f.read()
        rows = [ln for ln in text.splitlines()
                if ln.strip().startswith("|") and re.match(rf"^\|\s*(?:0*{chapter_no}|第\s*0*{chapter_no}\s*章)\s*\|", ln.strip())]
        if rows:
            notes.append("节奏配额已回写")
        else:
            debts.append(f"节奏配额.md 缺第{chapter_no}章记录：补 A/B/C 触发 + 事件 + 档位")
    else:
        notes.append("节奏配额.md 不存在（开书初期可忽略）")

    ledger = os.path.join(tracking, "伏笔台账.md")
    if os.path.isfile(ledger):
        with open(ledger, "r", encoding="utf-8-sig") as f:
            text = f.read()
        section = None
        overdue = []
        for line in text.splitlines():
            h = re.match(r"^#{1,4}\s*(.+)", line)
            if h:
                t = h.group(1)
                section = "overdue" if ("🔴" in t or "超期" in t) else None
                continue
            if section == "overdue" and line.strip().startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if cells and cells[0] and cells[0] != "ID" and not set(cells[0]) <= set("-: "):
                    overdue.append(cells[0])
        if overdue:
            debts.append(f"伏笔台账有 {len(overdue)} 项 🔴 超期（{'、'.join(overdue)}）："
                         f"先给处理方案（回收/延期/弃坑需作者点头）")
        else:
            notes.append("伏笔台账无超期项")
    return debts, notes


def check_next_outline(book_root, next_no):
    """检查下一章章纲是否存在，返回 备注。"""
    outline_dir = os.path.join(book_root, "大纲")
    if not os.path.isdir(outline_dir):
        return "大纲/ 目录不存在"
    for name in os.listdir(outline_dir):
        m = re.match(rf"^章纲_第\s*0*{next_no}\s*章.*\.md$", name)
        if m:
            return f"第{next_no}章章纲已就位（大纲/{name}）"
    return f"第{next_no}章章纲未建：按 outline-system.md 滚动补纲后再写"


MANUSCRIPT_DIRS = {"正文", "manuscript", "chapters", "drafts", "旧稿", "原稿"}
METADATA_DIRS = {"设定", "大纲", "追踪", "对标", "参考资料"}
MAX_SCAN_ENTRIES = 2000
TRACKING_FILES = {"章节摘要.md", "角色状态.md", "伏笔台账.md", "时间线.md", "节奏配额.md",
                  "entity_index.json", ".flow_lock.json", ".chapter-transaction.lock"}


def _is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _tracking_lines(text):
    """Ignore quoted/fenced/commented template examples, not story records."""
    lines, fenced = [], False
    for line in re.sub(r"<!--.*?-->", "", text, flags=re.S).splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced:
            lines.append(line)
    return lines


def _record_chapter(value):
    """A fixed tracking chapter cell/label: zero/placeholders are not history."""
    value = value.strip().strip("* ")
    match = re.match(r"^(?:第\s*(\d+)\s*章|([0-9]+)(?:\s*章)?)(?:\s|[：:]|$)", value)
    if match:
        return int(match.group(1) or match.group(2))
    if not value or "{" in value or value in {"-", "无", "未埋设", "第N章"}:
        return 0
    raise ValueError("章次无法确认：" + value)


def _has_tracking_history(name, text):
    from common import parse_summary_entries
    from timeline_manager import parse_timeline
    if name == "entity_index.json":
        index = json.loads(text)
        if not isinstance(index, dict) or any(
                not isinstance(chapters, list) or any(type(n) is not int or n < 0 for n in chapters)
                for chapters in index.values()):
            raise ValueError("实体索引不是实体到非负章号列表的映射")
        return any(n > 0 for chapters in index.values() for n in chapters)

    lines = _tracking_lines(text)
    clean = "\n".join(lines)
    if name == "章节摘要.md":
        if any(entry["chapter"] > 0 for entry in parse_summary_entries(clean)):
            return True
        for line in lines:
            heading = re.match(r"^#{2,4}\s*(第.+章.*)$", line.strip())
            if heading and _record_chapter(heading.group(1)) > 0:
                return True
    elif name == "角色状态.md":
        for match in re.finditer(r"第\s*(?:\d+|[零〇一二三四五六七八九十百千万两]+|\{[^{}\r\n]+\}|N)\s*章", clean):
            if _record_chapter(match.group()) > 0:
                return True
    else:
        if name == "时间线.md" and any(entry["chapter"] > 0 for entry in parse_timeline(clean)["chapters"]):
            return True
        columns = []
        for line in lines:
            if not line.strip().startswith("|"):
                columns = []
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if all(not cell or set(cell) <= set("-: ") for cell in cells):
                continue
            labels = {"埋设章节", "回收章节"} if name == "伏笔台账.md" else {"章节", "章号"}
            if any(cell in labels for cell in cells):
                columns = [i for i, cell in enumerate(cells) if cell in labels]
                continue
            # Quota rows historically also occur without a preceding table header.
            if not columns and name == "节奏配额.md" and re.match(r"^(?:第|\d)", cells[0]):
                columns = [0]
            if any(_record_chapter(cells[i]) > 0 for i in columns if i < len(cells)):
                return True
    return False


def _orphan_tracking_reasons(root):
    """Read only the five fixed ledgers and entity index before claiming empty."""
    reasons = []
    for name in ("章节摘要.md", "节奏配额.md", "时间线.md", "角色状态.md", "伏笔台账.md", "entity_index.json"):
        path = root / "追踪" / name
        relative = "追踪/" + name
        try:
            before = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            reasons.append("追踪状态无法检查：{}：{}".format(relative, exc))
            continue
        try:
            if _is_link(before) or not stat.S_ISREG(before.st_mode):
                raise ValueError("不是可直接读取的普通文件")
            with path.open("rb") as handle:
                raw = handle.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("超过空工程判定的1MiB读取上限，需确认")
            after = path.lstat()
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError("检查期间文件改变")
            if _has_tracking_history(name, raw.decode("utf-8-sig")):
                reasons.append("发现既往章节追踪记录但无正文，不能新建第1章：" + relative)
        except (OSError, ValueError) as exc:
            reasons.append("追踪记录无法确认，不能认定为空工程：{}：{}".format(relative, exc))
    return reasons


def _discover(book_root):
    """Bounded read-only discovery; never recursively search arbitrary layouts."""
    root = Path(book_root)
    candidates, reasons = [], []
    chapter_records = []
    auxiliary_files = []
    remaining = MAX_SCAN_ENTRIES

    def entries(directory):
        nonlocal remaining
        result = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    remaining -= 1
                    if remaining < 0:
                        reasons.append("扫描达到数量上限：" + str(directory.relative_to(root)))
                        break
                    result.append(Path(entry.path))
        except OSError as exc:
            reasons.append("扫描失败：{}：{}".format(directory.relative_to(root), exc))
        return sorted(result)

    def file_info(path):
        try:
            info = path.lstat()
            if _is_link(info):
                reasons.append("链接未跟随：" + path.relative_to(root).as_posix())
                return None
            return info
        except OSError as exc:
            reasons.append("读取状态失败：{}：{}".format(path.relative_to(root), exc))
            return None

    def candidate(path, info):
        try:
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise OSError("文件在扫描时被替换")
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            after = path.lstat()
            if (_is_link(after) or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise OSError("文件在扫描时改变")
            candidates.append({"path": path.relative_to(root).as_posix(),
                               "bytes": size, "sha256": digest.hexdigest()})
        except OSError as exc:
            reasons.append("候选读取失败：{}：{}".format(path.relative_to(root), exc))

    def scan(directory, mode, depth=0):
        for path in entries(directory):
            info = file_info(path)
            if info is None:
                continue
            relative = path.relative_to(root).as_posix()
            if stat.S_ISREG(info.st_mode):
                if mode == "metadata":
                    if path.relative_to(root).parts[0] in {"对标", "参考资料"}:
                        auxiliary_files.append(relative)
                    if path.suffix.lower() not in {".md", ".txt", ".json"} and relative != "追踪/.chapter-transaction.lock":
                        reasons.append("未识别资料文件：" + relative)
                    elif path.parent == root / "追踪" and path.name not in TRACKING_FILES:
                        reasons.append("未识别追踪文件：" + relative)
                    if relative.startswith("追踪/门禁/"):
                        chapter_records.append(relative)
                elif path.suffix.lower() in {".md", ".txt"}:
                    candidate(path, info)
                elif mode == "root" and path.name == ".deslop-whitelist":
                    pass
                else:
                    reasons.append("未识别文件：" + relative)
            elif stat.S_ISDIR(info.st_mode):
                if relative == "追踪/.chapter-transactions":
                    continue  # pending_transaction checks the journal separately.
                if mode == "root":
                    if path.name in MANUSCRIPT_DIRS:
                        scan(path, "prose")
                    elif path.name in METADATA_DIRS:
                        scan(path, "metadata")
                    else:
                        reasons.append("未知目录／可能为多书布局，需指定书籍目录：" + relative)
                        scan(path, "book_container")
                elif mode == "book_container" and path.name in MANUSCRIPT_DIRS:
                    scan(path, "prose")
                elif mode == "metadata" and depth < 3:
                    scan(path, "metadata", depth + 1)
                else:
                    reasons.append("目录未深入扫描：" + relative)
            else:
                reasons.append("非普通文件：" + relative)

    scan(root, "root")
    if chapter_records and not candidates:
        reasons.append("存在门禁记录但未找到对应正文，不能认定为空工程：" + chapter_records[0])
    if auxiliary_files and not candidates:
        reasons.append("仅发现参考／对标资料，不能据此认定为空工程：" + auxiliary_files[0])
    return sorted(candidates, key=lambda item: item["path"]), reasons


def build_report(book_root):
    """Classify an existing book without importing, renaming, or changing files."""
    book_root = os.path.abspath(os.fspath(book_root))
    if not os.path.isdir(book_root):
        raise ValueError("目录不存在：" + book_root)
    report = {"book_root": book_root, "last_chapter": None, "next_chapter": None,
              "debts": [], "notes": [], "project_state": "unknown", "candidates": [], "ready": False}
    root = Path(book_root)
    for path in (root, *root.parents):
        try:
            if _is_link(path.lstat()):
                report["debts"].append("书籍路径包含链接，未跟随：" + str(path))
                return report
        except OSError as exc:
            report["debts"].append("书籍路径无法检查：" + str(exc))
            return report
    from chapter_transaction import pending_transaction, recovery_command, TransactionError
    pending = None
    try:
        for relative in ("追踪", "追踪/.chapter-transactions", "追踪/.chapter-transactions/current",
                         "追踪/.chapter-transactions/current/journal.json"):
            try:
                info = (root / relative).lstat()
            except FileNotFoundError:
                break
            if _is_link(info):
                raise ValueError("事务路径包含链接，未跟随：" + relative)
        pending = pending_transaction(book_root)
    except (OSError, ValueError, TransactionError) as exc:
        report["debts"].append("事务状态无法检查：" + str(exc))

    candidates, reasons = _discover(book_root)
    report["candidates"] = candidates
    report["debts"].extend(reasons)
    if not candidates and not report["debts"]:
        report["debts"].extend(_orphan_tracking_reasons(root))
    native = []
    for item in candidates:
        path = Path(item["path"])
        match = CHAPTER_FILE_RE.search(path.name)
        if path.parent == Path("正文") and path.suffix == ".md" and match and int(match.group(1)) > 0:
            native.append((int(match.group(1)), os.path.join(book_root, item["path"])))
    if len({number for number, _ in native}) != len(native):
        report["debts"].append("同章存在多份正文，不能任选一稿；请作者确认版本")
    if native and len(native) != len(candidates):
        report["debts"].append("标准正文与未识别稿件并存，不能猜测书籍或章次")

    if report["debts"]:
        report["notes"].append("布局或读取结果尚未确认；保留原文件，先确认书籍与稿件范围")
    elif native:
        report["project_state"] = "native"
        last_no, last_path = max(native, key=lambda item: item[0])
        report["last_chapter"], report["next_chapter"] = last_no, last_no + 1
        try:
            d1, n1 = check_gate(book_root, last_no, last_path)
            d2, n2 = check_tracking_sync(book_root, last_no)
            report["debts"] = d1 + d2
            report["notes"] = n1 + n2 + [check_next_outline(book_root, last_no + 1)]
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            report["debts"].append("原生工程检查失败：" + str(exc))
        report["ready"] = not report["debts"]
    elif candidates:
        report["project_state"] = "external"
        report["notes"].append("已发现外来原稿；候选仅按原字节列出，需作者确认来源和章次，尚未导入")
    else:
        report["project_state"] = "empty"
        report["next_chapter"] = 1
        report["notes"].append("已确认无正文：可准备第1章设定与章纲；此报告不是正文写入授权")
        try:
            report["notes"].append(check_next_outline(book_root, 1))
        except OSError as exc:
            report["project_state"] = "unknown"
            report["next_chapter"] = None
            report["debts"].append("章纲检查失败：" + str(exc))
    if pending:
        report["project_state"] = "transaction_incomplete"
        report["ready"] = False
        report["next_chapter"] = None
        report["debts"].insert(0, "transaction_incomplete: " + recovery_command(book_root))
    return report


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description="会话恢复报告：写到哪 / 欠什么账 / 下一章是什么")
    ap.add_argument("book_root", help="书籍工程目录")
    ap.add_argument("--json", action="store_true", help="输出 JSON 格式报告")
    args = ap.parse_args()

    book_root = os.path.abspath(args.book_root)
    if not os.path.isdir(book_root):
        print(f"错误：目录不存在 {book_root}", file=sys.stderr)
        return 2

    report = build_report(book_root)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 20 + " 会话恢复报告 " + "=" * 20)
        print(f"书籍工程：{book_root}")
        print(f"工程状态：{report['project_state']}")
        if report["project_state"] == "native":
            print(f"进度：已写完第 {report['last_chapter']} 章 → 下一章第 {report['next_chapter']} 章")
        elif report["project_state"] == "empty":
            print("进度：已确认无正文；可准备首章，未授权正文写入")
        elif report["project_state"] == "external":
            print("进度：发现外来原稿；章次待作者确认")
        elif report["project_state"] == "transaction_incomplete":
            print("进度：存在未完成事务；先恢复，暂不判断下一章")
        else:
            print("进度：布局或稿件有歧义；暂不判断下一章")
        print()
        if report["debts"]:
            print(f"【欠账 {len(report['debts'])} 项——先补账再开写】")
            for d in report["debts"]:
                print(f"  ⛔ {d}")
            print()
        elif report["ready"]:
            print("【无欠账】可开写下一章")
            print()
        elif report["project_state"] == "empty":
            print("【准备阶段】先完成设定、章纲与写前确认")
        else:
            print("【待确认】尚不能开写下一章")
        if report["candidates"]:
            print("【稿件候选（只读）】")
            for item in report["candidates"]:
                print(f"  · {item['path']} ({item['bytes']} bytes, sha256={item['sha256']})")
        if report["notes"]:
            print("【状态备注】")
            for n in report["notes"]:
                print(f"  · {n}")
        print("=" * 54)

    return 1 if report["debts"] or report["project_state"] not in {"native", "empty"} else 0


if __name__ == "__main__":
    sys.exit(main())
