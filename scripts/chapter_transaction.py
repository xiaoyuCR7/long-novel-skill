#!/usr/bin/env python3
"""Journaled chapter commit: a staged book, eight-file checkpoint, safe recovery.

This is NOT an atomic multi-file replace. Cooperating writers take the lock;
hash checks detect non-cooperating changes. A process interruption leaves a
durable journal for explicit recovery. Readers must honor pending_transaction.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

TRACKING = ("章节摘要.md", "角色状态.md", "伏笔台账.md", "时间线.md", "节奏配额.md")
AREA = "追踪/.chapter-transactions"
LOCK = "追踪/.chapter-transaction.lock"
TERMINAL = {"committed", "recovered"}
SCRIPTS = Path(__file__).resolve().parent


class TransactionError(RuntimeError):
    pass


def _safe(root, relative):
    root = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise TransactionError("unsafe_path: " + str(relative))
    path = root / rel
    cursor = path
    while cursor != root:
        if cursor.is_symlink():
            raise TransactionError("unsafe_symlink: " + str(cursor))
        cursor = cursor.parent
    try:
        path.resolve().relative_to(root)
    except ValueError:
        raise TransactionError("unsafe_path: " + str(relative))
    return path


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def book_hashes(book):
    """Inventory non-hidden story files; transaction/legacy lock dirs are private."""
    book = Path(book).resolve()
    result = {}
    for directory, dirs, files in os.walk(str(book), followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in dirs + files:
            if not name.startswith("."):
                _safe(book, (Path(directory) / name).relative_to(book))
        for name in sorted(files):
            if not name.startswith("."):
                path = Path(directory) / name
                result[path.relative_to(book).as_posix()] = _hash(path)
    return result


def _flush_directory(directory):
    if os.name != "nt":
        descriptor = os.open(str(directory), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".journal-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, str(path))
        _flush_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def transaction_lock(book):
    lock_path = _safe(book, LOCK)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(lock_path), "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise TransactionError("transaction_locked") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _current(book):
    return _safe(book, AREA + "/current")


def load_journal(book):
    current = _current(book)
    try:
        value = json.loads((current / "journal.json").read_text(encoding="utf-8"))
        expected = _targets(value["chapter"], value["chapter_file"])
        if value["targets"] != expected or set(value["before"]) != set(expected):
            raise ValueError("target manifest mismatch")
        if value["status"] not in TERMINAL | {"preparing", "prepared", "validated", "committing", "recovering"}:
            raise ValueError("unknown status")
        # Never trust serialized absolute locations during recovery.
        value["stage_root"] = str(current / "stage")
        value["checkpoint_root"] = str(current / "checkpoint")
        return value
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TransactionError("transaction_incomplete: invalid journal; preserve " + str(current)) from exc


def pending_transaction(book):
    if not _current(book).exists():
        return None
    try:
        journal = load_journal(book)
    except TransactionError as exc:
        return {"status": "corrupt", "error": str(exc)}
    return None if journal["status"] in TERMINAL else journal


def recovery_command(book):
    return 'python scripts/chapter_transaction.py recover "{}"'.format(Path(book).resolve())


def _targets(chapter, chapter_file):
    if not isinstance(chapter, int) or chapter < 1:
        raise TransactionError("invalid_chapter")
    if Path(chapter_file).name != chapter_file or "/" in chapter_file or "\\" in chapter_file:
        raise TransactionError("unsafe_chapter_file")
    match = re.search(r"第\s*(\d+)\s*章", chapter_file)
    if not match or int(match.group(1)) != chapter or not chapter_file.endswith(".md"):
        raise TransactionError("invalid_chapter_file")
    return ["正文/" + chapter_file] + ["追踪/" + name for name in TRACKING] + [
        "追踪/门禁/gate_ch{}.json".format(chapter), "追踪/entity_index.json"]


def _save(book, journal):
    _write_json(_current(book) / "journal.json", journal)


def prepare(book, chapter, chapter_file=None):
    book = Path(book).resolve()
    if not book.is_dir():
        raise TransactionError("missing_book")
    with transaction_lock(book):
        if pending_transaction(book):
            raise TransactionError("transaction_incomplete: " + recovery_command(book))
        if (book / "追踪/.flow_lock.json").exists():
            raise TransactionError("transaction_locked: finish/unlock legacy novel_flow first")
        matches = sorted((book / "正文").glob("*.md"))
        matches = [p.name for p in matches if re.search(r"第\s*0*{}\s*章".format(chapter), p.name)]
        if len(matches) > 1:
            raise TransactionError("state_conflict: duplicate chapter files")
        chapter_file = chapter_file or (matches[0] if matches else "第{:03d}章.md".format(chapter))
        if matches and chapter_file != matches[0]:
            raise TransactionError("state_conflict: existing chapter uses another filename")
        targets = _targets(chapter, chapter_file)
        baseline = book_hashes(book)
        current = _current(book)
        if current.exists():
            os.replace(str(current), str(current.parent / ("archive-" + uuid.uuid4().hex)))
        stage, checkpoint = current / "stage", current / "checkpoint"
        journal = {"status": "preparing", "chapter": chapter, "chapter_file": chapter_file,
                   "stage_root": str(stage), "checkpoint_root": str(checkpoint), "targets": targets,
                   "before": {path: baseline.get(path) for path in targets}, "baseline": baseline}
        _save(book, journal)
        for relative in baseline:
            source, target = _safe(book, relative), _safe(stage, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source), str(target))
            if relative in targets:
                backup = _safe(checkpoint, relative)
                backup.parent.mkdir(parents=True, exist_ok=True)
                _install_file(source, backup)
        (stage / "正文").mkdir(parents=True, exist_ok=True)
        if book_hashes(book) != baseline or book_hashes(stage) != baseline:
            raise TransactionError("state_conflict: changed during prepare; " + recovery_command(book))
        for relative in targets:
            if _hash(_safe(checkpoint, relative)) != journal["before"][relative]:
                raise TransactionError("checkpoint_mismatch: " + relative)
        journal["status"] = "prepared"
        _save(book, journal)
        return journal


def _run(script, arguments, stage):
    env = dict(os.environ, PYTHONUTF8="1")
    result = subprocess.run([sys.executable, str(SCRIPTS / script)] + arguments, cwd=str(stage),
                            capture_output=True, encoding="utf-8", errors="replace", env=env, timeout=120)
    if result.returncode:
        raise TransactionError("gate_blocked: {}\n{}{}".format(script, result.stdout, result.stderr))


def validate(book, min_chars, max_chars, declare):
    with transaction_lock(book):
        journal = load_journal(book)
        if journal["status"] not in {"prepared", "validated"}:
            raise TransactionError("transaction_incomplete: " + recovery_command(book))
        # Invalidate old success before any checks or generated artifacts change.
        journal["status"] = "prepared"
        _save(book, journal)
        stage = Path(journal["stage_root"])
        prose = _safe(stage, journal["targets"][0])
        for relative in journal["targets"][:6]:
            if not _safe(stage, relative).is_file():
                raise TransactionError("required_context_missing: " + relative)
        if not declare or min_chars < 1 or max_chars < min_chars:
            raise TransactionError("invalid_validation_budget_or_declaration")
        _run("validate_tracking.py", [str(stage)], stage)
        import resume
        debts, _ = resume.check_tracking_sync(str(stage), journal["chapter"])
        if debts:
            raise TransactionError("tracking_incomplete: " + "; ".join(debts))
        chapter = str(journal["chapter"])
        _run("check_text.py", [str(prose), "--min-chars", str(min_chars), "--max-chars", str(max_chars),
                              "--ledger", str(stage / "追踪/伏笔台账.md"), "--current-chapter", chapter,
                              "--gate-report", "--gate-state"], stage)
        _run("rhythm_guard.py", ["--chapter-file", str(prose), "--chapter", chapter,
                                "--quota", str(stage / "追踪/节奏配额.md"), "--declare=" + declare,
                                "--gate-state"], stage)
        _run("entity_index.py", ["build", str(stage)], stage)
        gate = json.loads((stage / journal["targets"][-2]).read_text(encoding="utf-8"))
        if gate.get("chapter_sha256") != _hash(prose) or not gate.get("passed") or not gate.get("rhythm", {}).get("passed"):
            raise TransactionError("gate_blocked: staged gate/hash mismatch")
        staged = book_hashes(stage)
        untouched = set(staged) | set(journal["baseline"])
        if any(staged.get(p) != journal["baseline"].get(p) for p in untouched - set(journal["targets"])):
            raise TransactionError("stage_changed_outside_transaction: only prose + five tracking files may be edited")
        journal["validated_hashes"] = staged
        journal["after"] = {path: staged[path] for path in journal["targets"]}
        journal["status"] = "validated"
        _save(book, journal)
        return journal


def _install_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".chapter-", dir=str(target.parent))
    os.close(fd)
    try:
        shutil.copy2(str(source), temporary)
        with open(temporary, "rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, str(target))
        _flush_directory(target.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _recover(book, journal):
    if journal["status"] in TERMINAL:
        return journal
    if journal["status"] in {"committing", "recovering"}:
        # Preflight ALL paths before touching any: never erase foreign edits.
        for relative in journal["targets"]:
            before, after = journal["before"][relative], journal["after"][relative]
            if _hash(_safe(book, relative)) not in {before, after}:
                raise TransactionError("state_conflict: preserve external edit " + relative)
            if _hash(_safe(journal["checkpoint_root"], relative)) != before:
                raise TransactionError("checkpoint_mismatch: " + relative)
        journal["status"] = "recovering"
        _save(book, journal)
        for relative in reversed(journal["targets"]):
            target = _safe(book, relative)
            current = _hash(target)
            if current == journal["before"][relative]:
                continue
            if current != journal["after"][relative]:
                raise TransactionError("state_conflict: preserve external edit " + relative)
            if journal["before"][relative] is None:
                target.unlink()
                _flush_directory(target.parent)
            else:
                _install_file(_safe(journal["checkpoint_root"], relative), target)
    journal["status"] = "recovered"
    _save(book, journal)
    return journal


def recover(book):
    with transaction_lock(book):
        return _recover(book, load_journal(book))


def commit(book, self_review_confirmed=False):
    with transaction_lock(book):
        journal = load_journal(book)
        if not self_review_confirmed:
            raise TransactionError("self_review_confirmation_required")
        if journal["status"] != "validated":
            raise TransactionError("validation_required")
        stage = Path(journal["stage_root"])
        if book_hashes(stage) != journal["validated_hashes"]:
            raise TransactionError("stage_changed: rerun validate")
        if book_hashes(book) != journal["baseline"]:
            raise TransactionError("state_conflict: canonical changed; " + recovery_command(book))
        journal["status"] = "committing"
        _save(book, journal)
        try:
            for relative in journal["targets"]:
                target = _safe(book, relative)
                if _hash(target) != journal["before"][relative]:
                    raise TransactionError("state_conflict: " + relative)
                source = _safe(stage, relative)
                if _hash(source) != journal["after"][relative]:
                    raise TransactionError("stage_changed: " + relative)
                _install_file(source, target)
            expected = dict(journal["baseline"])
            expected.update(journal["after"])
            if book_hashes(book) != expected:
                raise TransactionError("state_conflict: changed during commit")
            journal["status"] = "committed"
            _save(book, journal)
            return journal
        except Exception as exc:
            journal["status"] = "committing"
            try:
                _recover(book, journal)
            except Exception as recovery_exc:
                raise TransactionError("transaction_incomplete: {}; {}; {}".format(
                    exc, recovery_exc, recovery_command(book))) from exc
            raise TransactionError("transaction_incomplete: rolled back; " + str(exc)) from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("book")
    prep.add_argument("--chapter", type=int, required=True)
    prep.add_argument("--chapter-file")
    val = sub.add_parser("validate")
    val.add_argument("book")
    val.add_argument("--min-chars", type=int, required=True)
    val.add_argument("--max-chars", type=int, required=True)
    val.add_argument("--declare", required=True)
    com = sub.add_parser("commit")
    com.add_argument("book")
    com.add_argument("--self-review-confirmed", action="store_true")
    rec = sub.add_parser("recover")
    rec.add_argument("book")
    status = sub.add_parser("status")
    status.add_argument("book")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.book, args.chapter, args.chapter_file)
        elif args.command == "validate":
            result = validate(args.book, args.min_chars, args.max_chars, args.declare)
        elif args.command == "commit":
            result = commit(args.book, args.self_review_confirmed)
        elif args.command == "recover":
            result = recover(args.book)
        else:
            result = pending_transaction(args.book) or {"status": "clean"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (TransactionError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
