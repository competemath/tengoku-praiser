"""Reputation that cannot be bought or invented: a track record computed from the public ledger.

Inputs are juridicator ledger entries, `{"seq", "kind", "body", "prev", "hash"}`, kinds `evidence`, `verdict`, `label`.

What counts, and what does not
  * The author system of a commit is the `producer.identity` of an `attested.provenance` evidence entry (role
    `author-system`) for that (repo, head_sha). If several identities claim one commit, none gets credit for it (credit
    needs a single claimant) but each is charged for a confirmed bad outcome (nobody can escape a bad one by adding a
    second claimant).
  * Only the commit's final verdict being ACCEPT, followed by a LATER human label, produces an outcome:
    label "accept" is confirmed good, label "reject" is confirmed bad. An ACCEPT nobody examined counts for NOTHING.
  * A label does not count if it is by the author system itself, or by any identity that produced non-human evidence in
    this ledger, or (when an allow-list `humans` is given) by anyone outside it. Each labeler's last label stands; if
    labelers disagree, reject wins (a person found it bad; a later person can only add their own label, not erase it).

The number (formula `track/1`, kept deliberately simple)
  age(case)    = how many other labelled outcomes were decided by a later label entry (position in the ledger)
  weight(case) = 0.5 ** (age / 200)                       half-life of 200 labelled cases
  good         = sum of weight over confirmed good cases
  failures     = sum of weight over confirmed good-turned-bad cases, times 10 (a confirmed bad counts as ten failures)
  lower_bound  = wilson_lower(good, good + failures)      95% Wilson lower bound; 0 when there is no outcome

Because of the decay, the total weight any author can have is below 1 / (1 - 0.5 ** (1/200)) = about 289, so no volume of
easy cases pushes the bound past about 0.987, and ten times as many cases do not help ten times as much.

`verify_against_ledger` re-derives a claimed record from the ledger. The statute reads `details.lower_bound` as given, so
whoever relies on a track record should call it: a record is only as good as that re-derivation.
"""

from __future__ import annotations

import math
import shlex
from typing import Iterable

from vendor.juridicator_evidence import canonical_json, sha256_text, validate

from .common import cap_command, case_ref, clip, make, producer_ref

FORMULA = "track/1"
HALF_LIFE = 200
FAILURE_WEIGHT = 10
GENESIS = "sha256:" + "0" * 64
NON_HUMAN_ROLES = ("wounder", "praiser", "tooling", "author-system", "judge-ai")


class LedgerError(ValueError):
    pass


def wilson_lower(successes: float, n: float, z: float = 1.96) -> float:
    """Lower end of the Wilson score interval for a proportion. 0 when there is nothing to count."""
    if n <= 0:
        return 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def entry_hash(seq: int, kind: str, body: dict, prev: str) -> str:
    """The juridicator ledger's entry hash, restated here because the ledger is not part of the vendored contract.
    tests/test_integration.py checks it against the real ledger when a checkout is present."""
    return "sha256:" + sha256_text(canonical_json({"seq": seq, "kind": kind, "body": body, "prev": prev}))


def verify_chain(entries: list[dict]) -> tuple[bool, int | None]:
    prev = GENESIS
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            return False, i
        if e.get("seq") != i or e.get("prev") != prev or e.get("hash") != entry_hash(i, e.get("kind", ""), e.get("body", {}), prev):
            return False, i
        prev = e["hash"]
    return True, None


def _key(where: object) -> tuple[str, str] | None:
    if not isinstance(where, dict):
        return None
    repo, head = where.get("repo"), where.get("head_sha")
    return (repo, head) if isinstance(repo, str) and isinstance(head, str) else None


