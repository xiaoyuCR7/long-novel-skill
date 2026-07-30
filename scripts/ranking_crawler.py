#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ranking_crawler.py — 多平台网文榜单爬虫 v1.0.0（纯标准库 urllib，无第三方依赖）。

支持 3 大平台的榜单数据爬取与解析：
  1. 番茄小说 (fanqie) — 热销榜、新书榜、口碑榜
  2. 起点中文网 (qidian) — 月票榜、收藏榜、新书榜
  3. 晋江文学城 (jjwxc) — 积分榜、新晋榜、VIP榜

核心功能：
  crawl   — 爬取指定平台指定榜单，输出 JSON/Markdown
  compare — 对比多平台同类榜单，找共性题材
  analyze — 分析榜单关键词、题材分布、书名模式
  list    — 列出支持的平台和榜单

技术特性：
  - 纯标准库：urllib.request / urllib.parse / re / json / html / argparse / datetime / pathlib
  - User-Agent 伪装：随机 UA，请求间隔 2-5 秒
  - HTML 解析：正则 + html.unescape，不用 BeautifulSoup
  - 错误处理：网络失败重试 3 次，超时 15 秒
  - 缓存机制：结果缓存到 对标/ranking_cache/ 目录，24 小时内不重复爬取

用法：
  python scripts/ranking_crawler.py list
  python scripts/ranking_crawler.py crawl fanqie hot_sales --format json
  python scripts/ranking_crawler.py crawl qidian monthly_ticket --top 20 --output out.md
  python scripts/ranking_crawler.py compare --category xuanhuan
  python scripts/ranking_crawler.py analyze fanqie hot_sales

退出码：0 = 成功；1 = 数据为空；2 = 参数/网络错误。
"""

import argparse
import hashlib
import html
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量 / 配置
# ---------------------------------------------------------------------------

CACHE_DIR_NAME = "ranking_cache"
CACHE_TTL_HOURS = 24
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
MIN_INTERVAL = 2.0
MAX_INTERVAL = 5.0

# 随机 User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.0.0",
]

# 平台与榜单配置
PLATFORMS = {
    "fanqie": {
        "name": "番茄小说",
        "base_url": "https://fanqienovel.com",
        "lists": {
            "hot_sales": {"name": "热销榜", "path": "/rank/hot_sales"},
            "new_book": {"name": "新书榜", "path": "/rank/new_book"},
            "reputation": {"name": "口碑榜", "path": "/rank/reputation"},
        },
    },
    "qidian": {
        "name": "起点中文网",
        "base_url": "https://www.qidian.com",
        "lists": {
            "monthly_ticket": {"name": "月票榜", "path": "/rank/monthlyTicket"},
            "collect": {"name": "收藏榜", "path": "/rank/collect"},
            "new_book": {"name": "新书榜", "path": "/rank/newBook"},
        },
    },
    "jjwxc": {
        "name": "晋江文学城",
        "base_url": "https://www.jjwxc.net",
        "lists": {
            "score": {"name": "积分榜", "path": "/top/score.php"},
            "new_author": {"name": "新晋榜", "path": "/top/newauthor.php"},
            "vip": {"name": "VIP榜", "path": "/top/vip.php"},
        },
    },
}

# 数据结构必需字段
REQUIRED_FIELDS = [
    "rank", "title", "author", "category", "score",
    "platform", "list_name", "update_time",
]

# 常见网文题材关键词（用于 analyze 题材分布）
GENRE_KEYWORDS = [
    "玄幻", "奇幻", "仙侠", "武侠", "都市", "言情", "科幻",
    "历史", "军事", "游戏", "悬疑", "灵异", "恐怖", "同人",
    "穿越", "重生", "系统", "快穿", "末世", "修仙", "修真",
    "豪门", "总裁", "校园", "青春", "古代", "民国", "宫廷",
    "种田", "经商", "官场", "职场", "竞技", "娱乐", "明星",
    "废柴", "逆袭", "打脸", "甜宠", "虐恋", "爽文", "无敌",
]

# 常见书名模式
TITLE_PATTERNS = [
    (r"^我在.*搞.*", "我在X搞Y"),
    (r"^.*之.*", "X之Y"),
    (r"^.*：.*", "X：Y（冒号分隔）"),
    (r"^.*的.*", "X的Y"),
    (r"^.*传$", "X传"),
    (r"^.*录$", "X录"),
    (r"^.*记$", "X记"),
    (r"^重生.*", "重生X"),
    (r"^穿越.*", "穿越X"),
    (r"^.*系统$", "X系统"),
    (r"^开局.*", "开局X"),
    (r"^.*时代$", "X时代"),
    (r"^.*世界$", "X世界"),
    (r"^从.*开始$", "从X开始"),
]


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _reconfigure_streams():
    """统一设置 stdout/stderr 为 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _random_user_agent():
    """随机选取一个 User-Agent。"""
    return random.choice(USER_AGENTS)


