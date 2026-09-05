#!/usr/bin/env python3
"""轻量知识图谱：节点+边+版本，支撑百万字级联影响分析。

职责：
1. 从 entity_index.json + 章节摘要 构建节点（角色/事件/地点/物品/势力）
2. 从已登记实体和关系描述提取带来源的候选，必须语义复核，不能自动确认正史
3. 改纲时级联标记受影响节点（cascade_pending）
4. 导出 Mermaid 可视化（可选）
5. 版本管理（每次更新写入时间戳，旧版保留备份）

数据落在 `追踪/story_graph.json`。
纯标准库，无第三方依赖。
"""

import argparse
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import (atomic_write_json, canonical_read_lock, extract_summary_fields,
                    find_chapter_file, load_char_names)


# =========================================================
# 常量
# =========================================================

GRAPH_FILE = "story_graph.json"
ENTITY_INDEX_FILE = "entity_index.json"
CHAPTER_SUMMARY_FILE = "章节摘要.md"
CHARACTER_STATE_FILE = "角色状态.md"
VERSION = "1.1.0"

# 节点类型
NODE_TYPES = {"character", "event", "location", "item", "faction", "secret", "rule"}

# 边类型（关系）
EDGE_TYPES = {
    "owns": "拥有",
    "kills": "杀死",
    "betrays": "背叛",
    "allies": "结盟",
    "loves": "爱慕",
    "hates": "仇恨",
    "mentors": "师徒",
    "rivals": "竞争",
    "belongs_to": "属于",
    "located_at": "位于",
    "reveals": "揭露",
    "causes": "导致",
    "participates_in": "参与",
    "appears_in": "出现于",
}

# Only these edges describe document structure rather than a story assertion.
STRUCTURAL_EDGE_TYPES = {"appears_in"}
EXTRACTOR = "story_graph_candidates_v1"

# Match text *between known entity mentions*. Do not guess new names or infer
# ownership/alliance/rivalry from giving, accompanying, protecting or defeating.
# (between, after target, relation, allowed source types, allowed target types)
RELATION_PATTERNS = [
    (r"杀(?:死|掉|害)?", "", "kills", {"character"}, {"character"}),
    (r"背叛", "", "betrays", {"character", "faction"}, {"character", "faction"}),
    (r"(?:与|和)", r"(?:结盟|联手|联合|合作)", "allies", {"character", "faction"}, {"character", "faction"}),
    (r"爱(?:上|慕)?", "", "loves", {"character"}, {"character"}),
    (r"仇恨", "", "hates", {"character", "faction"}, {"character", "faction"}),
    (r"(?:拜|认)", r"(?:为师|做师傅)", "mentors", {"character"}, {"character"}),
    (r"收", r"为徒", "mentors", {"character"}, {"character"}),
    (r"(?:与|和)", r"(?:竞争|较量|比试|对战)", "rivals", {"character", "faction"}, {"character", "faction"}),
    (r"揭露", "", "reveals", {"character", "faction"}, {"secret", "event"}),
    (r"导致", "", "causes", {"event", "rule"}, {"event"}),
    (r"(?:拥有|持有)", "", "owns", {"character", "faction"}, {"item"}),
    (r"(?:前往|去往|赶到|奔赴|来到|抵达|进入|到达|(?:出现|现身)(?:在|于))",
     "", "located_at", {"character"}, {"location"}),
]
_MODIFIERS = r"(?:(?:并没有|并未|没有|未曾|并非|从未|不曾|是否|可能|打算|准备|试图|已经|曾经|将要|不会|不能|不|没|未|已|曾|将|想|要|会|能)\s*)*"


# =========================================================
# 工具函数
# =========================================================

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def load_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data: Any) -> bool:
    return atomic_write_json(path, data)


def backup_graph(path: Path) -> Optional[Path]:
    """备份当前图谱，返回备份路径。"""
    if not path.exists():
        return None
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.stem}_{ts}.bak.json")
    try:
        content = path.read_bytes()
        backup.write_bytes(content)
        return backup
    except OSError:
        return None


