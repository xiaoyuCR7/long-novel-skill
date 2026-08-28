#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dashboard.py — 本地Web工作台MVP（纯标准库，零依赖）。

设计原则：
  1. 零第三方依赖，纯标准库 http.server
  2. 单页HTML应用，无构建步骤
  3. 编辑采用乐观版本、原子替换与可恢复删除
  4. 默认只监听 127.0.0.1

功能：
  1. 状态总览：最新章节、总字数、日更速度、门禁状态
  2. 章节列表：所有章节的字数、门禁通过状态、AI味分数
  3. 质量趋势：AI味分数趋势图、门禁通过率趋势图
  4. 伏笔台账：四态可视化表格
  5. 文件浏览：四目录树形视图 + Markdown预览

用法：
  python scripts/dashboard.py "书籍工程目录" --port 8765
  python novel-cli.py dashboard "书籍工程目录" --port 8765

  然后浏览器打开 http://localhost:8765
"""

import argparse
import hashlib
import http.server
import ipaddress
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# 让脚本能导入同目录的模块
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import common

DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"
MAX_REQUEST_BYTES = 2 * 1024 * 1024
EDITABLE_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini"}


class EditableFileError(ValueError):
    """文件路径、类型或内容不满足 Dashboard 编辑契约。"""

    def __init__(self, message: str, *, unsupported: bool = False, invalid_input: bool = False):
        super().__init__(message)
        self.unsupported = unsupported
        self.invalid_input = invalid_input


class FileConflictError(RuntimeError):
    """文件内容已在当前编辑会话之外变化。"""


class _HttpInputError(ValueError):
    """带安全 HTTP 状态的客户端输入错误。"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def resolve_editable_path(book_dir: Path, rel_path: str) -> Path:
    """把相对编辑路径约束在书籍目录内，并拒绝符号链接。"""
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise EditableFileError("路径非法")
    _utf8_bytes(rel_path, "path")
    if "\0" in rel_path:
        raise EditableFileError("path 不能包含空字符", invalid_input=True)
    relative = Path(rel_path)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise EditableFileError("路径非法")

    root = Path(book_dir).resolve()
    candidate = root.joinpath(relative)
    cursor = root
    for part in relative.parts:
        if part in ("", "."):
            continue
        cursor = cursor / part
        if cursor.is_symlink():
            raise EditableFileError("不允许编辑符号链接")

    target = candidate.resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise EditableFileError("路径非法") from exc
    if target.exists() and not target.is_file():
        raise EditableFileError("路径不是文件")
    if target.suffix.lower() not in EDITABLE_EXTENSIONS:
        raise EditableFileError("不支持的文件类型", unsupported=True)
    return target


def revision_for(data: bytes) -> str:
    """返回用于乐观并发控制的内容摘要。"""
    return hashlib.sha256(data).hexdigest()


def _utf8_bytes(value: str, field: str) -> bytes:
    """在接触文件系统之前拒绝 JSON 转义出的孤立代理字符。"""
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EditableFileError(field + " 必须是有效的 UTF-8 文本", invalid_input=True) from exc


def _is_loopback_host(host: str) -> bool:
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip().strip("[]")).is_loopback
    except ValueError:
        return False


def file_snapshot(book_dir: Path, rel_path: str) -> Dict[str, Any]:
    """读取可编辑文件，并返回权威内容及修订令牌。"""
    root = Path(book_dir).resolve()
    target = resolve_editable_path(root, rel_path)
    if not target.exists():
        raise EditableFileError("文件不存在")
    try:
        raw = target.read_bytes()
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EditableFileError("文件不是有效的 UTF-8 文本") from exc
    stat = target.stat()
    return {
        "ok": True,
        "path": target.relative_to(root).as_posix(),
        "content": content,
        "chars": len(content),
        "extension": target.suffix.lower(),
        "revision": revision_for(raw),
        "mtime_ns": stat.st_mtime_ns,
    }