def _sleep_random():
    """随机休眠 2-5 秒，模拟人类行为。"""
    delay = random.uniform(MIN_INTERVAL, MAX_INTERVAL)
    time.sleep(delay)


def _clean_text(text):
    """清理 HTML 文本：去标签、去多余空白、HTML 实体反转义。"""
    if not text:
        return ""
    # 反转义 HTML 实体
    text = html.unescape(text)
    # 去 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)
    # 去多余空白
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _safe_int(text, default=0):
    """安全解析整数，失败返回 default。"""
    if text is None:
        return default
    text = str(text).strip()
    text = text.replace(",", "").replace(".", "")
    m = re.search(r"\d+", text)
    if m:
        try:
            return int(m.group())
        except (ValueError, TypeError):
            return default
    return default


def _validate_record(record):
    """验证单条榜单记录是否包含所有必需字段。

    返回 (is_valid, missing_fields)。
    """
    missing = [f for f in REQUIRED_FIELDS if f not in record or record[f] is None]
    return len(missing) == 0, missing


def _cache_dir(base_dir=None):
    """获取缓存目录路径。"""
    if base_dir:
        return Path(base_dir) / CACHE_DIR_NAME
    # 默认：脚本所在目录的上级 / 对标 / ranking_cache
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent / "对标" / CACHE_DIR_NAME


def _cache_key(platform, list_name, top=None):
    """生成缓存键（基于平台+榜单名+top数的 MD5）。"""
    raw = json.dumps({"p": platform, "l": list_name, "t": top}, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _cache_path(platform, list_name, base_dir=None, top=None):
    """获取缓存文件路径。"""
    key = _cache_key(platform, list_name, top)
    return _cache_dir(base_dir) / f"{platform}_{list_name}_{key[:8]}.json"


def load_cache(platform, list_name, base_dir=None, top=None):
    """加载缓存数据，未命中或已过期返回 None。

    返回 (data, cache_file_path) 或 (None, cache_file_path)。
    """
    cache_path = _cache_path(platform, list_name, base_dir, top)
    if not cache_path.is_file():
        return None, str(cache_path)
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, ValueError):
        return None, str(cache_path)

    # 检查过期
    cached_time = cached.get("cached_at", "")
    if not cached_time:
        return None, str(cache_path)
    try:
        cached_dt = datetime.fromisoformat(cached_time)
    except (ValueError, TypeError):
        return None, str(cache_path)

    if datetime.now() - cached_dt > timedelta(hours=CACHE_TTL_HOURS):
        return None, str(cache_path)

    return cached.get("data", []), str(cache_path)


def save_cache(platform, list_name, data, base_dir=None, top=None):
    """保存数据到缓存。"""
    cache_path = _cache_path(platform, list_name, base_dir, top)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_obj = {
        "platform": platform,
        "list_name": list_name,
        "cached_at": datetime.now().isoformat(),
        "data": data,
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_obj, f, ensure_ascii=False, indent=2)
    return str(cache_path)


# ---------------------------------------------------------------------------
# HTTP 请求
# ---------------------------------------------------------------------------


def fetch_url(url, retries=MAX_RETRIES, timeout=REQUEST_TIMEOUT):
    """获取 URL 内容，失败重试。

    返回 (html_content, final_url)，失败抛出 urllib.error.URLError。
    """
    last_error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", _random_user_agent())
            req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
            req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                # 尝试多种编码
                charset = resp.headers.get_content_charset()
                if not charset:
                    # 从 HTML meta 中猜编码
                    meta_match = re.search(rb'charset=["\']?([\w-]+)', raw[:2048], re.I)
                    if meta_match:
                        charset = meta_match.group(1).decode("ascii", errors="ignore")
                    else:
                        charset = "utf-8"
                try:
                    content = raw.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    content = raw.decode("utf-8", errors="replace")
                return content, resp.geturl()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
            last_error = e
            if attempt < retries - 1:
                # 指数退避
                wait = 2 ** attempt
                time.sleep(wait)
            else:
                raise last_error


# ---------------------------------------------------------------------------
# 番茄小说解析器
# ---------------------------------------------------------------------------


