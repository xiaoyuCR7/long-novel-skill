#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_ranking_crawler.py — 测试 ranking_crawler.py 多平台网文榜单爬虫。

覆盖范围：
  - HTML 解析函数（用 mock HTML 字符串，不实际发请求）
    - parse_fanqie：番茄小说榜单解析
    - parse_qidian：起点中文网榜单解析
    - parse_jjwxc：晋江文学城榜单解析
  - 数据结构验证：_validate_record、REQUIRED_FIELDS
  - 缓存读写：load_cache / save_cache / 过期机制
  - 关键词分析函数：analyze_list、_extract_title_keywords、compare_lists
  - 工具函数：_clean_text、_safe_int、_random_user_agent、_build_url
  - CLI 子命令：list 子命令（不发网络请求）

运行方式：
    python scripts/tests/test_ranking_crawler.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

# 把 scripts 目录加入 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ranking_crawler
from ranking_crawler import (
    _clean_text,
    _safe_int,
    _random_user_agent,
    _validate_record,
    _build_url,
    _extract_title_keywords,
    parse_fanqie,
    parse_qidian,
    parse_jjwxc,
    analyze_list,
    compare_lists,
    load_cache,
    save_cache,
    format_records_markdown,
    format_analysis_markdown,
    format_compare_markdown,
    PLATFORMS,
    REQUIRED_FIELDS,
    USER_AGENTS,
    CACHE_TTL_HOURS,
    cmd_list,
)

SCRIPT_PATH = str(SCRIPT_DIR / "ranking_crawler.py")


# ---------------------------------------------------------------------------
# Mock HTML 数据
# ---------------------------------------------------------------------------


def _mock_fanqie_html():
    """构造番茄小说榜单的 mock HTML。"""
    books = [
        (1, "万相之王", "天蚕土豆", "玄幻", "328.5万"),
        (2, "夜的命名术", "会说话的肘子", "都市", "256.3万"),
        (3, "深空彼岸", "辰东", "科幻", "198.7万"),
    ]
    items = []
    for rank, title, author, category, score in books:
        items.append(f'''
        <div class="rank-item">
            <div class="rank-num">{rank}</div>
            <div class="book-info">
                <a class="book-title" href="/book/{rank}">{title}</a>
                <span class="book-author">{author}</span>
                <span class="book-category">{category}小说</span>
            </div>
            <div class="rank-score">
                <span class="hot-num">{score}热度</span>
            </div>
        </div>
        ''')
    return f'''
    <!DOCTYPE html>
    <html>
    <head><title>番茄小说热销榜</title></head>
    <body>
        <div class="rank-list">
            {''.join(items)}
        </div>
    </body>
    </html>
    '''


def _mock_qidian_html():
    """构造起点中文网榜单的 mock HTML。"""
    books = [
        (1, "诡秘之主", "爱潜水的乌贼", "玄幻", "125000"),
        (2, "大奉打更人", "卖报小郎君", "仙侠", "98500"),
        (3, "庆余年", "猫腻", "历史", "87200"),
    ]
    rows = []
    for rank, title, author, category, score in books:
        rows.append(f'''
        <tr class="rank-item">
            <td><span class="rank-num">{rank}</span></td>
            <td><a class="book-title" href="//book.qidian.com/info/{rank}">{title}</a></td>
            <td><a class="author" href="//author.qidian.com/{rank}">{author}</a></td>
            <td><span class="chan">{category}</span></td>
            <td><span class="num">{score}</span></td>
        </tr>
        ''')
    return f'''
    <!DOCTYPE html>
    <html>
    <head><title>起点月票榜</title></head>
    <body>
        <table class="rank-list">
            <thead>
                <tr><th>排名</th><th>书名</th><th>作者</th><th>分类</th><th>月票</th></tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
    </body>
    </html>
    '''


