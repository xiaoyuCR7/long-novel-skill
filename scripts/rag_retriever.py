#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rag_retriever.py — RAG剧情检索器 v1.0.1（v1.0.1: BM25Index 委托 common.py）。"""

import argparse
import glob
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter

# --- 从 common.py 导入共享 BM25 实现 ---
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
try:
    from common import (BM25Index, tokenize_chinese, load_char_names,
                        extract_summary_fields, recency_boost, prune_cache)
    _USE_COMMON = True
except ImportError:
    _USE_COMMON = False
    def load_char_names(b): return []
    def extract_summary_fields(body, char_names=None):
        return {"summary": "", "entities": [], "emotion_tags": []}
    def recency_boost(c, cur, decay=0.02): return 1.0
    def prune_cache(cache, **kw): return cache

RAG_INDEX_FILE = "rag_index.json"
RAG_CACHE_FILE = "rag_cache.json"
NEXT_PLOT_CTX_FILE = "next_plot_context.md"
BM25_K1 = 1.5
BM25_B = 0.75
INDEX_VERSION = "1.0.1"

LIGHT_SCENE_KEYWORDS = [
    "赶路", "过场", "日常", "过渡", "转场", "路途", "行路",
    "出发", "启程", "到达", "抵达", "离开", "告别", "休息", "夜宿",
]

ENTRY_RE = re.compile(r"^#{2,3}\s*第\s*(\d+)\s*章[：:\s]*(.*)$", re.M)
ENTITY_FIELD_RE = re.compile(r"关键实体[：:](.*?)(?:\n\s*-\s|\n###|\Z)", re.S)
EMOTION_FIELD_RE = re.compile(r"情绪基调[：:](.*?)(?:\n|$)", re.S)
SUMMARY_FIELD_RE = re.compile(r"章节摘要[：:](.*?)(?:\n\s*-\s|\n关键|\n情绪|\n###|\Z)", re.S)
_STOP_CHARS = set("的了吗呢吧啊呀哦嗯么着过在有了是不也就都还要这个那个一个什么怎么哪里为什么")


def _reconfigure_streams():
    for stream in (sys.stdout, sys.stderr):
        try: stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError): pass


def _tokenize_chinese(text, extra_terms=None):
    if _USE_COMMON:
        return tokenize_chinese(text, extra_terms)
    chars = [c for c in text if c.strip() and c not in _STOP_CHARS]
    unigrams = chars
    bigrams = [text[i:i + 2] for i in range(len(text) - 1)
               if text[i] not in _STOP_CHARS and text[i + 1] not in _STOP_CHARS]
    return unigrams + bigrams


def _file_hash(path, block_size=8192):
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(block_size)
                if not chunk: break
                h.update(chunk)
    except OSError: return ""
    return h.hexdigest()


def _parse_entities(field_text):
    text = re.sub(r"[（(][^）)]*[）)]", " ", field_text)
    parts = re.split(r"[，,、/；;\n]+", text)
    out = []
    for p in parts:
        p = p.strip().strip("。 ")
        if p and len(p) <= 20: out.append(p)
    return out


def _extract_emotion_tags(text):
    m = EMOTION_FIELD_RE.search(text)
    if not m: return []
    raw = m.group(1).strip()
    tags = re.split(r"[，,、/；;]+", raw)
    return [t.strip() for t in tags if t.strip() and len(t.strip()) <= 10]


def _extract_summary_text(text):
    m = SUMMARY_FIELD_RE.search(text)
    if m: return m.group(1).strip().strip("。 ")
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("关键") and not line.startswith("情绪"):
            return line[:200]
    return ""


def _load_chapter_meta(book_root, chapter_num):
    meta_path = os.path.join(book_root, "追踪", "chapter_meta", f"第{chapter_num}章.meta.json")
    if not os.path.isfile(meta_path): return None
    try:
        with open(meta_path, "r", encoding="utf-8-sig") as f: return json.load(f)
    except (OSError, ValueError): return None


