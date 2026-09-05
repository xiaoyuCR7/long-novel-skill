#!/usr/bin/env python3
"""Explicit author preferences; Python 3.8+, standard library only.

State belongs to an explicitly selected workspace, never the user's home.
Queries are read-only and emit at most 2048 UTF-8 bytes including the newline.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid

from common import atomic_write_json, ensure_utf8_stdout
from source_materialize import _safe_path


SCOPES = ("global", "genre", "workflow", "book")
KINDS = ("prose_style", "story_design", "workflow", "interaction")
QUERY_BYTES = 2048
STATE_BYTES = 4 * 1024 * 1024


class PreferenceError(ValueError):
    """Invalid input/state, conflict, or unsafe concurrent access."""


def serialize(value):
    """Canonical compact UTF-8 CLI serialization, including its one newline."""
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _nonempty(value, label, maximum=10000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PreferenceError("invalid " + label)
    # Reject lone surrogates before any filesystem mutation.
    value.encode("utf-8")


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 2 ** 53 - 1


def _scope(scope, value):
    if scope not in SCOPES:
        raise PreferenceError("invalid scope")
    _nonempty(value, "scope-value", 200)
    if (scope == "global" and value != "*") or (scope != "global" and value == "*"):
        raise PreferenceError("global scope-value must be '*'; other scopes need a specific value")


def _paths(workspace):
    if workspace is None or not str(workspace).strip():
        raise PreferenceError("explicit workspace is required")
    root = _safe_path(workspace)
    if not root.is_dir():
        raise PreferenceError("workspace must be an existing directory")
    state = _safe_path(root / ".novel" / "author-preferences.json")
    if state.parent.exists() and not state.parent.is_dir():
        raise PreferenceError(".novel must be a directory")
    return state


def _identity(entry):
    return entry["scope"], entry["scope_value"], entry["kind"], entry["key"]


def _validate_state(state):
    if not isinstance(state, dict) or set(state) != {"schema_version", "revision", "entries", "events"}:
        raise PreferenceError("malformed preference state")
    if type(state["schema_version"]) is not int or state["schema_version"] != 1:
        raise PreferenceError("unsupported preference schema_version")
    if not _integer(state["revision"]) or not isinstance(state["entries"], list) or not isinstance(state["events"], list):
        raise PreferenceError("malformed preference state")
    ids, active_keys = set(), set()
    for entry in state["entries"]:
        fields = {"id", "revision", "scope", "scope_value", "kind", "key", "text", "active", "history"}
        if not isinstance(entry, dict) or set(entry) != fields:
            raise PreferenceError("malformed preference entry")
        _nonempty(entry["id"], "id", 100)
        _scope(entry["scope"], entry["scope_value"])
        _nonempty(entry["key"], "key", 120)
        _nonempty(entry["text"], "text")
        if entry["kind"] not in KINDS or type(entry["active"]) is not bool:
            raise PreferenceError("invalid preference kind or active flag")
        if not _integer(entry["revision"], 1) or entry["revision"] > state["revision"]:
            raise PreferenceError("invalid entry revision")
        history = entry["history"]
        if not isinstance(history, list) or len(history) != entry["revision"]:
            raise PreferenceError("invalid preference history")
        for revision, item in enumerate(history, 1):
            if not isinstance(item, dict) or set(item) != {"revision", "action", "text", "evidence", "at"}:
                raise PreferenceError("malformed preference history")
            if type(item["revision"]) is not int or item["revision"] != revision:
                raise PreferenceError("invalid history revision")
            if item["action"] not in ("remember", "replace", "forget"):
                raise PreferenceError("invalid history action")
            for field in ("text", "evidence", "at"):
                _nonempty(item[field], "history " + field)
            if (revision == 1) != (item["action"] == "remember"):
                raise PreferenceError("invalid initial history action")
            if item["action"] == "forget" and revision != len(history):
                raise PreferenceError("revoked preference cannot be reactivated")
        if history[-1]["text"] != entry["text"] or entry["active"] != (history[-1]["action"] != "forget"):
            raise PreferenceError("entry/history mismatch")
        if entry["id"] in ids or (entry["active"] and _identity(entry) in active_keys):
            raise PreferenceError("duplicate preference id or active conflict")
        ids.add(entry["id"])
        if entry["active"]:
            active_keys.add(_identity(entry))
    event_ids, recorded_changes = set(), set()
    by_id = {entry["id"]: entry for entry in state["entries"]}
    for state_revision, event in enumerate(state["events"], 1):
        if not isinstance(event, dict) or set(event) != {"event_id", "fingerprint", "receipt"}:
            raise PreferenceError("malformed preference event")
        _nonempty(event["event_id"], "event-id", 200)
        fingerprint = event["fingerprint"]
        if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise PreferenceError("invalid event fingerprint")
        receipt = event["receipt"]
        if not isinstance(receipt, dict) or set(receipt) != {"event_id", "action", "id", "revision", "entry_revision"}:
            raise PreferenceError("malformed mutation receipt")
        if receipt["event_id"] != event["event_id"] or receipt["id"] not in ids or receipt["action"] not in ("remember", "replace", "forget"):
            raise PreferenceError("invalid mutation receipt")
        if not _integer(receipt["revision"], 1) or receipt["revision"] != state_revision or not _integer(receipt["entry_revision"], 1):
            raise PreferenceError("invalid receipt revision")
        entry = by_id[receipt["id"]]
        change = receipt["id"], receipt["entry_revision"]
        if (receipt["entry_revision"] > entry["revision"] or change in recorded_changes
                or entry["history"][receipt["entry_revision"] - 1]["action"] != receipt["action"]):
            raise PreferenceError("receipt/history mismatch")
        recorded_changes.add(change)
        if event["event_id"] in event_ids:
            raise PreferenceError("duplicate event-id")
        event_ids.add(event["event_id"])
    if len(state["events"]) != state["revision"] or sum(e["revision"] for e in state["entries"]) != state["revision"]:
        raise PreferenceError("inconsistent state revision")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PreferenceError("duplicate JSON key")
        result[key] = value
    return result


def _load(path):
    _safe_path(path)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return {"schema_version": 1, "revision": 0, "entries": [], "events": []}, None
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise PreferenceError("state must be a regular file without hard links")
    if before.st_size > STATE_BYTES:
        raise PreferenceError("preference state exceeds size limit")
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb") as handle:
        if not os.path.samestat(before, os.fstat(handle.fileno())):
            raise PreferenceError("state changed before read")
        raw = handle.read(STATE_BYTES + 1)
    _safe_path(path)
    after = path.stat()
    if len(raw) > STATE_BYTES or not os.path.samestat(before, after) or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise PreferenceError("state changed during read")
    try:
        state = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        _validate_state(state)
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise PreferenceError("malformed preference state: " + str(error)) from error
    return state, hashlib.sha256(raw).hexdigest()


@contextmanager
def _writer_lock(path):
    _safe_path(path.parent)
    path.parent.mkdir(exist_ok=True)
    lock = _safe_path(path.parent / "author-preferences.lock")
    try:
        descriptor = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError as error:
        raise PreferenceError("preferences locked; retry after the other writer finishes") from error
    owned = os.fstat(descriptor)
    os.close(descriptor)
    try:
        yield
    finally:
        _safe_path(lock)
        if lock.exists() and os.path.samestat(owned, lock.stat()):
            lock.unlink()


def check_preferences(workspace):
    """Validate state without initializing, repairing, or acquiring a write lock."""
    state, token = _load(_paths(workspace))
    return {"valid": True, "exists": token is not None, "revision": state["revision"],
            "active": sum(e["active"] for e in state["entries"]), "total": len(state["entries"])}


def query_preferences(workspace, book=None, genre=None, workflow=None, kinds=None):
    """Return bounded active preferences; callers should use serialize()."""
    selected = set(KINDS if kinds is None else kinds)
    if not selected.issubset(KINDS):
        raise PreferenceError("invalid query kind")
    context = {"global": "*", "book": book, "genre": genre, "workflow": workflow}
    for scope in ("book", "genre", "workflow"):
        if context[scope] is not None:
            _scope(scope, context[scope])
    state, _ = _load(_paths(workspace))
    matches = [e for e in state["entries"] if e["active"] and e["kind"] in selected
               and context[e["scope"]] == e["scope_value"]]
    matches.sort(key=lambda e: (-SCOPES.index(e["scope"]), e["kind"], e["key"], e["id"]))
    winners, seen = [], set()
    for entry in matches:
        topic = entry["kind"], entry["key"]
        if topic not in seen:
            winners.append(entry)
            seen.add(topic)
    output = {"revision": state["revision"], "entries": [], "omitted": len(winners),
              "shadowed": len(matches) - len(winners)}
    for entry in winners:
        public = {key: entry[key] for key in ("id", "revision", "scope", "scope_value", "kind", "key", "text")}
        public["evidence"] = entry["history"][-1]["evidence"]
        output["entries"].append(public)
        output["omitted"] -= 1
        if len(serialize(output)) > QUERY_BYTES:
            output["entries"].pop()
            output["omitted"] += 1
    return output


def apply_change(workspace, action, author_confirmed=False, evidence=None,
                 expected_revision=None, event_id=None, scope=None, scope_value=None,
                 kind=None, key=None, text=None, entry_id=None):
    """Apply one explicitly authorized change, atomically with its receipt."""
    if author_confirmed is not True:
        raise PreferenceError("explicit --author-confirmed is required; inferred preferences are not authorization")
    _nonempty(evidence, "author evidence")
    if not _integer(expected_revision):
        raise PreferenceError("--expected-revision is required and must be a nonnegative integer")
    if action not in ("remember", "replace", "forget"):
        raise PreferenceError("invalid mutation action")
    if event_id is not None:
        _nonempty(event_id, "event-id", 200)
    if action == "remember":
        _scope(scope, scope_value)
        if kind not in KINDS:
            raise PreferenceError("invalid kind; local story facts are not author preferences")
        _nonempty(key, "key", 120)
    else:
        _nonempty(entry_id, "id", 100)
    if action != "forget":
        _nonempty(text, "text")
    request = {"action": action, "scope": scope, "scope_value": scope_value, "kind": kind,
               "key": key, "text": text, "id": entry_id, "evidence": evidence}
    fingerprint = hashlib.sha256(serialize(request)).hexdigest()
    path = _paths(workspace)
    # Fail on malformed state before even creating the transient writer lock.
    _load(path)
    with _writer_lock(path):
        state, token = _load(path)
        for event in state["events"]:
            if event["event_id"] == event_id:
                if event["fingerprint"] != fingerprint:
                    raise PreferenceError("event-id conflict: this event already records a different request")
                return event["receipt"]
        if state["revision"] != expected_revision:
            raise PreferenceError("revision conflict: expected %s, current %s" % (expected_revision, state["revision"]))
        if action == "remember":
            entry = {"id": uuid.uuid4().hex, "revision": 1, "scope": scope, "scope_value": scope_value,
                     "kind": kind, "key": key, "text": text, "active": True, "history": []}
            if any(e["active"] and _identity(e) == _identity(entry) for e in state["entries"]):
                raise PreferenceError("preference conflict: use replace with the existing id and author confirmation")
            state["entries"].append(entry)
        else:
            entry = next((e for e in state["entries"] if e["id"] == entry_id), None)
            if entry is None or not entry["active"]:
                raise PreferenceError("id does not identify an active preference")
            entry["revision"] += 1
            if action == "replace":
                entry["text"] = text
            else:
                entry["active"] = False
        entry["history"].append({"revision": entry["revision"], "action": action, "text": entry["text"],
                                 "evidence": evidence, "at": datetime.now(timezone.utc).isoformat()})
        state["revision"] += 1
        receipt = {"event_id": event_id or uuid.uuid4().hex, "action": action, "id": entry["id"],
                   "revision": state["revision"], "entry_revision": entry["revision"]}
        state["events"].append({"event_id": receipt["event_id"], "fingerprint": fingerprint, "receipt": receipt})
        _validate_state(state)
        # atomic_write_json uses text mode: Windows writes each LF as CRLF.
        encoded_state = json.dumps(state, ensure_ascii=False, indent=2).replace("\n", os.linesep).encode("utf-8")
        if len(encoded_state) > STATE_BYTES:
            raise PreferenceError("preference state exceeds size limit")
        if _load(path)[1] != token:
            raise PreferenceError("state changed before write; refusing overwrite")
        _safe_path(path)
        atomic_write_json(path, state)
        return receipt


def main(argv=None):
    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("query", "check", "remember", "replace", "forget"):
        command = commands.add_parser(name)
        command.add_argument("--workspace", required=True, help="existing workspace; no default or home fallback")
        if name == "query":
            for scope in ("book", "genre", "workflow"):
                command.add_argument("--" + scope)
            command.add_argument("--kind", choices=KINDS, action="append", dest="kinds")
        elif name != "check":
            command.add_argument("--author-confirmed", action="store_true")
            command.add_argument("--evidence", required=True, help="the author's explicit authorization text")
            command.add_argument("--expected-revision", type=int, required=True)
            command.add_argument("--event-id", help="reuse for an identical retry, including after uncertain output")
            if name == "remember":
                command.add_argument("--scope", choices=SCOPES, required=True)
                command.add_argument("--scope-value", required=True)
                command.add_argument("--kind", choices=KINDS, required=True)
                command.add_argument("--key", required=True, help="stable topic key; reuse it for the same preference topic")
            else:
                command.add_argument("--id", required=True, dest="entry_id")
            if name != "forget":
                command.add_argument("--text", required=True)
    arguments = vars(parser.parse_args(argv))
    command = arguments.pop("command")
    try:
        if command == "query":
            result = query_preferences(**arguments)
        elif command == "check":
            result = check_preferences(**arguments)
        else:
            result = apply_change(action=command, **arguments)
        # Byte output avoids Windows newline translation violating the byte cap.
        sys.stdout.buffer.write(serialize(result))
        sys.stdout.buffer.flush()
        return 0
    except (ValueError, OSError, UnicodeError, RecursionError) as error:
        print("[ERROR] " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