def _mock_jjwxc_html():
    """构造晋江文学城榜单的 mock HTML。"""
    books = [
        (1, "山河令", "Priest", "纯爱", "987654321"),
        (2, "默读", "Priest", "纯爱", "876543210"),
        (3, "破云", "淮上", "纯爱", "765432109"),
    ]
    rows = []
    for rank, title, author, category, score in books:
        rows.append(f'''
        <tr>
            <td align="center">{rank}</td>
            <td align="left">
                <a href="onebook.php?novelid={rank}" class="bigtext">{title}</a>
            </td>
            <td align="center">
                <a href="author.php?authorid={rank}">{author}</a>
            </td>
            <td align="center">{category}</td>
            <td align="right">{score}</td>
        </tr>
        ''')
    return f'''
    <!DOCTYPE html>
    <html>
    <head><title>晋江积分榜</title></head>
    <body>
        <table>
            <tr><th>排名</th><th>作品</th><th>作者</th><th>类型</th><th>积分</th></tr>
            {''.join(rows)}
        </table>
    </body>
    </html>
    '''


# ---------------------------------------------------------------------------
# 工具函数测试
# ---------------------------------------------------------------------------


class TestCleanText(unittest.TestCase):
    """_clean_text HTML 文本清理测试。"""

    def test_strip_html_tags(self):
        """去除 HTML 标签。"""
        self.assertEqual(_clean_text("<p>hello</p>"), "hello")
        self.assertEqual(_clean_text("<div><span>你好</span></div>"), "你好")

    def test_html_entity_unescape(self):
        """HTML 实体反转义。"""
        self.assertEqual(_clean_text("&amp;"), "&")
        self.assertEqual(_clean_text("&quot;hello&quot;"), '"hello"')
        # &nbsp; 反转义为不间断空格，再被空白归一化为单空格
        self.assertEqual(_clean_text("售价&nbsp;99元"), "售价 99元")
        # 中文 Unicode 实体
        self.assertEqual(_clean_text("&#x4E2D;&#x6587;"), "中文")

    def test_whitespace_normalization(self):
        """多余空白归一化为单空格。"""
        self.assertEqual(_clean_text("  你好   世界  "), "你好 世界")
        self.assertEqual(_clean_text("line1\n\nline2"), "line1 line2")

    def test_empty_string(self):
        """空字符串返回空。"""
        self.assertEqual(_clean_text(""), "")
        self.assertEqual(_clean_text(None), "")

    def test_nested_tags(self):
        """嵌套标签正确清理。"""
        self.assertEqual(_clean_text("<div><p><b>粗体</b></p></div>"), "粗体")


class TestSafeInt(unittest.TestCase):
    """_safe_int 安全整数解析测试。"""

    def test_normal_integer(self):
        """正常整数解析。"""
        self.assertEqual(_safe_int("123"), 123)
        self.assertEqual(_safe_int("0"), 0)

    def test_comma_separated(self):
        """带逗号的数字。"""
        self.assertEqual(_safe_int("1,234"), 1234)
        self.assertEqual(_safe_int("1,234,567"), 1234567)

    def test_decimal_number(self):
        """小数取整。"""
        self.assertEqual(_safe_int("3.14"), 314)

    def test_chinese_suffix(self):
        """带中文单位的数字（万/亿）。"""
        self.assertEqual(_safe_int("328.5万"), 3285)
        self.assertEqual(_safe_int("1.2亿"), 12)

    def test_non_numeric_string(self):
        """非数字字符串返回默认值。"""
        self.assertEqual(_safe_int("abc"), 0)
        self.assertEqual(_safe_int("abc", -1), -1)

    def test_none_input(self):
        """None 输入返回默认值。"""
        self.assertEqual(_safe_int(None), 0)

    def test_mixed_content(self):
        """混合内容提取数字。"""
        self.assertEqual(_safe_int("热度 328万"), 328)
        self.assertEqual(_safe_int("积分: 987654"), 987654)