def parse_fanqie(html_content, platform="fanqie", list_name="hot_sales"):
    """解析番茄小说榜单 HTML，返回记录列表。

    采用「按字段提取 + 按索引对齐」策略，避免嵌套标签导致的块匹配失败：
      1. 分别提取书名、作者、分类、热度、排名等各字段列表
      2. 以书名为基准，按索引对齐其他字段
      3. 缺失字段用默认值填充

    每条记录包含 rank/title/author/category/score/platform/list_name/update_time。
    """
    records = []
    update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 按字段分别提取 ----

    # 书名：优先匹配 book-title 类，其次含 book 的链接
    titles = _extract_field_by_class(
        html_content, tag="a",
        class_patterns=["book-title", "title", "name"],
        href_pattern="book",
    )
    if not titles:
        return []

    # 排名：rank-num 类或纯数字 span
    ranks = _extract_field_by_class(
        html_content, tag="span",
        class_patterns=["rank-num", "rank-number", "index"],
    )
    if not ranks:
        # 回退：在列表项中找数字
        ranks = [str(i + 1) for i in range(len(titles))]

    # 作者：book-author 类
    authors = _extract_field_by_class(
        html_content, tag="span",
        class_patterns=["book-author", "author", "writer"],
    )

    # 分类：book-category 类
    categories = _extract_field_by_class(
        html_content, tag="span",
        class_patterns=["book-category", "category", "tag", "genre"],
    )

    # 热度/分数：hot-num / score / num 类
    scores = _extract_field_by_class(
        html_content, tag="span",
        class_patterns=["hot-num", "score", "num", "count", "value"],
    )
    if not scores:
        scores = _extract_field_by_class(
            html_content, tag="div",
            class_patterns=["hot-score", "rank-score"],
        )

    # ---- 按索引对齐组装 ----
    for i, title in enumerate(titles):
        if not title or len(title) > 60:
            continue

        # 排名
        if i < len(ranks):
            rank_val = _safe_int(ranks[i])
            if rank_val == 0:
                rank_val = len(records) + 1
        else:
            rank_val = len(records) + 1

        # 作者
        author = authors[i] if i < len(authors) else "未知"
        if not author:
            author = "未知"

        # 分类
        category = categories[i] if i < len(categories) else ""

        # 分数
        score_text = scores[i] if i < len(scores) else "0"
        score = _safe_int(score_text)

        record = {
            "rank": rank_val,
            "title": title,
            "author": author,
            "category": category,
            "score": score,
            "platform": platform,
            "list_name": list_name,
            "update_time": update_time,
        }
        records.append(record)

        if len(records) >= 100:
            break

    return records


def _extract_field_by_class(html_content, tag="span", class_patterns=None, href_pattern=None):
    """按 class 名提取指定标签的文本内容。

    参数：
      html_content: HTML 字符串
      tag: HTML 标签名（a/span/div 等）
      class_patterns: class 名关键词列表（任一匹配即可）
      href_pattern: 链接 href 关键词（可选，用于 a 标签）

    返回清理后的文本列表。
    """
    if class_patterns is None:
        class_patterns = []

    results = []

    # 构建 class 匹配正则
    if class_patterns:
        class_re = "|".join(re.escape(p) for p in class_patterns)
        pattern = (
            rf'<{tag}[^>]*class="[^"]*(?:{class_re})[^"]*"[^>]*>'
            rf'(.*?)</{tag}>'
        )
        matches = re.findall(pattern, html_content, re.S | re.I)
        for m in matches:
            text = _clean_text(m)
            if text:
                results.append(text)

    # 如果 class 匹配为空且指定了 href 模式，用 href 补充
    if not results and href_pattern and tag == "a":
        href_re = re.escape(href_pattern)
        pattern = rf'<a[^>]*href="[^"]*{href_re}[^"]*"[^>]*>(.*?)</a>'
        matches = re.findall(pattern, html_content, re.S | re.I)
        for m in matches:
            text = _clean_text(m)
            if text and len(text) <= 60:
                results.append(text)

    return results


# ---------------------------------------------------------------------------
# 起点中文网解析器
# ---------------------------------------------------------------------------


