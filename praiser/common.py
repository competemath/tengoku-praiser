"""Small pure helpers shared by the modules. No file, network or clock access."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from vendor.juridicator_evidence import CONTROL, HEX64, MAX_CLAIM, MAX_COMMAND, SHA40, canonical_json, make_evidence, validate

PRAISER = {"role": "praiser", "name": "tengoku-praiser", "identity": "tengoku-praiser"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def case_ref(case: dict) -> dict:
    """The part of a case that goes into evidence: repo, commit and class. The author block never does (the judge
    reads it from the case, and copying it into every record would make record ids depend on it)."""
    if not isinstance(case, dict):
        raise ValueError("case must be an object")
    out = {k: case.get(k) for k in ("repo", "head_sha", "class")}
    if not all(isinstance(v, str) and v for v in out.values()):
        raise ValueError("case needs repo, head_sha and class")
    if not SHA40.match(out["head_sha"]):
        raise ValueError("case.head_sha must be a 40-hex commit")
    return out


def producer_ref(producer: dict) -> dict:
    if not isinstance(producer, dict) or not all(isinstance(producer.get(k), str) and producer[k] for k in ("role", "name", "identity")):
        raise ValueError("producer needs role, name and identity")
    return {k: producer[k] for k in ("role", "name", "identity")}


def clip(text: Any, limit: int = MAX_CLAIM) -> str:
    """One line of plain text, control characters removed, cut to `limit` with an ellipsis."""
    s = " ".join(CONTROL.sub(" ", str(text)).split())
    return s if len(s) <= limit else s[: limit - 3] + "..."


def require_hex64(value: Any, name: str) -> str:
    if not isinstance(value, str) or not HEX64.match(value):
        raise ValueError(f"{name} must be a lowercase 64-hex sha-256")
    return value


def hash_map(value: Any, name: str) -> dict[str, str]:
    """A declaration {stored path: sha-256}. Each hash must name a path, or it could never be checked."""
    if not isinstance(value, dict):
        raise ValueError(f"{name} must map stored paths to sha-256 hashes")
    out = {}
    for path, digest in value.items():
        if not isinstance(path, str) or not path or CONTROL.search(path):
            raise ValueError(f"{name} has a bad path")
        out[path] = require_hex64(digest, f"{name}[{path}]")
    return out


def cap_command(command: str) -> str:
    """Keep a reproduce command inside the contract's length limit without ever returning an empty one."""
    command = " ".join(command.split())
    return command if len(command) <= MAX_COMMAND else command[: MAX_COMMAND - 3] + "..."


KIND_PART = re.compile(r"[^a-z0-9_]+")


def kind_part(name: str) -> str:
    """Turn a free-form check name into the lowercase [a-z0-9_] form a kind needs."""
    part = KIND_PART.sub("_", str(name).lower()).strip("_")
    if not part:
        raise ValueError(f"cannot make a kind out of {name!r}")
    return part


def fit_details(details: dict, droppable: tuple[str, ...] = (), limit: int = 7000) -> dict:
    """Keep `details` inside the contract's size limit by dropping the named bulky keys (in order) and saying so.
    Nothing a decision reads is ever dropped: callers list only listings meant for people."""
    from vendor.juridicator_evidence import MAX_DETAILS_BYTES

    limit = min(limit, MAX_DETAILS_BYTES - 500)
    out = dict(details)
    dropped = []
    for key in droppable:
        if len(canonical_json(out).encode("utf-8")) <= limit:
            break
        if key in out:
            del out[key]
            dropped.append(key)
    if dropped:
        out["dropped_for_size"] = dropped
    return out


def make(**fields: Any) -> dict:
    """`make_evidence`, then `validate`: a record this package emits is well formed or the call raises ValueError.
    (Well formed is not the same as true; the judge decides what is true enough.)"""
    ev = make_evidence(**fields)
    errors = validate(ev)
    if errors:
        raise ValueError("cannot make a valid record: " + "; ".join(errors[:3]))
    return ev