def _derive(entries: list[dict], humans: set[str] | None) -> dict[str, dict]:
    """{author system: {"events": [(label seq, "good"|"bad")], "n_unlabeled", "n_ambiguous"}} for every author system."""
    claims: dict[tuple, set[str]] = {}
    non_human: set[str] = set()
    verdicts: dict[tuple, tuple[int, str]] = {}
    labels: dict[tuple, list[tuple[int, str, str]]] = {}
    for e in entries:
        body = e.get("body")
        if not isinstance(body, dict):
            continue
        if e["kind"] == "evidence":
            if validate(body):
                continue
            role = body["producer"]["role"]
            if role in NON_HUMAN_ROLES:
                non_human.add(body["producer"]["identity"])
            if body["kind"] == "attested.provenance" and role == "author-system":
                claims.setdefault((body["case"]["repo"], body["case"]["head_sha"]), set()).add(body["producer"]["identity"])
        elif e["kind"] == "verdict":
            key = _key(body.get("case"))
            if key and isinstance(body.get("decision"), str):
                verdicts[key] = (e["seq"], body["decision"])
        elif e["kind"] == "label":
            key = _key(body)
            if key and body.get("label") in ("accept", "reject") and isinstance(body.get("by"), str) and body["by"]:
                labels.setdefault(key, []).append((e["seq"], body["label"], body["by"]))
    out: dict[str, dict] = {}
    for key, who in sorted(claims.items()):
        if key not in verdicts or verdicts[key][1] != "ACCEPT":
            continue
        vseq = verdicts[key][0]
        for author in sorted(who):
            res = out.setdefault(author, {"events": [], "n_unlabeled": 0, "n_ambiguous": 0})
            last: dict[str, tuple[int, str]] = {}
            for seq, label, by in labels.get(key, []):
                # The author system is a non-human producer by construction (its provenance record made it one), so its own labels,
                # like those of any tool, bot or reviewer AI in this ledger, never count.
                if seq > vseq and by not in non_human and (humans is None or by in humans):
                    last[by] = (seq, label)
            if not last:
                res["n_unlabeled"] += 1
                continue
            bad = any(label == "reject" for _, label in last.values())
            if not bad and len(who) > 1:
                res["n_ambiguous"] += 1
                continue
            res["events"].append((max(seq for seq, _ in last.values()), "bad" if bad else "good"))
    return out


def compute(entries: list[dict], author: str, *, humans: Iterable[str] | None = None, as_of_seq: int | None = None) -> dict:
    """The statistics for one author system as of ledger entry `as_of_seq` (default: the last). Raises LedgerError when
    the hash chain is broken, because a number derived from a tampered ledger means nothing."""
    ok, bad = verify_chain(entries)
    if not ok:
        raise LedgerError(f"the ledger's hash chain breaks at entry {bad}")
    last = len(entries) - 1 if as_of_seq is None else as_of_seq
    if not isinstance(last, int) or isinstance(last, bool) or last < -1 or last > len(entries) - 1:
        raise LedgerError("as_of_seq is outside the ledger")
    window = entries[: last + 1]
    derived = _derive(window, None if humans is None else {str(h) for h in humans})
    # Age is measured against every author's outcomes, so one author cannot make their own record look recent.
    all_seqs = {seq for res in derived.values() for seq, _ in res["events"]}
    res = derived.get(author, {"events": [], "n_unlabeled": 0, "n_ambiguous": 0})
    good = bad_w = 0.0
    n_good = n_bad = 0
    for seq, outcome in res["events"]:
        weight = 0.5 ** (sum(1 for s in all_seqs if s > seq) / HALF_LIFE)
        if outcome == "good":
            good += weight
            n_good += 1
        else:
            bad_w += weight
            n_bad += 1
    lower = wilson_lower(good, good + FAILURE_WEIGHT * bad_w)
    return {
        "author_system": author,
        "lower_bound": round(lower, 6),
        "n_good": n_good,
        "n_bad": n_bad,
        "n_unlabeled": res["n_unlabeled"],
        "n_ambiguous": res["n_ambiguous"],
        "weighted_good": round(good, 6),
        "weighted_bad": round(bad_w, 6),
        "as_of_seq": last,
        "ledger_head": window[-1]["hash"] if window else GENESIS,
    }