def parse_qidian(html_content, platform="qidian", list_name="monthly_ticket"):
    """解析起点中文网榜单 HTML，返回记录列表。

    起点榜单通常以 tr/table 或 div 列表形式呈现。
    """
    records = []
    update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 起点榜单常见结构：rank-list / book-list
    # 尝试提取列表项
    book_blocks = re.findall(
        r'(?:<tr|<div|<li)[^>]*class="[^"]*(?:rank-item|book-item|item|list-item|book-row)[^"]*"[^>]*>(.*?)(?:</tr>|</div>|</li>)',
        html_content,
        re.S | re.I,
    )

    if not book_blocks:
        # 回退：table 行
        book_blocks = re.findall(
            r'<tr[^>]*>(.*?)</tr>',
            html_content,
            re.S,
        )

    rank = 0
    for block in book_blocks:
        # 提取排名
        rank_match = re.search(
            r'<span[^>]*class="[^"]*(?:rank-num|rank-number|number|index|rank)[^"]*"[^>]*>(.*?)</span>',
            block, re.S | re.I,
        )
        if not rank_match:
            rank_match = re.search(r'>(\d{1,3})<', block)
        if rank_match:
            block_rank = _safe_int(rank_match.group(1))
            if block_rank == 0:
                rank += 1
                block_rank = rank
        else:
            rank += 1
            block_rank = rank

        if block_rank == 0:
            continue

        # 提取书名
        title_match = re.search(
            r'<a[^>]*class="[^"]*(?:book-title|title|name|bookname)[^"]*"[^>]*>(.*?)</a>',
            block, re.S | re.I,
        )
        if not title_match:
            title_match = re.search(
                r'<a[^>]*href="[^"]*(?:book|info)[^"]*"[^>]*>(.*?)</a>',
                block, re.S | re.I,
            )
        title = _clean_text(title_match.group(1)) if title_match else ""
        if not title or len(title) > 50:
            continue

        # 提取作者
        author_match = re.search(
            r'<a[^>]*class="[^"]*(?:author|writer)[^"]*"[^>]*>(.*?)</a>',
            block, re.S | re.I,
        )
        if not author_match:
            author_match = re.search(
                r'作者[：:\s]*<[^>]*>(.*?)</',
                block, re.S | re.I,
            )
        if not author_match:
            # 尝试从多个 a 标签中找作者
            a_tags = re.findall(r'<a[^>]*>(.*?)</a>', block, re.S)
            author = _clean_text(a_tags[1]) if len(a_tags) > 1 else "未知"
        else:
            author = _clean_text(author_match.group(1))
        if not author:
            author = "未知"

        # 提取分类
        category_match = re.search(
            r'<span[^>]*class="[^"]*(?:category|tag|genre|type|chan)[^"]*"[^>]*>(.*?)</span>',
            block, re.S | re.I,
        )
        if not category_match:
            category_match = re.search(
                r'[\u4e00-\u9fa5]{2,4}(?:小说|类|频道)',
                block,
            )
        category = _clean_text(category_match.group(0)) if category_match else ""

        # 提取分数/月票数
        score_match = re.search(
            r'<span[^>]*class="[^"]*(?:num|count|value|ticket|number|score)[^"]*"[^>]*>(.*?)</span>',
            block, re.S | re.I,
        )
        if not score_match:
            score_match = re.search(
                r'(\d{1,3}(?:[,\.]\d{3})*(?:\s*万|\s*亿)?)',
                block,
            )
        score_text = _clean_text(score_match.group(1)) if score_match else "0"
        score = _safe_int(score_text)

        record = {
            "rank": block_rank,
            "title": title,
            "author": author,
            "category": category,
            "score": score,
            "platform": platform,
            "list_name": list_name,
            "update_time": update_time,
        }
        records.append(record)

        if block_rank >= 100:
            break

    return records


# ---------------------------------------------------------------------------
# 晋江文学城解析器
# ---------------------------------------------------------------------------


def parse_jjwxc(html_content, platform="jjwxc", list_name="score"):
    """解析晋江文学城榜单 HTML，返回记录列表。

    晋江榜单多为 table 结构。
    """
    records = []
    update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 晋江榜单通常是表格形式
    rows = re.findall(
        r'<tr[^>]*>(.*?)</tr>',
        html_content,
        re.S | re.I,
    )

    rank = 0
    for row in rows:
        # 提取所有单元格
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S | re.I)
        if len(cells) < 3:
            continue

        # 第一列通常是排名
        rank_text = _clean_text(cells[0])
        block_rank = _safe_int(rank_text)
        if block_rank == 0:
            rank += 1
            block_rank = rank

        # 第二/三列通常是书名
        title = ""
        for cell in cells[:3]:
            title_match = re.search(
                r'<a[^>]*href="[^"]*onebook[^"]*"[^>]*>(.*?)</a>',
                cell, re.S | re.I,
            )
            if not title_match:
                title_match = re.search(r'<a[^>]*>(.*?)</a>', cell, re.S)
            if title_match:
                candidate = _clean_text(title_match.group(1))
                if candidate and 2 <= len(candidate) <= 50 and not candidate.isdigit():
                    title = candidate
                    break
        if not title:
            continue

        # 提取作者
        author = "未知"
        for cell in cells[1:5]:
            author_match = re.search(
                r'<a[^>]*href="[^"]*author[^"]*"[^>]*>(.*?)</a>',
                cell, re.S | re.I,
            )
            if not author_match:
                # 找第二个 a 标签或纯文本
                a_tags = re.findall(r'<a[^>]*>(.*?)</a>', cell, re.S)
                if len(a_tags) >= 2:
                    author = _clean_text(a_tags[1])
                    if author and author != title:
                        break
            else:
                author = _clean_text(author_match.group(1))
                if author:
                    break

        # 提取分类
        category = ""
        for cell in cells:
            cat_match = re.search(
                r'[\u4e00-\u9fa5]{2,4}(?:言情|纯爱|衍生|原创|武侠|仙侠|科幻|游戏|悬疑|历史|奇幻)',
                _clean_text(cell),
            )
            if cat_match:
                category = cat_match.group(0)
                break

        # 提取分数/积分
        score = 0
        for cell in cells[-3:]:
            score_text = _clean_text(cell)
            if re.search(r'\d', score_text):
                score = _safe_int(score_text)
                if score > 0:
                    break

        record = {
            "rank": block_rank,
            "title": title,
            "author": author,
            "category": category,
            "score": score,
            "platform": platform,
            "list_name": list_name,
            "update_time": update_time,
        }
        records.append(record)

        if block_rank >= 100:
            break

    return records