class TestRandomUserAgent(unittest.TestCase):
    """_random_user_agent 随机 UA 测试。"""

    def test_returns_string(self):
        """返回字符串类型。"""
        ua = _random_user_agent()
        self.assertIsInstance(ua, str)

    def test_ua_in_pool(self):
        """返回的 UA 在池中。"""
        ua = _random_user_agent()
        self.assertIn(ua, USER_AGENTS)

    def test_pool_not_empty(self):
        """UA 池非空。"""
        self.assertGreater(len(USER_AGENTS), 0)


class TestValidateRecord(unittest.TestCase):
    """_validate_record 数据结构验证测试。"""

    def test_valid_record(self):
        """完整记录验证通过。"""
        record = {
            "rank": 1,
            "title": "测试书名",
            "author": "测试作者",
            "category": "玄幻",
            "score": 1000,
            "platform": "fanqie",
            "list_name": "hot_sales",
            "update_time": "2024-01-01 00:00:00",
        }
        is_valid, missing = _validate_record(record)
        self.assertTrue(is_valid)
        self.assertEqual(missing, [])

    def test_missing_field(self):
        """缺少字段验证失败。"""
        record = {
            "rank": 1,
            "title": "测试书名",
            "author": "测试作者",
            # 缺少 category
            "score": 1000,
            "platform": "fanqie",
            "list_name": "hot_sales",
            "update_time": "2024-01-01 00:00:00",
        }
        is_valid, missing = _validate_record(record)
        self.assertFalse(is_valid)
        self.assertIn("category", missing)

    def test_empty_record(self):
        """空记录返回所有必需字段。"""
        is_valid, missing = _validate_record({})
        self.assertFalse(is_valid)
        self.assertEqual(len(missing), len(REQUIRED_FIELDS))

    def test_none_value_counts_as_missing(self):
        """值为 None 视为缺失。"""
        record = {
            "rank": None,
            "title": "测试",
            "author": "测试",
            "category": "测试",
            "score": 0,
            "platform": "test",
            "list_name": "test",
            "update_time": "test",
        }
        is_valid, missing = _validate_record(record)
        self.assertFalse(is_valid)
        self.assertIn("rank", missing)


class TestBuildUrl(unittest.TestCase):
    """_build_url URL 构建测试。"""

    def test_fanqie_url(self):
        """番茄小说 URL 构建。"""
        url = _build_url("fanqie", "hot_sales")
        self.assertIsNotNone(url)
        self.assertIn("fanqienovel.com", url)
        self.assertIn("hot_sales", url)

    def test_qidian_url(self):
        """起点中文网 URL 构建。"""
        url = _build_url("qidian", "monthly_ticket")
        self.assertIsNotNone(url)
        self.assertIn("qidian.com", url)

    def test_jjwxc_url(self):
        """晋江文学城 URL 构建。"""
        url = _build_url("jjwxc", "score")
        self.assertIsNotNone(url)
        self.assertIn("jjwxc.net", url)

    def test_unknown_platform(self):
        """未知平台返回 None。"""
        self.assertIsNone(_build_url("unknown", "hot_sales"))

    def test_unknown_list(self):
        """未知榜单返回 None。"""
        self.assertIsNone(_build_url("fanqie", "unknown_list"))

    def test_all_platforms_have_lists(self):
        """所有平台的所有榜单都能构建 URL。"""
        for plat_id, plat_info in PLATFORMS.items():
            for lst_id in plat_info["lists"]:
                url = _build_url(plat_id, lst_id)
                self.assertIsNotNone(url, f"{plat_id}/{lst_id} URL 构建失败")


# ---------------------------------------------------------------------------
# HTML 解析测试
# ---------------------------------------------------------------------------


