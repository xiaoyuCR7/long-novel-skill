#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_hooks.py — 部署/卸载 long-novel-skill 的机械 Hook 到 Claude Code settings.json。

把 hook_entry.py 注册进书籍工程的 `.claude/settings.json`，实现「无章纲写正文」
与「正文毒句式欠账」的机械强制（PreToolUse / PostToolUse），以及会话开始/压缩前
自动快照（SessionStart / PreCompact）。

用法：
    python scripts/deploy_hooks.py [书籍工程目录]     # 部署（默认当前目录）
    python scripts/deploy_hooks.py <目录> --uninstall  # 卸载本 skill 的 hook 条目

设计原则：
    - 幂等：重复部署只刷新本 skill 管理的条目，不动用户其它 hook。
    - 备份：首次改写 settings.json 前备份为 settings.json.lns-bak。
    - fail-open：hook_entry.py 在 Python/脚本缺失、book 定位失败时静默放行（exit 0）。
    - 豁免：正文文件含 ``<!-- lns:skip -->`` 时跳过该次检查。
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

_HOOK_SCRIPT = Path(__file__).resolve().parent / "hook_entry.py"
_MARKER = "hook_entry.py"  # 用于识别本 skill 管理的条目

# 需要守卫「写正文」的工具（正则）
_WRITE_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"


def _ensure_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _command(event):
    return f'python "{_HOOK_SCRIPT}" {event}'


def _managed_block():
    return {
        "SessionStart": [
            {"hooks": [{"type": "command", "command": _command("SessionStart")}]}
        ],
        "PreToolUse": [
            {"matcher": _WRITE_MATCHER,
             "hooks": [{"type": "command", "command": _command("PreToolUse")}]}
        ],
        "PostToolUse": [
            {"matcher": _WRITE_MATCHER,
             "hooks": [{"type": "command", "command": _command("PostToolUse")}]}
        ],
        "PreCompact": [
            {"hooks": [{"type": "command", "command": _command("PreCompact")}]}
        ],
    }


def _load(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _filter_managed(hooks_dict):
    """移除本 skill 已管理的 hook 条目（按 command 里的 hook_entry.py 识别）。"""
    cleaned = {}
    for event, rules in (hooks_dict or {}).items():
        if not isinstance(rules, list):
            cleaned[event] = rules
            continue
        kept = []
        for rule in rules:
            if not isinstance(rule, dict):
                kept.append(rule)
                continue
            sub = rule.get("hooks", [])
            if isinstance(sub, list) and any(
                isinstance(h, dict) and _MARKER in str(h.get("command", ""))
                for h in sub
            ):
                continue  # 属于本 skill，丢弃（下面会重新添加）
            kept.append(rule)
        if kept:  # 丢弃空的事件条目，避免留下 "PreToolUse": []
            cleaned[event] = kept
    return cleaned


def _backup(path):
    bak = path.with_suffix(path.suffix + ".lns-bak")
    if path.exists() and not bak.exists():
        shutil.copy2(path, bak)
        print(f"[deploy-hooks] 已备份原配置 → {bak.name}")
    return bak


def deploy(project_dir):
    project = Path(project_dir).resolve()
    settings_path = project / ".claude" / "settings.json"

    data = _load(settings_path)
    _backup(settings_path)

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
    hooks = _filter_managed(hooks)
    # 合并本 skill 的 hook 条目
    for event, rules in _managed_block().items():
        hooks[event] = hooks.get(event, []) + rules
    data["hooks"] = hooks

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[deploy-hooks] 已部署 4 类 hook 到 {settings_path}")
    print("  SessionStart / PreCompact  自动进度快照")
    print("  PreToolUse   guard-outline（无章纲写正文 → 阻断）")
    print("  PostToolUse  check-prose（毒句式欠账 → 阻断）")
    print("  豁免：正文文件含 <!-- lns:skip --> 时跳过；卸载：deploy_hooks.py <目录> --uninstall")
    return 0


def uninstall(project_dir):
    project = Path(project_dir).resolve()
    settings_path = project / ".claude" / "settings.json"

    data = _load(settings_path)
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
    hooks = _filter_managed(hooks)

    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)

    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[deploy-hooks] 已移除本 skill 的 hook 条目 → {settings_path}")
    return 0


def main(argv):
    _ensure_utf8()
    ap = argparse.ArgumentParser(description="部署/卸载 long-novel-skill 机械 Hook")
    ap.add_argument("project_dir", nargs="?", default=".", help="书籍工程目录（默认当前目录）")
    ap.add_argument("--uninstall", action="store_true", help="卸载本 skill 的 hook 条目")
    args = ap.parse_args(argv[1:])

    if args.uninstall:
        return uninstall(args.project_dir)
    return deploy(args.project_dir)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