# ---------------------------------------------------------------------------
# 解析调度
# ---------------------------------------------------------------------------

PARSERS = {
    "fanqie": parse_fanqie,
    "qidian": parse_qidian,
    "jjwxc": parse_jjwxc,
}


def _build_url(platform, list_name):
    """构建榜单完整 URL。"""
    plat = PLATFORMS.get(platform)
    if not plat:
        return None
    lst = plat["lists"].get(list_name)
    if not lst:
        return None
    return urllib.parse.urljoin(plat["base_url"], lst["path"])


def crawl_list(platform, list_name, top=None, use_cache=True, base_dir=None):
    """爬取指定平台指定榜单。

    参数：
      platform: 平台 ID（fanqie/qidian/jjwxc）
      list_name: 榜单 ID
      top: 返回前 N 条，None 表示全部
      use_cache: 是否使用缓存
      base_dir: 缓存基准目录

    返回 (records, from_cache)。
    """
    if platform not in PLATFORMS:
        raise ValueError(f"未知平台：{platform}")
    if list_name not in PLATFORMS[platform]["lists"]:
        raise ValueError(f"未知榜单：{platform}/{list_name}")

    # 先查缓存
    if use_cache:
        cached, cache_path = load_cache(platform, list_name, base_dir, top)
        if cached:
            if top:
                return cached[:top], True
            return cached, True

    # 实际爬取
    url = _build_url(platform, list_name)
    try:
        html_content, _ = fetch_url(url)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
        raise RuntimeError(f"爬取失败：{e}") from e

    parser = PARSERS[platform]
    records = parser(html_content, platform=platform, list_name=list_name)

    if not records:
        return [], False

    # 写入缓存
    if use_cache:
        save_cache(platform, list_name, records, base_dir, top)

    if top:
        return records[:top], False
    return records, False


# ---------------------------------------------------------------------------
# 榜单对比
# ---------------------------------------------------------------------------


def compare_lists(platforms=None, list_names=None, base_dir=None):
    """对比多平台榜单，找共性题材和重叠作品。

    参数：
      platforms: 平台列表，None 表示全部
      list_names: 榜单列表，None 表示各平台默认主榜
      base_dir: 缓存目录

    返回对比结果字典。
    """
    if platforms is None:
        platforms = list(PLATFORMS.keys())
    if list_names is None:
        list_names = {}
        for p in platforms:
            # 取每个平台第一个榜单作为默认
            first = list(PLATFORMS[p]["lists"].keys())[0]
            list_names[p] = first
    elif isinstance(list_names, str):
        list_names = {p: list_names for p in platforms}

    all_records = {}
    for p in platforms:
        lst = list_names.get(p)
        if not lst or lst not in PLATFORMS[p]["lists"]:
            continue
        try:
            records, _ = crawl_list(p, lst, top=50, use_cache=True, base_dir=base_dir)
            all_records[f"{p}:{lst}"] = records
        except (RuntimeError, ValueError):
            continue

    if not all_records:
        return {"error": "未获取到任何榜单数据"}

    # 统计各平台题材分布
    genre_dist = {}
    for key, records in all_records.items():
        genres = Counter()
        for r in records:
            cat = r.get("category", "")
            if cat:
                genres[cat] += 1
        genre_dist[key] = genres.most_common(10)

    # 找共性题材（出现在至少 2 个平台的前 10 题材）
    all_genres = set()
    for key, top_genres in genre_dist.items():
        for g, _ in top_genres[:5]:
            all_genres.add(g)

    common_genres = []
    for g in all_genres:
        appear_in = 0
        for key, top_genres in genre_dist.items():
            if any(gg == g for gg, _ in top_genres):
                appear_in += 1
        if appear_in >= 2:
            common_genres.append((g, appear_in))
    common_genres.sort(key=lambda x: -x[1])

    # 书名关键词重叠
    all_titles = []
    for key, records in all_records.items():
        for r in records:
            all_titles.append(r["title"])

    title_keywords = _extract_title_keywords(all_titles)

    return {
        "platforms_compared": list(all_records.keys()),
        "total_books": sum(len(v) for v in all_records.values()),
        "genre_distribution": genre_dist,
        "common_genres": common_genres[:15],
        "hot_title_keywords": title_keywords[:20],
    }


