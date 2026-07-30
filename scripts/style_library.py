#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style_library.py — 跨书风格库管理工具（纯标准库，无第三方依赖）。

风格库 = 跨书籍的风格指纹集合，用于多书写作/系列写作/风格迁移场景。
每条风格记录包含：六维指标、来源书信息、题材标签、锚点片段路径。
详见 references/workflow/style-library.md。

子命令：
  import   从书籍工程导入风格指纹 → 存入风格库
  list     列出风格库中所有条目
  search   按题材/标签搜索风格库
  apply    将风格库条目应用到新书（覆盖设定/文风锚.md）
  delete   从风格库中删除指定条目

用法：
  # 导入：从某本书的设定/文风锚.md 导入风格库
  python scripts/style_library.py import "D:/存放/小说/我的书" --name "冷酷修仙风" --tags "修仙,冷峻"

  # 列出所有条目
  python scripts/style_library.py list

  # 搜索
  python scripts/style_library.py search --genre "玄幻" --tag "热血"
  python scripts/style_library.py search --keyword "爽文"

  # 应用到新书
  python scripts/style_library.py apply "style-001" --target "D:/存放/小说/新书"

  # 删除
  python scripts/style_library.py delete "style-001"

风格库目录结构：
  assets/style_library/
  ├── index.json              # 风格条目索引
  └── snippets/               # 锚点片段（.md 文件，按 style_id 命名）