def track_record_evidence(
    author: str,
    entries: list[dict],
    case: dict,
    producer: dict,
    created: str,
    *,
    humans: Iterable[str] | None = None,
    as_of_seq: int | None = None,
) -> dict:
    """`reproducible.track_record`: pass when the lower bound is above 0, else inconclusive."""
    if not isinstance(author, str) or not author:
        raise ValueError("author must name the author system")
    stats = compute(entries, author, humans=humans, as_of_seq=as_of_seq)
    allow = None if humans is None else sorted({str(h) for h in humans})
    lb = stats["lower_bound"]
    if lb > 0:
        outcome = "pass"
        claim = clip(f"Author system {author}: with 95% confidence at least {lb:.0%} of its accepted work is confirmed good "
                     f"({stats['n_good']} confirmed good, {stats['n_bad']} confirmed bad).")
    else:
        outcome = "inconclusive"
        claim = clip(f"Author system {author}: no usable track record ({stats['n_good']} confirmed good, {stats['n_bad']} confirmed bad).")
    how = (f"python3 -m praiser track-record --ledger ledger.jsonl --author {shlex.quote(author)} --as-of {stats['as_of_seq']}"
           + (" --humans humans.json" if allow is not None else "")
           + "   # prints the numbers; they must equal details")
    details = dict(stats, formula=FORMULA, half_life=HALF_LIFE, failure_weight=FAILURE_WEIGHT, humans=allow)
    return make(
        case=case_ref(case), producer=producer_ref(producer), kind="reproducible.track_record", claim=claim,
        outcome=outcome, verifiability="reproducible", created=created, reproduce={"command": cap_command(how)},
        details=details,
    )


CLAIMED = ("lower_bound", "n_good", "n_bad", "weighted_good", "weighted_bad", "ledger_head")


def verify_against_ledger(
    record: dict,
    entries: list[dict],
    *,
    humans: Iterable[str] | None = None,
    max_lag: int | None = None,
) -> tuple[bool, list[str]]:
    """Re-derive a claimed track record from the ledger. Returns (ok, problems); ok is True only with no problem.

    Catches: a number that differs from the re-derivation, a record about a ledger state that does not exist, a broken
    hash chain, a different labeler allow-list than the one the verifier uses, a snapshot that predates a later
    confirmed bad outcome for the same author (cherry-picking), and (with `max_lag`) a snapshot older than allowed."""
    problems = [f"not valid evidence: {e}" for e in validate(record)]
    if problems:
        return False, problems
    if record["kind"] != "reproducible.track_record":
        return False, ["not a track record"]
    d = record["details"]
    author, as_of = d.get("author_system"), d.get("as_of_seq")
    if not isinstance(author, str) or not isinstance(as_of, int) or isinstance(as_of, bool):
        return False, ["the record does not say whose track record it is and as of when"]
    try:
        fresh = compute(entries, author, humans=humans, as_of_seq=as_of)
        latest = compute(entries, author, humans=humans)
    except LedgerError as exc:
        return False, [str(exc)]
    for field in CLAIMED:
        if d.get(field) != fresh[field]:
            problems.append(f"{field}: record says {d.get(field)!r}, the ledger gives {fresh[field]!r}")
    allow = None if humans is None else sorted({str(h) for h in humans})
    if d.get("humans") != allow:
        problems.append("the record was computed with a different set of accepted labelers")
    expected = "pass" if fresh["lower_bound"] > 0 else "inconclusive"
    if record["outcome"] != expected:
        problems.append(f"outcome is {record['outcome']} but the ledger gives {expected}")
    if latest["n_bad"] > fresh["n_bad"]:
        problems.append("a confirmed bad outcome for this author was recorded after the snapshot the record uses")
    if max_lag is not None and len(entries) - 1 - as_of > max_lag:
        problems.append(f"the snapshot is {len(entries) - 1 - as_of} entries old (limit {max_lag})")
    return not problems, problems


def label_body(repo: str, head_sha: str, label: str, by: str) -> dict:
    """The body of a `label` ledger entry, so the shape in docs/PRAISE-RULES.md has one definition."""
    if label not in ("accept", "reject"):
        raise ValueError("label must be accept or reject")
    return {"repo": repo, "head_sha": head_sha, "label": label, "by": by}