def _get_prose_path(book_root, chapter_num):
    prose_dir = os.path.join(book_root, "正文")
    pattern = os.path.join(prose_dir, f"*{chapter_num:03d}*.md")
    matches = glob.glob(pattern)
    if matches: return matches[0]
    pattern2 = os.path.join(prose_dir, f"*第*{chapter_num}*章*.md")
    matches2 = glob.glob(pattern2)
    return matches2[0] if matches2 else None


def _read_snippet(file_path, query_tokens, max_len=300):
    if not os.path.isfile(file_path): return ""
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f: content = f.read()
    except (OSError, ValueError): return ""
    paragraphs = re.split(r"\n\s*\n", content)
    query_set = set(query_tokens)
    best_score, best_para = 0, ""
    for para in paragraphs:
        para_tokens = set(_tokenize_chinese(para))
        overlap = len(para_tokens & query_set)
        if overlap > best_score and len(para.strip()) > 10:
            best_score = overlap; best_para = para.strip()
    if best_para: return best_para[:max_len] + ("..." if len(best_para) > max_len else "")
    return content[:200].strip() + "..."


# --- BM25Index: 优先 common.py，回退本地 ---
if not _USE_COMMON:
    class BM25Index:
        def __init__(self, documents, k1=BM25_K1, b=BM25_B):
            self.k1 = k1; self.b = b
            self.doc_ids = [d[0] for d in documents]
            self.doc_tokens = {}; self.doc_len = {}; self.df = Counter(); self.avgdl = 0.0
            self._build(documents)
        def _build(self, documents):
            total_len = 0
            for doc_id, text in documents:
                tokens = _tokenize_chinese(text)
                self.doc_tokens[doc_id] = tokens
                self.doc_len[doc_id] = len(tokens)
                total_len += len(tokens)
                for term in set(tokens): self.df[term] += 1
            n = len(documents)
            self.avgdl = total_len / n if n > 0 else 0.0
        def idf(self, term):
            n = len(self.doc_ids); df = self.df.get(term, 0)
            return math.log((n - df + 0.5) / (df + 0.5) + 1)
        def score(self, query_tokens, doc_id):
            if doc_id not in self.doc_tokens: return 0.0
            doc_tokens = self.doc_tokens[doc_id]; dl = self.doc_len[doc_id]
            tf_map = Counter(doc_tokens); score = 0.0
            for qt in query_tokens:
                if qt not in tf_map: continue
                tf = tf_map[qt]; idf_val = self.idf(qt)
                score += idf_val * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            return score
        def search(self, query_tokens, top_k=8):
            results = []
            for doc_id in self.doc_ids:
                s = self.score(query_tokens, doc_id)
                if s > 0:
                    doc_tf = Counter(self.doc_tokens[doc_id])
                    matched = [(t, doc_tf[t]) for t in query_tokens if t in doc_tf]
                    matched.sort(key=lambda x: -x[1])
                    results.append((doc_id, s, matched[:10]))
            results.sort(key=lambda x: -x[1])
            return results[:top_k]


def _make_bm25(documents, extra_terms=None):
    if _USE_COMMON: return BM25Index(documents, k1=BM25_K1, b=BM25_B, extra_terms=extra_terms)
    return BM25Index(documents)


def _tfidf_rerank(query_tokens, candidates_text, top_k=4):
    if not candidates_text: return []
    n = len(candidates_text); df = Counter(); doc_tokens_map = {}
    for doc_id, text in candidates_text:
        tokens = _tokenize_chinese(text)
        doc_tokens_map[doc_id] = tokens
        for term in set(tokens): df[term] += 1
    results = []
    for doc_id, text in candidates_text:
        tokens = doc_tokens_map[doc_id]; tf_map = Counter(tokens); dl = len(tokens)
        avgdl = sum(len(t) for t in doc_tokens_map.values()) / max(n, 1)
        score = 0.0; matched = []
        for qt in query_tokens:
            if qt not in tf_map: continue
            tf = tf_map[qt]
            idf_val = math.log((n - df.get(qt, 0) + 0.5) / (df.get(qt, 0) + 0.5) + 1)
            norm_tf = tf / (tf + 1.5 * (0.25 + 0.75 * dl / max(avgdl, 1)))
            s = idf_val * norm_tf; score += s
            matched.append((qt, tf, round(s, 4)))
        if score > 0:
            matched.sort(key=lambda x: -x[2])
            results.append((doc_id, score, matched[:8]))
    results.sort(key=lambda x: -x[1])
    return results[:top_k]