def _atomic_write_bytes(
    target: Path, data: bytes, expected_current_revision: Optional[str] = None
) -> None:
    """在目标同目录落盘并原子替换，异常时清理临时文件。"""
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_current_revision is not None:
            latest = target.read_bytes() if target.exists() else b""
            if revision_for(latest) != expected_current_revision:
                raise FileConflictError("文件已被外部修改")
        os.replace(temp_name, str(target))
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_save(
    book_dir: Path,
    rel_path: str,
    content: str,
    expected_revision: str,
) -> Dict[str, Any]:
    """仅在 revision 匹配时，以同目录原子替换保存 UTF-8 文本。"""
    if not isinstance(content, str):
        raise EditableFileError("content 必须是字符串")
    encoded_content = _utf8_bytes(content, "content")
    root = Path(book_dir).resolve()
    target = resolve_editable_path(root, rel_path)
    current = target.read_bytes() if target.exists() else b""
    if revision_for(current) != expected_revision:
        raise FileConflictError("文件已被外部修改")

    target.parent.mkdir(parents=True, exist_ok=True)
    backup: Optional[Path] = None
    if target.exists():
        backup = target.with_name(f".{target.name}.dashboard-backup")
        _atomic_write_bytes(backup, current)
        try:
            shutil.copystat(str(target), str(backup), follow_symlinks=False)
        except OSError:
            pass

    _atomic_write_bytes(target, encoded_content, expected_revision)
    result = file_snapshot(root, rel_path)
    result["backup"] = str(backup) if backup is not None else None
    return result


def _trash_directory(root: Path) -> Path:
    """返回受根目录约束的回收目录，并拒绝已有符号链接组件。"""
    cursor = root
    for part in ("追踪", ".dashboard-trash"):
        cursor = cursor / part
        if cursor.is_symlink():
            raise EditableFileError("不允许使用符号链接回收目录")
        if cursor.exists() and not cursor.is_dir():
            raise EditableFileError("回收路径不是目录")
    trash = (root / "追踪" / ".dashboard-trash").resolve(strict=False)
    try:
        trash.relative_to(root)
    except ValueError as exc:
        raise EditableFileError("回收路径非法") from exc
    trash.mkdir(parents=True, exist_ok=True)
    return trash


def recoverable_delete(
    book_dir: Path, rel_path: str, expected_revision: str
) -> Dict[str, Any]:
    """校验 revision 后把文件移动到书籍工程内的回收目录。"""
    root = Path(book_dir).resolve()
    target = resolve_editable_path(root, rel_path)
    if not target.exists():
        raise EditableFileError("文件不存在")
    current = target.read_bytes()
    if revision_for(current) != expected_revision:
        raise FileConflictError("文件已被外部修改")

    trash_dir = _trash_directory(root)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    while True:
        suffix = uuid.uuid4().hex[:8]
        trash = trash_dir / f"{timestamp}-{suffix}-{target.name}"
        if not trash.exists() and not trash.is_symlink():
            break
    latest = target.read_bytes() if target.exists() else b""
    if revision_for(latest) != expected_revision:
        raise FileConflictError("文件已被外部修改")
    os.replace(str(target), str(trash))
    return {
        "ok": True,
        "path": target.relative_to(root).as_posix(),
        "trash_path": str(trash),
        "revision": revision_for(current),
    }


# =============================================================================
# 数据收集函数（所有函数都是只读的，不修改书籍工程）
# =============================================================================

def _collect_status(book_dir: Path) -> Dict[str, Any]:
    """收集书籍工程总览状态。"""
    last_chapter = common.find_latest_chapter(book_dir) or 0

    # 统计总字数
    total_chars = 0
    chapter_count = 0
    prose_dir = book_dir / "正文"
    if prose_dir.exists():
        for f in sorted(prose_dir.glob("*.md")):
            text = common.read_text(f) or ""
            total_chars += common.count_chars(text)
            chapter_count += 1

    # 门禁状态（最新章节）
    gate_passed = None
    last_gate_ch = None
    gate_dir = book_dir / "追踪" / "门禁"
    if gate_dir.exists() and last_chapter > 0:
        # 找最新的门禁结果
        for ch in range(last_chapter, 0, -1):
            gate_path = gate_dir / f"gate_ch{ch}.json"
            if gate_path.exists():
                data = common.read_json(gate_path) or {}
                gate_passed = data.get("passed")
                last_gate_ch = ch
                break

    # 日更速度（简单估算：总字数 / 章节数）
    daily_avg = round(total_chars / max(chapter_count, 1), 0) if chapter_count > 0 else 0

    return {
        "book_name": book_dir.name,
        "last_chapter": last_chapter,
        "chapter_count": chapter_count,
        "total_chars": total_chars,
        "daily_avg": int(daily_avg),
        "gate_passed": gate_passed,
        "last_gate_chapter": last_gate_ch,
    }


