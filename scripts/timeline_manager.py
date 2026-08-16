#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timeline_manager.py — 章节时间线管理模块（纯标准库）。

把「Agent 手写的时间线.md 账本」升级为完整的章节时间线管理系统：
  - 解析：兼容模板表格式与 demo 旧格式，产出机器可读 timeline.json。
  - 归一化：把自由时间描述转为可排序数值（自定义纪元/相对基准/锚点偏移）。
  - 冲突检测：五类（时间倒退 / 跳跃过大 / 承诺到期 / 前文引用矛盾 / 分支交错）。
  - 时间锚点：声明绝对时间参照，章节可用 @锚点+偏移 引用。
  - 可视化：mermaid timeline + ASCII 表 + 可选自包含 HTML 时间轴。

用法：
  python scripts/timeline_manager.py build "<书目录>"           # 解析→timeline.json
  python scripts/timeline_manager.py check "<书目录>" [--json]   # 五类冲突检测
  python scripts/timeline_manager.py viz "<书目录>" [--html]     # 可视化
  python scripts/timeline_manager.py anchor "<书目录>" --list    # 时间锚点
  python scripts/timeline_manager.py status "<书目录>"           # 概览

退出码：0 = 通过/成功；1 = 检测到 ERROR/WARN（check）；2 = 参数/文件错误。
"""

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:
    from common import read_text, write_text
except ImportError:
    def read_text(path, encoding="utf-8-sig"):
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except (OSError, ValueError):
            return ""

    def write_text(path, content, encoding="utf-8"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding=encoding) as f:
            f.write(content)
        return True

try:
    from config import TIMELINE_JSON_FILE, TIMELINE_MAX_SILENT_GAP, TIMELINE_CHECK_ENABLED
except ImportError:
    TIMELINE_JSON_FILE = "timeline.json"
    TIMELINE_MAX_SILENT_GAP = 30  # 天；相邻章 silent gap 超此值且无时间标记 → 警告
    TIMELINE_CHECK_ENABLED = True

VERSION = "1.0.0"

# =========================================================
# 解析层
# =========================================================

_CHAPTER_CELL_RE = re.compile(r"第\s*(\d+)\s*章")
_OLD_SECTION_RE = re.compile(r"^#{3}\s*(.+?)[（(][^）)]*[）)]\s*[—-]{1,2}\s*第\s*(\d+)\s*章", re.M)
_DATE_HEADER_RE = re.compile(r"^(\d+)\s*[年月日.]+\s*(\d+)?\s*[日号]?")

# 时间标记列里的承诺/跳跃关键词
_CN_DIGITS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_NUM_CLS = "0-9" + "".join(_CN_DIGITS.keys())
_PROMISE_RE = re.compile(
    rf"([{_NUM_CLS}]+)\s*日(?:后|之后|以后)|"
    rf"([{_NUM_CLS}]+)\s*天(?:后|之后|以后)|"
    rf"([{_NUM_CLS}]+)\s*个?月(?:后|之后|以后)|"
    rf"([{_NUM_CLS}]+)\s*年(?:后|之后|以后)")
_JUMP_MARKER_RE = re.compile(r"\d+\s*(?:年后|月后|日后|天后)|数月后|几日后|若干年后|三个月后|半年后|一年后")


def _to_digits(s):
    """把阿拉伯/中文数字串转 int（支持 十/十一~十九）。失败返回 None。"""
    if s.isdigit():
        return int(s)
    if s in _CN_DIGITS:
        return _CN_DIGITS[s]
    m = re.fullmatch(r"十([一二三四五六七八九])", s)
    if m:
        return 10 + _CN_DIGITS[m.group(1)]
    if s == "十":
        return 10
    return None


def _is_sep_row(cells):
    return cells and set(cells[0]) <= set("-: ")


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_anchors(md_text):
    """解析顶部「## 时间锚点」区块：`A1 标签 = 时间表达式` 或表格 编号|标签|时间。"""
    anchors = OrderedDict()
    in_block = False
    for line in md_text.splitlines():
        if re.match(r"^#{1,3}\s*时间锚点", line):
            in_block = True
            continue
        if in_block:
            if re.match(r"^#{1,3}\s", line) and not re.match(r"^#{1,3}\s*时间锚点", line):
                break
            m = re.match(r"\s*\|?\s*(A\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|?$", line)
            if not m:
                m = re.match(r"\s*(A\d+)\s*[:：=]\s*([^#]+?)(?:\s*#.*)?$", line)
            if m:
                aid, label, time_expr = m.group(1), m.group(2).strip(), (m.group(3) if m.lastindex >= 3 else "").strip()
                if not time_expr:
                    time_expr = label
                    label = aid
                anchors[aid] = {"label": label, "time_expr": time_expr}
    return anchors