def _rag_index_path(book_root):
    return os.path.join(book_root, "追踪", RAG_INDEX_FILE)

def _rag_cache_path(book_root):
    return os.path.join(book_root, "追踪", RAG_CACHE_FILE)

def _next_plot_context_path(book_root):
    return os.path.join(book_root, "追踪", NEXT_PLOT_CTX_FILE)


def load_rag_index(book_root):
    path = _rag_index_path(book_root)
    if not os.path.isfile(path): return None, path
    try:
        with open(path, "r", encoding="utf-8-sig") as f: return json.load(f), path
    except (OSError, ValueError): return None, path


def save_rag_index(book_root, index_data):
    path = _rag_index_path(book_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)


def _migrate_legacy_index(book_root, old_index):
    """迁移 legacy retrieval_index.json（v6.x 旧检索脚本产物）→ rag_index.json。

    仅当 rag_index.json 不存在且 legacy 存在时执行一次；失败静默（fail-open）。
    """
    if old_index is not None:
        return
    legacy = os.path.join(book_root, "追踪", "retrieval_index.json")
    if not os.path.isfile(legacy):
        return
    try:
        with open(legacy, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict) and "chapters" in data:
            data["version"] = INDEX_VERSION
            save_rag_index(book_root, data)
            print(f"[迁移] legacy retrieval_index.json → rag_index.json（{len(data['chapters'])} 章）")
    except (OSError, ValueError):
        pass


def load_rag_cache(book_root):
    path = _rag_cache_path(book_root)
    if not os.path.isfile(path): return {}, path
    try:
        with open(path, "r", encoding="utf-8-sig") as f: return json.load(f), path
    except (OSError, ValueError): return {}, path