# ---------------------------------------------------------------------------
# 榜单分析
# ---------------------------------------------------------------------------


def _extract_title_keywords(titles):
    """从书名列表中提取高频关键词（2-4 字词）。"""
    word_counter = Counter()
    for title in titles:
        if not title:
            continue
        # 2字词滑窗
        for i in range(len(title) - 1):
            w = title[i:i + 2]
            if re.match(r'^[\u4e00-\u9fa5]{2,}$', w):
                word_counter[w] += 1
        # 3字词滑窗
        for i in range(len(title) - 2):
            w = title[i:i + 3]
            if re.match(r'^[\u4e00-\u9fa5]{3,}$', w):
                word_counter[w] += 1
    return word_counter.most_common()


def analyze_list(records):
    """分析榜单数据，返回关键词、题材分布、书名模式统计。

    参数：
      records: 榜单记录列表

    返回分析结果字典。
    """
    if not records:
        return {"error": "无数据可分析"}

    # 题材分布
    category_counter = Counter()
    for r in records:
        cat = r.get("category", "")
        if cat:
            category_counter[cat] += 1

    # 书名关键词
    titles = [r.get("title", "") for r in records]
    title_keywords = _extract_title_keywords(titles)

    # 题材关键词匹配
    genre_hits = Counter()
    for r in records:
        title = r.get("title", "")
        cat = r.get("category", "")
        text = f"{title} {cat}"
        for g in GENRE_KEYWORDS:
            if g in text:
                genre_hits[g] += 1

    # 书名模式统计
    pattern_stats = []
    total_books = len(records)
    for pattern, label in TITLE_PATTERNS:
        count = sum(1 for t in titles if re.search(pattern, t))
        if count > 0:
            pct = round(count / total_books * 100, 1)
            pattern_stats.append({
                "pattern": label,
                "count": count,
                "percentage": pct,
            })
    pattern_stats.sort(key=lambda x: -x["count"])

    # 作者分布
    author_counter = Counter()
    for r in records:
        author = r.get("author", "")
        if author and author != "未知":
            author_counter[author] += 1

    # 分数统计
    scores = [r.get("score", 0) for r in records if r.get("score", 0) > 0]
    score_stats = {}
    if scores:
        score_stats = {
            "max": max(scores),
            "min": min(scores),
            "avg": round(sum(scores) / len(scores), 2),
            "sample_count": len(scores),
        }

    return {
        "total_books": total_books,
        "category_distribution": category_counter.most_common(15),
        "genre_hits": genre_hits.most_common(15),
        "title_keywords": title_keywords[:20],
        "title_patterns": pattern_stats,
        "top_authors": author_counter.most_common(10),
        "score_stats": score_stats,
    }


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------


def format_records_markdown(records, platform=None, list_name=None):
    """将记录格式化为 Markdown 表格。"""
    lines = []
    if platform and list_name:
        plat_name = PLATFORMS.get(platform, {}).get("name", platform)
        lst_name = PLATFORMS.get(platform, {}).get("lists", {}).get(list_name, {}).get("name", list_name)
        lines.append(f"# {plat_name} - {lst_name}")
        lines.append("")

    if not records:
        lines.append("_无数据_")
        return "\n".join(lines)

    update_time = records[0].get("update_time", "")
    if update_time:
        lines.append(f"_更新时间：{update_time}_")
        lines.append("")

    lines.append("| 排名 | 书名 | 作者 | 分类 | 热度/积分 |")
    lines.append("|------|------|------|------|----------|")
    for r in records:
        lines.append(
            f"| {r.get('rank', '-')} | {r.get('title', '')} | "
            f"{r.get('author', '')} | {r.get('category', '')} | "
            f"{r.get('score', 0)} |"
        )
    return "\n".join(lines)