def _collect_chapters(book_dir: Path) -> List[Dict[str, Any]]:
    """收集所有章节的元数据。"""
    chapters: List[Dict[str, Any]] = []
    prose_dir = book_dir / "正文"
    gate_dir = book_dir / "追踪" / "门禁"

    if not prose_dir.exists():
        return chapters

    for f in sorted(prose_dir.glob("*.md")):
        ch_no = common.parse_chapter_number(f.name)
        if ch_no is None:
            continue
        text = common.read_text(f) or ""
        chars = common.count_chars(text)

        # 门禁结果
        gate_passed = None
        ai_score = None
        gate_path = gate_dir / f"gate_ch{ch_no}.json" if gate_dir.exists() else None
        if gate_path and gate_path.exists():
            data = common.read_json(gate_path) or {}
            gate_passed = data.get("passed")
            ai_score = data.get("ai_score")

        chapters.append({
            "chapter": ch_no,
            "title": f.stem,
            "file": str(f.name),
            "chars": chars,
            "gate_passed": gate_passed,
            "ai_score": ai_score,
        })

    return chapters


def _collect_quality_trend(chapters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """收集质量趋势数据（给前端画图用）。"""
    # 只取最近20章，避免数据点过多
    recent = chapters[-20:] if len(chapters) > 20 else chapters
    return {
        "labels": [f"第{c['chapter']}章" for c in recent],
        "ai_scores": [c.get("ai_score") for c in recent],
        "gate_pass": [1 if c.get("gate_passed") else (0 if c.get("gate_passed") is False else None) for c in recent],
        "chars": [c["chars"] for c in recent],
    }


def _collect_foreshadowing(book_dir: Path) -> List[Dict[str, Any]]:
    """收集伏笔台账数据。"""
    ledger_path = book_dir / "追踪" / "伏笔台账.md"
    if not ledger_path.exists():
        return []

    text = common.read_text(ledger_path) or ""
    entries = common.parse_foreshadow_ledger(text)
    result = []
    for e in entries:
        result.append({
            "id": e.get("id", ""),
            "content": e.get("content", ""),
            "state": e.get("state", "未知"),  # 埋设/激活/回收/废弃
            "planted_ch": e.get("planted_chapter"),
            "recycled_ch": e.get("recycled_chapter"),
            "overdue": e.get("overdue", False),
        })
    return result


def _collect_file_tree(book_dir: Path) -> Dict[str, Any]:
    """收集四目录树形结构。"""
    dirs = ["大纲", "设定", "正文", "追踪"]

    def _scan_dir(d: Path, depth: int = 0, max_depth: int = 3) -> List[Dict[str, Any]]:
        if depth >= max_depth or not d.exists():
            return []
        items = []
        try:
            for child in sorted(d.iterdir()):
                item = {
                    "name": child.name,
                    "path": str(child.relative_to(book_dir)),
                    "type": "dir" if child.is_dir() else "file",
                }
                if child.is_dir():
                    item["children"] = _scan_dir(child, depth + 1, max_depth)
                items.append(item)
        except OSError:
            pass
        return items

    tree = []
    for dir_name in dirs:
        d = book_dir / dir_name
        if d.exists():
            tree.append({
                "name": dir_name,
                "path": dir_name,
                "type": "dir",
                "children": _scan_dir(d, 1, 3),
            })
    return {"root": str(book_dir), "dirs": tree}


# =============================================================================
# HTTP 服务器
# =============================================================================

class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """HTTP请求处理器。"""

    book_dir: Optional[Path] = None  # 类变量，由main设置
    bind_host: Optional[str] = None

    # ------------------------------------------------------------------
    # 请求路由
    # ------------------------------------------------------------------

    def do_GET(self):
        if not self._authorize_request():
            return
        parsed = urllib.parse.urlparse(self.path)

        # 静态资源（只有index.html）
        if parsed.path in ("/", "/index.html", ""):
            self._serve_html()
            return

        # API 路由
        if parsed.path.startswith("/api/"):
            self._serve_api(parsed.path, parsed.query)
            return

        # 其他路径404
        self.send_error(404, "Not Found")

    def do_POST(self):
        self._serve_mutation("POST")

    def do_DELETE(self):
        self._serve_mutation("DELETE")

    @staticmethod
    def _authority(value: str):
        """严格解析 HTTP authority，不接受用户信息、路径、空白或非法端口。"""
        if not value or re.search(r"[\s/@?#,\\]", value):
            raise ValueError("invalid authority")
        parsed = urllib.parse.urlsplit("http://" + value)
        host, port = parsed.hostname, parsed.port
        if not host or not re.fullmatch(r"[A-Za-z0-9.:-]+", host):
            raise ValueError("invalid host")
        if value.endswith(":"):
            raise ValueError("empty port")
        return host.lower(), 80 if port is None else port

    def _session_token(self) -> str:
        # HTTPServer serializes requests; the token belongs to the server, not a handler class.
        if not hasattr(self.server, "dashboard_token"):
            self.server.dashboard_token = secrets.token_urlsafe(32)
        return self.server.dashboard_token

    def _authorize_request(self, mutation: bool = False) -> bool:
        """拦截不受信 Host、跨源访问及无会话令牌的写请求。"""
        try:
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1:
                raise ValueError("Host required")
            host, port = self._authority(hosts[0])
            bound = self.bind_host or self.server.server_address[0]
            if _is_loopback_host(bound):
                allowed = {"localhost", "127.0.0.1", "::1"}
            else:
                # A wildcard bind only admits the concrete interface receiving this request,
                # never an arbitrary DNS name supplied by a browser.
                allowed = {bound.lower().strip("[]"), self.connection.getsockname()[0].lower()}
            if host not in allowed or port != self.server.server_port:
                raise ValueError("untrusted Host")
            origins = self.headers.get_all("Origin", [])
            if len(origins) > 1 or (mutation and not origins):
                raise ValueError("Origin required")
            if origins:
                origin = origins[0]
                if not origin.startswith("http://") or self._authority(origin[7:]) != (host, port):
                    raise ValueError("cross-origin request")
            if mutation:
                tokens = self.headers.get_all("X-Dashboard-Token", [])
                if (len(tokens) != 1 or not tokens[0].isascii()
                        or not secrets.compare_digest(tokens[0], self._session_token())):
                    raise ValueError("session token required")
        except (ValueError, TypeError):
            self._discard_small_request_body()
            self._json({"error": "请求来源或会话令牌不受信任"}, 403)
            return False
        return True

    # ------------------------------------------------------------------
    # HTML 页面
    # ------------------------------------------------------------------

    def _serve_html(self):
        """返回单页HTML。"""
        html_path = _SCRIPT_DIR.parent / "assets" / "dashboard" / "index.html"
        if html_path.exists():
            content = common.read_text(html_path) or ""
        else:
            # Fallback：最小化HTML（如果前端文件还没创建）
            content = _FALLBACK_HTML

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    # ------------------------------------------------------------------
    # API 路由
    # ------------------------------------------------------------------

    def _serve_api(self, path: str, query_string: str):
        """REST API端点。"""
        params = urllib.parse.parse_qs(query_string)
        book = self.__class__.book_dir
        if book is None:
            self._json({"error": "未设置书籍目录"}, 500)
            return

        try:
            if path == "/api/session":
                data = {"token": self._session_token()}
            elif path == "/api/status":
                data = _collect_status(book)
            elif path == "/api/chapters":
                data = _collect_chapters(book)
            elif path == "/api/quality-trend":
                chapters = _collect_chapters(book)
                data = _collect_quality_trend(chapters)
            elif path == "/api/foreshadowing":
                data = _collect_foreshadowing(book)
            elif path == "/api/file-tree":
                data = _collect_file_tree(book)
            elif path == "/api/file":
                rel = params.get("path", [""])[0]
                data = file_snapshot(book, rel)
            else:
                self._json({"error": f"未知API: {path}"}, 404)
                return

            self._json(data)
        except EditableFileError as exc:
            self._editable_error(exc)
        except OSError:
            self._json({"error": "文件读取失败"}, 500)

    def _serve_mutation(self, method: str) -> None:
        """处理唯一允许的写端点，不让解析错误或异常细节逸出。"""
        if not self._authorize_request(mutation=True):
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/file":
            self._discard_small_request_body()
            self._json({"error": f"未知API: {parsed.path}"}, 404)
            return
        book = self.__class__.book_dir
        if book is None:
            self._json({"error": "未设置书籍目录"}, 500)
            return
        try:
            payload = self._read_json_body()
            rel_path = payload.get("path")
            revision = payload.get("revision")
            if not isinstance(rel_path, str) or not isinstance(revision, str):
                self._json({"error": "path 和 revision 必须是字符串"}, 400)
                return
            if method == "POST":
                content = payload.get("content")
                if not isinstance(content, str):
                    self._json({"error": "content 必须是字符串"}, 400)
                    return
                data = atomic_save(book, rel_path, content, revision)
            else:
                data = recoverable_delete(book, rel_path, revision)
            self._json(data)
        except FileConflictError as exc:
            self._json({"error": str(exc)}, 409)
        except EditableFileError as exc:
            self._editable_error(exc)
        except _HttpInputError as exc:
            self._json({"error": str(exc)}, exc.status)
        except UnicodeDecodeError:
            self._json({"error": "请求体必须是 UTF-8"}, 400)
        except (json.JSONDecodeError, TypeError):
            self._json({"error": "JSON 请求体格式错误"}, 400)
        except OSError:
            self._json({"error": "文件操作失败"}, 500)

    def _read_json_body(self) -> Dict[str, Any]:
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            self._discard_small_request_body()
            raise EditableFileError("Content-Type 必须是 application/json", unsupported=True)
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError as exc:
            raise TypeError("缺少有效的 Content-Length") from exc
        if content_length < 0:
            raise TypeError("Content-Length 非法")
        if content_length > MAX_REQUEST_BYTES:
            # 丢弃上限附近已经到达的请求体，避免 Windows 在响应前因未读数据复位连接。
            # 对远大于上限的声明不做无界读取。
            if content_length <= MAX_REQUEST_BYTES + 65536:
                self.rfile.read(content_length)
            raise _HttpInputError(413, "请求体超过 2 MiB 上限")
        raw = self.rfile.read(content_length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("JSON 请求体必须是对象")
        return payload

    def _discard_small_request_body(self) -> None:
        """消费小型未知请求体，使错误响应在常见客户端上可可靠接收。"""
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return
        if 0 < content_length <= 65536:
            self.rfile.read(content_length)

    def _editable_error(self, exc: EditableFileError) -> None:
        status = 400 if exc.invalid_input else (415 if exc.unsupported else (404 if str(exc) == "文件不存在" else 403))
        self._json({"error": str(exc)}, status)

    def _json(self, data: Any, status: int = 200):
        """返回JSON响应。"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    # 静默日志（避免刷屏）
    # ------------------------------------------------------------------

    def log_message(self, format, *args):
        """覆盖BaseHTTPRequestHandler的日志输出，只记录错误。"""
        if "error" in format.lower() or args and any("404" in str(a) for a in args):
            sys.stderr.write("%s - - [%s] %s\n" % (
                self.address_string(),
                self.log_date_time_string(),
                format % args,
            ))


# =============================================================================
# Fallback HTML（前端文件还没创建时的最小可用页面）
# =============================================================================

_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Long Novel Dashboard</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;padding:20px;background:#1a1a2e;color:#eee}
h1{color:#e94560}
.card{background:#16213e;padding:20px;border-radius:8px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,0.3)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px}
.stat-value{font-size:2em;font-weight:bold;color:#e94560}
.stat-label{color:#888;margin-top:4px}
table{width:100%;border-collapse:collapse}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #333}
th{color:#e94560}
.pass{color:#4ade80}
.fail{color:#f87171}
.loading{color:#888}
</style>
</head>
<body>
<h1>📖 Long Novel Dashboard</h1>
<div id="app">加载中...</div>
<script>
async function api(path){const r=await fetch(path);return r.json()}
async function render(){
const app=document.getElementById('app');
const s=await api('/api/status');
app.innerHTML=
'<div class="grid">'+
  '<div class="card"><div class="stat-value">'+s.last_chapter+'</div><div class="stat-label">最新章节</div></div>'+
  '<div class="card"><div class="stat-value">'+(s.total_chars/10000).toFixed(1)+'万</div><div class="stat-label">总字数</div></div>'+
  '<div class="card"><div class="stat-value">'+s.chapter_count+'</div><div class="stat-label">章节数</div></div>'+
  '<div class="card"><div class="stat-value">'+s.daily_avg+'</div><div class="stat-label">平均每章字数</div></div>'+
'</div>'+
'<div class="card"><h2>📚 章节列表</h2><div id="chapters">加载中...</div></div>';
const chs=await api('/api/chapters');
const rows=chs.slice().reverse().slice(0,20).map(c=>
  '<tr>'+
    '<td>第'+c.chapter+'章</td>'+
    '<td>'+c.title+'</td>'+
    '<td>'+c.chars+'字</td>'+
    '<td>'+(c.ai_score!=null?c.ai_score.toFixed(1)+'分':'<span class="loading">未评分</span>')+'</td>'+
    '<td>'+(c.gate_passed===true?'<span class="pass">✅通过</span>':c.gate_passed===false?'<span class="fail">❌未通过</span>':'<span class="loading">未检查</span>')+'</td>'+
  '</tr>'
).join('');
document.getElementById('chapters').innerHTML=
  '<table><thead><tr><th>章节</th><th>标题</th><th>字数</th><th>AI味分</th><th>门禁</th></tr></thead>'+
  '<tbody>'+rows+'</tbody></table>';
}
render();
</script>
</body>
</html>"""


# =============================================================================
# 主入口
# =============================================================================

def main():
    # Windows 中文控制台默认 GBK 输出，在 Git Bash 等 UTF-8 终端下会乱码；统一按 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(
        description="Long Novel Dashboard — 本地Web工作台（纯标准库）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python scripts/dashboard.py "我的小说"
  python scripts/dashboard.py "我的小说" --port 9000
  python novel-cli.py dashboard "我的小说"
""",
    )
    ap.add_argument("book_dir", help="书籍工程目录路径")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"HTTP服务端口（默认{DEFAULT_PORT}）")
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help=f"监听地址（默认{DEFAULT_HOST}，仅本机可访问）")
    args = ap.parse_args()

    book_dir = Path(args.book_dir).resolve()
    if not book_dir.is_dir():
        print(f"错误：目录不存在 {book_dir}", file=sys.stderr)
        return 2

    # 检查是否为有效书籍工程（至少有一个核心目录）
    has_book = any((book_dir / d).exists() for d in ["正文", "大纲", "设定", "追踪"])
    if not has_book:
        print(f"警告：{book_dir.name} 看起来不是书籍工程目录（缺少正文/大纲/设定/追踪）", file=sys.stderr)

    # 设置Handler的book_dir
    DashboardHandler.book_dir = book_dir
    DashboardHandler.bind_host = args.host

    if not _is_loopback_host(args.host):
        print("=" * 68, file=sys.stderr)
        print("⚠ 警告：Dashboard 已显式绑定非回环地址，将暴露到网络。", file=sys.stderr)
        print("  该服务没有身份认证或 TLS；只应在可信隔离网络中临时使用。", file=sys.stderr)
        print("=" * 68, file=sys.stderr)

    # 启动服务器
    print(f"📖 Long Novel Dashboard 启动")
    print(f"   书籍：{book_dir.name}")
    print(f"   地址：http://{args.host}:{args.port}")
    print(f"   按 Ctrl+C 停止")
    print()

    try:
        server = http.server.HTTPServer((args.host, args.port), DashboardHandler)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard 已停止")
        server.server_close()
    except OSError as exc:
        print(f"错误：Dashboard 无法在 {args.host}:{args.port} 启动：{exc}", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
