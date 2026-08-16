#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel_flow.py — 统一流程执行器 v1.1（纯标准库，无第三方依赖）。

将本 skill 的分散工作流（开书/写章/日更/检修/改纲）整合为统一入口，
提供可脚本化的流程编排。参考 novel-creator-skill 的 novel_flow_executor.py 设计，
但改为纯标准库实现，且编排的是本 skill 的现有脚本生态。

核心命令：
  status   — 诊断书籍工程状态（会话恢复+欠账检查+下一步建议）
  prepare  — 写前准备（大纲锚点注入+上下文选取+节奏预检）
  write    — 单章写作流程编排（prepare→[Agent写]→check→track）
  daily    — 日更批量模式（串行执行N章 write）
  revise   — 改纲级联（锚点重算+图谱标记+索引重建）
  report   — 进度报告（全书进度+追踪状态+质量趋势）
  rollback — 从指定快照恢复追踪文件
  unlock   — 强制清除执行锁
  snapshots — 列出可用快照

不是替代 Agent 的创作功能，而是编排 Agent 的工作流——
Agent 负责"写"，本脚本负责"前后脚的确定性问题"。

用法：
  python3 scripts/novel_flow.py status "{书名目录}"
  python3 scripts/novel_flow.py prepare "{书名目录}" --chapter 37
  python3 scripts/novel_flow.py daily "{书名目录}" --chapters 3
  python3 scripts/novel_flow.py report "{书名目录}"
  python3 scripts/novel_flow.py rollback "{书名目录}" --snapshot {timestamp}
  python3 scripts/novel_flow.py unlock "{书名目录}"
  python3 scripts/novel_flow.py snapshots "{书名目录}"
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# =========================================================
# 常量
# =========================================================

VERSION = "1.1.0"

# 脚本目录（相对于本文件）
SCRIPTS_DIR = Path(__file__).parent

# =========================================================
# 从 config.py 导入幂等回滚相关常量
# =========================================================

_SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPT_DIR))
try:
    from config import (FLOW_LOCK_FILE, FLOW_SNAPSHOT_DIR,
                        FLOW_SNAPSHOT_MAX_KEEP, FLOW_SCRIPT_TIMEOUT,
                        DEFAULT_MIN_CHARS, DEFAULT_MAX_CHARS)
except ImportError:
    FLOW_LOCK_FILE = "追踪/.flow_lock.json"
    FLOW_SNAPSHOT_DIR = "追踪/.snapshots"
    FLOW_SNAPSHOT_MAX_KEEP = 10
    FLOW_SCRIPT_TIMEOUT = 120
    DEFAULT_MIN_CHARS = 2000
    DEFAULT_MAX_CHARS = 4500

# 需要备份的追踪文件列表
SNAPSHOT_TRACKING_FILES = [
    "伏笔台账.md",
    "角色状态.md",
    "章节摘要.md",
    "节奏配额.md",
    "entity_index.json",
    "story_graph.json",
]

# =========================================================
# 工具函数
# =========================================================

def find_book_dir(path: str) -> Optional[Path]:
    """查找书籍工程目录"""
    p = Path(path)
    if not p.exists():
        return None
    if (p / "追踪").exists() and (p / "大纲").exists():
        return p
    for child in p.iterdir():
        if child.is_dir() and (child / "追踪").exists():
            return child
    return None


def read_file_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return ""


def run_script(script_name: str, args: List[str], book_dir: Optional[Path] = None) -> Tuple[int, str, str]:
    """运行另一个脚本"""
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        return 1, "", f"脚本不存在: {script_path}"

    cmd = [sys.executable, str(script_path)] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(book_dir) if book_dir else None,
            timeout=FLOW_SCRIPT_TIMEOUT,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"脚本执行超时: {script_name}"
    except Exception as e:
        return 1, "", f"脚本执行异常: {e}"


def find_latest_chapter(book_dir: Path) -> int:
    """找到最新已写章节号"""
    text_dir = book_dir / "正文"
    if not text_dir.exists():
        return 0
    max_ch = 0
    for f in text_dir.glob("第*章*.md"):
        match = re.search(r"第(\d+)章", f.name)
        if match:
            ch = int(match.group(1))
            if ch > max_ch:
                max_ch = ch
    return max_ch


def _find_chapter_file(book_dir: Path, chapter: int) -> Optional[Path]:
    """定位第 chapter 章正文文件（兼容 第NNN章_标题.md / 第N章_标题.md 命名）。"""
    text_dir = book_dir / "正文"
    if not text_dir.exists():
        return None
    for f in text_dir.glob("第*章*.md"):
        m = re.search(r"第0*(\d+)章", f.name)
        if m and int(m.group(1)) == chapter:
            return f
    return None


def find_next_chapter_outline(book_dir: Path, current_ch: int) -> Optional[int]:
    """找到下一个有章纲的章节号"""
    outline_dir = book_dir / "大纲"
    if not outline_dir.exists():
        return None
    candidates = []
    for f in outline_dir.glob("章纲_第*章*.md"):
        match = re.search(r"第(\d+)章", f.name)
        if match:
            ch = int(match.group(1))
            if ch > current_ch:
                candidates.append(ch)
    if not candidates:
        return None
    return min(candidates)