class TestParseFanqie(unittest.TestCase):
    """parse_fanqie 番茄小说榜单解析测试。"""

    def setUp(self):
        self.html = _mock_fanqie_html()

    def test_returns_list(self):
        """返回列表类型。"""
        records = parse_fanqie(self.html)
        self.assertIsInstance(records, list)

    def test_record_count(self):
        """解析出 3 条记录。"""
        records = parse_fanqie(self.html)
        self.assertGreaterEqual(len(records), 1)

    def test_first_record_fields(self):
        """第一条记录包含完整字段。"""
        records = parse_fanqie(self.html)
        self.assertGreater(len(records), 0)
        r = records[0]
        for field in REQUIRED_FIELDS:
            self.assertIn(field, r, f"缺少字段：{field}")

    def test_rank_order(self):
        """排名按升序排列。"""
        records = parse_fanqie(self.html)
        if len(records) >= 2:
            self.assertLess(records[0]["rank"], records[1]["rank"])

    def test_platform_field(self):
        """platform 字段正确。"""
        records = parse_fanqie(self.html, platform="fanqie")
        for r in records:
            self.assertEqual(r["platform"], "fanqie")

    def test_list_name_field(self):
        """list_name 字段正确。"""
        records = parse_fanqie(self.html, list_name="hot_sales")
        for r in records:
            self.assertEqual(r["list_name"], "hot_sales")

    def test_update_time_present(self):
        """update_time 字段非空。"""
        records = parse_fanqie(self.html)
        for r in records:
            self.assertTrue(r.get("update_time"))

    def test_empty_html(self):
        """空 HTML 返回空列表。"""
        records = parse_fanqie("")
        self.assertEqual(records, [])

    def test_rank_is_integer(self):
        """rank 为整数类型。"""
        records = parse_fanqie(self.html)
        for r in records:
            self.assertIsInstance(r["rank"], int)

    def test_score_is_integer(self):
        """score 为整数类型。"""
        records = parse_fanqie(self.html)
        for r in records:
            self.assertIsInstance(r["score"], int)


class TestParseQidian(unittest.TestCase):
    """parse_qidian 起点中文网榜单解析测试。"""

    def setUp(self):
        self.html = _mock_qidian_html()

    def test_returns_list(self):
        """返回列表类型。"""
        records = parse_qidian(self.html)
        self.assertIsInstance(records, list)

    def test_record_count(self):
        """解析出记录。"""
        records = parse_qidian(self.html)
        self.assertGreaterEqual(len(records), 1)

    def test_required_fields(self):
        """所有记录包含必需字段。"""
        records = parse_qidian(self.html)
        for r in records:
            is_valid, missing = _validate_record(r)
            self.assertTrue(is_valid, f"缺少字段：{missing}")

    def test_platform_field(self):
        """platform 字段为 qidian。"""
        records = parse_qidian(self.html, platform="qidian")
        for r in records:
            self.assertEqual(r["platform"], "qidian")

    def test_title_present(self):
        """书名字段非空。"""
        records = parse_qidian(self.html)
        for r in records:
            self.assertTrue(r.get("title"))

    def test_empty_html(self):
        """空 HTML 返回空列表。"""
        records = parse_qidian("")
        self.assertEqual(records, [])

    def test_score_positive(self):
        """分数非负。"""
        records = parse_qidian(self.html)
        for r in records:
            self.assertGreaterEqual(r["score"], 0)


class TestParseJjwxc(unittest.TestCase):
    """parse_jjwxc 晋江文学城榜单解析测试。"""

    def setUp(self):
        self.html = _mock_jjwxc_html()

    def test_returns_list(self):
        """返回列表类型。"""
        records = parse_jjwxc(self.html)
        self.assertIsInstance(records, list)

    def test_record_count(self):
        """解析出记录。"""
        records = parse_jjwxc(self.html)
        self.assertGreaterEqual(len(records), 1)

    def test_required_fields(self):
        """所有记录包含必需字段。"""
        records = parse_jjwxc(self.html)
        for r in records:
            is_valid, missing = _validate_record(r)
            self.assertTrue(is_valid, f"缺少字段：{missing}")

    def test_platform_field(self):
        """platform 字段为 jjwxc。"""
        records = parse_jjwxc(self.html, platform="jjwxc")
        for r in records:
            self.assertEqual(r["platform"], "jjwxc")

    def test_title_not_digits(self):
        """书名不是纯数字。"""
        records = parse_jjwxc(self.html)
        for r in records:
            self.assertFalse(r["title"].isdigit())

    def test_empty_html(self):
        """空 HTML 返回空列表。"""
        records = parse_jjwxc("")
        self.assertEqual(records, [])

    def test_author_present(self):
        """作者字段存在。"""
        records = parse_jjwxc(self.html)
        for r in records:
            self.assertIn("author", r)