def _parse_table_entries(md_text):
    """解析模板表格式：`| 章节 | 故事内时间 | 事件 | 时间标记/约定 |`。"""
    entries = []
    header_seen = False
    for line in md_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            header_seen = False
            continue
        cells = _cells(line)
        if _is_sep_row(cells):
            header_seen = True
            continue
        if not header_seen:
            if cells and "章节" in cells[0] and len(cells) >= 2:
                header_seen = True
            continue
        if cells and _CHAPTER_CELL_RE.search(cells[0]):
            m = _CHAPTER_CELL_RE.search(cells[0])
            entries.append({
                "chapter": int(m.group(1)),
                "time_desc": cells[1] if len(cells) > 1 else "",
                "event": cells[2] if len(cells) > 2 else "",
                "promise": cells[3] if len(cells) > 3 else "",
            })
    return entries


def _parse_old_sections(md_text):
    """解析 demo 旧格式：`### 9月3日（周一）—— 第N章` 节头。"""
    entries = []
    for m in _OLD_SECTION_RE.finditer(md_text):
        header, ch = m.group(1).strip(), int(m.group(2))
        date_match = _DATE_HEADER_RE.search(header)
        time_desc = header if date_match else ""
        entries.append({"chapter": ch, "time_desc": time_desc, "event": "", "promise": ""})
    return entries


def parse_timeline(md_text):
    """解析时间线 md，返回 {anchors, chapters}（章节按章号排序，去重）。"""
    anchors = parse_anchors(md_text)
    table_entries = _parse_table_entries(md_text)
    old_entries = _parse_old_sections(md_text)
    merged = OrderedDict()
    for e in table_entries + old_entries:
        ch = e["chapter"]
        if ch not in merged:
            merged[ch] = e
        else:
            # 表格式优先（更完整）；旧格式只在表格式缺时间时补
            cur = merged[ch]
            if not cur["time_desc"] and e["time_desc"]:
                cur["time_desc"] = e["time_desc"]
    chapters = [merged[k] for k in sorted(merged.keys())]
    return {"anchors": dict(anchors), "chapters": chapters}


# =========================================================
# 时间归一化
# =========================================================

def normalize_time(desc, anchors=None):
    """把时间描述转为可排序数值 (value, unit)。失败返回 None。

    unit: "day"（天基准）| "year"（年基准）。跨 unit 比较时 year→day 需放大。
    支持：公历 X年X月X日 / 第X天 / 纪元X年春 / 穿越后第X天 / @锚点±偏移。
    """
    if not desc or not isinstance(desc, str):
        return None
    text = desc.strip()
    if not text:
        return None

    # 锚点引用：@A1 或 @A1+5 / @A1-3
    m = re.search(r"@(A\d+)(?:\s*([+-])\s*(\d+))?", text)
    if m and anchors:
        aid = m.group(1)
        base = None
        if aid in anchors:
            base = normalize_time(anchors[aid].get("time_expr"), anchors)
        if base is None:
            return None
        offset = 0
        if m.group(3):
            offset = int(m.group(3))
            if m.group(2) == "-":
                offset = -offset
        if base[1] == "day":
            return (base[0] + offset, "day")
        return (base[0] + offset, base[1])

    # 纪元+年+季节：天元历300年春 / 天元300年 / 300年春
    m = re.search(r"(\d+)\s*年", text)
    if m:
        year = int(m.group(1))
        # 季节/月给年内偏移，用于同日历内排序
        month = 0
        for i, s in enumerate(("孟", "仲", "季"), 1):
            if s + "春" in text or s + "夏" in text or s + "秋" in text or s + "冬" in text:
                month = i * 3
                break
        m2 = re.search(r"(\d+)\s*月", text)
        if m2:
            month = int(m2.group(1))
        day = 0
        m3 = re.search(r"(\d+)\s*日", text)
        if m3:
            day = int(m3.group(1))
        # 转天基准（年×400 粗估，保证同纪元内排序正确）
        return (year * 400 + month * 30 + day, "day")

    # 公历月日：X月X日
    m = re.search(r"(\d+)\s*月\s*(\d+)?\s*[日号]?", text)
    if m:
        month = int(m.group(1))
        day = int(m.group(2)) if m.group(2) else 1
        return (month * 100 + day, "day")

    # 相对天数：第X天 / 穿越后第X天 / 第X日
    m = re.search(r"第\s*(\d+)\s*[天日]", text)
    if m:
        return (int(m.group(1)), "day")

    # 约定后偏移：七日后 → 用于 promise，不直接当章节时间
    m = re.search(r"(\d+)\s*[天日]后", text)
    if m:
        return (int(m.group(1)), "day")

    return None


