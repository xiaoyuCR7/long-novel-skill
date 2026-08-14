#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dashboard.py — 本地Web工作台MVP（纯标准库，零依赖）。

设计原则：
  1. 零第三方依赖，纯标准库 http.server
  2. 单页HTML应用，无构建步骤
  3. 只做只读操作，不修改书籍工程文件
  4. 只监听 localhost（安全，不暴露到网络）

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
import http.server
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

# 让脚本能导入同目录的模块
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import common

DEFAULT_PORT = 8765


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


def _read_file_content(book_dir: Path, rel_path: str) -> Dict[str, Any]:
    """读取文件内容（用于Markdown预览）。"""
    # 安全检查：防止路径穿越
    safe_path = (book_dir / rel_path).resolve()
    try:
        safe_path.relative_to(book_dir.resolve())
    except ValueError:
        return {"error": "路径非法", "content": ""}

    if not safe_path.exists() or not safe_path.is_file():
        return {"error": "文件不存在", "content": ""}

    # 只支持文本文件（.md, .txt, .json, .yaml, .yml, .ini）
    ext = safe_path.suffix.lower()
    if ext not in (".md", ".txt", ".json", ".yaml", ".yml", ".ini"):
        return {"error": "不支持的文件类型（仅支持 .md/.txt/.json/.yaml/.ini）", "content": ""}

    text = common.read_text(safe_path) or ""
    return {
        "ok": True,
        "name": safe_path.name,
        "path": rel_path,
        "content": text,
        "chars": common.count_chars(text),
        "ext": ext,
    }


# =============================================================================
# HTTP 服务器
# =============================================================================

class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """HTTP请求处理器。"""

    book_dir: Optional[Path] = None  # 类变量，由main设置

    # ------------------------------------------------------------------
    # 请求路由
    # ------------------------------------------------------------------

    def do_GET(self):
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
            if path == "/api/status":
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
                data = _read_file_content(book, rel)
            else:
                self._json({"error": f"未知API: {path}"}, 404)
                return

            self._json(data)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _json(self, data: Any, status: int = 200):
        """返回JSON响应。"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
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
    ap.add_argument("--host", default="localhost",
                    help="监听地址（默认localhost，仅本机可访问）")
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
    except OSError as e:
        print(f"错误：端口 {args.port} 已被占用，请用 --port 指定其他端口", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    sys.exit(main())
