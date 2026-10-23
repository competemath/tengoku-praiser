"""The reviewer's checks as evidence: findings in, one `mechanical.review.<check>` record per check out.

Every check in the reviewer family (style, lint, naming, docs, api_gaps, dedupe, reuse, generalise, minimise, robust, compat)
returns findings of one shape and goes through here, so a gate sees the same record whichever check made it. Nothing here
runs a tool: a check that did not run is `not_run`, and a check whose tool could not give an answer is `inconclusive`. Neither
is a pass.

A finding is {check, severity, name, line, detail, ...}. Severity:
  fail          the check found something a reviewer would send the proposal back for
  warn          worth a person's eye; recorded, never blocking by itself
  info          the record
  inconclusive  the tool could not decide (timeout, crash, unparsable output): that is not a pass
A finding may carry `patch`, the full text of a corrected module that the tool VERIFIED (the oracle compiled it). The record
keeps the patch's hash and size and the finding's name, not the patch: patches travel in files next to the record.
"""

from __future__ import annotations

import shlex
from collections import Counter
from typing import Callable, Iterable

from vendor.juridicator_evidence import canonical_json

from .common import cap_command, case_ref, clip, fit_details, kind_part, make, producer_ref, sha256_bytes

SEVERITIES = ("fail", "warn", "info", "inconclusive")
KIND_PREFIX = "mechanical.review."


def finding(check: str, severity: str, detail: str, *, name: str = "", line: int = 0, module: str = "", **extra) -> dict:
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}, not {severity!r}")
    if not isinstance(check, str) or not check.strip():
        raise ValueError("a finding needs a check")
    out = {"check": check, "severity": severity, "name": clip(name, 120), "line": int(line), "module": clip(module, 120),
           "detail": clip(detail, 300)}
    out.update(extra)
    return out


def _checked(f: object) -> dict:
    if not isinstance(f, dict) or not isinstance(f.get("check"), str) or not f["check"].strip():
        raise ValueError("a finding must be an object with a non-empty 'check'; refusing to drop it silently")
    if f.get("severity") not in SEVERITIES:
        raise ValueError(f"finding severity must be one of {SEVERITIES}")
    return f


def patch_digest(patch: str) -> dict:
    data = patch.encode("utf-8")
    return {"patch_sha256": sha256_bytes(data), "patch_bytes": len(data)}


def from_findings(
    findings: Iterable[dict],
    case: dict,
    producer: dict,
    checks: Iterable[str],
    created: str,
    *,
    ran: Iterable[str] = (),
    command_for: Callable[[str], str],
    label: Callable[[str], str] | None = None,
) -> list[dict]:
    """One record per check in `checks` (plus any check that has a finding, because a failure is never dropped for being unexpected).

    fail          any finding with severity fail
    inconclusive  no fail, at least one inconclusive finding
    pass          findings of lower severity only, or none and the check is in `ran`
    not_run       no findings and not marked as run (silence is not a pass)
    """
    findings = [_checked(f) for f in findings]
    by_check: dict[str, list[dict]] = {}
    for f in findings:
        by_check.setdefault(f["check"], []).append(f)
    ran_set = {str(c) for c in ran}
    names = sorted({str(c) for c in checks} | set(by_check))
    kinds: dict[str, str] = {}
    for n in names:
        part = kind_part(n)
        if part in kinds:
            raise ValueError(f"checks {kinds[part]!r} and {n!r} collide as kind {KIND_PREFIX}{part}")
        kinds[part] = n
    case_r, prod_r = case_ref(case), producer_ref(producer)
    pretty = label or (lambda c: c)
    out = []
    for part, n in sorted(kinds.items()):
        fs = by_check.get(n, [])
        counts = Counter(f["severity"] for f in fs)
        if counts["fail"]:
            outcome, claim = "fail", f"Review check {pretty(n)}: {counts['fail']} failing finding(s) of {len(fs)}."
        elif counts["inconclusive"]:
            outcome = "inconclusive"
            claim = f"Review check {pretty(n)}: could not decide ({counts['inconclusive']} inconclusive); that is not a pass."
        elif fs:
            outcome, claim = "pass", f"Review check {pretty(n)}: ran, nothing blocking ({len(fs)} finding(s) of lower severity)."
        elif n in ran_set:
            outcome, claim = "pass", f"Review check {pretty(n)}: ran and reported nothing."
        else:
            outcome, claim = "not_run", f"Review check {pretty(n)}: no finding and not marked as run; counted as missing."

        def row(f: dict) -> dict:
            r = {"name": clip(f.get("name", ""), 100), "line": f.get("line", 0), "detail": clip(f.get("detail", ""), 160)}
            if isinstance(f.get("patch"), str):
                r.update(patch_digest(f["patch"]))
            return r

        blocking = [row(f) for f in fs if f["severity"] == "fail"]
        undecided = [row(f) for f in fs if f["severity"] == "inconclusive"]
        notes = [row(f) for f in fs if f["severity"] == "warn"]
        details = {"check": clip(n, 80), "counts": dict(sorted(counts.items())), "n_findings": len(fs), "marked_run": n in ran_set,
                   "failing": blocking[:15], "undecided": undecided[:8], "warnings": notes[:15]}
        out.append(make(
            case=case_r, producer=prod_r, kind=f"{KIND_PREFIX}{part}", claim=clip(claim), outcome=outcome,
            verifiability="mechanical", created=created, reproduce={"command": cap_command(command_for(n))},
            details=fit_details(details, ("warnings", "undecided", "failing"))))
    return out


def command_template(template: str) -> Callable[[str], str]:
    """`command_for` from a template with `{check}`: `python3 -m praiser review --checks {check} ...`."""
    return lambda check: template.format(check=shlex.quote(check))


def findings_digest(findings: Iterable[dict]) -> str:
    """A hash of the findings (patches included) so a second run can be compared with the first byte for byte."""
    return sha256_bytes(canonical_json(sorted(
        (dict(f) for f in findings), key=lambda f: (f.get("check", ""), f.get("name", ""), f.get("line", 0), f.get("detail", "")))).encode("utf-8"))