def _time_key(value, unit):
    """统一到天基准做比较。year 单位近似 400 天。"""
    if unit == "year":
        return value * 400
    return value


# =========================================================
# 冲突检测
# =========================================================

def _extract_promises(entry):
    """从 promise/事件 列提取 (days, 描述)。支持阿拉伯与中文数字。"""
    text = f"{entry.get('promise', '')} {entry.get('event', '')}"
    out = []
    for m in _PROMISE_RE.finditer(text):
        for gi, mult in ((1, 1), (2, 1), (3, 30), (4, 400)):
            raw = m.group(gi)
            if raw is None:
                continue
            n = _to_digits(raw)
            if n is not None:
                out.append((n * mult, "天"))
    return out


def check_timeline(book_dir, target_chapter=None, md_text=None, json_out=False):
    """运行五类冲突检测，返回 (issues, meta)。"""
    if not TIMELINE_CHECK_ENABLED:
        return [], {"enabled": False}
    if md_text is None:
        path = os.path.join(book_dir, "追踪", "时间线.md")
        md_text = read_text(path)
    if not md_text:
        return [], {"enabled": True, "empty": True}

    data = parse_timeline(md_text)
    chapters = data["chapters"]
    anchors = data["anchors"]
    issues = []
    if len(chapters) < 2:
        return issues, {"enabled": True, "entries": len(chapters)}

    # 归一化章节时间
    norm = []
    for ch in chapters:
        tv = normalize_time(ch.get("time_desc"), anchors)
        norm.append({"chapter": ch["chapter"], "time_desc": ch.get("time_desc", ""),
                     "time_value": tv[0] if tv else None, "time_unit": tv[1] if tv else None,
                     "promise": ch.get("promise", ""), "event": ch.get("event", "")})

    prev_key = None
    prev_ch = None
    open_promises = []  # [(from_chapter, from_time_key, days, reported)]
    for i, cur in enumerate(norm):
        key = None
        if cur["time_value"] is not None:
            key = _time_key(cur["time_value"], cur["time_unit"])

        # C1 时间倒退
        if prev_key is not None and key is not None and key < prev_key:
            issues.append({
                "level": "ERROR", "type": "C1_time_regression",
                "chapter_from": prev_ch, "chapter_to": cur["chapter"],
                "message": f"第{cur['chapter']}章时间({cur['time_desc']})早于第{prev_ch}章({norm[i-1]['time_desc']})",
                "fix_hint": "检查是否闪回/插叙；如确为闪回，在时间标记列注明「闪回」",
            })

        # C2 时间跳跃过大（相邻可解析章 gap 超阈值且无时间标记）
        if prev_key is not None and key is not None:
            gap = key - prev_key
            jump_marked = _JUMP_MARKER_RE.search(cur.get("promise", "") or "") or \
                          _JUMP_MARKER_RE.search(cur.get("event", "") or "") or \
                          _JUMP_MARKER_RE.search(cur.get("time_desc", "") or "")
            if gap > TIMELINE_MAX_SILENT_GAP and not jump_marked:
                issues.append({
                    "level": "WARN", "type": "C2_silent_time_jump",
                    "chapter_from": prev_ch, "chapter_to": cur["chapter"],
                    "message": f"第{prev_ch}→第{cur['chapter']}章时间跨 {gap} 天且无「N年后/数月后」显式标记",
                    "fix_hint": "补时间标记（如「三个月后」），或调整章节间时间跨度",
                })

        # C3 承诺到期未兑现：历史章承诺 N 日，当前章时间已超 deadline 未标记兑现（每条只报一次）
        if key is not None:
            for op in open_promises:
                if not op[3] and key > op[1] + op[2]:
                    issues.append({
                        "level": "WARN", "type": "C3_promise_overdue",
                        "chapter_from": op[0], "chapter_to": cur["chapter"],
                        "message": f"第{op[0]}章约定 {op[2]} 天后兑现，但至第{cur['chapter']}章已超期未标记兑现",
                        "fix_hint": "在时间标记列注明「约定已兑现」，或调整约定期限",
                    })
                    op[3] = True  # 标记已报，避免重复

        # 记录本章新承诺（约定期限 = 承诺章时间 + N 天；prev_key 即承诺章时间值）
        if prev_ch is not None and norm[i - 1]["promise"] and prev_key is not None:
            for days, unit in _extract_promises(norm[i - 1]):
                open_promises.append([norm[i - 1]["chapter"], prev_key, days, False])

        # C4 前文引用矛盾：当前章事件含「昨天/前日」但与前章 gap > 2 天
        if key is not None and prev_key is not None:
            recent_ref = re.search(r"昨天|前日|昨儿|刚才", cur.get("event", "") or "")
            if recent_ref and (key - prev_key) > 2:
                issues.append({
                    "level": "WARN", "type": "C4_recent_ref_conflict",
                    "chapter_from": prev_ch, "chapter_to": cur["chapter"],
                    "message": f"第{cur['chapter']}章引用「{recent_ref.group(0)}」但距第{prev_ch}章已 {key - prev_key} 天",
                    "fix_hint": "统一事件时间参照（改为「几日前」），或调整时间线",
                })

        prev_key = key
        prev_ch = cur["chapter"]

    # C5 分支交错：同 time_value 被多章复用但描述不一致
    if len(norm) >= 2:
        seen_time = {}
        for cur in norm:
            if cur["time_value"] is None:
                continue
            tv = (cur["time_value"], cur["time_unit"])
            if tv in seen_time and seen_time[tv][1] != cur["time_desc"]:
                issues.append({
                    "level": "WARN", "type": "C5_branch_time_conflict",
                    "chapter_from": seen_time[tv][0],
                    "chapter_to": cur["chapter"],
                    "message": f"第{cur['chapter']}章与第{seen_time[tv][0]}章时间点相同（{cur['time_desc']}）但描述不一致",
                    "fix_hint": "多线视角下同一时间点应复用同一时间描述，或标注分支名",
                })
            elif tv not in seen_time:
                seen_time[tv] = (cur["chapter"], cur["time_desc"])

    meta = {"enabled": True, "entries": len(chapters), "anchors": len(anchors),
            "error_count": sum(1 for i in issues if i["level"] == "ERROR"),
            "warn_count": sum(1 for i in issues if i["level"] == "WARN")}
    return issues, meta