def format_analysis_markdown(analysis):
    """将分析结果格式化为 Markdown。"""
    lines = ["# 榜单分析报告", ""]

    if "error" in analysis:
        lines.append(f"_错误：{analysis['error']}_")
        return "\n".join(lines)

    lines.append(f"**总样本数：** {analysis['total_books']} 本")
    lines.append("")

    # 题材分布
    lines.append("## 题材分布 Top 15")
    lines.append("")
    lines.append("| 排名 | 题材 | 数量 | 占比 |")
    lines.append("|------|------|------|------|")
    total = analysis["total_books"]
    for i, (cat, cnt) in enumerate(analysis.get("category_distribution", [])[:15], 1):
        pct = round(cnt / total * 100, 1) if total > 0 else 0
        lines.append(f"| {i} | {cat} | {cnt} | {pct}% |")
    lines.append("")

    # 热门题材关键词
    lines.append("## 热门题材关键词")
    lines.append("")
    genre_hits = analysis.get("genre_hits", [])
    if genre_hits:
        lines.append("| 关键词 | 命中数 |")
        lines.append("|--------|--------|")
        for g, cnt in genre_hits[:15]:
            lines.append(f"| {g} | {cnt} |")
    lines.append("")

    # 书名高频词
    lines.append("## 书名高频词 Top 20")
    lines.append("")
    title_kws = analysis.get("title_keywords", [])
    if title_kws:
        lines.append("| 排名 | 词汇 | 出现次数 |")
        lines.append("|------|------|----------|")
        for i, (w, cnt) in enumerate(title_kws[:20], 1):
            lines.append(f"| {i} | {w} | {cnt} |")
    lines.append("")

    # 书名模式
    lines.append("## 书名模式统计")
    lines.append("")
    patterns = analysis.get("title_patterns", [])
    if patterns:
        lines.append("| 模式 | 数量 | 占比 |")
        lines.append("|------|------|------|")
        for p in patterns[:10]:
            lines.append(f"| {p['pattern']} | {p['count']} | {p['percentage']}% |")
    lines.append("")

    # 作者榜
    lines.append("## 上榜作者 Top 10")
    lines.append("")
    authors = analysis.get("top_authors", [])
    if authors:
        lines.append("| 排名 | 作者 | 上榜数 |")
        lines.append("|------|------|--------|")
        for i, (a, cnt) in enumerate(authors[:10], 1):
            lines.append(f"| {i} | {a} | {cnt} |")
    lines.append("")

    # 分数统计
    score_stats = analysis.get("score_stats", {})
    if score_stats:
        lines.append("## 热度/积分统计")
        lines.append("")
        lines.append(f"- 最大值：{score_stats.get('max', 0)}")
        lines.append(f"- 最小值：{score_stats.get('min', 0)}")
        lines.append(f"- 平均值：{score_stats.get('avg', 0)}")
        lines.append(f"- 有效样本：{score_stats.get('sample_count', 0)}")
        lines.append("")

    return "\n".join(lines)


def format_compare_markdown(compare_result):
    """将对比结果格式化为 Markdown。"""
    lines = ["# 多平台榜单对比报告", ""]

    if "error" in compare_result:
        lines.append(f"_错误：{compare_result['error']}_")
        return "\n".join(lines)

    lines.append(f"**对比平台：** {', '.join(compare_result.get('platforms_compared', []))}")
    lines.append(f"**总样本数：** {compare_result.get('total_books', 0)} 本")
    lines.append("")

    # 共性题材
    lines.append("## 共性题材（出现在 2+ 平台）")
    lines.append("")
    common = compare_result.get("common_genres", [])
    if common:
        lines.append("| 题材 | 覆盖平台数 |")
        lines.append("|------|------------|")
        for g, cnt in common:
            lines.append(f"| {g} | {cnt} |")
    else:
        lines.append("_无共性题材_")
    lines.append("")

    # 各平台题材分布
    lines.append("## 各平台题材分布 Top 10")
    lines.append("")
    for key, dist in compare_result.get("genre_distribution", {}).items():
        lines.append(f"### {key}")
        lines.append("")
        lines.append("| 题材 | 数量 |")
        lines.append("|------|------|")
        for g, cnt in dist[:10]:
            lines.append(f"| {g} | {cnt} |")
        lines.append("")

    # 书名热门关键词
    lines.append("## 跨平台书名热门关键词 Top 20")
    lines.append("")
    kws = compare_result.get("hot_title_keywords", [])
    if kws:
        lines.append("| 排名 | 词汇 | 出现次数 |")
        lines.append("|------|------|----------|")
        for i, (w, cnt) in enumerate(kws[:20], 1):
            lines.append(f"| {i} | {w} | {cnt} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI 子命令
# ---------------------------------------------------------------------------


def cmd_list():
    """list 子命令：列出所有支持的平台和榜单。"""
    print("=" * 60)
    print("支持的平台与榜单")
    print("=" * 60)
    for plat_id, plat_info in PLATFORMS.items():
        print(f"\n【{plat_info['name']}】 (id: {plat_id})")
        print(f"  主页：{plat_info['base_url']}")
        print(f"  榜单列表：")
        for lst_id, lst_info in plat_info["lists"].items():
            print(f"    - {lst_info['name']} (id: {lst_id}) → {lst_info['path']}")
    print()
    print(f"缓存目录：{_cache_dir()}")
    print(f"缓存有效期：{CACHE_TTL_HOURS} 小时")
    return 0


def cmd_crawl(args):
    """crawl 子命令：爬取指定平台榜单。"""
    platform = args.platform
    list_name = args.list_name
    top = args.top
    fmt = args.format
    output = args.output
    no_cache = args.no_cache
    base_dir = args.cache_dir

    try:
        records, from_cache = crawl_list(
            platform, list_name, top=top,
            use_cache=not no_cache, base_dir=base_dir,
        )
    except (ValueError, RuntimeError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2

    if not records:
        print("警告：未获取到任何榜单数据", file=sys.stderr)
        return 1

    # 格式化输出
    if fmt == "json":
        output_text = json.dumps(records, ensure_ascii=False, indent=2)
    elif fmt == "markdown":
        output_text = format_records_markdown(records, platform, list_name)
    else:
        # 纯文本表格
        plat_name = PLATFORMS.get(platform, {}).get("name", platform)
        lst_name = PLATFORMS[platform]["lists"][list_name]["name"]
        lines = [
            f"=== {plat_name} · {lst_name} ===",
            f"共 {len(records)} 条（{'缓存' if from_cache else '实时'}）",
            "",
            f"{'排名':<6} {'书名':<25} {'作者':<12} {'分类':<10} {'热度':<10}",
            "-" * 70,
        ]
        for r in records:
            title = r.get("title", "")[:24]
            author = r.get("author", "")[:10]
            category = r.get("category", "")[:8]
            lines.append(
                f"{r.get('rank', '-'):<6} {title:<25} {author:<12} {category:<10} {r.get('score', 0):<10}"
            )
        output_text = "\n".join(lines)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"已输出到：{out_path}")
    else:
        print(output_text)

    return 0


def cmd_compare(args):
    """compare 子命令：对比多平台榜单。"""
    platforms = args.platforms if args.platforms else None
    base_dir = args.cache_dir

    result = compare_lists(platforms=platforms, base_dir=base_dir)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        md = format_compare_markdown(result)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"对比报告已写入：{out_path}")
    else:
        print(format_compare_markdown(result))

    return 0


