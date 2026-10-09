"""Reproducibility: two independent rebuilds that produce the same thing.

A receipt records what one runner did: the command, a digest of its environment, a digest of its output and the exit
code, sealed with a hash of those fields. Two receipts from different runners that agree are evidence the result does
not depend on one machine. The same runner twice proves little, so that is `inconclusive`, not `pass`.
"""

from __future__ import annotations

from vendor.juridicator_evidence import canonical_json

from .common import cap_command, case_ref, clip, make, producer_ref, require_hex64, sha256_bytes

FIELDS = ("command", "env_digest", "stdout_digest", "exit_code")


def digest_of(data: bytes) -> str:
    """The digest to use for stdout (or any output) when making a receipt."""
    return sha256_bytes(data)


def digest_env(env: dict) -> str:
    """A digest of an environment description (toolchain version, OS image, locked inputs): canonical JSON, sorted keys."""
    return sha256_bytes(canonical_json(env).encode("utf-8"))


def _seal(body: dict) -> str:
    return sha256_bytes(canonical_json(body).encode("utf-8"))


def make_receipt(command: str, env_digest: str, stdout_digest: str, exit_code: int, *, runner: str | None = None) -> dict:
    """A receipt with its own hash. `runner` names who ran it (a distinct machine or bot identity) so the comparison can
    tell two independent runs from one run counted twice."""
    if not isinstance(command, str) or not command.strip():
        raise ValueError("a receipt needs the command that was run")
    require_hex64(env_digest, "env_digest")
    require_hex64(stdout_digest, "stdout_digest")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise ValueError("exit_code must be an integer")
    body = {"command": command, "env_digest": env_digest, "stdout_digest": stdout_digest, "exit_code": exit_code,
            "runner": runner}
    body["receipt_sha256"] = _seal(body)
    return body


def verify_receipt(receipt: dict) -> bool:
    if not isinstance(receipt, dict) or not all(k in receipt for k in FIELDS + ("receipt_sha256",)):
        return False
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    return receipt["receipt_sha256"] == _seal(body)


def compare_receipts(a: dict, b: dict, case: dict, producer: dict, created: str) -> dict:
    """`reproducible.rebuild_match`. pass iff command, env digest, stdout digest and exit code are all equal AND the two
    receipts come from different runners. A difference is a fail naming the field(s). Equal receipts from one runner (or
    with no runner stated) are inconclusive. A receipt whose seal does not verify is refused (ValueError)."""
    for r in (a, b):
        if not verify_receipt(r):
            raise ValueError("a receipt is malformed or was altered after it was sealed")
    differing = [f for f in FIELDS if a[f] != b[f]]
    ra, rb = a.get("runner"), b.get("runner")
    if differing:
        outcome, claim = "fail", clip("The two rebuilds differ in: " + ", ".join(differing) + ".")
    elif not ra or not rb or ra == rb:
        outcome, claim = "inconclusive", "The rebuilds agree, but they were not shown to come from two different runners: the same runner twice proves little."
    else:
        outcome, claim = "pass", "Two independent rebuilds agree on command, environment, output and exit code."
    how = (f"python3 -m praiser compare-receipts receipt_a.json receipt_b.json   # receipts come from running: {a['command']}")
    return make(
        case=case_ref(case), producer=producer_ref(producer), kind="reproducible.rebuild_match", claim=claim,
        outcome=outcome, verifiability="reproducible", created=created, reproduce={"command": cap_command(how)},
        details={"differing": differing, "runners": [clip(ra or "", 80), clip(rb or "", 80)],
                 "receipts": [a["receipt_sha256"], b["receipt_sha256"]], "stdout_digest": a["stdout_digest"],
                 "env_digest": a["env_digest"], "exit_code": a["exit_code"]},
    )