# =========================================================
# 持久化 timeline.json
# =========================================================

def build_timeline_json(book_dir):
    """解析 时间线.md → 追踪/timeline.json。"""
    md_path = os.path.join(book_dir, "追踪", "时间线.md")
    md_text = read_text(md_path)
    data = parse_timeline(md_text)
    out = {
        "version": VERSION,
        "generated_at": _now(),
        "anchors": data["anchors"],
        "chapters": data["chapters"],
    }
    out_path = os.path.join(book_dir, "追踪", TIMELINE_JSON_FILE)
    write_text(out_path, json.dumps(out, ensure_ascii=False, indent=2))
    return out, out_path


def _now():
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# =========================================================
# 可视化
# =========================================================

def viz_mermaid(data):
    """生成 mermaid timeline 块。"""
    lines = ["```mermaid", "timeline", "    title 小说时间线"]
    if data.get("anchors"):
        for aid, a in data["anchors"].items():
            lines.append(f"    section 锚点 {aid}: {a.get('label', '')} ({a.get('time_expr', '')})")
    section = "主线"
    for i, ch in enumerate(data.get("chapters", [])):
        if i % 10 == 0:
            section = f"第{ch['chapter']}章起"
            lines.append(f"    section {section}")
        label = f"第{ch['chapter']}章：{ch.get('time_desc', '?')}"
        lines.append(f"    {label} : {ch.get('event', '')[:40]}")
    lines.append("```")
    return "\n".join(lines)


def viz_ascii(data):
    lines = ["章节       故事内时间              事件"]
    lines.append("-" * 70)
    for ch in data.get("chapters", []):
        t = (ch.get("time_desc") or "?")[:18]
        e = (ch.get("event") or "")[:40]
        lines.append(f"第{ch['chapter']}章    {t:<20} {e}")
    return "\n".join(lines)