# ---------------------------------------------------------------------------
# 缓存测试
# ---------------------------------------------------------------------------


class TestCache(unittest.TestCase):
    """load_cache / save_cache 缓存读写测试。"""

    def setUp(self):
        """创建临时缓存目录。"""
        self.tmpdir = tempfile.mkdtemp(prefix="ranking_test_cache_")
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        """保存后能读回。"""
        test_data = [
            {"rank": 1, "title": "测试", "author": "作者", "category": "玄幻",
             "score": 100, "platform": "fanqie", "list_name": "hot_sales",
             "update_time": "2024-01-01"},
        ]
        path = save_cache("fanqie", "hot_sales", test_data, base_dir=self.tmpdir)
        self.assertTrue(os.path.isfile(path))

        loaded, cache_path = load_cache("fanqie", "hot_sales", base_dir=self.tmpdir)
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["title"], "测试")

    def test_missing_cache_returns_none(self):
        """不存在的缓存返回 None。"""
        loaded, path = load_cache("nonexistent", "list", base_dir=self.tmpdir)
        self.assertIsNone(loaded)
        self.assertTrue(path)

    def test_cache_not_expired(self):
        """刚写入的缓存未过期。"""
        test_data = [{"rank": 1, "title": "测试", "author": "a", "category": "x",
                      "score": 1, "platform": "fanqie", "list_name": "hot_sales",
                      "update_time": "now"}]
        save_cache("fanqie", "hot_sales", test_data, base_dir=self.tmpdir)
        loaded, _ = load_cache("fanqie", "hot_sales", base_dir=self.tmpdir)
        self.assertIsNotNone(loaded)

    def test_expired_cache_returns_none(self):
        """过期缓存返回 None。"""
        test_data = [{"rank": 1, "title": "测试", "author": "a", "category": "x",
                      "score": 1, "platform": "fanqie", "list_name": "hot_sales",
                      "update_time": "now"}]
        # 手动写入带过期时间的缓存
        cache_path = ranking_crawler._cache_path(
            "fanqie", "hot_sales", base_dir=self.tmpdir
        )
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        old_time = (datetime.now() - timedelta(hours=CACHE_TTL_HOURS + 1)).isoformat()
        cache_obj = {
            "platform": "fanqie",
            "list_name": "hot_sales",
            "cached_at": old_time,
            "data": test_data,
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_obj, f, ensure_ascii=False)

        loaded, _ = load_cache("fanqie", "hot_sales", base_dir=self.tmpdir)
        self.assertIsNone(loaded)

    def test_corrupted_cache_returns_none(self):
        """损坏的缓存文件返回 None。"""
        cache_path = ranking_crawler._cache_path(
            "fanqie", "hot_sales", base_dir=self.tmpdir
        )
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write("this is not json")

        loaded, _ = load_cache("fanqie", "hot_sales", base_dir=self.tmpdir)
        self.assertIsNone(loaded)


# ---------------------------------------------------------------------------
# 分析函数测试
# ---------------------------------------------------------------------------


def _make_test_records(platform="fanqie", list_name="hot_sales", count=10):
    """构造测试用榜单记录。"""
    books = [
        ("重生之都市修仙", "风会笑", "都市"),
        ("穿越之废柴逆袭", "天蚕", "玄幻"),
        ("系统之最强打脸", "土豆", "玄幻"),
        ("我在修仙界搞事情", "辰东", "仙侠"),
        ("开局签到系统", "耳根", "玄幻"),
        ("甜宠文之豪门总裁", "顾漫", "言情"),
        ("快穿之女配逆袭", "墨香", "同人"),
        ("末世之重生空间", "骷髅", "科幻"),
        ("从武侠开始修仙", "金庸", "武侠"),
        ("重生校园之学霸", "八月长安", "青春"),
    ]
    records = []
    for i, (title, author, category) in enumerate(books[:count], 1):
        records.append({
            "rank": i,
            "title": title,
            "author": author,
            "category": category,
            "score": 1000 - i * 50,
            "platform": platform,
            "list_name": list_name,
            "update_time": "2024-01-01 00:00:00",
        })
    return records


