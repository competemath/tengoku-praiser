"""Refresh the vendored evidence contract from a juridicator checkout.

    python3 scripts/sync_contract.py --from ../tengoku-juridicator

Copies juridicator/evidence.py byte for byte to vendor/juridicator_evidence.py and rewrites vendor/EVIDENCE.sha256.
It refuses a checkout whose evidence.py differs from the one committed at its HEAD, because the pin must name a
commit anyone can fetch. This is a developer tool (it runs git); nothing in the `praiser` package does.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_PATH = "juridicator/evidence.py"
VENDORED = os.path.join(ROOT, "vendor", "juridicator_evidence.py")
PIN = os.path.join(ROOT, "vendor", "EVIDENCE.sha256")
PIN_RE = re.compile(r"^([0-9a-f]{64})  (\S+)  # tengoku-juridicator ([0-9a-f]{40})\n?$")


def render_pin(sha256: str, commit: str) -> str:
    return f"{sha256}  {SOURCE_PATH}  # tengoku-juridicator {commit}\n"


def parse_pin(text: str) -> tuple[str, str, str]:
    """(sha256, path, juridicator commit). Raises ValueError when the line is not in the pinned shape."""
    m = PIN_RE.match(text)
    if not m:
        raise ValueError("vendor/EVIDENCE.sha256 is not '<sha256>  juridicator/evidence.py  # tengoku-juridicator <commit>'")
    return m.group(1), m.group(2), m.group(3)


def _git(checkout: str, *args: str) -> bytes:
    return subprocess.run(["git", "-C", checkout, *args], check=True, capture_output=True).stdout


def sync(checkout: str) -> str:
    src = os.path.join(checkout, SOURCE_PATH)
    with open(src, "rb") as fh:
        data = fh.read()
    commit = _git(checkout, "rev-parse", "HEAD").decode().strip()
    committed = _git(checkout, "show", f"HEAD:{SOURCE_PATH}")
    if committed != data:
        raise SystemExit("refusing: evidence.py in that checkout differs from the one committed at its HEAD")
    digest = hashlib.sha256(data).hexdigest()
    with open(VENDORED, "wb") as fh:
        fh.write(data)
    with open(PIN, "w", encoding="utf-8") as fh:
        fh.write(render_pin(digest, commit))
    return digest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="source", required=True, help="path to a tengoku-juridicator checkout")
    args = ap.parse_args(argv)
    print(sync(args.source))
    return 0


if __name__ == "__main__":
    sys.exit(main())