def check_gate_passed(book_dir: Path, chapter: int) -> bool:
    """检查指定章节的门禁是否通过"""
    gate_file = book_dir / "追踪" / "门禁" / f"gate_ch{chapter}.json"
    if not gate_file.exists():
        return False
    try:
        data = json.loads(read_file_safe(gate_file))
        return data.get("passed", False)
    except (json.JSONDecodeError, TypeError):
        return False


def check_tracking_sync(book_dir: Path, chapter: int) -> Dict[str, bool]:
    """检查追踪文件是否同步到指定章节"""
    tracking_dir = book_dir / "追踪"
    checks = {}

    # 章节摘要
    summary = read_file_safe(tracking_dir / "章节摘要.md")
    checks["章节摘要"] = f"第{chapter}章" in summary

    # 角色状态
    state = read_file_safe(tracking_dir / "角色状态.md")
    checks["角色状态"] = f"第{chapter}章" in state or str(chapter) in state

    # 伏笔台账
    foreshadow = read_file_safe(tracking_dir / "伏笔台账.md")
    checks["伏笔台账"] = True  # 伏笔台账不一定每章更新

    # 节奏配额
    rhythm = read_file_safe(tracking_dir / "节奏配额.md")
    checks["节奏配额"] = f"第{chapter}章" in rhythm

    return checks


def check_foreshadow_overdue(book_dir: Path, current_ch: int) -> List[str]:
    """检查超期伏笔"""
    foreshadow_file = book_dir / "追踪" / "伏笔台账.md"
    if not foreshadow_file.exists():
        return []
    content = read_file_safe(foreshadow_file)
    overdue = []
    for line in content.split("\n"):
        if "🔴" in line:
            # 检查回收窗口
            match = re.search(r"第(\d+)-(\d+)章", line)
            if match:
                end_ch = int(match.group(2))
                if end_ch < current_ch:
                    overdue.append(line.strip())
            else:
                overdue.append(line.strip())
    return overdue


# =========================================================
# 幂等回滚机制 — 执行锁
# =========================================================

def _lock_path(book_dir: Path) -> Path:
    """获取锁文件路径"""
    return book_dir / FLOW_LOCK_FILE


def _is_pid_alive(pid: int) -> bool:
    """检查进程是否存活（跨平台）"""
    try:
        if sys.platform == "win32":
            # Windows: tasklist 方式
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        else:
            # Unix: os.kill(pid, 0) 不发信号只检查
            os.kill(pid, 0)
            return True
    except (OSError, subprocess.TimeoutExpired, Exception):
        return False


def _lock_is_expired(lock_data: Dict[str, Any]) -> bool:
    """判断锁是否过期"""
    try:
        started_at = lock_data.get("started_at", "")
        if not started_at:
            return True
        started = datetime.fromisoformat(started_at)
        elapsed = (datetime.now() - started).total_seconds()
        return elapsed > FLOW_SCRIPT_TIMEOUT
    except (ValueError, TypeError):
        return True