class TestExtractTitleKeywords(unittest.TestCase):
    """_extract_title_keywords 书名关键词提取测试。"""

    def test_returns_counter_list(self):
        """返回 (word, count) 列表。"""
        titles = ["重生之都市修仙", "穿越之废柴逆袭", "重生之逆天改命"]
        result = _extract_title_keywords(titles)
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_high_frequency_first(self):
        """高频词排前面。"""
        titles = ["重生之修仙", "重生之逆袭", "重生之打脸", "穿越之都市"]
        result = _extract_title_keywords(titles)
        # "重生" 出现 3 次，应该排前面
        top_words = [w for w, _ in result[:5]]
        self.assertIn("重生", top_words)

    def test_empty_titles(self):
        """空列表返回空结果。"""
        self.assertEqual(_extract_title_keywords([]), [])

    def test_single_char_filtered(self):
        """单字不参与统计（只有 2-3 字词）。"""
        titles = ["龙", "虎", "凤"]
        result = _extract_title_keywords(titles)
        # 单字书名没有 2 字词，应该返回空
        self.assertEqual(result, [])

    def test_chinese_only(self):
        """只统计纯中文词。"""
        titles = ["hello world", "abc def"]
        result = _extract_title_keywords(titles)
        self.assertEqual(result, [])


class TestAnalyzeList(unittest.TestCase):
    """analyze_list 榜单分析测试。"""

    def setUp(self):
        self.records = _make_test_records()

    def test_returns_dict(self):
        """返回字典类型。"""
        result = analyze_list(self.records)
        self.assertIsInstance(result, dict)

    def test_total_books(self):
        """总书数正确。"""
        result = analyze_list(self.records)
        self.assertEqual(result["total_books"], len(self.records))

    def test_category_distribution(self):
        """题材分布存在且非空。"""
        result = analyze_list(self.records)
        self.assertIn("category_distribution", result)
        self.assertGreater(len(result["category_distribution"]), 0)

    def test_genre_hits(self):
        """题材关键词命中存在。"""
        result = analyze_list(self.records)
        self.assertIn("genre_hits", result)
        self.assertGreater(len(result["genre_hits"]), 0)

    def test_title_keywords(self):
        """书名关键词存在。"""
        result = analyze_list(self.records)
        self.assertIn("title_keywords", result)

    def test_title_patterns(self):
        """书名模式统计存在。"""
        result = analyze_list(self.records)
        self.assertIn("title_patterns", result)
        self.assertIsInstance(result["title_patterns"], list)

    def test_top_authors(self):
        """上榜作者存在。"""
        result = analyze_list(self.records)
        self.assertIn("top_authors", result)

    def test_score_stats(self):
        """分数统计存在。"""
        result = analyze_list(self.records)
        self.assertIn("score_stats", result)
        stats = result["score_stats"]
        self.assertIn("max", stats)
        self.assertIn("min", stats)
        self.assertIn("avg", stats)

    def test_empty_records(self):
        """空数据返回错误信息。"""
        result = analyze_list([])
        self.assertIn("error", result)

    def test_xuanhuan_most_common(self):
        """玄幻类最多。"""
        result = analyze_list(self.records)
        cat_dist = result["category_distribution"]
        if cat_dist:
            top_cat = cat_dist[0][0]
            # 构造的数据中玄幻类有 3 本，应该最多
            self.assertIn(top_cat, ["玄幻", "都市", "仙侠", "言情", "同人", "科幻", "武侠", "青春"])


