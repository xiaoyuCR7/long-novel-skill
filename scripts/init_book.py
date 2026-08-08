#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""init_book.py — 一键初始化书籍工程骨架（纯标准库，无第三方依赖）。

按 assets/templates/book-structure.md 的布局创建书籍工程目录，
从 assets/templates/ 拷贝追踪/设定模板，把「开书先搭骨架」从手工活变成一条命令。

创建内容：
  {书名}/
  ├── 大纲/  正文/  对标/  参考资料/
  ├── 设定/  题材定位.md、读者契约.md、文风锚.md、敏感词替换表.md、禁用词.txt、角色/
  ├── 追踪/  伏笔台账.md、角色状态.md、章节摘要.md、时间线.md、节奏配额.md、门禁/
  └── .deslop-whitelist（白名单模板）

已存在且非空的目录默认拒绝覆盖（--force 强制重建模板文件，不动正文/大纲）。

用法：
  python3 scripts/init_book.py "我的小说" --genre 玄幻 --platform 番茄
  python3 scripts/init_book.py "我的小说" --dir "D:/存放/小说" --force

退出码：0 = 成功；1 = 目录已存在且非空（未 --force）；2 = 参数/文件错误。
"""

import argparse
import os
import shutil
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, os.pardir, "assets", "templates"))

# 追踪文件模板（原样拷贝）
TRACKING_TEMPLATES = {
    "伏笔台账.md": "foreshadowing-ledger.md",
    "角色状态.md": "character-state.md",
    "章节摘要.md": "chapter-summary.md",
    "时间线.md": "timeline.md",
    "节奏配额.md": "rhythm-quota.md",
}

# 设定文件模板（原样拷贝）
SETTING_TEMPLATES = {
    "题材定位.md": "genre-profile.md",
    "读者契约.md": "reader-contract.md",
    "文风锚.md": "style-anchor.md",
    "敏感词替换表.md": "sensitive-word-replacement.md",
}

WHITELIST_TEMPLATE = """# 去AI味白名单（每行一个词，# 开头为注释）
# 命中段若子串在本名单中存在则跳过。适用：术语、绰号、设定专有名词。
"""

BANNED_TEMPLATE = """# 题材专属禁用词（每行一个词，# 开头为注释）
# 开书时从题材卡的「专属禁用词」一节拷贝至此；check_text.py 自动加载。
"""

DIRS = ["大纲", "正文", "对标", "参考资料",
        os.path.join("设定", "角色"), "追踪", os.path.join("追踪", "门禁")]


def fill_genre_profile(path, title, genre, platform):
    """对题材定位模板做轻量预填（只填确定信息，其余留占位）。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError:
        return
    if title:
        text = text.replace("- 书名：", f"- 书名：{title}", 1)
    if genre:
        text = text.replace("- 主题材：（必填，用于匹配 references/genres/INDEX.md 的题材卡）",
                            f"- 主题材：{genre}", 1)
    if platform:
        text = text.replace("- 目标平台：（番茄 / 起点 / 晋江 / 其他：____）",
                            f"- 目标平台：{platform}", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description="一键初始化书籍工程骨架")
    ap.add_argument("title", help="书名（目录名）")
    ap.add_argument("--dir", default=".", help="父目录（默认当前目录）")
    ap.add_argument("--genre", default="", help="主题材（预填题材定位）")
    ap.add_argument("--platform", default="", help="目标平台（预填题材定位）")
    ap.add_argument("--force", action="store_true",
                    help="目录已存在时重建缺失的模板文件（不动 正文/ 与 大纲/）")
    args = ap.parse_args()

    book_root = os.path.join(args.dir, args.title)
    if os.path.isdir(book_root) and os.listdir(book_root) and not args.force:
        print(f"错误：目录已存在且非空：{book_root}（用 --force 重建缺失模板）",
              file=sys.stderr)
        return 1

    created, skipped = [], []

    for d in DIRS:
        os.makedirs(os.path.join(book_root, d), exist_ok=True)

    for name, tpl in TRACKING_TEMPLATES.items():
        dst = os.path.join(book_root, "追踪", name)
        src = os.path.join(TEMPLATE_DIR, tpl)
        if os.path.exists(dst):
            skipped.append(f"追踪/{name}（已存在）")
            continue
        shutil.copyfile(src, dst)
        created.append(f"追踪/{name}")

    for name, tpl in SETTING_TEMPLATES.items():
        dst = os.path.join(book_root, "设定", name)
        src = os.path.join(TEMPLATE_DIR, tpl)
        if os.path.exists(dst):
            skipped.append(f"设定/{name}（已存在）")
            continue
        shutil.copyfile(src, dst)
        created.append(f"设定/{name}")

    for name, content in [("禁用词.txt", BANNED_TEMPLATE)]:
        dst = os.path.join(book_root, "设定", name)
        if not os.path.exists(dst):
            with open(dst, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(f"设定/{name}")
        else:
            skipped.append(f"设定/{name}（已存在）")

    dst = os.path.join(book_root, ".deslop-whitelist")
    if not os.path.exists(dst):
        with open(dst, "w", encoding="utf-8") as f:
            f.write(WHITELIST_TEMPLATE)
        created.append(".deslop-whitelist")
    else:
        skipped.append(".deslop-whitelist（已存在）")

    fill_genre_profile(os.path.join(book_root, "设定", "题材定位.md"),
                       args.title, args.genre, args.platform)

    print(f"书籍工程已初始化：{os.path.abspath(book_root)}")
    if created:
        print(f"  新建：{'、'.join(created)}")
    if skipped:
        print(f"  跳过：{'、'.join(skipped)}")
    print()
    print("下一步（按 references/workflow/book-init.md 走）：")
    print("  1. 补全 设定/题材定位.md（一句话卖点/目标字数/更新计划/对标）")
    print("  2. 填 设定/读者契约.md；把题材卡「专属禁用词」拷入 设定/禁用词.txt")
    print("  3. 建 设定/敏感词替换表.md（真实地名/机构/人物 → 全书代称，见 craft/sensitive-word-replacement.md）")
    print("  4. 建人物卡（设定/角色/）与总纲（大纲/总纲.md）")
    print("  5. 首批章纲 5–10 章停靠；写第 1 章前用 rhythm_guard.py --declare 预检")
    return 0


if __name__ == "__main__":
    sys.exit(main())