def cmd_analyze(args):
    """analyze 子命令：分析榜单关键词、题材分布、书名模式。"""
    platform = args.platform
    list_name = args.list_name
    base_dir = args.cache_dir
    no_cache = args.no_cache

    try:
        records, from_cache = crawl_list(
            platform, list_name,
            use_cache=not no_cache, base_dir=base_dir,
        )
    except (ValueError, RuntimeError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2

    if not records:
        print("警告：无数据可分析", file=sys.stderr)
        return 1

    analysis = analyze_list(records)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        md = format_analysis_markdown(analysis)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"分析报告已写入：{out_path}")
    else:
        print(format_analysis_markdown(analysis))

    return 0


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main():
    _reconfigure_streams()

    ap = argparse.ArgumentParser(
        description="多平台网文榜单爬虫 v1.0.0：crawl 爬取 / compare 对比 / analyze 分析 / list 列出"
    )
    subparsers = ap.add_subparsers(dest="command", help="子命令")

    # list 子命令
    subparsers.add_parser("list", help="列出所有支持的平台和榜单")

    # crawl 子命令
    crawl_p = subparsers.add_parser("crawl", help="爬取指定平台指定榜单")
    crawl_p.add_argument("platform", help="平台 ID（fanqie/qidian/jjwxc）")
    crawl_p.add_argument("list_name", help="榜单 ID")
    crawl_p.add_argument("--top", type=int, default=None,
                         help="返回前 N 条（默认全部）")
    crawl_p.add_argument("--format", choices=["json", "markdown", "text"],
                         default="text", help="输出格式（默认 text）")
    crawl_p.add_argument("--output", "-o", default=None,
                         help="输出文件路径（默认 stdout）")
    crawl_p.add_argument("--no-cache", action="store_true",
                         help="不使用缓存，强制重新爬取")
    crawl_p.add_argument("--cache-dir", default=None,
                         help="缓存目录（默认 对标/ranking_cache/）")

    # compare 子命令
    cmp_p = subparsers.add_parser("compare", help="对比多平台榜单，找共性题材")
    cmp_p.add_argument("--platforms", nargs="*", default=None,
                       help="指定平台列表（默认全部）")
    cmp_p.add_argument("--output", "-o", default=None,
                       help="输出文件路径")
    cmp_p.add_argument("--cache-dir", default=None,
                       help="缓存目录")

    # analyze 子命令
    ana_p = subparsers.add_parser("analyze", help="分析榜单关键词、题材分布、书名模式")
    ana_p.add_argument("platform", help="平台 ID")
    ana_p.add_argument("list_name", help="榜单 ID")
    ana_p.add_argument("--output", "-o", default=None,
                       help="输出文件路径")
    ana_p.add_argument("--no-cache", action="store_true",
                       help="不使用缓存")
    ana_p.add_argument("--cache-dir", default=None,
                         help="缓存目录")

    args = ap.parse_args()

    if args.command == "list":
        return cmd_list()
    elif args.command == "crawl":
        return cmd_crawl(args)
    elif args.command == "compare":
        return cmd_compare(args)
    elif args.command == "analyze":
        return cmd_analyze(args)
    else:
        ap.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