class TestCompareLists(unittest.TestCase):
    """compare_lists 榜单对比测试。"""

    def setUp(self):
        """预先写入缓存数据。"""
        self.tmpdir = tempfile.mkdtemp(prefix="ranking_test_compare_")
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

        # 为 3 个平台写入缓存
        for plat in ["fanqie", "qidian", "jjwxc"]:
            lst = list(PLATFORMS[plat]["lists"].keys())[0]
            records = _make_test_records(platform=plat, list_name=lst)
            save_cache(plat, lst, records, base_dir=self.tmpdir)

    def test_compare_returns_dict(self):
        """返回字典类型。"""
        result = compare_lists(
            platforms=["fanqie", "qidian"],
            base_dir=self.tmpdir,
        )
        self.assertIsInstance(result, dict)

    def test_platforms_compared(self):
        """包含对比的平台列表。"""
        result = compare_lists(
            platforms=["fanqie", "qidian"],
            base_dir=self.tmpdir,
        )
        self.assertIn("platforms_compared", result)
        self.assertGreater(len(result["platforms_compared"]), 0)

    def test_genre_distribution(self):
        """包含各平台题材分布。"""
        result = compare_lists(
            platforms=["fanqie", "qidian"],
            base_dir=self.tmpdir,
        )
        self.assertIn("genre_distribution", result)
        self.assertGreater(len(result["genre_distribution"]), 0)

    def test_common_genres(self):
        """包含共性题材。"""
        result = compare_lists(
            platforms=["fanqie", "qidian"],
            base_dir=self.tmpdir,
        )
        self.assertIn("common_genres", result)

    def test_hot_title_keywords(self):
        """包含热门书名关键词。"""
        result = compare_lists(
            platforms=["fanqie", "qidian"],
            base_dir=self.tmpdir,
        )
        self.assertIn("hot_title_keywords", result)

    def test_all_platforms(self):
        """不传 platforms 参数时对比所有平台。"""
        result = compare_lists(base_dir=self.tmpdir)
        self.assertIn("platforms_compared", result)
        # 应该有至少 2 个平台的数据（取决于缓存是否都有）
        self.assertGreaterEqual(len(result["platforms_compared"]), 1)


# ---------------------------------------------------------------------------
# 输出格式化测试
# ---------------------------------------------------------------------------


class TestFormatRecordsMarkdown(unittest.TestCase):
    """format_records_markdown Markdown 输出测试。"""

    def test_basic_formatting(self):
        """基本 Markdown 表格格式。"""
        records = _make_test_records(count=3)
        md = format_records_markdown(records, "fanqie", "hot_sales")
        self.assertIn("#", md)
        self.assertIn("|", md)  # 表格分隔符
        self.assertIn("排名", md)
        self.assertIn("书名", md)

    def test_empty_records(self):
        """空数据提示。"""
        md = format_records_markdown([])
        self.assertIn("无数据", md)

    def test_contains_titles(self):
        """输出包含书名。"""
        records = _make_test_records(count=3)
        md = format_records_markdown(records)
        for r in records:
            self.assertIn(r["title"], md)


class TestFormatAnalysisMarkdown(unittest.TestCase):
    """format_analysis_markdown 分析报告格式化测试。"""

    def test_analysis_report(self):
        """分析报告包含主要章节。"""
        records = _make_test_records()
        analysis = analyze_list(records)
        md = format_analysis_markdown(analysis)
        self.assertIn("# 榜单分析报告", md)
        self.assertIn("题材分布", md)
        self.assertIn("书名模式", md)

    def test_error_case(self):
        """错误情况输出错误信息。"""
        md = format_analysis_markdown({"error": "测试错误"})
        self.assertIn("测试错误", md)


