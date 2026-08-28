#!/usr/bin/env python3
"""Copy one file's raw bytes, without rewriting or replacing user files.

Publication requires hard-link support on the destination filesystem; failure
does not fall back to an overwriting rename. `identical` means current bytes
match, not that an earlier interrupted operation completed. Read/hash/stat
checks detect observed concurrent changes, not an absolute filesystem snapshot.
--text-json accepts a UTF-8 JSON single string as conversation text, emitting
its exact UTF-8 representation, not claiming original uploaded-file bytes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile


def _safe_path(path):
    path = Path(os.path.abspath(os.fspath(path)))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("unsafe link/reparse point: " + str(part))
    return path


def _signature(info):
    # Windows path stat and descriptor stat may expose different ctime meanings
    # (birth time versus change time). Content is independently rehashed below.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns if os.name != "nt" else None)


def _digest(handle):
    digest = hashlib.sha256()
    count = 0
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        count += len(chunk)
        digest.update(chunk)
    return count, digest.hexdigest()


def _read_file(path):
    _safe_path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("not a regular file: " + str(path))
    with path.open("rb") as handle:
        if _signature(os.fstat(handle.fileno())) != _signature(before):
            raise RuntimeError("file changed before reading: " + str(path))
        result = _digest(handle)
        if _signature(os.fstat(handle.fileno())) != _signature(before):
            raise RuntimeError("file changed while reading: " + str(path))
    _safe_path(path)
    if _signature(path.stat()) != _signature(before):
        raise RuntimeError("file changed while reading: " + str(path))
    return result, before


def _verify_source(source, before, expected):
    actual, after = _read_file(source)
    if _signature(before) != _signature(after) or actual != expected:
        raise RuntimeError("source changed during copy: " + str(source))


def copy_source(source, destination):
    """Return source/destination/bytes/sha256/status after raw-byte verification.

    Parents must exist. All symlinks/reparse points are rejected, including
    ancestor links. Only a temporary file owned by this call is cleaned up;
    an existing or concurrently published destination is never removed.
    """
    return _materialize(source, destination, text_json=False)


def materialize_text_source(source_json, destination):
    """Materialize one JSON string as UTF-8, without normalization or added LF."""
    return _materialize(source_json, destination, text_json=True)


def _materialize(source, destination, text_json):
    source, destination = _safe_path(source), _safe_path(destination)
    source_expected, before = _read_file(source)
    expected = source_expected
    payload = None
    representation = "conversation_string_utf8" if text_json else "file_bytes"
    if text_json:
        raw = source.read_bytes()
        if (len(raw), hashlib.sha256(raw).hexdigest()) != source_expected:
            raise RuntimeError("source JSON changed while reading")
        value = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(value, str):
            raise ValueError("--text-json requires a single JSON string")
        payload = value.encode("utf-8")
        expected = (len(payload), hashlib.sha256(payload).hexdigest())
        _verify_source(source, before, source_expected)
    if destination.exists():
        actual, _ = _read_file(destination)
        _verify_source(source, before, source_expected)
        if actual != expected:
            raise FileExistsError("destination differs; refusing overwrite: " + str(destination))
        return {"source": str(source), "destination": str(destination),
                "bytes": actual[0], "sha256": actual[1], "status": "identical",
                "representation": representation}

    descriptor, name = tempfile.mkstemp(prefix=".source-materialize-", dir=str(destination.parent))
    temporary = Path(name)
    owned = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "w+b") as output:
            _safe_path(source)
            if payload is not None:
                output.write(payload)
            else:
                with source.open("rb") as input_file:
                    if _signature(os.fstat(input_file.fileno())) != _signature(before):
                        raise RuntimeError("source changed before copy: " + str(source))
                    for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                        output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        actual, _ = _read_file(temporary)
        if actual != expected:
            raise RuntimeError("destination readback mismatch")
        _verify_source(source, before, source_expected)
        _safe_path(destination)
        # Atomic, exclusive publication: unlike replace/rename, never overwrites.
        os.link(str(temporary), str(destination))
        actual, _ = _read_file(destination)
        if actual != expected:
            raise RuntimeError("published destination readback mismatch")
        _verify_source(source, before, source_expected)
        return {"source": str(source), "destination": str(destination),
                "bytes": actual[0], "sha256": actual[1], "status": "copied",
                "representation": representation}
    finally:
        # Do not delete a replacement created by another writer, even on failure.
        try:
            current = temporary.lstat()
            if (stat.S_ISREG(current.st_mode) and current.st_dev == owned.st_dev
                    and current.st_ino == owned.st_ino):
                temporary.unlink()
        except FileNotFoundError:
            pass


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(description="Copy a file's original bytes; never overwrite a different target")
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--text-json", action="store_true",
                        help="source is a UTF-8 file containing one JSON string, emitted as exact UTF-8")
    args = parser.parse_args()
    try:
        materialize = materialize_text_source if args.text_json else copy_source
        result = materialize(args.source, args.destination)
    except (OSError, ValueError, RuntimeError) as exc:
        print("source_materialize failed: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