def viz_html(book_dir, data, issues):
    """生成自包含 HTML 时间轴（纯 stdlib）。"""
    rows = []
    for ch in data.get("chapters", []):
        t = ch.get("time_desc") or "?"
        e = ch.get("event") or ""
        rows.append(f"<div class='ev'><span class='t'>{t}</span><span class='ch'>第{ch['chapter']}章</span><span class='d'>{e}</span></div>")
    iss_html = ""
    for i in issues:
        iss_html += (f"<div class='iss {i['level'].lower()}'><b>{i['type']}</b> "
                     f"{i['message']} <i>{i['fix_hint']}</i></div>")
    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>小说时间线</title><style>
body{{font-family:sans-serif;margin:24px;background:#fafafa}}
h1{{font-size:20px}} .wrap{{display:flex;flex-direction:column;gap:6px}}
.ev{{display:flex;gap:12px;border-left:2px solid #888;padding:4px 8px;background:#fff}}
.t{{width:200px;font-weight:600}} .ch{{width:70px;color:#555}} .d{{color:#333}}
.iss{{padding:6px;border-radius:4px;margin:4px 0}}
.iss.error{{background:#fdecea;border:1px solid #f5c6cb}}
.iss.warn{{background:#fff3cd;border:1px solid #ffe69c}}
</style></head><body><h1>小说时间线</h1>
<div class="iss"><b>检测结果</b> 错误 {sum(1 for i in issues if i['level']=='ERROR')} 处 / 警告 {sum(1 for i in issues if i['level']=='WARN')} 处</div>
{iss_html}
<div class="wrap">{''.join(rows)}</div></body></html>"""
    out = os.path.join(book_dir, "追踪", "timeline_chart.html")
    write_text(out, html)
    return out


# =========================================================
# CLI
# =========================================================

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(description="章节时间线管理模块")
    ap.add_argument("mode", choices=["build", "check", "viz", "anchor", "status"])
    ap.add_argument("book_dir", help="书籍工程目录")
    ap.add_argument("--chapter", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()
    book_dir = os.path.abspath(args.book_dir)
    if not os.path.isdir(book_dir):
        print(f"错误：目录不存在 {book_dir}", file=sys.stderr)
        return 2

    if args.mode == "build":
        data, out_path = build_timeline_json(book_dir)
        print(f"时间线已构建：{out_path}")
        print(f"  章节：{len(data['chapters'])}  锚点：{len(data['anchors'])}")
        return 0

    if args.mode == "check":
        issues, meta = check_timeline(book_dir, args.chapter)
        if args.json:
            print(json.dumps({"issues": issues, "meta": meta}, ensure_ascii=False, indent=2))
        else:
            if not meta.get("enabled"):
                print("时间线检查已禁用"); return 0
            if meta.get("empty"):
                print("时间线文件不存在或为空（跳过）"); return 0
            if not issues:
                print(f"时间线检查通过：{meta['entries']} 章，0 问题")
                return 0
            for i in issues:
                tag = "❌" if i["level"] == "ERROR" else "⚠️"
                print(f"{tag} [{i['type']}] 第{i.get('chapter_from','?')}→第{i.get('chapter_to','?')}章：{i['message']}")
                print(f"   修复：{i['fix_hint']}")
            print(f"\n总计：{meta['error_count']} 错误 / {meta['warn_count']} 警告（{meta['entries']} 章）")
        return 1 if meta.get("error_count") or meta.get("warn_count") else 0

    if args.mode == "viz":
        data, _ = build_timeline_json(book_dir)
        issues, _ = check_timeline(book_dir, args.chapter)
        if args.html:
            out = viz_html(book_dir, data, issues)
            print(f"HTML 时间轴已生成：{out}")
        else:
            print(viz_mermaid(data))
            print()
            print(viz_ascii(data))
        return 0

    if args.mode == "anchor":
        md_text = read_text(os.path.join(book_dir, "追踪", "时间线.md"))
        anchors = parse_anchors(md_text)
        if args.json:
            print(json.dumps(anchors, ensure_ascii=False, indent=2))
        else:
            if not anchors:
                print("时间锚点：无（在 时间线.md 顶部加「## 时间锚点」区块声明）")
            else:
                print("时间锚点：")
                for aid, a in anchors.items():
                    print(f"  {aid}  {a['label']}  =  {a['time_expr']}")
        return 0

    if args.mode == "status":
        md_text = read_text(os.path.join(book_dir, "追踪", "时间线.md"))
        data = parse_timeline(md_text)
        issues, meta = check_timeline(book_dir, args.chapter, md_text=md_text)
        print(f"章节时间线状态：{len(data['chapters'])} 章，{len(data['anchors'])} 锚点")
        print(f"冲突：{meta.get('error_count', 0)} 错误 / {meta.get('warn_count', 0)} 警告")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