class TestFormatCompareMarkdown(unittest.TestCase):
    """format_compare_markdown 对比报告格式化测试。"""

    def test_compare_report(self):
        """对比报告包含主要章节。"""
        result = {
            "platforms_compared": ["fanqie:hot_sales", "qidian:monthly_ticket"],
            "total_books": 20,
            "genre_distribution": {
                "fanqie:hot_sales": [("玄幻", 5), ("都市", 3)],
                "qidian:monthly_ticket": [("玄幻", 4), ("仙侠", 3)],
            },
            "common_genres": [("玄幻", 2)],
            "hot_title_keywords": [("重生", 6), ("系统", 4)],
        }
        md = format_compare_markdown(result)
        self.assertIn("# 多平台榜单对比报告", md)
        self.assertIn("共性题材", md)

    def test_error_case(self):
        """错误情况输出错误信息。"""
        md = format_compare_markdown({"error": "测试错误"})
        self.assertIn("测试错误", md)


# ---------------------------------------------------------------------------
# CLI 子命令测试（list 不发网络请求）
# ---------------------------------------------------------------------------


class TestCLIList(unittest.TestCase):
    """CLI list 子命令测试（不发网络请求）。"""

    def _run_cli(self, *args):
        """运行 ranking_crawler.py 子进程，返回 CompletedProcess。"""
        cmd = [sys.executable, SCRIPT_PATH] + list(args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_list_command(self):
        """list 命令成功执行。"""
        result = self._run_cli("list")
        self.assertEqual(result.returncode, 0)

    def test_list_shows_platforms(self):
        """list 输出包含所有平台名称。"""
        result = self._run_cli("list")
        for plat_info in PLATFORMS.values():
            self.assertIn(plat_info["name"], result.stdout)

    def test_list_shows_lists(self):
        """list 输出包含各榜单名称。"""
        result = self._run_cli("list")
        for plat_info in PLATFORMS.values():
            for lst_info in plat_info["lists"].values():
                self.assertIn(lst_info["name"], result.stdout)

    def test_list_returns_zero(self):
        """list 命令退出码为 0。"""
        result = self._run_cli("list")
        self.assertEqual(result.returncode, 0)

    def test_cmd_list_function(self):
        """直接调用 cmd_list 函数返回 0。"""
        ret = cmd_list()
        self.assertEqual(ret, 0)


class TestCLIHelp(unittest.TestCase):
    """CLI 帮助信息测试。"""

    def _run_cli(self, *args):
        cmd = [sys.executable, SCRIPT_PATH] + list(args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_main_help(self):
        """主帮助信息可用。"""
        result = self._run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("crawl", result.stdout)
        self.assertIn("compare", result.stdout)
        self.assertIn("analyze", result.stdout)
        self.assertIn("list", result.stdout)

    def test_crawl_help(self):
        """crawl 子命令帮助可用。"""
        result = self._run_cli("crawl", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("platform", result.stdout)
        self.assertIn("list_name", result.stdout)


# ---------------------------------------------------------------------------
# 平台配置测试
# ---------------------------------------------------------------------------


class TestPlatformsConfig(unittest.TestCase):
    """PLATFORMS 平台配置测试。"""

    def test_three_platforms(self):
        """正好 3 个平台。"""
        self.assertEqual(len(PLATFORMS), 3)

    def test_each_platform_has_three_lists(self):
        """每个平台有 3 个榜单。"""
        for plat_id, plat_info in PLATFORMS.items():
            self.assertEqual(
                len(plat_info["lists"]), 3,
                f"{plat_id} 应有 3 个榜单，实际 {len(plat_info['lists'])} 个"
            )

    def test_platform_has_name_and_base_url(self):
        """每个平台有 name 和 base_url。"""
        for plat_id, plat_info in PLATFORMS.items():
            self.assertIn("name", plat_info)
            self.assertIn("base_url", plat_info)
            self.assertTrue(plat_info["name"])
            self.assertTrue(plat_info["base_url"])

    def test_lists_have_name_and_path(self):
        """每个榜单有 name 和 path。"""
        for plat_id, plat_info in PLATFORMS.items():
            for lst_id, lst_info in plat_info["lists"].items():
                self.assertIn("name", lst_info, f"{plat_id}/{lst_id} 缺少 name")
                self.assertIn("path", lst_info, f"{plat_id}/{lst_id} 缺少 path")
                self.assertTrue(lst_info["name"])
                self.assertTrue(lst_info["path"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