def _text_hash(text: str) -> str:
    """Hash decoded UTF-8 text, with Python's universal newline normalization."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _known_mentions(text: str, names, start: int = 0, end: Optional[int] = None) -> list:
    """Longest known names win; aliases must be registered as entities explicitly."""
    names = sorted({n for n in names if n}, key=lambda n: (-len(n), n))
    if not names:
        return []
    pattern = "|".join(re.escape(name) for name in names)
    mentions = []
    for match in re.compile(pattern).finditer(text, start, len(text) if end is None else end):
        # English names inside words are not entity mentions. Chinese has no
        # equivalent word boundary; candidate endpoints are checked separately.
        start, end = match.span()
        if match[0][0].isascii() and start and re.match(r"[A-Za-z0-9_]", text[start - 1]):
            continue
        if match[0][-1].isascii() and end < len(text) and re.match(r"[A-Za-z0-9_]", text[end]):
            continue
        mentions.append(match)
    return mentions


def _endpoint_boundary(text: str, start: int, end: int) -> bool:
    """Conservatively reject unknown names extending a known Chinese name.

    Common grammatical prefixes/suffixes are allowed; this is deliberately not
    segmentation or a claim of full Chinese syntax/alias resolution.
    """
    if start and re.match(r"[\u3400-\u9fff]", text[start - 1]):
        if not re.search(r"(?:如果|假如|要是|倘若|假设|一旦|除非|听说|据说|传闻|声称|谎称|认为|以为|原来|于是|然后|其实|但|若|是|让|由|说|问|的)$", text[:start]):
            return False
    if end < len(text) and re.match(r"[\u3400-\u9fff]", text[end]):
        if not re.match(r"[的了后时并又却便就仍而也才在与和这那]", text[end:]):
            return False
    return True


def _quote_ranges(text: str) -> list:
    pairs = {"“": "”", "‘": "’", "「": "」", "『": "』", '"': '"'}
    stack, ranges = [], []
    for index, char in enumerate(text):
        if stack and char == stack[-1][1]:
            start, _ = stack.pop()
            ranges.append((start, index + 1))
        elif char in pairs:
            stack.append((index, pairs[char]))
    ranges.extend((start, len(text)) for start, _ in stack)
    return ranges


def _relation_candidates(text: str, nodes: list, chapter: int,
                         source_path: str, source_kind: str,
                         start: int = 0, end: Optional[int] = None,
                         source_hash: Optional[str] = None) -> list:
    """Return typed, unconfirmed candidates with exact source spans.

    Spans are zero-based, end-exclusive offsets in the decoded source file.
    The full sentence is kept for semantic review, including negation/quotes.
    """
    end = len(text) if end is None else end
    node_map = {node["label"]: node for node in nodes}
    mentions = _known_mentions(text, node_map, start, end)
    quotes = [(a + start, b + start) for a, b in _quote_ranges(text[start:end])]
    source_hash = source_hash or _text_hash(text)
    candidates = []
    for source, target in zip(mentions, mentions[1:]):
        if source[0] == target[0]:
            continue
        gap = text[source.end():target.start()]
        if len(gap) > 40 or re.search(r"[。！？!?\n，,；;：:]", gap):
            continue
        for between, after, edge_type, source_types, target_types in RELATION_PATTERNS:
            if node_map[source[0]]["type"] not in source_types or node_map[target[0]]["type"] not in target_types:
                continue
            if not re.fullmatch(r"\s*" + _MODIFIERS + between + r"(?:了|过)?\s*", gap):
                continue
            suffix = re.match(r"\s*" + _MODIFIERS + after, text[target.end():end]) if after else None
            if after and not suffix:
                continue
            match_end = target.end() + (suffix.end() if suffix else 0)
            if not _endpoint_boundary(text, source.start(), match_end):
                continue
            # Bound review context by sentence, not by the relation match.
            boundaries = list(re.finditer(r"[。！？!?\n]", text[start:source.start()]))
            sentence_start = start + boundaries[-1].end() if boundaries else start
            stop = re.search(r"[。！？!?\n]", text[match_end:end])
            sentence_end = match_end + stop.end() if stop else end
            context = text[sentence_start:sentence_end]
            semantic_context = context
            if source_kind == "summary":
                semantic_context = re.sub(r"^\s*-\s*(?:\*\*)?[^：:\n*]+(?:\*\*)?\s*[：:]\s*", "", context)
            flags = []
            if re.search(r"[？?]|是否|难道|吗|么[。！!]?$", semantic_context):
                flags.append("question")
            if re.search(r"如果|假如|要是|倘若|假设|一旦|除非|可能|打算|准备|试图|将要|若|想|要|将|会", semantic_context):
                flags.append("hypothetical")
            if re.search(r"不|没|未|并非", semantic_context):
                flags.append("negated")
            if any(a < source.start() < b for a, b in quotes) or re.search(r"听说|据说|传闻|声称|谎称|认为|以为", semantic_context):
                flags.append("quoted_claim")
            candidates.append({
                "source_label": source[0], "target_label": target[0],
                "type": edge_type, "label": EDGE_TYPES[edge_type], "chapter": chapter,
                "status": "unconfirmed", "semantic_review_required": True,
                "assertion_kind": flags[0] if flags else "declarative",
                "context_flags": flags,
                "evidence": {"extractor": EXTRACTOR, "source_kind": source_kind,
                             "source_path": source_path, "chapter": chapter,
                             "source_hash": source_hash, "text": context,
                             "span": [sentence_start, sentence_end],
                             "match_span": [source.start(), match_end]},
            })
            break
    return candidates


def _graph_edges(candidates: list, nodes: list) -> list:
    node_ids = {n["label"]: n["id"] for n in nodes}
    edges = []
    for candidate in candidates:
        edge = dict(candidate)
        edge["source"] = node_ids[edge.pop("source_label")]
        edge["target"] = node_ids[edge.pop("target_label")]
        edge["props"] = {}
        edges.append(edge)
    return edges


def _edge_view(edge: dict, book_root: Path, source_cache: Optional[dict] = None) -> dict:
    """Read legacy data without upgrading an assertion to canon or writing it."""
    view = dict(edge)
    if edge.get("type") in STRUCTURAL_EDGE_TYPES:
        view.setdefault("status", "structural")
        view.setdefault("semantic_review_required", False)
        return view
    view.setdefault("status", "legacy_unconfirmed")
    view.setdefault("semantic_review_required", True)
    evidence = edge.get("evidence") or {}
    if evidence.get("source_path") and evidence.get("source_hash"):
        cache = source_cache if source_cache is not None else {}
        path = evidence["source_path"]
        if path not in cache:
            source = read_text(book_root / path)
            cache[path] = _text_hash(source) if source is not None else None
        view["evidence_status"] = "current" if cache[path] == evidence["source_hash"] else "stale"
        if view["evidence_status"] == "stale":
            view["status"] = "stale"
            view["semantic_review_required"] = True
    else:
        view["evidence_status"] = "unavailable"
    return view


def _replace_source_edges(graph: dict, candidates: list, source_kind: str,
                          chapter: int) -> Tuple[int, int]:
    """Replace only our generated evidence for this source; retain legacy data.

    Deduplication includes the evidence, so separate chapters/claims survive.
    Unattributed legacy edges cannot safely be assigned to a source generator.
    """
    old = graph.get("edges", [])
    replaced, kept = [], []
    for edge in old:
        evidence = edge.get("evidence") or {}
        if (evidence.get("extractor") == EXTRACTOR and
                evidence.get("source_kind") == source_kind and evidence.get("chapter") == chapter):
            replaced.append(edge)
        else:
            kept.append(edge)
    graph["edges"] = kept + candidates
    return (sum(edge not in replaced for edge in candidates),
            sum(edge not in candidates for edge in replaced))


# =========================================================
# 节点提取
# =========================================================

def extract_character_nodes(
    book_root: Path,
) -> List[Dict[str, Any]]:
    """从角色状态文件提取角色节点。"""
    nodes = []
    char_state_path = book_root / "追踪" / CHARACTER_STATE_FILE
    text = read_text(char_state_path)
    if not text:
        return nodes

    # 解析角色状态文件的 ## 角色名 节
    sections = re.split(r"\n## ", text)
    for sec in sections[1:]:  # 跳过第一个（可能是前言）
        lines = sec.strip().split("\n", 1)
        name = lines[0].strip()
        status = lines[1].strip()[:200] if len(lines) > 1 else ""

        node_id = f"char_{name}"
        nodes.append({
            "id": node_id,
            "type": "character",
            "label": name,
            "props": {"status_snippet": status},
            "first_appear_chapter": None,
            "last_updated_chapter": None,
            "cascade_pending": False,
        })

    return nodes


def extract_entity_nodes(
    book_root: Path,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """从 entity_index.json 和章节摘要提取非角色节点和边。"""
    nodes = _entity_nodes(book_root)
    return nodes, _extract_edges_from_summaries(book_root, nodes)


def _entity_nodes(book_root: Path) -> list:
    """Load the entity registry without extracting every summary's relations."""
    nodes = []

    # 从 entity_index.json 提取实体
    entity_index = load_json(book_root / "追踪" / ENTITY_INDEX_FILE, {})
    if isinstance(entity_index, dict) and "entities" in entity_index:
        entities = entity_index.get("entities", {})
        chapter_entities = entity_index.get("chapter_entities", {})
    else:
        # entity_index.py 实际写入 flat {实体名: [章节号]}；保留 nested legacy schema。
        entities = entity_index if isinstance(entity_index, dict) else {}
        chapter_entities = {}

    if not entities:
        # 从章节摘要回退提取
        entities, chapter_entities = _extract_from_summaries(book_root)

    # 创建节点
    for entity_name, info in entities.items():
        if isinstance(info, dict):
            etype = info.get("type", "item")
            chapters = info.get("chapters", [])
        else:
            etype = "item"
            chapters = list(info) if isinstance(info, list) else []

        if etype not in NODE_TYPES:
            etype = "item"

        node_id = f"{etype}_{entity_name}"
        nodes.append({
            "id": node_id,
            "type": etype,
            "label": entity_name,
            "props": {},
            "first_appear_chapter": min(chapters) if chapters else None,
            "last_updated_chapter": max(chapters) if chapters else None,
            "cascade_pending": False,
        })

    return nodes


