#!/usr/bin/env python3
"""Prepare raw agent tasks and record evidence; never synthesize model success."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
from datetime import datetime, timezone

from common import ensure_utf8_stdout
from source_materialize import _safe_path, _signature

ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    """Read one stable regular file, rejecting links and existing reparse paths."""
    path = _safe_path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("expected a regular file without hard links: " + str(path))
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb") as handle:
        if _signature(before) != _signature(os.fstat(handle.fileno())):
            raise ValueError("file changed before reading: " + str(path))
        raw = handle.read()
        if _signature(before) != _signature(os.fstat(handle.fileno())):
            raise ValueError("file changed while reading: " + str(path))
    if _signature(before) != _signature(_safe_path(path).stat()):
        raise ValueError("file changed while reading: " + str(path))
    return raw


def _hash(path):
    return hashlib.sha256(_read(path)).hexdigest()


def _write(path, value):
    with _safe_path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _input_paths(names, allow_prompt=False):
    """Use one portable spelling; reserve runner metadata and Windows devices."""
    reserved = {"run.json", "observation.json", "prompt.md"}
    devices = {"con", "prn", "aux", "nul", "conin$", "conout$"}
    devices.update(prefix + digit for prefix in ("com", "lpt") for digit in "123456789¹²³")
    normalized = []
    for name in names:
        if not isinstance(name, str):
            raise ValueError("fixture paths must be strings")
        path = PurePosixPath(name)
        parts = path.parts
        if (not parts or path.is_absolute() or ".." in parts or path.as_posix() != name
                or any(c in '<>:"\\|?*' or ord(c) < 32 for c in name)
                or any(p.endswith((" ", ".")) or p.split(".", 1)[0].casefold() in devices for p in parts)
                or (parts[0].casefold() in reserved and not (allow_prompt and name == "prompt.md"))):
            raise ValueError("unsafe fixture path: " + name)
        normalized.append(name.casefold())
    if len(set(normalized)) != len(normalized) or any(
            name.startswith(other + "/") for name in normalized for other in normalized):
        raise ValueError("fixture paths collide on Windows")


def _run_path(path):
    path = _safe_path(path)
    if path == ROOT or ROOT in path.parents or any(
            (parent / "追踪").is_dir() and (parent / "大纲").is_dir() for parent in (path, *path.parents)):
        raise ValueError("prepare/record cases outside the Skill repository and any real book")
    return path


def load_suite(path=None):
    suite = json.loads(_read(path or ROOT / "evals/cases.json").decode("utf-8"), object_pairs_hook=_json_object)
    if (not isinstance(suite, dict) or type(suite.get("schema_version")) is not int
            or suite["schema_version"] != 1 or not isinstance(suite.get("cases"), list)):
        raise ValueError("invalid evaluation suite")
    seen = set()
    for case in suite["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"].strip():
            raise ValueError("nonempty case identifier required")
        if case["id"] in seen or case["kind"] not in ("defect", "clean", "generative"):
            raise ValueError("duplicate id or invalid case kind")
        seen.add(case["id"])
        if (any(not isinstance(case.get(key), str) or not case[key].strip() for key in ("prompt", "genre"))
                or not isinstance(case.get("criteria"), list) or not case["criteria"]
                or any(not isinstance(c, str) or not c.strip() for c in case["criteria"])
                or not isinstance(case.get("files"), dict)):
            raise ValueError("prompt, genre and reviewer criteria are required")
        _input_paths(case["files"])
        if any(not isinstance(content, str) for content in case["files"].values()):
            raise ValueError("fixture content must be text")
    return suite


def prepare_case(case_id, output, suite_path=None):
    suite = load_suite(suite_path)
    case = next((c for c in suite["cases"] if c["id"] == case_id), None)
    if case is None:
        raise ValueError("unknown case: " + case_id)
    output = _run_path(output)
    output.mkdir(parents=True, exist_ok=False)
    inputs = dict(case["files"])
    inputs["prompt.md"] = case["prompt"] + "\n"
    for name, content in inputs.items():
        path = _safe_path(output / name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _safe_path(path).open("x", encoding="utf-8") as handle:
            handle.write(content)
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                                           stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unavailable"
    # A commit alone cannot identify a dirty worktree. Hash all behavior-bearing files.
    skill_files = sorted(p for p in ROOT.rglob("*") if p.is_file()
                         and p.suffix in (".py", ".md", ".yaml", ".json")
                         and not any(x in (".git", "__pycache__", "evals", "docs") for x in p.relative_to(ROOT).parts)
                         and "tests" not in p.relative_to(ROOT).parts)
    manifest = {p.relative_to(ROOT).as_posix(): _hash(p) for p in skill_files}
    receipt = {"schema_version": 1, "case_id": case_id, "status": "prepared",
               "model_execution": "not_run", "skill_revision": revision,
               "skill_manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
               "input_hashes": {name: _hash(output / name) for name in inputs},
               "prepared_at": datetime.now(timezone.utc).isoformat(), "passed": None}
    _write(output / "run.json", receipt)
    return receipt


def _validate_receipt(receipt):
    fields = {"schema_version", "case_id", "status", "model_execution", "skill_revision",
              "skill_manifest_sha256", "input_hashes", "prepared_at", "passed"}
    if not isinstance(receipt, dict) or set(receipt) != fields:
        raise ValueError("incomplete prepared receipt")
    if (type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
            or receipt["status"] != "prepared" or receipt["model_execution"] != "not_run"
            or receipt["passed"] is not None):
        raise ValueError("invalid prepared receipt state")
    if any(not isinstance(receipt[key], str) or not receipt[key].strip()
           for key in ("case_id", "skill_revision", "prepared_at")):
        raise ValueError("invalid prepared receipt identity")
    if datetime.fromisoformat(receipt["prepared_at"]).tzinfo is None:
        raise ValueError("prepared_at must include a timezone")
    hashes = receipt["input_hashes"]
    if not isinstance(hashes, dict) or "prompt.md" not in hashes:
        raise ValueError("prepared receipt requires input hashes including prompt.md")
    _input_paths(hashes, allow_prompt=True)
    for digest in [receipt["skill_manifest_sha256"], *hashes.values()]:
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid prepared receipt hash")


def record_run(run_dir, response_path, trace_path, model):
    run_dir = _run_path(run_dir)
    receipt = json.loads(_read(run_dir / "run.json").decode("utf-8"), object_pairs_hook=_json_object)
    _validate_receipt(receipt)
    if not isinstance(model, str) or not model.strip():
        raise ValueError("explicit model identifier required")
    response_path, trace_path = _safe_path(response_path), _safe_path(trace_path)
    response_raw, trace_raw = _read(response_path), _read(trace_path)
    if not response_raw.decode("utf-8").strip():
        raise ValueError("empty response")
    trace = json.loads(trace_raw.decode("utf-8"), object_pairs_hook=_json_object)
    if not isinstance(trace, list) or not trace or any(not isinstance(x, dict) or not any(
            isinstance(x.get(key), str) and x[key].strip() for key in ("tool", "action")) for x in trace):
        raise ValueError("trace needs an identifiable tool/action in each observed record")
    for name, expected in receipt["input_hashes"].items():
        if _hash(run_dir / name) != expected:
            raise ValueError("prepared input changed: " + name)
    record = dict(receipt, status="observed", model_execution="artifacts_supplied",
                  model=model, recorded_at=datetime.now(timezone.utc).isoformat(),
                  response={"path": str(response_path), "sha256": hashlib.sha256(response_raw).hexdigest()},
                  trace={"path": str(trace_path), "sha256": hashlib.sha256(trace_raw).hexdigest()},
                  semantic_review={"status": "not_run"}, passed=None)
    # Presence and hashes attest supplied artifacts, not that their contents are truthful.
    record["evidence_boundary"] = "supplied_artifacts_not_independently_attested"
    _write(run_dir / "observation.json", record)
    return record


def retrieval_eval(fixture, top_k=5):
    from common import BM25Index, tokenize_chinese
    if top_k < 1:
        raise ValueError("top_k must be positive")
    documents, queries = fixture["documents"], fixture["queries"]
    ids = [d["id"] for d in documents]
    if not documents or not queries or len(set(ids)) != len(ids):
        raise ValueError("nonempty, unique documents and queries required")
    index = BM25Index([(d["id"], d["text"]) for d in documents])
    rows = []
    for query in queries:
        gold = set(query["relevant"])
        if not gold or not gold.issubset(ids):
            raise ValueError("gold evidence must refer to supplied documents")
        hits = [hit[0] for hit in index.search(tokenize_chinese(query["query"]), top_k=top_k)]
        rows.append({"id": query["id"], "retrieved": hits, "relevant": sorted(gold),
                     "recall_at_k": len(set(hits) & gold) / len(gold),
                     "reciprocal_rank": next((1 / (i + 1) for i, h in enumerate(hits) if h in gold), 0.0)})
    return {"scope": "synthetic_retrieval_fixture", "backend": "common.BM25Index",
            "top_k": top_k, "query_count": len(rows), "rows": rows,
            "recall_at_k": sum(r["recall_at_k"] for r in rows) / len(rows),
            "mean_reciprocal_rank": sum(r["reciprocal_rank"] for r in rows) / len(rows),
            "limitation": "Does not measure production context selection or long-serial recall."}


def main(argv=None):
    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    prepare = sub.add_parser("prepare")
    prepare.add_argument("case_id")
    prepare.add_argument("output")
    record = sub.add_parser("record")
    record.add_argument("run_dir")
    record.add_argument("--response", required=True)
    record.add_argument("--trace", required=True)
    record.add_argument("--model", required=True)
    retrieval = sub.add_parser("retrieval")
    retrieval.add_argument("--fixture", default=str(ROOT / "evals/retrieval.json"))
    retrieval.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = {"cases": len(load_suite()["cases"]), "fixture_validation": "pass", "model_execution": "not_run"}
        elif args.command == "prepare":
            result = prepare_case(args.case_id, args.output)
        elif args.command == "record":
            result = record_run(args.run_dir, args.response, args.trace, args.model)
        else:
            result = retrieval_eval(json.loads(_read(args.fixture).decode("utf-8"), object_pairs_hook=_json_object), args.top_k)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
