#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hook_entry.py — Claude Code hook 分发器（纯标准库，fail-open）。

由 settings.json 的 hooks 配置调用：
    python <skill>/scripts/hook_entry.py <event>

<event> 取值（与 Claude Code hook 事件一一对应）：
    SessionStart | PreToolUse | PostToolUse | PreCompact

运行时从 stdin 读取 Claude Code 传入的 JSON 事件，解析 cwd / tool_name /
tool_input，自动定位书籍工程目录，分发到 hooks.py 对应子命令：

    SessionStart → hooks.py session-start <book>
    PreToolUse   → 若工具在写正文 → hooks.py guard-outline <book> --chapter <N>
    PostToolUse  → 若工具写了正文 → hooks.py check-prose <file> --book-dir <book>
    PreCompact   → hooks.py pre-compact <book>

阻断语义（对齐 oh-story 的「宁可漏拦不可误伤」）：
    hooks.py 返回 1（blocking 规则命中）→ 本脚本 exit 2（平台级阻断工具）
    其余（0 通过 / 2 参数错误 / 异常 / JSON 解析失败 / 无法定位 book）→ exit 0 放行

豁免：
    目标正文文件内容、或事件 JSON 字符串中含 ``<!-- lns:skip -->`` 时跳过检查，exit 0。
    book 目录可用环境变量 ``LNS_BOOK_DIR`` 显式指定，优先级最高。
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOKS_PY = HERE / "hooks.py"

# 需要守卫「写正文」的工具名（按 Claude Code 工具名）
_WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# 正文目录相对路径特征
_PROSE_DIR_RE = re.compile(r"[\\/]正文[\\/]")
_CHAPTER_RE = re.compile(r"第\s*0*(\d+)\s*章")
_SKIP_MARKER = "<!-- lns:skip -->"

_BOOK_MARKERS = ("追踪", "大纲")


def _ensure_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _load_event():
    """读取 stdin 上的 JSON 事件；失败返回 None（fail-open）。"""
    try:
        raw = sys.stdin.read()
    except Exception:
        return None
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _looks_like_book(d):
    if not d or not os.path.isdir(d):
        return False
    return all(os.path.isdir(os.path.join(d, m)) for m in _BOOK_MARKERS)


def _resolve_book_dir(event):
    """定位书籍工程目录，返回 str 或 None（绝不猜测，宁可 None 放行）。"""
    # 1. 显式环境变量（最高优先级）
    env = os.environ.get("LNS_BOOK_DIR")
    if env and _looks_like_book(env):
        return os.path.abspath(env)

    # 2. 事件里的 cwd
    cwd = (event or {}).get("cwd")
    if isinstance(cwd, str) and cwd:
        if _looks_like_book(cwd):
            return os.path.abspath(cwd)
        # 3. cwd 下的 .active-book 指向（多书切换时由用户/模型维护）
        marker = Path(cwd) / ".active-book"
        try:
            if marker.is_file():
                rel = marker.read_text(encoding="utf-8").strip()
                if rel and _looks_like_book(os.path.join(cwd, rel)):
                    return os.path.abspath(os.path.join(cwd, rel))
        except OSError:
            pass

    # 4. 当前进程 cwd
    if _looks_like_book(os.getcwd()):
        return os.path.abspath(os.getcwd())

    return None


def _is_prose_path(file_path):
    return isinstance(file_path, str) and _PROSE_DIR_RE.search(file_path) and file_path.endswith(".md")


def _extract_chapter(file_path):
    m = _CHAPTER_RE.search(os.path.basename(file_path))
    return int(m.group(1)) if m else None


def _skip_requested(event, file_path):
    """命中豁免标记则放行。"""
    if isinstance(file_path, str):
        try:
            if _SKIP_MARKER in Path(file_path).read_text(encoding="utf-8-sig", errors="ignore"):
                return True
        except OSError:
            pass
    try:
        blob = json.dumps(event or {}, ensure_ascii=False)
    except (TypeError, ValueError):
        blob = ""
    return _SKIP_MARKER in blob


def _run_hook(subcmd, args):
    """调用 hooks.py 子命令，返回 (exit_code, stdout, stderr)。失败 → (0, '', '')。"""
    cmd = [sys.executable, str(HOOKS_PY), subcmd] + [str(a) for a in args]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except Exception:
        return 0, "", ""


def _emit(rc, stdout, stderr):
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    return rc


def _block_if_violated(hook_rc):
    """hooks.py 返回 1 = blocking 规则命中 → 平台级 exit 2；否则放行。"""
    return 2 if hook_rc == 1 else 0


def handle_session_start(book_dir):
    rc, out, err = _run_hook("session-start", [book_dir])
    return _emit(0, out, err)  # 进度快照为信息性，不阻断


def handle_pre_compact(book_dir):
    rc, out, err = _run_hook("pre-compact", [book_dir])
    return _emit(0, out, err)  # 快照类不阻断


def handle_pre_tool_use(event):
    tool = (event or {}).get("tool_name", "")
    tool_input = (event or {}).get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (ValueError, TypeError):
            tool_input = {}
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None

    if tool not in _WRITE_TOOLS or not _is_prose_path(file_path):
        return 0
    if _skip_requested(event, file_path):
        return 0
    book_dir = _resolve_book_dir(event)
    if not book_dir:
        return 0
    chapter = _extract_chapter(file_path)
    if chapter is None:
        return 0
    rc, out, err = _run_hook("guard-outline", [book_dir, "--chapter", str(chapter)])
    return _emit(_block_if_violated(rc), out, err)


def handle_post_tool_use(event):
    tool = (event or {}).get("tool_name", "")
    tool_input = (event or {}).get("tool_input") or {}
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (ValueError, TypeError):
            tool_input = {}
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None

    if tool not in _WRITE_TOOLS or not _is_prose_path(file_path):
        return 0
    if _skip_requested(event, file_path):
        return 0
    book_dir = _resolve_book_dir(event)
    if not book_dir:
        return 0
    rc, out, err = _run_hook("check-prose", [file_path, "--book-dir", book_dir])
    return _emit(_block_if_violated(rc), out, err)


def main(argv):
    _ensure_utf8()
    event = _load_event()

    event_name = argv[1] if len(argv) > 1 else ""

    if event_name == "SessionStart":
        book_dir = _resolve_book_dir(event)
        if not book_dir:
            return 0
        return handle_session_start(book_dir)

    if event_name == "PreToolUse":
        return handle_pre_tool_use(event)

    if event_name == "PostToolUse":
        return handle_post_tool_use(event)

    if event_name == "PreCompact":
        book_dir = _resolve_book_dir(event)
        if not book_dir:
            return 0
        return handle_pre_compact(book_dir)

    return 0  # 未知事件 → 放行


if __name__ == "__main__":
    sys.exit(main(sys.argv))
