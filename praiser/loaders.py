"""Thin loaders: the only place that touches files. The logic modules never import this."""

from __future__ import annotations

import glob
import json
import os

MAX_FILE = 16 * 1024 * 1024


class InputError(ValueError):
    """Bad input from the outside world (unreadable file, wrong shape, path that escapes the checkout)."""


def read_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc


def read_records(paths: list[str]) -> list:
    """Records from .json files (an object or a list) and .jsonl files; a directory contributes its .json/.jsonl files."""
    files: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "*.json")) + glob.glob(os.path.join(p, "*.jsonl")))
        else:
            files.append(p)
    out: list = []
    for f in files:
        if f.endswith(".jsonl"):
            out += read_ledger(f)
        else:
            data = read_json(f)
            out += data if isinstance(data, list) else [data]
    return out


def read_ledger(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except (OSError, ValueError) as exc:
        raise InputError(f"cannot read ledger {path}: {exc}") from exc


def read_files_under(root: str, paths) -> dict[str, bytes]:
    """{declared path: bytes} for the declared paths that exist as regular files inside `root`. A path that is absolute,
    climbs out with `..`, or resolves (through a symlink) outside the root is an error, not a silent skip: a declaration
    must not be able to make the checker read something else. A path that simply is not there is left out, and the check
    reports it as "not stored"."""
    base = os.path.realpath(root)
    if not os.path.isdir(base):
        raise InputError(f"{root} is not a directory")
    out: dict[str, bytes] = {}
    for p in paths:
        if os.path.isabs(p) or ".." in p.replace("\\", "/").split("/"):
            raise InputError(f"declared path {p!r} is not a path inside the checkout")
        full = os.path.realpath(os.path.join(base, p))
        if os.path.commonpath([base, full]) != base:
            raise InputError(f"declared path {p!r} resolves outside the checkout")
        if os.path.isfile(full):
            if os.path.getsize(full) > MAX_FILE:
                raise InputError(f"{p} is larger than {MAX_FILE} bytes")
            with open(full, "rb") as fh:
                out[p] = fh.read()
    return out


def write_json(obj, path: str | None) -> None:
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if not path or path == "-":
        print(text, end="")
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