"""

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
STYLE_LIB_DIR = os.path.join(SKILL_DIR, "assets", "style_library")
INDEX_PATH = os.path.join(STYLE_LIB_DIR, "index.json")
SNIPPETS_DIR = os.path.join(STYLE_LIB_DIR, "snippets")

# 依赖 style_fingerprint.py 的公开函数
sys.path.insert(0, SCRIPT_DIR)
try:
    from style_fingerprint import (
        compute_six_dimensions,
        count_chars,
        format_anchor_md,
        parse_anchor_md,
        DEFAULT_TOLERANCE,
    )
except ImportError:
    print("错误：无法导入 style_fingerprint.py，请确认该文件在 scripts/ 目录下", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# 索引文件读写
# ---------------------------------------------------------------------------
def _ensure_dirs():
    """确保风格库目录存在。"""
    os.makedirs(SNIPPETS_DIR, exist_ok=True)


def _load_index():
    """加载风格库索引，不存在则返回空列表。"""
    _ensure_dirs()
    if not os.path.exists(INDEX_PATH):
        return []
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(entries):
    """保存风格库索引。"""
    _ensure_dirs()
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _generate_id():
    """生成唯一风格条目 ID，格式：style-YYYYMMDD-{uuid8}。"""
    now = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"style-{now}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# 子命令：import
# ---------------------------------------------------------------------------
def cmd_import(args):
    """从书籍工程导入风格指纹到风格库。"""
    book_dir = os.path.abspath(args.book_dir)
    anchor_path = os.path.join(book_dir, "设定", "文风锚.md")
    fingerprint_path = os.path.join(book_dir, "设定", "文风指纹.md")
    genre_path = os.path.join(book_dir, "设定", "题材定位.md")

    # 1. 确定风格锚文件
    source_path = None
    source_type = None
    if os.path.exists(anchor_path):
        source_path = anchor_path
        source_type = "anchor"
    elif os.path.exists(fingerprint_path):
        source_path = fingerprint_path
        source_type = "fingerprint"
    else:
        print(f"错误：书籍工程中未找到 设定/文风锚.md 或 设定/文风指纹.md", file=sys.stderr)
        print(f"  检查路径：{book_dir}", file=sys.stderr)
        return 2

    # 2. 解析文风锚获取六维指标
    if source_type == "anchor":
        metrics, tolerance = parse_anchor_md(source_path)
    else:
        with open(source_path, "r", encoding="utf-8-sig") as f:
            md_text = f.read()
        metrics = {
            "avg_sent_len": 0.0,
            "dialogue_ratio": 0.0,
            "median_para_len": 0.0,
            "punct_rhythm": {"q": 0.0, "e": 0.0, "ellipsis": 0.0},
            "sentence_pattern": {"alternation_ratio": 0.0, "short_count": 0, "long_count": 0},
            "top_words": [],
        }
        tolerance = dict(DEFAULT_TOLERANCE)
        # 简单解析文风指纹 markdown
        for line in md_text.splitlines():
            s = line.strip()
            if s.startswith("- 平均句长"):
                m = re.search(r"(\d+\.?\d*)", s)
                if m:
                    metrics["avg_sent_len"] = float(m.group(1))
            elif s.startswith("- 对话占比"):
                m = re.search(r"(\d+\.?\d*)", s)
                if m:
                    metrics["dialogue_ratio"] = float(m.group(1))
            elif s.startswith("- 段落中位长度"):
                m = re.search(r"(\d+\.?\d*)", s)
                if m:
                    metrics["median_para_len"] = float(m.group(1))
            elif s.startswith("- 标点节奏"):
                nums = re.findall(r"(\d+\.?\d*)", s)
                if len(nums) >= 1:
                    metrics["punct_rhythm"]["q"] = float(nums[0])
                if len(nums) >= 2:
                    metrics["punct_rhythm"]["e"] = float(nums[1])
                if len(nums) >= 3:
                    metrics["punct_rhythm"]["ellipsis"] = float(nums[2])
            elif s.startswith("- 句式偏好"):
                m = re.search(r"交替比\s*(\d+\.?\d*)", s)
                if m:
                    metrics["sentence_pattern"]["alternation_ratio"] = float(m.group(1))

    # 3. 提取题材和标签
    genre = args.genre or ""
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]

    if not genre and os.path.exists(genre_path):
        with open(genre_path, "r", encoding="utf-8-sig") as f:
            gtext = f.read()
        m = re.search(r"主题材[：:]\s*(.+)", gtext)
        if m:
            genre = m.group(1).strip()

    # 4. 提取书名
    book_name = args.name or os.path.basename(book_dir)

    # 5. 提取锚点片段
    snippet_text = ""
    with open(source_path, "r", encoding="utf-8-sig") as f:
        full_text = f.read()

    # 尝试从 "## 样板段落" 或 "## 锚点片段" 之后提取
    for heading in ("## 样板段落", "## 锚点片段", "## 样板段落（"):
        idx = full_text.find(heading)
        if idx >= 0:
            snippet_text = full_text[idx:]
            break

    # 6. 保存锚点片段
    style_id = _generate_id()
    snippet_filename = f"{style_id}.md"
    snippet_path = os.path.join(SNIPPETS_DIR, snippet_filename)
    with open(snippet_path, "w", encoding="utf-8") as f:
        f.write(f"# 锚点片段：{book_name}\n")
        f.write(f"> 来源：{source_path}\n")
        f.write(f"> 导入时间：{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n\n")
        f.write(snippet_text if snippet_text else "（无锚点片段）")

    # 7. 构建风格条目
    entry = {
        "id": style_id,
        "name": args.name or book_name,
        "source_book": book_name,
        "source_path": source_path,
        "genre": genre,
        "tags": tags,
        "metrics": {
            "avg_sent_len": metrics["avg_sent_len"],
            "dialogue_ratio": metrics["dialogue_ratio"],
            "median_para_len": metrics["median_para_len"],
            "punct_rhythm": metrics["punct_rhythm"],
            "sentence_pattern": metrics["sentence_pattern"],
            "top_words": metrics.get("top_words", []),
        },
        "snippet_path": snippet_path,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": args.notes or "",
    }

    # 8. 写入索引
    entries = _load_index()
    entries.append(entry)
    _save_index(entries)

    print(f"已导入风格条目：{style_id}")
    print(f"  名称：{entry['name']}")
    print(f"  来源：{entry['source_book']}")
    print(f"  题材：{genre or '（未指定）'}")
    print(f"  标签：{', '.join(tags) if tags else '（无）'}")
    print(f"  六维：句长 {metrics['avg_sent_len']:.1f} / 对话 {metrics['dialogue_ratio']:.1f}% / "
          f"段落 {metrics['median_para_len']:.0f} 字")
    return 0


# ---------------------------------------------------------------------------
# 子命令：list
# ---------------------------------------------------------------------------
def cmd_list(args):
    """列出风格库中所有条目。"""
    entries = _load_index()
    if not entries:
        print("风格库为空。使用 import 子命令导入风格。")
        return 0

    if args.format == "json":
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0

    print(f"风格库共 {len(entries)} 条记录：\n")
    for i, e in enumerate(entries, 1):
        m = e.get("metrics", {})
        pr = m.get("punct_rhythm", {})
        print(f"  [{i}] {e['id']}")
        print(f"      名称：{e.get('name', '')}")
        print(f"      来源：{e.get('source_book', '')}")
        print(f"      题材：{e.get('genre', '')}")
        print(f"      标签：{', '.join(e.get('tags', []))}")
        print(f"      六维：句长 {m.get('avg_sent_len', 0):.1f} / "
              f"对话 {m.get('dialogue_ratio', 0):.1f}% / "
              f"段落 {m.get('median_para_len', 0):.0f} 字 / "
              f"？{pr.get('q', 0):.1f}% ！{pr.get('e', 0):.1f}% ……{pr.get('ellipsis', 0):.1f}%")
        print(f"      创建：{e.get('created_at', '')}")
        if e.get("notes"):
            print(f"      备注：{e['notes']}")
        print()
    return 0


# ---------------------------------------------------------------------------
# 子命令：search
# ---------------------------------------------------------------------------
def cmd_search(args):
    """按题材/标签/关键词搜索风格库。"""
    entries = _load_index()
    if not entries:
        print("风格库为空。")
        return 0

    results = []
    for e in entries:
        score = 0
        reasons = []

        # 题材匹配
        if args.genre:
            g = args.genre.lower()
            entry_genre = (e.get("genre", "") or "").lower()
            if g in entry_genre or entry_genre in g:
                score += 3
                reasons.append(f"题材匹配：{e.get('genre', '')}")

        # 标签匹配
        if args.tag:
            tags_lower = [t.lower() for t in e.get("tags", [])]
            for t in args.tag.split(","):
                t = t.strip().lower()
                if any(t in tag or tag in t for tag in tags_lower):
                    score += 2
                    reasons.append(f"标签匹配：{t}")

        # 关键词匹配（名称/来源书/备注）
        if args.keyword:
            kw = args.keyword.lower()
            search_text = " ".join([
                str(e.get("name", "")),
                str(e.get("source_book", "")),
                str(e.get("genre", "")),
                " ".join(e.get("tags", [])),
                str(e.get("notes", "")),
            ]).lower()
            if kw in search_text:
                score += 1
                reasons.append(f"关键词匹配：{kw}")

        if score > 0 or (not args.genre and not args.tag and not args.keyword):
            results.append((score, reasons, e))

    # 按评分降序排序
    results.sort(key=lambda x: x[0], reverse=True)

    if args.limit and args.limit > 0:
        results = results[:args.limit]

    if not results:
        print("未找到匹配的风格条目。")
        return 0

    print(f"找到 {len(results)} 条匹配风格：\n")
    for i, (score, reasons, e) in enumerate(results, 1):
        m = e.get("metrics", {})
        pr = m.get("punct_rhythm", {})
        print(f"  [{i}] {e['id']}  匹配度：{'*' * min(score, 5)}")
        print(f"      名称：{e.get('name', '')}")
        print(f"      来源：{e.get('source_book', '')}")
        print(f"      题材：{e.get('genre', '')}")
        print(f"      标签：{', '.join(e.get('tags', []))}")
        print(f"      六维：句长 {m.get('avg_sent_len', 0):.1f} / "
              f"对话 {m.get('dialogue_ratio', 0):.1f}% / "
              f"段落 {m.get('median_para_len', 0):.0f} 字 / "
              f"？{pr.get('q', 0):.1f}% ！{pr.get('e', 0):.1f}% ……{pr.get('ellipsis', 0):.1f}%")
        print(f"      创建：{e.get('created_at', '')}")
        if reasons:
            print(f"      匹配原因：{' | '.join(reasons)}")
        if e.get("notes"):
            print(f"      备注：{e['notes']}")
        print()

    if args.format == "json":
        print(json.dumps([e for _, _, e in results], ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# 子命令：apply
# ---------------------------------------------------------------------------
def cmd_apply(args):
    """将风格库条目应用到目标书籍工程。"""
    entries = _load_index()
    target = None
    for e in entries:
        if e["id"] == args.style_id:
            target = e
            break

    if target is None:
        print(f"错误：未找到风格条目 {args.style_id}", file=sys.stderr)
        print("  使用 list 子命令查看所有条目。", file=sys.stderr)
        return 2

    book_dir = os.path.abspath(args.target)
    anchor_path = os.path.join(book_dir, "设定", "文风锚.md")

    # 确保目标目录存在
    setting_dir = os.path.join(book_dir, "设定")
    os.makedirs(setting_dir, exist_ok=True)

    m = target.get("metrics", {})
    pr = m.get("punct_rhythm", {})
    sp = m.get("sentence_pattern", {})

    # 生成文风锚 Markdown
    lines = []
    lines.append("# 文风锚")
    lines.append("")
    lines.append(f"> 由 style_library.py apply 从风格库导入。来源：{target.get('source_book', '')}")
    lines.append(f"> 风格条目 ID：{target['id']}")
    lines.append(f"> 应用时间：{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append("")
    lines.append("## 量化基线")
    lines.append(f"- 平均句长：{m.get('avg_sent_len', 0):.1f} 字（容差 ±3）")
    lines.append(f"- 对话占比：{m.get('dialogue_ratio', 0):.1f}%（容差 ±5%）")
    lines.append(f"- 段落中位长度：{m.get('median_para_len', 0):.0f} 字（容差 ±10）")
    lines.append(f"- 标点节奏：？{pr.get('q', 0):.1f}% / ！{pr.get('e', 0):.1f}% / ……{pr.get('ellipsis', 0):.1f}%"
                 f"（容差 ±2%）")
    lines.append(f"- 句式偏好：长短句交替比 {sp.get('alternation_ratio', 0):.2f}"
                 f"（短句 {sp.get('short_count', 0)} / 长句 {sp.get('long_count', 0)}，容差 ±0.2）")
    lines.append("")

    # 高频词
    lines.append("## 高频词 Top20")
    tw = m.get("top_words", [])
    if tw:
        if isinstance(tw[0], list):
            for i, (w, c) in enumerate(tw, 1):
                lines.append(f"{i}. {w} ({c})")
        else:
            for i, w in enumerate(tw, 1):
                lines.append(f"{i}. {w}")
    else:
        lines.append("（无）")
    lines.append("")

    # 腔调关键词
    lines.append("## 腔调关键词")
    lines.append(f"- 本书的腔调是：{target.get('genre', '')} {', '.join(target.get('tags', []))}")
    lines.append("- 不用的腔调：（作者手填）")
    lines.append("")

    # 锚点片段
    lines.append("## 锚点片段")
    snippet_path = target.get("snippet_path", "")
    if snippet_path and os.path.exists(snippet_path):
        with open(snippet_path, "r", encoding="utf-8") as f:
            snippet_content = f.read()
        # 跳过第一行标题
        snippet_lines = snippet_content.splitlines()
        if snippet_lines and snippet_lines[0].startswith("#"):
            snippet_lines = snippet_lines[1:]
        lines.extend(snippet_lines)
    else:
        lines.append("（无锚点片段）")
    lines.append("")

    lines.append("## 高频词白名单")
    lines.append("- （作者手填：本书合理的高频词，不作为 AI 套话处理）")
    lines.append("")

    # 写入
    with open(anchor_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"已将风格条目 {args.style_id} 应用到：{anchor_path}")
    print(f"  来源：{target.get('source_book', '')}")
    print(f"  题材：{target.get('genre', '')}")
    print(f"  标签：{', '.join(target.get('tags', []))}")
    return 0


# ---------------------------------------------------------------------------
# 子命令：delete
# ---------------------------------------------------------------------------
def cmd_delete(args):
    """从风格库中删除指定条目。"""
    entries = _load_index()
    target_idx = None
    for i, e in enumerate(entries):
        if e["id"] == args.style_id:
            target_idx = i
            break

    if target_idx is None:
        print(f"错误：未找到风格条目 {args.style_id}", file=sys.stderr)
        return 2

    entry = entries[target_idx]

    if not args.force:
        print(f"确认删除风格条目？")
        print(f"  ID：{entry['id']}")
        print(f"  名称：{entry.get('name', '')}")
        print(f"  来源：{entry.get('source_book', '')}")
        print(f"  创建：{entry.get('created_at', '')}")
        print()
        print("  使用 --force 参数跳过确认。")
        return 1

    # 删除锚点片段文件
    snippet_path = entry.get("snippet_path", "")
    if snippet_path and os.path.exists(snippet_path):
        os.remove(snippet_path)

    # 从索引中移除
    entries.pop(target_idx)
    _save_index(entries)

    print(f"已删除风格条目：{args.style_id}")
    print(f"  名称：{entry.get('name', '')}")
    return 0


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description="跨书风格库管理：导入、检索、应用风格指纹到新书。"
    )
    sub = ap.add_subparsers(dest="command", required=True)

    # ---- import ----
    p_import = sub.add_parser("import", help="从书籍工程导入风格指纹到风格库")
    p_import.add_argument("book_dir", help="书籍工程目录路径")
    p_import.add_argument("--name", default=None, help="风格条目名称（默认取书名）")
    p_import.add_argument("--genre", default=None, help="题材（默认从题材定位.md 自动提取）")
    p_import.add_argument("--tags", default=None, help="标签，逗号分隔")
    p_import.add_argument("--notes", default=None, help="备注")
    p_import.set_defaults(func=cmd_import)

    # ---- list ----
    p_list = sub.add_parser("list", help="列出风格库中所有条目")
    p_list.add_argument("--format", choices=["table", "json"], default="table",
                        help="输出格式（默认 table）")
    p_list.set_defaults(func=cmd_list)

    # ---- search ----
    p_search = sub.add_parser("search", help="按题材/标签/关键词搜索风格库")
    p_search.add_argument("--genre", default=None, help="按题材搜索")
    p_search.add_argument("--tag", default=None, help="按标签搜索（逗号分隔）")
    p_search.add_argument("--keyword", default=None, help="按关键词搜索（名称/书名/备注）")
    p_search.add_argument("--limit", type=int, default=None, help="限制返回数量")
    p_search.add_argument("--format", choices=["table", "json"], default="table",
                          help="输出格式（默认 table）")
    p_search.set_defaults(func=cmd_search)

    # ---- apply ----
    p_apply = sub.add_parser("apply", help="将风格库条目应用到新书")
    p_apply.add_argument("style_id", help="风格条目 ID")
    p_apply.add_argument("--target", required=True, help="目标书籍工程目录")
    p_apply.set_defaults(func=cmd_apply)

    # ---- delete ----
    p_delete = sub.add_parser("delete", help="从风格库中删除指定条目")
    p_delete.add_argument("style_id", help="风格条目 ID")
    p_delete.add_argument("--force", action="store_true", help="跳过确认直接删除")
    p_delete.set_defaults(func=cmd_delete)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())