#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""outline_anchor.py — 大纲锚点动态约束注入（纯标准库，无第三方依赖）。

解决 AI 写长篇时「把长线任务当短线跑」的通病：
- 维护 outline_anchors.json 全局进度条
- 每章写前生成自然语言约束（禁止揭露 / 必须达成 / 保留未解决冲突）
- 改纲时重算锚点

用法：
  python scripts/outline_anchor.py init "{书名目录}" --total 300 --volumes 8
  python scripts/outline_anchor.py inject "{书名目录}" --chapter 37
  python scripts/outline_anchor.py advance "{书名目录}" --chapter 50 --volume-end
  python scripts/outline_anchor.py check "{书名目录}" --chapter 37 --quota A
  python scripts/outline_anchor.py status "{书名目录}"

退出码：0 = 正常；1 = 越界/违规；2 = 参数错误。
"""

import argparse
import json
import os
import re
import sys


ANCHOR_FILE = "outline_anchors.json"

DEFAULT_SCHEMA = {
    "total_chapters": 0,
    "total_volumes": 0,
    "current_chapter": 0,
    "current_volume": 0,
    "progress_pct": 0.0,
    "volumes": [],
}

VOLUME_SCHEMA = {
    "volume_num": 0,
    "name": "",
    "chapter_start": 0,
    "chapter_end": 0,
    "progress_start_pct": 0.0,
    "progress_end_pct": 0.0,
    "must_achieve": [],
    "must_not_reveal": [],
    "foreshadows_to_plant": [],
    "resolved": False,
}


def _anchor_path(book_root):
    return os.path.join(book_root, "大纲", ANCHOR_FILE)


def _load(book_root):
    path = _anchor_path(book_root)
    if not os.path.isfile(path):
        return None, path
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f), path


def _save(book_root, data):
    path = _anchor_path(book_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def cmd_init(book_root, args):
    """初始化大纲锚点文件。"""
    data = dict(DEFAULT_SCHEMA)
    data["total_chapters"] = args.total
    data["total_volumes"] = args.volumes
    
    # 生成卷级骨架
    chap_per_vol = max(1, args.total // args.volumes)
    for i in range(1, args.volumes + 1):
        vol = dict(VOLUME_SCHEMA)
        vol["volume_num"] = i
        vol["chapter_start"] = (i - 1) * chap_per_vol + 1
        vol["chapter_end"] = i * chap_per_vol if i < args.volumes else args.total
        vol["progress_start_pct"] = round((i - 1) / args.volumes * 100, 1)
        vol["progress_end_pct"] = round(i / args.volumes * 100, 1)
        data["volumes"].append(vol)
    
    path = _save(book_root, data)
    print(f"锚点文件已初始化：{path}")
    print(f"  全书 {args.total} 章 / {args.volumes} 卷")
    for vol in data["volumes"]:
        print(f"  第{vol['volume_num']}卷：第{vol['chapter_start']}-{vol['chapter_end']}章 "
              f"（{vol['progress_start_pct']}%-{vol['progress_end_pct']}%）")
    return 0


def _find_volume(data, chapter):
    """找到章节所属的卷。"""
    for vol in data["volumes"]:
        if vol["chapter_start"] <= chapter <= vol["chapter_end"]:
            return vol
    return None


def cmd_inject(book_root, args):
    """生成第 N 章的自然语言约束注入文本。"""
    data, path = _load(book_root)
    if not data:
        print(f"错误：锚点文件不存在，先运行 init。", file=sys.stderr)
        return 2
    
    chap = args.chapter
    vol = _find_volume(data, chap)
    if not vol:
        print(f"错误：第{chap}章不在任何卷的章节范围内。", file=sys.stderr)
        return 2
    
    pct = round((chap / data["total_chapters"]) * 100, 1)
    vol_pct = round(((chap - vol["chapter_start"] + 1) / 
                      (vol["chapter_end"] - vol["chapter_start"] + 1)) * 100, 1)
    
    lines = [
        f"## 大纲锚点约束（第{chap}章）",
        f"",
        f"- 全书进度：{pct}%（第{chap}/{data['total_chapters']}章）",
        f"- 本卷进度：第{vol['volume_num']}卷 {vol_pct}%（第{chap - vol['chapter_start'] + 1}/{vol['chapter_end'] - vol['chapter_start'] + 1}章）",
    ]
    
    if vol["must_not_reveal"]:
        lines.append(f"- **禁止揭露**：{'、'.join(vol['must_not_reveal'])}")
    if vol["must_achieve"]:
        achieved = []
        remaining = []
        # 简单启发式：如果章节进度过半，假设前半已达成
        if vol_pct > 50:
            achieved = vol["must_achieve"][:(len(vol["must_achieve"]) + 1) // 2]
            remaining = vol["must_achieve"][len(achieved):]
        else:
            remaining = vol["must_achieve"]
        if achieved:
            lines.append(f"- **已达成**：{'、'.join(achieved)}")
        if remaining:
            lines.append(f"- **必须达成**（本章或后续）：{'、'.join(remaining)}")
    if vol["foreshadows_to_plant"]:
        lines.append(f"- **待埋伏笔**：{'、'.join(vol['foreshadows_to_plant'])}")
    
    # 全局进度约束
    if pct < 30:
        lines.append(f"- **阶段定位**：开篇期（<30%），聚焦主角立足与核心冲突建立，不要推进到中期剧情")
    elif pct < 60:
        lines.append(f"- **阶段定位**：发展期（30-60%），可以升级冲突但不要揭露核心秘密或解决主线")
    elif pct < 85:
        lines.append(f"- **阶段定位**：高潮期（60-85%），核心冲突可以正面碰撞，但保留终局底牌")
    else:
        lines.append(f"- **阶段定位**：终局期（>85%），可以开始揭露核心秘密和推进终局，但每章至多揭露一项")
    
    text = "\n".join(lines)
    print(text)
    
    if args.output:
        out = os.path.join(book_root, args.output) if not os.path.isabs(args.output) else args.output
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\n已写入：{out}")
    
    return 0


def cmd_check(book_root, args):
    """检查某章的 A/B/C 配额是否与锚点进度兼容。"""
    data, path = _load(book_root)
    if not data:
        print(f"错误：锚点文件不存在，先运行 init。", file=sys.stderr)
        return 2
    
    chap = args.chapter
    quota = args.quota.upper() if args.quota else ""
    pct = round((chap / data["total_chapters"]) * 100, 1)
    vol = _find_volume(data, chap)
    
    issues = []
    
    # 规则1：进度 < 15% 不允许 A（主线实质推进）
    if pct < 15 and quota == "A":
        issues.append(f"进度 {pct}% < 15%，不允许触发 A（主线实质推进），当前应聚焦开篇立人设")
    
    # 规则2：进度 < 40% 不允许 C（核心秘密揭露）
    if pct < 40 and quota == "C":
        issues.append(f"进度 {pct}% < 40%，不允许触发 C（核心秘密揭露）")
    
    # 规则3：卷内进度 > 80% 才允许 A
    if vol and quota == "A":
        vol_pct = round(((chap - vol["chapter_start"] + 1) / 
                          (vol["chapter_end"] - vol["chapter_start"] + 1)) * 100, 1)
        if vol_pct < 80:
            issues.append(f"本卷进度 {vol_pct}% < 80%，A（主线推进）应在卷末 80% 后触发")
    
    # 规则4：C 触发后 10 章内不允许再 C
    if quota == "C" and hasattr(args, 'last_c_chapter') and args.last_c_chapter:
        gap = chap - args.last_c_chapter
        if gap < 10:
            issues.append(f"距上次 C 触发仅 {gap} 章，C（核心秘密揭露）冷却期 ≥ 10 章")
    
    if issues:
        print(f"⛔ 第{chap}章配额 [{quota}] 与锚点冲突：")
        for i in issues:
            print(f"  - {i}")
        return 1
    else:
        print(f"✓ 第{chap}章配额 [{quota or '未声明'}] 与锚点兼容（进度 {pct}%）")
        return 0


def cmd_advance(book_root, args):
    """推进当前章节指针（每章写完后调用）。"""
    data, path = _load(book_root)
    if not data:
        print(f"错误：锚点文件不存在。", file=sys.stderr)
        return 2
    
    old_chap = data["current_chapter"]
    data["current_chapter"] = args.chapter
    data["progress_pct"] = round((args.chapter / data["total_chapters"]) * 100, 1)
    
    vol = _find_volume(data, args.chapter)
    if vol:
        data["current_volume"] = vol["volume_num"]
    
    # 卷末标记
    if args.volume_end and vol:
        vol["resolved"] = True
    
    _save(book_root, data)
    print(f"锚点已推进：第{old_chap}章 → 第{args.chapter}章（{data['progress_pct']}%）")
    if args.volume_end and vol:
        print(f"  第{vol['volume_num']}卷已标记为完结")
    return 0


def cmd_status(book_root, args):
    """显示当前锚点状态。"""
    data, path = _load(book_root)
    if not data:
        print(f"错误：锚点文件不存在，先运行 init。", file=sys.stderr)
        return 2
    
    print(f"全书进度：第{data['current_chapter']}/{data['total_chapters']}章（{data['progress_pct']}%）")
    print(f"当前卷：第{data['current_volume']}卷")
    for vol in data["volumes"]:
        status = "✅ 已完结" if vol["resolved"] else "📝 进行中" if vol["volume_num"] == data["current_volume"] else "⬜ 未开始"
        print(f"  第{vol['volume_num']}卷：{vol['chapter_start']}-{vol['chapter_end']}章 "
              f"（{vol['progress_start_pct']}%-{vol['progress_end_pct']}%）{status}")
        if vol["must_not_reveal"]:
            print(f"    禁止揭露：{'、'.join(vol['must_not_reveal'])}")
        if vol["must_achieve"]:
            print(f"    必须达成：{'、'.join(vol['must_achieve'])}")
    
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description="大纲锚点：init 初始化 / inject 约束注入 / check 配额兼容 / advance 推进 / status 状态")
    sub = ap.add_subparsers(dest="command")
    
    # init
    p_init = sub.add_parser("init", help="初始化锚点文件")
    p_init.add_argument("book_root")
    p_init.add_argument("--total", type=int, required=True, help="全书总章数")
    p_init.add_argument("--volumes", type=int, required=True, help="总卷数")
    
    # inject
    p_inject = sub.add_parser("inject", help="生成第N章的约束注入文本")
    p_inject.add_argument("book_root")
    p_inject.add_argument("--chapter", type=int, required=True, help="目标章节号")
    p_inject.add_argument("--output", default=None, help="输出文件路径（可选）")
    
    # check
    p_check = sub.add_parser("check", help="检查配额与锚点是否兼容")
    p_check.add_argument("book_root")
    p_check.add_argument("--chapter", type=int, required=True, help="章节号")
    p_check.add_argument("--quota", default=None, choices=["A", "B", "C"], help="本章声明的配额")
    p_check.add_argument("--last-c-chapter", type=int, default=None, help="上次触发 C 的章节号")
    
    # advance
    p_advance = sub.add_parser("advance", help="推进章节指针")
    p_advance.add_argument("book_root")
    p_advance.add_argument("--chapter", type=int, required=True, help="当前完成的章节号")
    p_advance.add_argument("--volume-end", action="store_true", help="标记本卷完结")
    
    # status
    p_status = sub.add_parser("status", help="显示锚点状态")
    p_status.add_argument("book_root")
    p_status.add_argument("--json", action="store_true", help="机器可读输出")
    
    args = ap.parse_args()
    if not args.command:
        ap.print_help()
        return 2
    
    book_root = os.path.abspath(args.book_root)
    
    cmds = {
        "init": cmd_init,
        "inject": cmd_inject,
        "check": cmd_check,
        "advance": cmd_advance,
        "status": cmd_status,
    }
    return cmds[args.command](book_root, args)


if __name__ == "__main__":
    sys.exit(main())