def acquire_lock(book_dir: Path, command: str, chapter: Optional[int] = None) -> Tuple[bool, str]:
    """获取执行锁。

    Returns:
        (success, message) — 成功返回 (True, "")，失败返回 (False, 原因)
    """
    lock_file = _lock_path(book_dir)

    # 检查锁是否已存在
    if lock_file.exists():
        try:
            lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            lock_data = {}

        status = lock_data.get("status", "")
        pid = lock_data.get("pid")

        if status == "running" and pid is not None:
            if _is_pid_alive(pid):
                cmd_name = lock_data.get("command", "?")
                ch_info = f", chapter={lock_data.get('chapter')}" if lock_data.get("chapter") else ""
                started = lock_data.get("started_at", "?")
                return False, (
                    f"执行锁冲突：进程 PID={pid} 正在执行 {cmd_name}{ch_info}"
                    f"（启动于 {started}）。如确认进程已死，请用 unlock 命令强制清除。"
                )
            else:
                # PID 已死，锁可以安全清除
                pass

        if not _lock_is_expired(lock_data):
            # 锁未过期但 PID 已死 — 这种情况说明进程异常退出但锁未清理
            # 保留原行为：允许继续（因为 PID 已不存在了）
            pass

        # 清除过期/残留的锁文件
        try:
            lock_file.unlink()
        except OSError:
            pass

    # 创建锁文件
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_data = {
        "command": command,
        "chapter": chapter,
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
    }
    try:
        lock_file.write_text(json.dumps(lock_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, ""
    except OSError as e:
        return False, f"无法创建锁文件: {e}"


def release_lock(book_dir: Path) -> None:
    """释放执行锁（删除锁文件）"""
    lock_file = _lock_path(book_dir)
    try:
        if lock_file.exists():
            lock_file.unlink()
    except OSError:
        pass


def force_unlock(book_dir: Path) -> Tuple[bool, str]:
    """强制清除执行锁。

    Returns:
        (success, message)
    """
    lock_file = _lock_path(book_dir)
    if not lock_file.exists():
        return False, "当前无执行锁，无需清除。"
    try:
        lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
        cmd_info = f"{lock_data.get('command', '?')}"
        ch_info = f" chapter={lock_data.get('chapter')}" if lock_data.get("chapter") else ""
        pid_info = f" (PID={lock_data.get('pid', '?')})" if lock_data.get("pid") else ""
        started = lock_data.get("started_at", "?")
        lock_file.unlink()
        return True, f"已清除执行锁：{cmd_info}{ch_info}{pid_info}（启动于 {started}）"
    except (json.JSONDecodeError, OSError) as e:
        try:
            lock_file.unlink()
            return True, f"已清除（无法解析锁文件内容: {e}）"
        except OSError as e2:
            return False, f"无法删除锁文件: {e2}"


# =========================================================
# 幂等回滚机制 — 快照
# =========================================================

def _snapshot_dir(book_dir: Path) -> Path:
    """获取快照根目录"""
    return book_dir / FLOW_SNAPSHOT_DIR


def create_snapshot(book_dir: Path) -> Optional[str]:
    """创建追踪文件快照。

    如同一秒内已存在快照，自动追加序号后缀（_2, _3, ...）以保证唯一。

    Returns:
        快照时间戳字符串（格式: YYYYMMDD_HHMMSS 或 YYYYMMDD_HHMMSS_N），失败返回 None
    """
    tracking_dir = book_dir / "追踪"
    snapshot_root = _snapshot_dir(book_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_path = snapshot_root / f"snapshot_{timestamp}"

    # 冲突检测：同一秒内已存在快照则追加序号后缀
    if snapshot_path.exists():
        idx = 2
        while True:
            candidate = snapshot_root / f"snapshot_{timestamp}_{idx}"
            if not candidate.exists():
                timestamp = f"{timestamp}_{idx}"
                snapshot_path = candidate
                break
            idx += 1

    # 确保快照目录存在
    snapshot_path.mkdir(parents=True, exist_ok=True)

    copied = []
    for filename in SNAPSHOT_TRACKING_FILES:
        src = tracking_dir / filename
        if src.exists():
            try:
                shutil.copy2(str(src), str(snapshot_path / filename))
                copied.append(filename)
            except OSError:
                pass

    if not copied:
        # 没有任何文件被备份，删除空快照目录
        try:
            snapshot_path.rmdir()
        except OSError:
            pass
        return None

    # 清理超出数量上限的旧快照
    _cleanup_old_snapshots(snapshot_root)

    return timestamp


def _cleanup_old_snapshots(snapshot_root: Path) -> None:
    """清理超出数量上限的最旧快照"""
    if not snapshot_root.exists():
        return
    snapshots = sorted(
        [d for d in snapshot_root.iterdir()
         if d.is_dir() and d.name.startswith("snapshot_")],
        key=lambda d: d.name,
    )
    while len(snapshots) > FLOW_SNAPSHOT_MAX_KEEP:
        oldest = snapshots.pop(0)
        try:
            shutil.rmtree(str(oldest))
        except OSError:
            pass


def list_snapshots(book_dir: Path) -> List[Dict[str, Any]]:
    """列出可用快照。

    Returns:
        快照信息列表，按时间倒序排列
    """
    snapshot_root = _snapshot_dir(book_dir)
    if not snapshot_root.exists():
        return []
    snapshots = []
    for d in sorted(
        [d for d in snapshot_root.iterdir()
         if d.is_dir() and d.name.startswith("snapshot_")],
        key=lambda d: d.name,
        reverse=True,
    ):
        # 从目录名提取时间戳
        ts_str = d.name.replace("snapshot_", "")
        files = [f.name for f in d.iterdir() if f.is_file()]
        snapshots.append({
            "timestamp": ts_str,
            "path": str(d),
            "files": files,
            "file_count": len(files),
        })
    return snapshots


def restore_snapshot(book_dir: Path, timestamp: str) -> Tuple[bool, str]:
    """从指定快照恢复追踪文件。

    恢复前会先创建一个安全网快照（备份当前状态）。

    Args:
        book_dir: 书籍工程目录
        timestamp: 快照时间戳（格式: YYYYMMDD_HHMMSS）

    Returns:
        (success, message)
    """
    snapshot_root = _snapshot_dir(book_dir)
    snapshot_path = snapshot_root / f"snapshot_{timestamp}"

    if not snapshot_path.exists():
        return False, f"快照不存在: snapshot_{timestamp}"

    # 安全网：恢复前备份当前状态
    safety_ts = create_snapshot(book_dir)
    safety_info = ""
    if safety_ts:
        safety_info = f"（当前状态已安全备份为 snapshot_{safety_ts}）"

    # 恢复文件
    tracking_dir = book_dir / "追踪"
    restored = []
    missing_in_snapshot = []
    for filename in SNAPSHOT_TRACKING_FILES:
        src = snapshot_path / filename
        if src.exists():
            try:
                shutil.copy2(str(src), str(tracking_dir / filename))
                restored.append(filename)
            except OSError as e:
                return False, f"恢复 {filename} 失败: {e}"
        else:
            missing_in_snapshot.append(filename)

    msg = f"已从 snapshot_{timestamp} 恢复 {len(restored)} 个文件: {', '.join(restored)}"
    if missing_in_snapshot:
        msg += f"\n跳过（快照中不存在）: {', '.join(missing_in_snapshot)}"
    msg += safety_info

    return True, msg


# =========================================================
# 命令实现
# =========================================================

def cmd_status(book_dir: Path, args) -> Dict[str, Any]:
    """status 命令 — 诊断书籍工程状态"""
    result = {
        "book_dir": str(book_dir),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checks": {},
        "recommendations": [],
    }

    # 1. 最新章节
    latest_ch = find_latest_chapter(book_dir)
    result["latest_chapter"] = latest_ch
    result["checks"]["has_chapters"] = latest_ch > 0

    # 2. 下一章章纲
    next_ch = find_next_chapter_outline(book_dir, latest_ch)
    result["next_chapter_with_outline"] = next_ch
    result["checks"]["next_outline_ready"] = next_ch is not None

    # 3. 门禁状态
    if latest_ch > 0:
        gate_passed = check_gate_passed(book_dir, latest_ch)
        result["checks"]["latest_gate_passed"] = gate_passed
        if not gate_passed:
            result["recommendations"].append(
                f"⚠️ 第{latest_ch}章门禁未通过，需执行修复后再写下一章"
            )
    else:
        result["checks"]["latest_gate_passed"] = True

    # 4. 追踪同步
    if latest_ch > 0:
        tracking = check_tracking_sync(book_dir, latest_ch)
        result["checks"]["tracking_sync"] = tracking
        unsynced = [k for k, v in tracking.items() if not v]
        if unsynced:
            result["recommendations"].append(
                f"⚠️ 追踪文件未同步到第{latest_ch}章：{', '.join(unsynced)}"
            )

    # 5. 超期伏笔
    overdue = check_foreshadow_overdue(book_dir, latest_ch)
    result["checks"]["overdue_foreshadows"] = len(overdue)
    if overdue:
        result["recommendations"].append(
            f"⚠️ 发现 {len(overdue)} 条超期伏笔（🔴），需处理后再继续"
        )

    # 6. 运行 resume.py（如果存在）
    rc, stdout, stderr = run_script("resume.py", [str(book_dir)], book_dir)
    if rc == 0 and stdout:
        result["resume_output"] = stdout[:500]

    # 7. 大纲锚点状态
    rc, stdout, stderr = run_script("outline_anchor.py", ["status", str(book_dir)], book_dir)
    if rc == 0 and stdout:
        result["anchor_status"] = stdout[:500]

    # 8. 建议
    if latest_ch == 0:
        result["recommendations"].append("→ 书籍工程为空，建议先执行开书流程")
    elif not next_ch:
        result["recommendations"].append(f"→ 第{latest_ch+1}章章纲缺失，建议先补纲")
    elif all(result["checks"].get(k, True) for k in ["latest_gate_passed", "next_outline_ready"]):
        result["recommendations"].append(f"→ 状态良好，可执行写第{next_ch}章")

    return result


def cmd_prepare(book_dir: Path, chapter: int, args) -> Dict[str, Any]:
    """prepare 命令 — 写前准备（带执行锁保护）"""
    # 获取执行锁
    ok, err = acquire_lock(book_dir, "prepare", chapter)
    if not ok:
        return {
            "chapter": chapter,
            "steps": [],
            "all_ready": False,
            "error": err,
        }
    try:
        result = _cmd_prepare_inner(book_dir, chapter, args)
        return result
    finally:
        release_lock(book_dir)


def _cmd_prepare_inner(book_dir: Path, chapter: int, args) -> Dict[str, Any]:
    """prepare 命令核心逻辑"""
    result = {
        "chapter": chapter,
        "steps": [],
    }

    # Step 1: 大纲锚点注入
    rc, stdout, stderr = run_script(
        "outline_anchor.py",
        ["inject", str(book_dir), "--chapter", str(chapter)],
        book_dir
    )
    result["steps"].append({
        "name": "outline_anchor_inject",
        "success": rc == 0,
        "output": stdout[:300] if stdout else stderr[:300],
    })

    # Step 2: 锚点配额检查
    if hasattr(args, 'quota') and args.quota:
        rc, stdout, stderr = run_script(
            "outline_anchor.py",
            ["check", str(book_dir), "--chapter", str(chapter), "--quota", args.quota],
            book_dir
        )
        result["steps"].append({
            "name": "quota_check",
            "success": rc == 0,
            "output": stdout[:300] if stdout else stderr[:300],
        })

    # Step 3: 上下文选取
    rc, stdout, stderr = run_script(
        "context_manager.py",
        ["select", str(book_dir), "--chapter", str(chapter), "--brief"],
        book_dir
    )
    result["steps"].append({
        "name": "context_select",
        "success": rc == 0,
        "output": stdout[:500] if stdout else stderr[:300],
    })

    # Step 4: 实体检索
    rc, stdout, stderr = run_script(
        "entity_index.py",
        ["semantic", str(book_dir), "--chapter", str(chapter)],
        book_dir
    )
    result["steps"].append({
        "name": "entity_retrieval",
        "success": rc == 0,
        "output": stdout[:300] if stdout else stderr[:200],
    })

    # Step 5: 事件推荐
    rc, stdout, stderr = run_script(
        "event_matrix.py",
        ["recommend", str(book_dir), "--chapter", str(chapter)],
        book_dir
    )
    result["steps"].append({
        "name": "event_recommend",
        "success": rc == 0,
        "output": stdout[:300] if stdout else stderr[:200],
    })

    # Step 6: 知识图谱查询
    rc, stdout, stderr = run_script(
        "story_graph.py",
        ["query", str(book_dir), "--chapter", str(chapter)],
        book_dir
    )
    result["steps"].append({
        "name": "graph_query",
        "success": rc == 0,
        "output": stdout[:300] if stdout else stderr[:200],
    })

    # Step 7: 情节建议（基于记忆的下一章方向参考）
    rc, stdout, stderr = run_script(
        "plot_suggest.py",
        [str(book_dir), "--chapter", str(chapter)],
        book_dir
    )
    result["steps"].append({
        "name": "plot_suggest",
        "success": rc == 0,
        "output": stdout[:300] if stdout else stderr[:200],
    })

    result["all_ready"] = all(s["success"] for s in result["steps"])
    return result


def cmd_check(book_dir: Path, chapter: int, chapter_file: str) -> Dict[str, Any]:
    """check 命令 — 写后检查（带执行锁保护）"""
    # 获取执行锁
    ok, err = acquire_lock(book_dir, "check", chapter)
    if not ok:
        return {
            "chapter": chapter,
            "steps": [],
            "all_passed": False,
            "error": err,
        }
    try:
        result = _cmd_check_inner(book_dir, chapter, chapter_file)
        return result
    finally:
        release_lock(book_dir)


def _cmd_check_inner(book_dir: Path, chapter: int, chapter_file: str) -> Dict[str, Any]:
    """check 命令核心逻辑"""
    result = {
        "chapter": chapter,
        "steps": [],
    }

    # Step 1: 标点归一化检查
    rc, stdout, stderr = run_script(
        "normalize_punct.py",
        [chapter_file, "--check"],
        book_dir
    )
    result["steps"].append({
        "name": "punct_check",
        "success": rc == 0,
        "output": stdout[:300] if stdout else stderr[:200],
    })

    # Step 2: 机器闸口
    rc, stdout, stderr = run_script(
        "check_text.py",
        [chapter_file, "--min-chars", str(DEFAULT_MIN_CHARS), "--max-chars", str(DEFAULT_MAX_CHARS),
         "--ledger", str(book_dir / "追踪" / "伏笔台账.md"),
         "--current-chapter", str(chapter),
         "--gate-report"],
        book_dir
    )
    result["steps"].append({
        "name": "gate_check",
        "success": rc == 0,
        "output": stdout[:500] if stdout else stderr[:300],
    })

    # Step 3: 节奏配额检查
    rc, stdout, stderr = run_script(
        "rhythm_guard.py",
        ["--chapter-file", chapter_file,
         "--quota", str(book_dir / "追踪" / "节奏配额.md")],
        book_dir
    )
    result["steps"].append({
        "name": "rhythm_check",
        "success": rc == 0,
        "output": stdout[:300] if stdout else stderr[:200],
    })

    # Step 3.5: 时间线一致性检查（倒退/跳跃/承诺/引用/分支）
    rc, stdout, stderr = run_script(
        "timeline_manager.py",
        ["check", str(book_dir), "--chapter", str(chapter)],
        book_dir
    )
    result["steps"].append({
        "name": "timeline_check",
        "success": rc in (0, 1),  # 1 = 检出 WARN/ERROR（作为提示，不阻断本章）
        "output": stdout[:300] if stdout else stderr[:200],
    })

    # Step 4: 内容扩充建议
    rc, stdout, stderr = run_script(
        "content_expander.py",
        ["analyze", chapter_file, "--target", "3000"],
        book_dir
    )
    result["steps"].append({
        "name": "content_expander",
        "success": rc == 0,
        "output": stdout[:300] if stdout else stderr[:200],
    })

    result["all_passed"] = result["steps"][1]["success"]  # gate_check 是关键
    return result


def cmd_track(book_dir: Path, chapter: int) -> Dict[str, Any]:
    """track 命令 — 追踪更新"""
    result = {
        "chapter": chapter,
        "steps": [],
    }

    # Step 1: 追踪格式校验
    rc, stdout, stderr = run_script(
        "validate_tracking.py",
        [str(book_dir)],
        book_dir
    )
    result["steps"].append({
        "name": "tracking_validate",
        "success": rc == 0,
        "output": stdout[:300] if stdout else stderr[:200],
    })

    # Step 2: 实体索引更新
    rc, stdout, stderr = run_script(
        "entity_index.py",
        ["build", str(book_dir)],
        book_dir
    )
    result["steps"].append({
        "name": "entity_index_build",
        "success": rc == 0,
        "output": stdout[:200] if stdout else stderr[:200],
    })

    # Step 2.5: RAG 索引重建（rich 索引：摘要/实体/情绪，供语义检索）
    rc, stdout, stderr = run_script(
        "rag_retriever.py",
        ["build", str(book_dir)],
        book_dir
    )
    result["steps"].append({
        "name": "rag_index_build",
        "success": rc == 0,
        "output": stdout[:200] if stdout else stderr[:200],
    })

    # Step 3: 大纲锚点推进
    rc, stdout, stderr = run_script(
        "outline_anchor.py",
        ["advance", str(book_dir), "--chapter", str(chapter)],
        book_dir
    )
    result["steps"].append({
        "name": "anchor_advance",
        "success": rc == 0,
        "output": stdout[:200] if stdout else stderr[:200],
    })

    # Step 4: 事件矩阵记录
    rc, stdout, stderr = run_script(
        "event_matrix.py",
        ["record", str(book_dir), "--chapter", str(chapter)],
        book_dir
    )
    result["steps"].append({
        "name": "event_record",
        "success": rc == 0,
        "output": stdout[:200] if stdout else stderr[:200],
    })

    # Step 5: 知识图谱更新（每5章）
    if chapter % 5 == 0:
        rc, stdout, stderr = run_script(
            "story_graph.py",
            ["build", str(book_dir)],
            book_dir
        )
        result["steps"].append({
            "name": "graph_build",
            "success": rc == 0,
            "output": stdout[:200] if stdout else stderr[:200],
        })

    result["all_done"] = all(s["success"] for s in result["steps"])
    return result


def cmd_report(book_dir: Path) -> str:
    """report 命令 — 进度报告"""
    lines = []
    lines.append("# 书籍工程进度报告")
    lines.append(f"\n生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"工程目录：{book_dir.name}")

    # 状态诊断
    status = cmd_status(book_dir, None)
    lines.append(f"\n## 基本状态")
    lines.append(f"- 最新章节：第{status['latest_chapter']}章")
    lines.append(f"- 下一章纲：第{status.get('next_chapter_with_outline', '?')}章")
    lines.append(f"- 门禁状态：{'✅ 通过' if status['checks'].get('latest_gate_passed') else '❌ 未通过'}")
    lines.append(f"- 超期伏笔：{status['checks'].get('overdue_foreshadows', 0)} 条")

    # 追踪同步
    tracking = status["checks"].get("tracking_sync", {})
    if tracking:
        lines.append(f"\n## 追踪文件同步")
        for name, synced in tracking.items():
            lines.append(f"- {name}：{'✅' if synced else '❌'}")

    # 建议
    if status["recommendations"]:
        lines.append(f"\n## 下一步建议")
        for rec in status["recommendations"]:
            lines.append(rec)

    # 正文章节列表
    text_dir = book_dir / "正文"
    if text_dir.exists():
        chapters = sorted(text_dir.glob("第*章*.md"))
        lines.append(f"\n## 已写章节（共{len(chapters)}章）")
        if chapters:
            # 只显示最近5章
            recent = chapters[-5:]
            for f in recent:
                lines.append(f"- {f.stem}")

    # 门禁历史
    gate_dir = book_dir / "追踪" / "门禁"
    if gate_dir.exists():
        gates = sorted(gate_dir.glob("gate_ch*.json"))
        passed = 0
        failed = 0
        for g in gates:
            try:
                data = json.loads(read_file_safe(g))
                if data.get("passed"):
                    passed += 1
                else:
                    failed += 1
            except:
                pass
        lines.append(f"\n## 门禁历史")
        lines.append(f"- 通过：{passed} 章")
        lines.append(f"- 未通过：{failed} 章")

    return "\n".join(lines)


def cmd_daily(book_dir: Path, num_chapters: int) -> Dict[str, Any]:
    """daily 命令 — 日更批量模式（带执行锁 + 快照保护）"""
    result = {
        "target_chapters": num_chapters,
        "completed": 0,
        "failed": 0,
        "chapters": [],
    }

    # 获取执行锁
    ok, err = acquire_lock(book_dir, "daily", find_latest_chapter(book_dir) + 1)
    if not ok:
        result["error"] = err
        return result

    # 创建快照（安全网）
    snapshot_ts = create_snapshot(book_dir)
    result["snapshot"] = snapshot_ts

    try:
        latest_ch = find_latest_chapter(book_dir)

        for i in range(num_chapters):
            target_ch = latest_ch + 1 + i
            ch_result = {"chapter": target_ch, "status": "pending"}

            # 1. 准备
            prep = _cmd_prepare_inner(book_dir, target_ch, None)
            if not prep.get("all_ready"):
                ch_result["status"] = "prepare_failed"
                ch_result["error"] = "写前准备失败"
                result["failed"] += 1
                result["chapters"].append(ch_result)
                break

            # 2. 写作（由 Agent 执行，这里只输出指引）
            ch_result["status"] = "ready_for_writing"
            ch_result["prepare_steps"] = len(prep["steps"])

            # 3. 检查（需要章节文件已生成）
            chapter_file = book_dir / "正文" / f"第{target_ch:03d}章_待写.md"
            if not chapter_file.exists():
                chapter_file = book_dir / "正文" / f"第{target_ch}章_待写.md"

            if chapter_file.exists():
                check_result = _cmd_check_inner(book_dir, target_ch, str(chapter_file))
                ch_result["check_passed"] = check_result.get("all_passed", False)

                if check_result.get("all_passed"):
                    # 4. 追踪更新
                    track_result = cmd_track(book_dir, target_ch)
                    ch_result["track_done"] = track_result.get("all_done", False)
                    ch_result["status"] = "completed"
                    result["completed"] += 1
                else:
                    ch_result["status"] = "check_failed"
                    result["failed"] += 1
                    break  # fail-fast：检查不过不继续下一章
            else:
                ch_result["status"] = "waiting_for_agent"
                ch_result["message"] = f"等待 Agent 写第{target_ch}章正文"

            result["chapters"].append(ch_result)

            # 如果还在等 Agent，不继续
            if ch_result["status"] in ["waiting_for_agent", "check_failed", "prepare_failed"]:
                break

        return result
    finally:
        release_lock(book_dir)


# =========================================================
# CLI
# =========================================================

def cmd_write(book_dir: Path, chapter: int, args) -> Dict[str, Any]:
    """write 命令 — 单章写作流程编排（prepare → [Agent写] → check → track）。

    机械部分（准备/检查/追踪）在一个锁内进程内串联，正文写作仍由 Agent 执行——
    编排器只做确定性闸口，不冒充写正文。
    """
    result = {"chapter": chapter, "status": "pending"}

    ok, err = acquire_lock(book_dir, "write", chapter)
    if not ok:
        result["error"] = err
        return result

    try:
        # 1. 写前准备
        prep = _cmd_prepare_inner(book_dir, chapter, args)
        result["prepare_ready"] = prep.get("all_ready", False)
        result["prepare_steps"] = len(prep.get("steps", []))
        if not prep.get("all_ready"):
            result["status"] = "prepare_failed"
            result["error"] = "写前准备失败"
            return result

        # 2. 写作（由 Agent 执行，此处仅定位正文文件）
        chapter_file = _find_chapter_file(book_dir, chapter)
        if chapter_file is None:
            result["status"] = "waiting_for_agent"
            result["message"] = f"等待 Agent 写第{chapter}章正文"
            return result

        # 3. 写后检查
        check = _cmd_check_inner(book_dir, chapter, str(chapter_file))
        result["check_passed"] = check.get("all_passed", False)
        if not check.get("all_passed"):
            result["status"] = "check_failed"
            return result

        # 4. 追踪更新
        track = cmd_track(book_dir, chapter)
        result["track_done"] = track.get("all_done", False)
        result["status"] = "completed"
        return result
    finally:
        release_lock(book_dir)


def main():
    # Windows 中文控制台默认 GBK 输出，在 Git Bash 等 UTF-8 终端下会乱码；统一按 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(
        description="统一流程执行器 — 编排写作工作流（v1.1 幂等回滚）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    # status
    p_status = sub.add_parser("status", help="诊断书籍工程状态")
    p_status.add_argument("book_dir", help="书籍工程目录")
    p_status.add_argument("--json", action="store_true")

    # prepare
    p_prepare = sub.add_parser("prepare", help="写前准备")
    p_prepare.add_argument("book_dir", help="书籍工程目录")
    p_prepare.add_argument("--chapter", type=int, required=True)
    p_prepare.add_argument("--quota", choices=["A", "B", "C"], help="A/B/C配额预声明")
    p_prepare.add_argument("--json", action="store_true")

    # check
    p_check = sub.add_parser("check", help="写后检查")
    p_check.add_argument("book_dir", help="书籍工程目录")
    p_check.add_argument("--chapter", type=int, required=True)
    p_check.add_argument("--file", required=True, help="章节文件路径")
    p_check.add_argument("--json", action="store_true")

    # track
    p_track = sub.add_parser("track", help="追踪更新")
    p_track.add_argument("book_dir", help="书籍工程目录")
    p_track.add_argument("--chapter", type=int, required=True)
    p_track.add_argument("--json", action="store_true")

    # daily
    p_daily = sub.add_parser("daily", help="日更批量模式")
    p_daily.add_argument("book_dir", help="书籍工程目录")
    p_daily.add_argument("--chapters", type=int, default=3, help="目标章数")
    p_daily.add_argument("--json", action="store_true")

    # write
    p_write = sub.add_parser("write", help="单章写作流程编排（prepare→check→track）")
    p_write.add_argument("book_dir", help="书籍工程目录")
    p_write.add_argument("--chapter", type=int, required=True)
    p_write.add_argument("--quota", choices=["A", "B", "C"], help="A/B/C配额预声明")
    p_write.add_argument("--json", action="store_true")

    # report
    p_report = sub.add_parser("report", help="进度报告")
    p_report.add_argument("book_dir", help="书籍工程目录")
    p_report.add_argument("--output", help="输出文件路径")

    # revise
    p_revise = sub.add_parser("revise", help="改纲级联")
    p_revise.add_argument("book_dir", help="书籍工程目录")
    p_revise.add_argument("--from-chapter", type=int, required=True)
    p_revise.add_argument("--description", default="")
    p_revise.add_argument("--json", action="store_true")

    # rollback
    p_rollback = sub.add_parser("rollback", help="从指定快照恢复追踪文件")
    p_rollback.add_argument("book_dir", help="书籍工程目录")
    p_rollback.add_argument("--snapshot", required=True,
                             help="快照时间戳（格式: YYYYMMDD_HHMMSS）")

    # unlock
    p_unlock = sub.add_parser("unlock", help="强制清除执行锁")
    p_unlock.add_argument("book_dir", help="书籍工程目录")

    # snapshots
    p_snapshots = sub.add_parser("snapshots", help="列出可用快照")
    p_snapshots.add_argument("book_dir", help="书籍工程目录")

    args = parser.parse_args()

    if args.command == "status":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            print(f"错误：未找到书籍工程", file=sys.stderr)
            sys.exit(1)
        result = cmd_status(book_dir, args)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"=== 书籍工程状态 ===")
            print(f"最新章节：第{result['latest_chapter']}章")
            print(f"下一章纲：第{result.get('next_chapter_with_outline', '?')}章")
            print(f"门禁状态：{'✅' if result['checks'].get('latest_gate_passed') else '❌'}")
            print(f"超期伏笔：{result['checks'].get('overdue_foreshadows', 0)} 条")
            for rec in result["recommendations"]:
                print(rec)

    elif args.command == "prepare":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            print(f"错误：未找到书籍工程", file=sys.stderr)
            sys.exit(1)
        result = cmd_prepare(book_dir, args.chapter, args)
        if result.get("error"):
            print(f"错误：{result['error']}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"=== 写前准备 — 第{args.chapter}章 ===")
            for step in result["steps"]:
                status = "✅" if step["success"] else "❌"
                print(f"{status} {step['name']}")
                if step.get("output"):
                    print(f"   {step['output'][:200]}")
            print(f"\n{'✅ 准备就绪' if result['all_ready'] else '❌ 准备失败'}")

    elif args.command == "check":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            sys.exit(1)
        result = cmd_check(book_dir, args.chapter, args.file)
        if result.get("error"):
            print(f"错误：{result['error']}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for step in result["steps"]:
                status = "✅" if step["success"] else "❌"
                print(f"{status} {step['name']}")

    elif args.command == "track":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            sys.exit(1)
        result = cmd_track(book_dir, args.chapter)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for step in result["steps"]:
                status = "✅" if step["success"] else "❌"
                print(f"{status} {step['name']}")

    elif args.command == "write":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            print(f"错误：未找到书籍工程", file=sys.stderr)
            sys.exit(1)
        result = cmd_write(book_dir, args.chapter, args)
        if result.get("error"):
            print(f"错误：{result['error']}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"=== 单章写作 — 第{args.chapter}章 ===")
            print(f"准备：{'✅' if result.get('prepare_ready') else '❌'}")
            if result["status"] == "check_failed":
                print(f"检查：❌")
            elif result.get("check_passed"):
                print(f"检查：✅")
            else:
                print(f"检查：—")
            if result.get("track_done"):
                print(f"追踪：✅")
            print(f"状态：{result['status']}")
            if result.get("message"):
                print(result["message"])

    elif args.command == "daily":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            sys.exit(1)
        result = cmd_daily(book_dir, args.chapters)
        if result.get("error"):
            print(f"错误：{result['error']}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"=== 日更模式 — 目标 {args.chapters} 章 ===")
            if result.get("snapshot"):
                print(f"快照备份：snapshot_{result['snapshot']}")
            print(f"完成：{result['completed']} | 失败：{result['failed']}")
            for ch in result["chapters"]:
                print(f"  第{ch['chapter']}章：{ch['status']}")

    elif args.command == "report":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            sys.exit(1)
        report = cmd_report(book_dir)
        if args.output:
            Path(args.output).write_text(report, encoding="utf-8")
            print(f"报告已写入 {args.output}")
        else:
            print(report)

    elif args.command == "revise":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            sys.exit(1)
        # 改纲级联：锚点重算
        rc, stdout, stderr = run_script(
            "outline_anchor.py",
            ["init", str(book_dir), "--from-chapter", str(args.from_chapter)],
            book_dir
        )
        print(f"锚点重算：{'✅' if rc == 0 else '❌'}")
        if stdout:
            print(stdout[:300])
        # 图谱级联标记
        rc2, stdout2, stderr2 = run_script(
            "story_graph.py",
            ["cascade", str(book_dir), "--from-chapter", str(args.from_chapter)],
            book_dir
        )
        print(f"图谱级联：{'✅' if rc2 == 0 else '❌'}")
        if stdout2:
            print(stdout2[:300])
        # 实体索引重建
        rc3, stdout3, stderr3 = run_script(
            "entity_index.py",
            ["build", str(book_dir)],
            book_dir
        )
        print(f"索引重建：{'✅' if rc3 == 0 else '❌'}")

    elif args.command == "rollback":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            print(f"错误：未找到书籍工程", file=sys.stderr)
            sys.exit(1)
        ok, msg = restore_snapshot(book_dir, args.snapshot)
        if ok:
            print(f"回滚成功：{msg}")
        else:
            print(f"回滚失败：{msg}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "unlock":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            print(f"错误：未找到书籍工程", file=sys.stderr)
            sys.exit(1)
        ok, msg = force_unlock(book_dir)
        print(msg)

    elif args.command == "snapshots":
        book_dir = find_book_dir(args.book_dir)
        if not book_dir:
            print(f"错误：未找到书籍工程", file=sys.stderr)
            sys.exit(1)
        snapshots = list_snapshots(book_dir)
        if not snapshots:
            print("当前无可用快照。")
        else:
            print(f"可用快照（共 {len(snapshots)} 个，保留上限 {FLOW_SNAPSHOT_MAX_KEEP}）:")
            for snap in snapshots:
                print(f"  snapshot_{snap['timestamp']}  —  {snap['file_count']} 个文件: {', '.join(snap['files'])}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