def _extract_from_summaries(
    book_root: Path,
) -> Tuple[Dict[str, Any], Dict[str, List[int]]]:
    """从章节摘要回退提取实体。"""
    entities: Dict[str, Any] = {}
    chapter_entities: Dict[str, List[int]] = defaultdict(list)

    summary_path = book_root / "追踪" / CHAPTER_SUMMARY_FILE
    text = read_text(summary_path)
    if not text:
        return entities, chapter_entities

    for ch_num, block in _summary_chapter_blocks(text):
        for entity in extract_summary_fields(block).get("entities", []):
            etype = "item"
            ename = entity
            if ":" in entity:
                etype, ename = entity.split(":", 1)
                etype = etype.strip()
                ename = ename.strip()
            if not ename:
                continue
            if ename not in entities:
                entities[ename] = {"type": etype, "chapters": []}
            if ch_num not in entities[ename]["chapters"]:
                entities[ename]["chapters"].append(ch_num)

    return entities, dict(chapter_entities)


def _extract_edges_from_summaries(
    book_root: Path,
    nodes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extract review candidates with spans in the original summary file."""
    text = read_text(book_root / "追踪" / CHAPTER_SUMMARY_FILE)
    if not text:
        return []
    candidates = []
    offset = 0
    source_hash = _text_hash(text)
    for chapter, block in _summary_chapter_blocks(text):
        start = text.index(block, offset)
        offset = start + len(block)
        candidates.extend(_relation_candidates(
            text, nodes, chapter, f"追踪/{CHAPTER_SUMMARY_FILE}",
            "summary", start, offset, source_hash))
    return _graph_edges(candidates, nodes)


def _summary_chapter_blocks(text: str) -> List[Tuple[int, str]]:
    """枚举 h2/h3 章节摘要块，兼容文件首行即章节标题。"""
    entries = list(re.finditer(r"^#{2,3}\s*第\s*(\d+)\s*章.*$", text or "", re.M))
    blocks = []
    for idx, match in enumerate(entries):
        end = entries[idx + 1].start() if idx + 1 < len(entries) else len(text)
        blocks.append((int(match.group(1)), text[match.start():end]))
    return blocks


# =========================================================
# v1.1 从正文直接提取（不依赖章节摘要）
# =========================================================

def extract_from_chapter(
    book_root: Path,
    chapter: int,
) -> Dict[str, Any]:
    with canonical_read_lock(book_root):
        return _extract_from_chapter_unlocked(book_root, chapter)


def _extraction_nodes(book_root: Path) -> list:
    """Use registered names only; do not discover aliases from relation text."""
    graph = load_json(book_root / "追踪" / GRAPH_FILE, {}) or {}
    nodes = {n["label"]: dict(n) for n in graph.get("nodes", [])}
    for node in _entity_nodes(book_root) + extract_character_nodes(book_root):
        nodes.setdefault(node["label"], node)
    for name in load_char_names(book_root):
        node = nodes.setdefault(name, {"id": f"char_{name}", "label": name, "type": "character"})
        node["type"] = "character"
    world = read_text(book_root / "设定" / "世界观.md") or ""
    pattern = r"(?:地点|城市|区域|地域|国家)(?:\*\*)?\s*[：:]\s*([^\n，。；]+)"
    for match in re.finditer(pattern, world):
        name = match[1].strip()
        if name:
            nodes.setdefault(name, {"id": f"location_{name}", "label": name, "type": "location"})
    return list(nodes.values())


def _extract_from_chapter_unlocked(
    book_root: Path,
    chapter: int,
) -> Dict[str, Any]:
    """Read prose and emit unconfirmed relation candidates, never canon."""
    chapter_file = find_chapter_file(book_root, chapter)
    if chapter_file is None:
        return {"chapter": chapter, "error": "章节文件不存在", "characters_found": [],
                "locations_found": [], "new_edges": [], "text_length": 0}
    text = chapter_file.read_text(encoding="utf-8")
    nodes = _extraction_nodes(book_root)
    mentions = {m[0] for m in _known_mentions(text, [n["label"] for n in nodes])}
    found = [n for n in nodes if n["label"] in mentions]
    source_path = chapter_file.relative_to(book_root).as_posix()
    return {
        "chapter": chapter, "file": chapter_file.name,
        "characters_found": sorted(n["label"] for n in found if n["type"] == "character"),
        "locations_found": sorted(n["label"] for n in found if n["type"] == "location"),
        "new_edges": _relation_candidates(text, nodes, chapter, source_path, "prose"),
        "text_length": len(re.sub(r"\s", "", text)),
        "source_hash": _text_hash(text), "source_path": source_path,
        "semantic_review_required": True,
    }


def extract_and_update(
    book_root: Path,
    chapter: int,
) -> Dict[str, Any]:
    """Replace this chapter's generated candidates while holding the canon lock."""
    with canonical_read_lock(book_root):
        extracted = _extract_from_chapter_unlocked(book_root, chapter)
        if "error" in extracted:
            return {"ok": False, "error": extracted["error"], "chapter": chapter}
        graph_path = book_root / "追踪" / GRAPH_FILE
        graph = load_json(graph_path)
        if not graph:
            return {"ok": False, "error": "图谱不存在，请先 build", "chapter": chapter}
        nodes = {n["label"]: n for n in graph.get("nodes", [])}
        needed = set(extracted["characters_found"] + extracted["locations_found"])
        for edge in extracted["new_edges"]:
            needed.update((edge["source_label"], edge["target_label"]))
        added_nodes = 0
        for node in _extraction_nodes(book_root):
            label = node["label"]
            if label not in needed:
                continue
            if label not in nodes:
                nodes[label] = {**node, "props": node.get("props", {}),
                                "first_appear_chapter": chapter,
                                "last_updated_chapter": chapter, "cascade_pending": False}
                added_nodes += 1
            else:
                current = nodes[label]
                current["first_appear_chapter"] = min(current.get("first_appear_chapter") or chapter, chapter)
                current["last_updated_chapter"] = max(current.get("last_updated_chapter") or chapter, chapter)
        new_edges = _graph_edges(extracted["new_edges"], list(nodes.values()))
        added_edges, removed_edges = _replace_source_edges(graph, new_edges, "prose", chapter)
        _store_nodes(graph, nodes)
        _refresh_stats(graph)
        save_json(graph_path, graph)
        return {"ok": True, "chapter": chapter, "added_nodes": added_nodes,
                "added_edges": added_edges, "removed_edges": removed_edges,
                "total_nodes": len(graph["nodes"]), "total_edges": len(graph["edges"]),
                "semantic_review_required": True, "saved_to": str(graph_path)}


def _refresh_stats(graph: dict) -> None:
    graph["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    type_counts = defaultdict(int)
    for node in graph["nodes"]:
        type_counts[node["type"]] += 1
    graph["stats"] = {"total_nodes": len(graph["nodes"]), "total_edges": len(graph["edges"]),
                      "node_types": dict(type_counts)}


def _store_nodes(graph: dict, nodes_by_label: dict) -> None:
    # Old graphs may already contain two IDs for one label. Keep those IDs so
    # legacy edges remain resolvable; updates reuse an ID and add no duplicates.
    by_id = {n["id"]: n for n in graph.get("nodes", [])}
    by_id.update({n["id"]: n for n in nodes_by_label.values()})
    graph["nodes"] = list(by_id.values())


# =========================================================
# 图谱构建
# =========================================================

def build_graph(
    book_root: Path,
    from_scratch: bool = False,
) -> Dict[str, Any]:
    with canonical_read_lock(book_root):
        return _build_graph_unlocked(book_root, from_scratch)


def _build_graph_unlocked(
    book_root: Path,
    from_scratch: bool = False,
) -> Dict[str, Any]:
    """构建/更新知识图谱。

    Args:
        book_root: 书籍工程根目录
        from_scratch: 是否从头重建（忽略已有图谱）

    Returns:
        图谱字典
    """
    graph_path = book_root / "追踪" / GRAPH_FILE

    existing = None
    if not from_scratch and graph_path.exists():
        existing = load_json(graph_path)

    # 提取角色节点
    char_nodes = extract_character_nodes(book_root)

    # 提取实体节点和边
    entity_nodes, edges = extract_entity_nodes(book_root)

    # 合并节点（去重）
    all_nodes = {}
    for n in char_nodes + entity_nodes:
        nid = n["id"]
        if nid in all_nodes:
            # 合并：保留已有章节信息
            existing_n = all_nodes[nid]
            if n.get("first_appear_chapter"):
                if not existing_n.get("first_appear_chapter") or \
                   n["first_appear_chapter"] < existing_n["first_appear_chapter"]:
                    existing_n["first_appear_chapter"] = n["first_appear_chapter"]
            if n.get("last_updated_chapter"):
                if not existing_n.get("last_updated_chapter") or \
                   n["last_updated_chapter"] > existing_n["last_updated_chapter"]:
                    existing_n["last_updated_chapter"] = n["last_updated_chapter"]
            existing_n["props"].update(n.get("props", {}))
        else:
            all_nodes[nid] = n

    graph = {
        "version": VERSION,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats": {
            "total_nodes": len(all_nodes),
            "total_edges": len(edges),
            "node_types": {},
        },
        "nodes": list(all_nodes.values()),
        "edges": edges,
    }

    # 统计节点类型
    type_counts = defaultdict(int)
    for n in all_nodes.values():
        type_counts[n["type"]] += 1
    graph["stats"]["node_types"] = dict(type_counts)

    return graph


def update_chapter(
    book_root: Path,
    chapter: int,
) -> Dict[str, Any]:
    with canonical_read_lock(book_root):
        return _update_chapter_unlocked(book_root, chapter)


def _update_chapter_unlocked(
    book_root: Path,
    chapter: int,
) -> Dict[str, Any]:
    """增量更新：从单章摘要提取实体，替换该章生成的关系候选。

    每章写完后调用，避免全量 rebuild 的代价。
    """
    graph_path = book_root / "追踪" / GRAPH_FILE
    graph = load_json(graph_path)
    if not graph:
        # 图谱不存在，降级为全量构建
        return {
            "ok": False,
            "error": "图谱不存在，请先 build",
            "fallback": "建议先运行: python story_graph.py build",
        }

    # 从单章摘要提取实体和关系
    summary_path = book_root / "追踪" / CHAPTER_SUMMARY_FILE
    text = read_text(summary_path)
    if not text:
        return {"ok": False, "error": "章节摘要文件不存在"}

    # 找到本章摘要块
    chapter_block = next((block for ch_num, block in _summary_chapter_blocks(text)
                          if ch_num == chapter), "")

    if not chapter_block:
        return {"ok": False, "error": f"第{chapter}章摘要未找到"}

    # 从本章摘要提取实体
    new_entities: Dict[str, Any] = {}
    for entity in extract_summary_fields(chapter_block).get("entities", []):
        etype = "item"
        ename = entity
        if ":" in entity:
            etype, ename = entity.split(":", 1)
            etype = etype.strip()
            ename = ename.strip()
        if etype not in NODE_TYPES:
            etype = "item"
        if not ename:
            continue
        if ename not in new_entities:
            new_entities[ename] = {"type": etype, "chapters": []}
        if chapter not in new_entities[ename]["chapters"]:
            new_entities[ename]["chapters"].append(chapter)

    nodes = {n["label"]: n for n in graph.get("nodes", [])}
    added_nodes = updated_nodes = 0
    for name, info in new_entities.items():
        if name in nodes:
            node = nodes[name]
            node["first_appear_chapter"] = min(node.get("first_appear_chapter") or chapter, chapter)
            node["last_updated_chapter"] = max(node.get("last_updated_chapter") or chapter, chapter)
            updated_nodes += 1
        else:
            nodes[name] = {"id": f"{info['type']}_{name}", "type": info["type"], "label": name,
                           "props": {}, "first_appear_chapter": chapter,
                           "last_updated_chapter": chapter, "cascade_pending": False}
            added_nodes += 1
    start = text.index(chapter_block)
    candidates = _relation_candidates(text, list(nodes.values()), chapter,
                                     f"追踪/{CHAPTER_SUMMARY_FILE}", "summary",
                                     start, start + len(chapter_block))
    new_edges = _graph_edges(candidates, list(nodes.values()))
    added_edges, removed_edges = _replace_source_edges(graph, new_edges, "summary", chapter)
    _store_nodes(graph, nodes)
    _refresh_stats(graph)
    save_json(graph_path, graph)
    return {"ok": True, "chapter": chapter, "added_nodes": added_nodes,
            "updated_nodes": updated_nodes, "added_edges": added_edges,
            "removed_edges": removed_edges, "semantic_review_required": True,
            "total_nodes": len(graph["nodes"]), "total_edges": len(graph["edges"]),
            "saved_to": str(graph_path)}


# =========================================================
# 级联标记
# =========================================================

def cascade_mark(
    book_root: Path,
    from_chapter: int,
    change_description: str = "",
) -> Dict[str, Any]:
    """改纲后标记受影响节点。

    将所有 last_updated_chapter >= from_chapter 的节点标记为 cascade_pending=True。
    """
    graph_path = book_root / "追踪" / GRAPH_FILE
    graph = load_json(graph_path)
    if not graph:
        return {"ok": False, "error": "图谱不存在，请先 build"}

    backup_graph(graph_path)

    affected = []
    for node in graph.get("nodes", []):
        last_ch = node.get("last_updated_chapter")
        if last_ch is not None and last_ch >= from_chapter:
            node["cascade_pending"] = True
            affected.append({
                "id": node["id"],
                "label": node["label"],
                "type": node["type"],
                "last_updated": last_ch,
            })

    # 也标记涉及这些节点的边
    affected_ids = {a["id"] for a in affected}
    affected_edges = []
    for edge in graph.get("edges", []):
        if edge["source"] in affected_ids or edge["target"] in affected_ids:
            affected_edges.append(edge)

    graph["cascade"] = {
        "from_chapter": from_chapter,
        "description": change_description,
        "marked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "affected_nodes": len(affected),
        "affected_edges": len(affected_edges),
    }

    save_json(graph_path, graph)

    return {
        "ok": True,
        "affected_nodes": affected,
        "affected_edges_count": len(affected_edges),
        "total_nodes": len(graph.get("nodes", [])),
        "total_edges": len(graph.get("edges", [])),
    }


# =========================================================
# 查询
# =========================================================

def query_graph(
    book_root: Path,
    node_label: str,
    depth: int = 1,
) -> Dict[str, Any]:
    """查询节点及其邻接关系。

    Args:
        book_root: 书籍工程根目录
        node_label: 节点标签（模糊匹配）
        depth: 查询深度（1=直接邻居，2=邻居的邻居）

    Returns:
        查询结果
    """
    graph_path = book_root / "追踪" / GRAPH_FILE
    graph = load_json(graph_path)
    if not graph:
        return {"ok": False, "error": "图谱不存在，请先 build"}

    # 查找匹配节点
    matched = []
    for node in graph.get("nodes", []):
        if node_label.lower() in node["label"].lower():
            matched.append(node)

    if not matched:
        return {"ok": True, "matched": [], "message": f"未找到匹配 '{node_label}' 的节点"}

    # 查找邻接边
    result_nodes = []
    result_edges = []
    source_cache = {}
    seen_edges = set()
    visited = set()

    for m in matched:
        visited.add(m["id"])
        result_nodes.append(m)

    current_depth = 0
    frontier = set(visited)

    while current_depth < depth:
        next_frontier = set()
        for edge_index, edge in enumerate(graph.get("edges", [])):
            src = edge["source"]
            tgt = edge["target"]
            if src in frontier or tgt in frontier:
                if edge_index not in seen_edges:
                    seen_edges.add(edge_index)
                    result_edges.append(_edge_view(edge, book_root, source_cache))
                if src not in visited:
                    next_frontier.add(src)
                if tgt not in visited:
                    next_frontier.add(tgt)

        # 添加新发现的节点
        node_map = {n["id"]: n for n in graph.get("nodes", [])}
        for nid in next_frontier:
            if nid in node_map and nid not in visited:
                result_nodes.append(node_map[nid])
                visited.add(nid)

        frontier = next_frontier
        current_depth += 1

    return {
        "ok": True,
        "query": node_label,
        "depth": depth,
        "matched": [{"id": m["id"], "label": m["label"], "type": m["type"]} for m in matched],
        "nodes": result_nodes,
        "edges": result_edges,
        "total_related": len(result_nodes),
        "semantic_review_required": any(e.get("semantic_review_required") for e in result_edges),
    }


# =========================================================
# Mermaid 导出
# =========================================================

def export_mermaid(book_root: Path, output_path: Optional[Path] = None) -> str:
    """导出图谱为 Mermaid 格式。

    Returns:
        Mermaid 文本
    """
    graph_path = book_root / "追踪" / GRAPH_FILE
    graph = load_json(graph_path)
    if not graph:
        return "graph TD\n  A[图谱不存在]"

    lines = ["graph TD"]
    lines.append("  %% 知识图谱 — 自动生成于 " + graph.get("updated_at", ""))
    lines.append("")

    # 节点定义
    type_styles = {
        "character": "[/%s/]",
        "event": "[%s]",
        "location": "[(%s)]",
        "item": "([%s])",
        "faction": "{{%s}}",
        "secret": "[\"%s\"]",
        "rule": "{%s}",
    }

    node_ids = {}
    for i, node in enumerate(graph.get("nodes", [])):
        nid = node["id"]
        safe_id = f"n{i}"
        node_ids[nid] = safe_id
        style = type_styles.get(node["type"], "[%s]")
        label = node["label"]
        cascade = " ⚠" if node.get("cascade_pending") else ""
        lines.append(f"  {safe_id}{style % (label + cascade)}")

    lines.append("")

    # Relation labels and uncertainty are visible even for legacy graphs.
    source_cache = {}
    status_labels = {"unconfirmed": "未确认·需语义复核", "legacy_unconfirmed": "旧图谱·未确认",
                     "stale": "来源已变更·需重新提取"}
    for edge in graph.get("edges", []):
        src = node_ids.get(edge["source"])
        tgt = node_ids.get(edge["target"])
        if src and tgt:
            view = _edge_view(edge, book_root, source_cache)
            parts = [edge.get("label", edge.get("type", ""))]
            if edge.get("chapter"):
                parts.append(f"Ch{edge['chapter']}")
            if view.get("status") in status_labels:
                parts.append(status_labels[view["status"]])
            if edge.get("assertion_kind"):
                parts.append(edge["assertion_kind"])
            label = " · ".join(parts).replace('"', "#quot;").replace("|", "#124;")
            lines.append(f'  {src} -->|"{label}"| {tgt}')

    mermaid_text = "\n".join(lines)

    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(mermaid_text)
        except OSError:
            pass

    return mermaid_text


# =========================================================
# 影响分析
# =========================================================

def impact_analysis(
    book_root: Path,
    node_label: Optional[str] = None,
    chapter: Optional[int] = None,
) -> Dict[str, Any]:
    """Read-only review scope, not a proof that downstream prose must change.

    Definite = selected entity/current source mentions and the supplied source
    chapter. Possible = up to two graph hops and entity-index chapter references,
    including legacy, stale or unconfirmed evidence. Never edit prose or graph.
    """
    graph = load_json(book_root / "追踪" / GRAPH_FILE, {}) or {}
    if not graph and chapter is None:
        return {"ok": False, "error": "图谱不存在，请先 build"}
    if node_label is None and chapter is None:
        return {"ok": False, "error": "请提供节点标签或 --chapter"}
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    matched = [n for n in nodes.values() if node_label and node_label.lower() in n["label"].lower()]
    definite = {n["label"] for n in matched}
    seed_ids = {n["id"] for n in matched}
    possible = set()
    possible_chapters = set()
    references = []
    source_info = None
    if chapter is not None:
        chapter_file = find_chapter_file(book_root, chapter)
        if chapter_file is None:
            return {"ok": False, "error": "章节文件不存在", "chapter": chapter, "read_only": True}
        text = chapter_file.read_text(encoding="utf-8")
        known = _extraction_nodes(book_root)
        mentions = _known_mentions(text, [n["label"] for n in known])
        if node_label:
            mentions = [m for m in mentions if node_label.lower() in m[0].lower()]
        definite = {m[0] for m in mentions}
        source_info = {"chapter": chapter, "source_path": chapter_file.relative_to(book_root).as_posix(),
                       "source_hash": _text_hash(text)}
        for mention in mentions:
            references.append({"kind": "source_mention", "entity": mention[0],
                               "span": list(mention.span()), **source_info})
        seed_ids.update(nid for nid, node in nodes.items() if node["label"] in definite)
        # Removed/renamed mentions can remain in old graph evidence. Include them
        # as possible review targets, never as current source facts.
        for edge in graph.get("edges", []):
            evidence = edge.get("evidence") or {}
            if evidence.get("chapter", edge.get("chapter")) == chapter:
                if not node_label or edge["source"] in seed_ids or edge["target"] in seed_ids:
                    seed_ids.update((edge["source"], edge["target"]))
    direct, indirect = [], []
    seen_ids = set(seed_ids)
    frontier = set(seed_ids)
    seen_edges = set()
    source_cache = {}
    for depth in range(2):
        next_frontier = set()
        for index, edge in enumerate(graph.get("edges", [])):
            if edge["source"] not in frontier and edge["target"] not in frontier:
                continue
            next_frontier.update((edge["source"], edge["target"]))
            if index in seen_edges:
                continue
            seen_edges.add(index)
            view = _edge_view(edge, book_root, source_cache)
            item = {"from": edge["source"], "to": edge["target"],
                    "relation": edge.get("label", edge.get("type")), "chapter": edge.get("chapter"),
                    "status": view["status"], "semantic_review_required": view["semantic_review_required"]}
            (direct if depth == 0 else indirect).append(item)
            references.append({"kind": "graph_edge", **item,
                               "evidence": edge.get("evidence"), "evidence_status": view.get("evidence_status")})
            if isinstance(edge.get("chapter"), int):
                possible_chapters.add(edge["chapter"])
        frontier = next_frontier - seen_ids
        seen_ids.update(next_frontier)
    possible.update(nodes[nid]["label"] for nid in seen_ids if nid in nodes)
    labels = definite | possible
    index = load_json(book_root / "追踪" / ENTITY_INDEX_FILE, {}) or {}
    entities = index.get("entities", index) if isinstance(index, dict) else {}
    for label, info in entities.items():
        # Flat indexes may keep the type prefix from the summary template.
        name = label.split(":", 1)[-1].strip()
        if name not in labels:
            continue
        chapters = info.get("chapters", []) if isinstance(info, dict) else info
        if not isinstance(chapters, list):
            continue
        chapters = [number for number in chapters if isinstance(number, int)]
        possible_chapters.update(chapters)
        references.append({"kind": "entity_index", "entity": name, "chapters": chapters,
                           "source_path": f"追踪/{ENTITY_INDEX_FILE}", "status": "unverified_reference"})
    definite_chapters = {chapter} if chapter is not None else set()
    return {"ok": True, "node": node_label, "chapter": chapter,
            "matched": [{"id": n["id"], "label": n["label"], "type": n["type"]} for n in matched],
            "direct_impact": direct, "indirect_impact": indirect,
            "total_impact": len(direct) + len(indirect),
            "definite_entities": sorted(definite), "possible_entities": sorted(possible - definite),
            "definite_chapters": sorted(definite_chapters),
            "possible_chapters": sorted(possible_chapters - definite_chapters),
            "source": source_info, "references": references,
            "read_only": True, "semantic_review_required": True,
            "scope_note": "确定项仅表示修改源或当前原文点名；可能项来自两跳图谱及未核验索引，需逐章复核，不代表必须改文。"}


# =========================================================
# CLI
# =========================================================

def main():
    # Windows 中文控制台默认 GBK 输出，在 Git Bash 等 UTF-8 终端下会乱码；统一按 UTF-8 输出
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(
        description="轻量知识图谱：节点+边+版本，支撑百万字级联影响分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/story_graph.py build "{书名目录}"
  python scripts/story_graph.py query "{书名目录}" 林雷
  python scripts/story_graph.py query "{书名目录}" 林雷 --depth 2
  python scripts/story_graph.py cascade "{书名目录}" --from-chapter 50 --desc "改主线"
  python scripts/story_graph.py impact "{书名目录}" 林雷
  python scripts/story_graph.py impact "{书名目录}" --chapter 37
  python scripts/story_graph.py export "{书名目录}" --output graph.md
  python scripts/story_graph.py status "{书名目录}"
  python scripts/story_graph.py update "{书名目录}" --chapter 37
        """,
    )
    sub = parser.add_subparsers(dest="command")

    p_build = sub.add_parser("build", help="构建/更新知识图谱")
    p_build.add_argument("book_root", help="书籍工程根目录")
    p_build.add_argument("--from-scratch", action="store_true", help="从头重建")

    p_query = sub.add_parser("query", help="查询节点及邻接关系")
    p_query.add_argument("book_root", help="书籍工程根目录")
    p_query.add_argument("node", help="节点标签（模糊匹配）")
    p_query.add_argument("--depth", type=int, default=1, help="查询深度（默认1）")

    p_cascade = sub.add_parser("cascade", help="改纲后标记受影响节点")
    p_cascade.add_argument("book_root", help="书籍工程根目录")
    p_cascade.add_argument("--from-chapter", type=int, required=True, help="改纲影响起始章节")
    p_cascade.add_argument("--desc", default="", help="改纲说明")

    p_impact = sub.add_parser("impact", help="只读列出修改源及可能需要复核的关联实体/章节")
    p_impact.add_argument("book_root", help="书籍工程根目录")
    p_impact.add_argument("node", nargs="?", help="节点标签（可选）")
    p_impact.add_argument("--chapter", type=int, help="修改源章号；只读列出确定/可能复核范围")

    p_export = sub.add_parser("export", help="导出 Mermaid 可视化")
    p_export.add_argument("book_root", help="书籍工程根目录")
    p_export.add_argument("--output", help="输出文件路径")

    p_status = sub.add_parser("status", help="查看图谱状态")
    p_status.add_argument("book_root", help="书籍工程根目录")

    p_update = sub.add_parser("update", help="增量更新单章（每章写完后调用）")
    p_update.add_argument("book_root", help="书籍工程根目录")
    p_update.add_argument("--chapter", type=int, required=True, help="章节号")

    # v1.1 新增 extract 子命令
    p_extract = sub.add_parser("extract", help="从正文章节提取实体和关系候选（需语义复核）")
    p_extract.add_argument("book_root", help="书籍工程根目录")
    p_extract.add_argument("--chapter", type=int, required=True, help="章节号")
    p_extract.add_argument("--update", action="store_true", help="提取后自动更新图谱")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(2)

    book_root = Path(args.book_root).expanduser().resolve()

    if args.command == "build":
        graph = build_graph(book_root, from_scratch=args.from_scratch)
        graph_path = book_root / "追踪" / GRAPH_FILE
        save_json(graph_path, graph)
        print(json.dumps({
            "ok": True,
            "stats": graph["stats"],
            "saved_to": str(graph_path),
        }, ensure_ascii=False, indent=2))

    elif args.command == "query":
        result = query_graph(book_root, args.node, args.depth)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "cascade":
        result = cascade_mark(book_root, args.from_chapter, args.desc)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "impact":
        result = impact_analysis(book_root, args.node, args.chapter)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "export":
        out = Path(args.output) if args.output else None
        text = export_mermaid(book_root, out)
        if not args.output:
            print(text)

    elif args.command == "status":
        graph_path = book_root / "追踪" / GRAPH_FILE
        graph = load_json(graph_path)
        if not graph:
            print(json.dumps({"ok": False, "error": "图谱不存在"}, ensure_ascii=False))
            sys.exit(1)
        cascade = graph.get("cascade", {})
        print(json.dumps({
            "ok": True,
            "stats": graph["stats"],
            "updated_at": graph.get("updated_at"),
            "cascade": cascade,
            "has_pending_cascade": any(
                n.get("cascade_pending") for n in graph.get("nodes", [])
            ),
        }, ensure_ascii=False, indent=2))

    elif args.command == "update":
        result = update_chapter(book_root, args.chapter)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "extract":
        if args.update:
            result = extract_and_update(book_root, args.chapter)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            result = extract_from_chapter(book_root, args.chapter)
            print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
