#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""logger.py — 结构化日志系统（纯标准库，企业级）。

设计原则：
1. 零第三方依赖，纯标准库实现
2. 结构化JSON输出，便于后续分析和Dashboard消费
3. 日志分级：DEBUG/INFO/WARN/ERROR/FATAL
4. 控制台+文件双通道输出
5. 日志写入失败不得影响主流程
6. Windows ANSI 颜色兼容（复用common.colorize）

用法：
    from logger import get_logger
    log = get_logger("check_text", book_dir="我的小说")
    log.info("开始检查章节", chapter=37, chars=4500)
    log.warn("检测到AI腔", pattern="不是A而是B", line=197)
    log.error("文件读取失败", exc=e, path="第037章.md")
"""

import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# =============================================================================
# 日志级别
# =============================================================================

LEVEL_DEBUG = 10
LEVEL_INFO = 20
LEVEL_WARN = 30
LEVEL_ERROR = 40
LEVEL_FATAL = 50

LEVEL_NAMES = {
    LEVEL_DEBUG: "DEBUG",
    LEVEL_INFO: "INFO",
    LEVEL_WARN: "WARN",
    LEVEL_ERROR: "ERROR",
    LEVEL_FATAL: "FATAL",
}

# 从环境变量读取日志级别（可选）
_ENV_LEVEL = os.environ.get("LNS_LOG_LEVEL", "INFO").upper()
DEFAULT_CONSOLE_LEVEL = {
    "DEBUG": LEVEL_DEBUG,
    "INFO": LEVEL_INFO,
    "WARN": LEVEL_WARN,
    "ERROR": LEVEL_ERROR,
}.get(_ENV_LEVEL, LEVEL_INFO)
DEFAULT_FILE_LEVEL = LEVEL_DEBUG


class StructuredLogger:
    """结构化日志器。

    每条日志都是一个JSON对象，包含：
    - ts: ISO时间戳
    - level: 日志级别
    - session: 会话ID
    - msg: 日志消息
    - 其他自定义字段
    """

    def __init__(
        self,
        name: str = "lns",
        book_dir: Optional[str] = None,
        console_level: int = DEFAULT_CONSOLE_LEVEL,
        file_level: int = DEFAULT_FILE_LEVEL,
    ):
        self.name = name
        self.console_level = console_level
        self.file_level = file_level
        self.log_file: Optional[Path] = None
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 文件输出：写入 {book_dir}/追踪/logs/{name}_{session}.log
        if book_dir:
            log_dir = Path(book_dir) / "追踪" / "logs"
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                self.log_file = log_dir / f"{name}_{self._session_id}.log"
            except OSError:
                pass  # 目录创建失败就只输出到控制台

    # ------------------------------------------------------------------
    # 核心日志方法
    # ------------------------------------------------------------------

    def _log(self, level: int, message: str, **kwargs: Any) -> None:
        entry: Dict[str, Any] = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "level": LEVEL_NAMES.get(level, "UNKNOWN"),
            "session": self._session_id,
            "logger": self.name,
            "msg": message,
        }
        if kwargs:
            entry.update(kwargs)

        # 控制台输出（带颜色）
        if level >= self.console_level and sys.stdout.isatty():
            self._print_console(entry)

        # 文件输出（JSON Lines格式）
        if self.log_file and level >= self.file_level:
            self._write_file(entry)

    def _print_console(self, entry: Dict[str, Any]) -> None:
        """控制台彩色输出（复用common.colorize，避免重复代码）。"""
        try:
            from common import colorize
        except ImportError:
            colorize = None  # type: ignore

        level = entry["level"]
        if colorize:
            if level in ("ERROR", "FATAL"):
                prefix = colorize(f"[{level}]", "red")
            elif level == "WARN":
                prefix = colorize(f"[{level}]", "yellow")
            elif level == "DEBUG":
                prefix = colorize(f"[{level}]", "dim")
            else:
                prefix = colorize(f"[{level}]", "cyan")
        else:
            prefix = f"[{level}]"

        extra = ""
        for k, v in entry.items():
            if k not in ("ts", "level", "session", "logger", "msg"):
                extra += f" {k}={v}"
        print(f"{prefix} {entry['msg']}{extra}")

    def _write_file(self, entry: Dict[str, Any]) -> None:
        """写入日志文件（JSON Lines，每行一条）。"""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 日志写入失败绝不能影响主流程

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    def debug(self, msg: str, **kw: Any) -> None:
        self._log(LEVEL_DEBUG, msg, **kw)

    def info(self, msg: str, **kw: Any) -> None:
        self._log(LEVEL_INFO, msg, **kw)

    def warn(self, msg: str, **kw: Any) -> None:
        self._log(LEVEL_WARN, msg, **kw)

    def warning(self, msg: str, **kw: Any) -> None:
        self.warn(msg, **kw)

    def error(self, msg: str, exc: Optional[Exception] = None, **kw: Any) -> None:
        if exc is not None:
            kw["exception"] = traceback.format_exc()
            kw["exc_type"] = type(exc).__name__
            kw["exc_msg"] = str(exc)
        self._log(LEVEL_ERROR, msg, **kw)

    def fatal(self, msg: str, exc: Optional[Exception] = None, **kw: Any) -> None:
        if exc is not None:
            kw["exception"] = traceback.format_exc()
        self._log(LEVEL_FATAL, msg, **kw)

    # ------------------------------------------------------------------
    # 计时上下文管理器
    # ------------------------------------------------------------------

    def timer(self, name: str, **kw: Any) -> "_TimerContext":
        """用于测量代码块执行时间的上下文管理器。

        用法：
            with log.timer("7 Gate检查", chapter=37):
                run_checks()
            # 自动输出：[INFO] 7 Gate检查 耗时 0.234s chapter=37
        """
        return _TimerContext(self, name, kw)


class _TimerContext:
    """计时器上下文管理器。"""

    def __init__(self, logger: StructuredLogger, name: str, extra: Dict[str, Any]):
        self.logger = logger
        self.name = name
        self.extra = extra
        self.start = 0.0

    def __enter__(self) -> "_TimerContext":
        self.start = time.time()
        return self

    def __exit__(self, *args) -> None:
        elapsed = time.time() - self.start
        self.logger.info(f"{self.name}", duration=f"{elapsed:.3f}s", **self.extra)


# =============================================================================
# 全局logger缓存（延迟初始化）
# =============================================================================

_logger_cache: Dict[str, StructuredLogger] = {}


def get_logger(name: str = "lns", book_dir: Optional[str] = None) -> StructuredLogger:
    """获取全局logger实例（同一name+book_dir共享一个实例）。

    延迟初始化：第一次调用时才创建，避免不必要的文件IO。
    """
    key = f"{name}:{book_dir or 'noglobal'}"
    if key not in _logger_cache:
        _logger_cache[key] = StructuredLogger(name=name, book_dir=book_dir)
    return _logger_cache[key]


# =============================================================================
# 模块元信息
# =============================================================================

__version__ = "1.0.0"
__all__ = [
    "StructuredLogger",
    "get_logger",
    "LEVEL_DEBUG", "LEVEL_INFO", "LEVEL_WARN", "LEVEL_ERROR", "LEVEL_FATAL",
]