def save_rag_cache(book_root, cache):
    path = _rag_cache_path(book_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _cache_key(query, top_k, light=False, index_hash="", current_chapter=None):
    raw = json.dumps({"q": query, "top": top_k, "light": light, "ih": index_hash,
                      "cur": current_chapter}, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _index_hash(index_data):
    if not index_data: return ""
    raw = f"{index_data.get('last_updated', '')}|{index_data.get('total_chapters', 0)}|{index_data.get('indexed_chapters', 0)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def is_light_scene(query):
    return any(kw in query for kw in LIGHT_SCENE_KEYWORDS)


def _scan_chapters(book_root):
    prose_dir = os.path.join(book_root, "正文")
    if not os.path.isdir(prose_dir): return []
    chapters = []
    for path in glob.glob(os.path.join(prose_dir, "*.md")):
        basename = os.path.basename(path)
        m = re.search(r"第\s*(\d+)\s*章", basename)
        if m: chapters.append((int(m.group(1)), basename, path))
    chapters.sort(key=lambda x: x[0])
    return chapters


def _scan_summary_entries(book_root):
    summary_path = os.path.join(book_root, "追踪", "章节摘要.md")
    if not os.path.isfile(summary_path): return {}
    with open(summary_path, "r", encoding="utf-8-sig") as f: text = f.read()
    entries = list(ENTRY_RE.finditer(text))
    result = {}
    for idx, m in enumerate(entries):
        chap = int(m.group(1)); start = m.start()
        end = entries[idx + 1].start() if idx + 1 < len(entries) else len(text)
        result[chap] = text[start:end]
    return result


def cmd_build(book_root):
    chapters = _scan_chapters(book_root)
    if not chapters: print("错误：正文目录下未找到章节文件", file=sys.stderr); return 2
    summary_entries = _scan_summary_entries(book_root)
    old_index, _ = load_rag_index(book_root)
    old_chapters = {}
    if old_index and "chapters" in old_index:
        for ch in old_index["chapters"]: old_chapters[ch["chapter"]] = ch
    # legacy retrieval_index.json 迁移（v6.x 旧检索脚本产物）
    _migrate_legacy_index(book_root, old_index)
    char_names = load_char_names(book_root)
    updated, skipped = 0, 0
    new_entries = []
    for chap, basename, file_path in chapters:
        content_hash = _file_hash(file_path)
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f: content = f.read()
            char_count = len(re.sub(r"\s+", "", content))
        except (OSError, ValueError): char_count = 0
        entry_body = summary_entries.get(chap, "")
        fields = extract_summary_fields(entry_body, char_names)
        summary_text = fields["summary"]
        entities = fields["entities"]
        emotion_tags = fields["emotion_tags"]
        title_match = re.search(r"第\s*\d+\s*章[：:\s]*(.*)\.md$", basename)
        title = title_match.group(1).strip() if title_match else ""
        if not title and entry_body:
            tm2 = ENTRY_RE.search(entry_body)
            if tm2 and tm2.group(2): title = tm2.group(2).strip()
        if not title: title = f"第{chap}章"
        old_entry = old_chapters.get(chap)
        if old_entry and old_entry.get("content_hash") == content_hash:
            new_entries.append(old_entry); skipped += 1; continue
        entry = {"chapter": chap, "title": title, "file": os.path.relpath(file_path, book_root).replace("\\", "/"),
                  "summary": summary_text, "entities": entities, "char_count": char_count,
                  "emotion_tags": emotion_tags, "content_hash": content_hash,
                  "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        new_entries.append(entry); updated += 1
    new_entries.sort(key=lambda x: x["chapter"])
    index_data = {"version": INDEX_VERSION, "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "total_chapters": len(chapters), "indexed_chapters": len(new_entries),
                  "chapters": new_entries}
    save_rag_index(book_root, index_data)
    print(f"RAG 索引已构建：{_rag_index_path(book_root)}")
    print(f"  总章节：{len(chapters)}  已索引：{len(new_entries)}")
    print(f"  新增/更新：{updated}  跳过（未变）：{skipped}")
    return 0


def _relevance_label(score):
    if score >= 0.6: return "high"
    if score >= 0.3: return "medium"
    return "low"


def _normalize_score(score, max_score):
    if max_score <= 0: return 0.0
    return min(score / max_score, 1.0)


def _weighted_doc(ch):
    """构造字段加权文档：title×3、entities×2、emotion_tags×1、summary×1。

    通过重复 token 实现加权（BM25 对词频敏感），零新依赖。
    """
    parts = []
    title = (ch.get("title") or "").strip()
    if title:
        parts.append(" ".join([title] * 3))
    ents = ch.get("entities") or []
    if ents:
        parts.append(" ".join([" ".join(ents)] * 2))
    emo = ch.get("emotion_tags") or []
    if emo:
        parts.append(" ".join(emo))
    parts.append(ch.get("summary") or "")
    return " ".join(parts)


def rag_query(book_root, query, top_k=5, light=False, current_chapter=None):
    index_data, _ = load_rag_index(book_root)
    if not index_data or "chapters" not in index_data:
        return {"query": query, "triggered": False, "cache_hit": False, "results": [],
                "context_suggestion": None, "error": "RAG 索引不存在，请先运行 build"}
    chapters = index_data["chapters"]
    if not chapters:
        return {"query": query, "triggered": False, "cache_hit": False, "results": [],
                "context_suggestion": None, "error": "索引为空"}
    extra_terms = sorted({e for ch in chapters for e in (ch.get("entities") or []) if len(e) >= 2})
    query_tokens = _tokenize_chinese(query, extra_terms)
    if light or is_light_scene(query):
        results = []; query_set = set(query_tokens)
        for ch in chapters:
            score = 0.0; matched = []
            for ent in ch.get("entities", []):
                ent_tokens = set(_tokenize_chinese(ent))
                overlap = len(query_set & ent_tokens)
                if overlap > 0: score += overlap * 0.3; matched.append(ent)
            if score > 0:
                results.append({"chapter": ch["chapter"], "title": ch["title"],
                                "score": round(min(score, 1.0), 4), "matched_keywords": matched[:5],
                                "snippet": ch.get("summary", "")[:200],
                                "relevance": _relevance_label(score)})
        results.sort(key=lambda x: -x["score"]); results = results[:top_k]
        return {"query": query, "triggered": True, "cache_hit": False, "light_mode": True,
                "results": results, "context_suggestion": None}
    docs = []
    for ch in chapters:
        docs.append((ch["chapter"], _weighted_doc(ch)))
    bm25 = _make_bm25(docs, extra_terms)
    coarse = bm25.search(query_tokens, top_k=8)
    if not coarse:
        return {"query": query, "triggered": True, "cache_hit": False, "results": [], "context_suggestion": None}
    chapter_map = {ch["chapter"]: ch for ch in chapters}
    candidate_texts = []
    for chap, _, _ in coarse:
        ch = chapter_map.get(chap)
        if ch:
            rich_text = f"{ch.get('title', '')} {ch.get('summary', '')} {' '.join(ch.get('entities', []))} {' '.join(ch.get('emotion_tags', []))}"
            candidate_texts.append((chap, rich_text))
    reranked = _tfidf_rerank(query_tokens, candidate_texts, top_k=top_k)
    bm25_scores = {chap: score for chap, score, _ in coarse}
    max_combined = 0.0; raw_results = []
    for chap, tfidf_score, matched in reranked:
        bm25_score = bm25_scores.get(chap, 0)
        combined = (bm25_score * 0.6 + tfidf_score * 0.4) * recency_boost(chap, current_chapter)
        ch = chapter_map.get(chap)
        if not ch: continue
        matched_keywords = []
        for token, _, _ in matched:
            if token in query and token not in matched_keywords: matched_keywords.append(token)
        for ent in ch.get("entities", []):
            if any(t in ent or ent in t for t in query_tokens if len(t) >= 2):
                if ent not in matched_keywords and len(matched_keywords) < 6:
                    matched_keywords.append(ent)
        prose_path = _get_prose_path(book_root, chap)
        snippet = ""
        if prose_path:
            full_path = os.path.join(book_root, prose_path.replace("/", os.sep))
            snippet = _read_snippet(full_path, query_tokens, max_len=300)
        if not snippet: snippet = ch.get("summary", "")[:200]
        raw_results.append({"chapter": chap, "title": ch["title"], "raw_score": combined,
                            "matched_keywords": matched_keywords[:5], "snippet": snippet})
        if combined > max_combined: max_combined = combined
    for r in raw_results:
        r["score"] = round(_normalize_score(r["raw_score"], max_combined), 4)
        r["relevance"] = _relevance_label(r["score"]); del r["raw_score"]
    raw_results.sort(key=lambda x: -x["score"])
    results = raw_results[:top_k]
    context_suggestion = _generate_context_suggestion(book_root, query, results)
    return {"query": query, "triggered": True, "cache_hit": False, "results": results,
            "context_suggestion": context_suggestion}


def _generate_context_suggestion(book_root, query, results):
    if not results: return None
    top_chapters = [r["chapter"] for r in results[:3]]
    ctx_path = _next_plot_context_path(book_root)
    os.makedirs(os.path.dirname(ctx_path), exist_ok=True)
    rel_map = {"high": "高", "medium": "中", "low": "低"}
    lines = ["# 写前上下文建议", "", "## 检索查询", query, "",
             f"## 推荐回读章节（Top {min(len(results), 3)}）", ""]
    for r in results[:3]:
        rel_zh = rel_map.get(r.get("relevance", "low"), "低")
        lines.append(f"### 第{r['chapter']}章：{r['title']}（相关度：{rel_zh}）")
        if r.get("matched_keywords"): lines.append(f"- 匹配关键词：{'、'.join(r['matched_keywords'])}")
        if r.get("snippet"): lines.append(f"- 相关片段：> {r['snippet'][:150]}")
        lines.append("")
    lines.append("---"); lines.append(f"*生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}*")
    with open(ctx_path, "w", encoding="utf-8") as f: f.write("\n".join(lines))
    rel_file = os.path.relpath(ctx_path, book_root).replace("\\", "/")
    return {"file": rel_file, "top_chapters": top_chapters,
            "reason": f"与「{query}」最相关的{min(len(results), 3)}章"}


def cmd_query(book_root, args):
    if not args.query: print("错误：query 模式需要查询文本", file=sys.stderr); return 2
    query = args.query
    cache, _ = load_rag_cache(book_root)
    cache = prune_cache(cache)
    index_data, _ = load_rag_index(book_root)
    ih = _index_hash(index_data)
    cur = getattr(args, "current_chapter", None)
    key = _cache_key(query, args.top, args.light, ih, cur)
    if key in cache:
        cached = cache[key]
        print(f"（命中查询缓存，查询时间：{cached.get('time', '?')}）")
        result = cached["result"]; result["cache_hit"] = True
    else:
        result = rag_query(book_root, query, args.top, args.light, cur)
        if result.get("error"): print(f"错误：{result['error']}", file=sys.stderr); return 2
        cache[key] = {"query": query, "top": args.top, "light": args.light,
                       "index_hash": ih, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "result": result}
        save_rag_cache(book_root, prune_cache(cache))
    if not result.get("triggered", False): print("检索未触发"); return 1
    light_tag = " [轻场景·快速匹配]" if result.get("light_mode") else ""
    print(f"RAG 检索结果（查询：{repr(query)}）{light_tag}")
    print(f"{'章节':<12} {'相关度':<10} {'匹配关键词':<30} 相关片段"); print("-" * 90)
    results = result.get("results", [])
    if not results: print("未找到相关章节"); return 1
    rel_map = {"high": "高", "medium": "中", "low": "低"}
    for r in results:
        rel_zh = rel_map.get(r.get("relevance", "low"), "低")
        kw_str = "、".join(r.get("matched_keywords", [])[:4]) or "-"
        snippet = r.get("snippet", "")[:40] or "-"
        print(f"第{r['chapter']}章：{r['title']:<8} {rel_zh}({r['score']:.4f})  {kw_str:<30} {snippet}")
    ctx = result.get("context_suggestion")
    if ctx:
        print(f"\n写前上下文建议已写入：{ctx['file']}")
        print(f"  推荐回读章节：{', '.join(f'第{c}章' for c in ctx['top_chapters'])}")
        print(f"  {ctx['reason']}")
    return 0


def cmd_status(book_root):
    index_data, idx_path = load_rag_index(book_root)
    cache_data, cache_path = load_rag_cache(book_root)
    print("=" * 50); print("RAG 检索器状态"); print("=" * 50)
    if not index_data:
        print(f"索引文件：{idx_path}"); print("状态：未构建（请先运行 build）")
        print(f"缓存文件：{cache_path}"); print(f"缓存条目：{len(cache_data)}"); return 0
    chapters = index_data.get("chapters", [])
    total = index_data.get("total_chapters", 0); indexed = index_data.get("indexed_chapters", 0)
    coverage = (indexed / total * 100) if total > 0 else 0
    print(f"索引文件：{idx_path}"); print(f"索引版本：{index_data.get('version', '未知')}")
    print(f"最后更新：{index_data.get('last_updated', '未知')}")
    print(f"总章节数：{total}"); print(f"已索引章：{indexed}"); print(f"覆盖率：  {coverage:.1f}%")
    all_emotions = Counter(); total_chars = 0
    for ch in chapters:
        total_chars += ch.get("char_count", 0)
        for tag in ch.get("emotion_tags", []): all_emotions[tag] += 1
    print(f"总字数：  {total_chars:,}")
    if all_emotions: print(f"高频情绪：{'、'.join(f'{e[0]}({e[1]})' for e in all_emotions.most_common(5))}")
    print("-" * 50); print(f"缓存文件：{cache_path}"); print(f"缓存条目：{len(cache_data)}")
    return 0


def main():
    _reconfigure_streams()
    ap = argparse.ArgumentParser(description="RAG 剧情检索器 v1.0.1")
    ap.add_argument("mode", choices=["build", "query", "status"])
    ap.add_argument("book_root", help="书籍工程目录")
    ap.add_argument("query", nargs="?", default=None)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--light", action="store_true")
    ap.add_argument("--current-chapter", type=int, default=None, help="当前章节号（用于 recency 加权）")
    args = ap.parse_args()
    book_root = os.path.abspath(args.book_root)
    if args.mode == "build": return cmd_build(book_root)
    elif args.mode == "query": return cmd_query(book_root, args)
    elif args.mode == "status": return cmd_status(book_root)


if __name__ == "__main__":
    sys.exit(main())
