"""A plain-language trust card (Markdown) for a theorem or pull request.

`render(verdict, evidence)` is a pure function of the juridicator's verdict and the evidence records: the same inputs give
the same text, byte for byte (everything is sorted; there is no clock). The card shows only the evidence the judge
actually weighed (well formed, about this commit, not ignored), says when what it was shown does not match the judge's
evidence digest, and always ends with what it does NOT claim. Every string that came from a record is untrusted: control
characters are removed and Markdown and HTML punctuation is escaped, so a claim cannot plant a link or a tag on a page.
"""

from __future__ import annotations

import re
from typing import Iterable

from vendor.juridicator_evidence import canonical_json, sha256_text, validate

DECISIONS = {
    "ACCEPT": "This content was accepted: every check the library requires passed, and nothing is in dispute.",
    "HOLD": "This content is on hold: something the library requires is missing or has to be run again.",
    "ESCALATE": "This content needs a person's decision: checkers disagree, or a reviewer raised a concern.",
    "REJECT": "This content was rejected: at least one check that anyone can re-run failed.",
}
TIERS = {
    0: "light: only occasional spot checks",
    1: "ordinary: a regular sample is re-examined",
    2: "raised: a large share is re-examined",
    3: "full: every acceptance at this level is re-examined",
}
SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+!|~&])")


def _md(text: object, limit: int = 200) -> str:
    """Untrusted text made safe to print inside Markdown: one line, no control characters, punctuation escaped."""
    s = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(text)).split())
    if len(s) > limit:
        s = s[: limit - 3] + "..."
    return SPECIAL.sub(r"\\\1", s)


def _names(evs: Iterable[dict]) -> str:
    names = sorted({e["producer"]["identity"] for e in evs})
    return ", ".join(_md(n, 60) for n in names) if names else "none"


def _audit_sentence(rate: float) -> str:
    if rate >= 1:
        return "Every acceptance at this level is re-examined later by a person."
    if rate <= 0:
        return "No acceptance at this level is re-examined later."
    return f"About 1 in {round(1 / rate)} acceptances at this level is re-examined later by a person."


def weighed_evidence(verdict: dict, evidence: Iterable[dict]) -> tuple[list[dict], bool]:
    """The records the judge weighed (as far as this card can tell), and whether they match its evidence digest."""
    case = verdict["case"]
    ignored = {d.get("id") for d in verdict.get("ignored_evidence", []) if isinstance(d, dict)}
    seen, live = set(), []
    for ev in evidence:
        if validate(ev) or ev["id"] in ignored or ev["id"] in seen:
            continue
        if ev["case"]["repo"] != case["repo"] or ev["case"]["head_sha"] != case["head_sha"]:
            continue
        seen.add(ev["id"])
        live.append(ev)
    live.sort(key=lambda e: e["id"])
    digest = "sha256:" + sha256_text(canonical_json(sorted(seen)))
    return live, digest == verdict.get("evidence_digest")


def _of(live: list[dict], kind: str) -> list[dict]:
    return [e for e in live if e["kind"] == kind]


def _checks(live: list[dict]) -> list[str]:
    lines = []
    kc = _of(live, "mechanical.kernel_check")
    agreed = [e for e in kc if e["outcome"] == "pass"]
    lines.append(f"- Proof checkers that accepted it ({len({e['producer']['identity'] for e in agreed})}): {_names(agreed)}.")
    rejected = [e for e in kc if e["outcome"] == "fail"]
    silent = [e for e in kc if e["outcome"] not in ("pass", "fail")]
    if rejected:
        lines.append(f"- Proof checkers that REJECTED it: {_names(rejected)}.")
    if silent:
        lines.append(f"- Proof checkers that gave no answer: {_names(silent)}.")
    for e in sorted(_of(live, "mechanical.axiom_closure"), key=lambda e: e["id"]):
        d = e["details"]
        if e["outcome"] == "pass":
            used = ", ".join(_md(a, 60) for a in d.get("axioms", [])) or "none beyond the logic itself"
            lines.append(f"- Axioms used: {used}. All are in the allowed list.")
        elif e["outcome"] == "fail":
            extra = ", ".join(_md(a, 60) for a in d.get("outside_allowed", [])) or "unknown"
            lines.append(f"- Axioms: it depends on axioms outside the allowed list: {extra}.")
        else:
            lines.append("- Axioms: the check did not run.")
    if not _of(live, "mechanical.axiom_closure"):
        lines.append("- Axioms: no axiom check was reported.")
    for e in sorted(_of(live, "mechanical.no_sorry"), key=lambda e: e["id"]):
        text = {"pass": "no unfinished proofs (sorry) were found", "fail": "unfinished proofs (sorry) WERE found"}.get(
            e["outcome"], "the scan did not run")
        lines.append(f"- Unfinished proofs: {text}.")
    other = [e for e in live if e["kind"].startswith("mechanical.jinshi.")]
    if other:
        passed = sorted(_md(e["details"].get("check", e["kind"]), 60) for e in other if e["outcome"] == "pass")
        failed = sorted(_md(e["details"].get("check", e["kind"]), 60) for e in other if e["outcome"] == "fail")
        missing = sorted(_md(e["details"].get("check", e["kind"]), 60) for e in other if e["outcome"] not in ("pass", "fail"))
        lines.append(f"- Jinshi soundness checks passed: {', '.join(passed) or 'none'}; failed: {', '.join(failed) or 'none'}; "
                     f"not run or undecided: {', '.join(missing) or 'none'}.")
    rb = _of(live, "reproducible.rebuild_match")
    if not rb:
        lines.append("- Independent rebuild: none was reported.")
    for e in sorted(rb, key=lambda e: e["id"]):
        lines.append("- Independent rebuild: " + {
            "pass": "yes, two different runners produced identical output.",
            "fail": f"NO, the rebuilds differ ({_md(', '.join(e['details'].get('differing', [])) or 'see record', 80)}).",
        }.get(e["outcome"], "not shown: the two rebuilds could not be told apart as independent."))
    pv = _of(live, "mechanical.provenance_consistent")
    if not pv:
        lines.append("- Provenance: it was not checked against stored files.")
    for e in sorted(pv, key=lambda e: e["id"]):
        lines.append("- Provenance: " + {
            "pass": "the stored prompts, tool manifest and toolchain files match what was declared.",
            "fail": "does NOT match: " + _md(e["claim"], 160),
        }.get(e["outcome"], "partly checked: " + _md(e["claim"], 160)))
    for e in sorted(_of(live, "mechanical.statement_preregistered"), key=lambda e: e["id"]):
        lines.append("- Statement fixed before the proof: " + {
            "pass": "yes, it matches a commitment recorded in an earlier commit.",
            "fail": "NO: " + _md(e["claim"], 160)}.get(e["outcome"], "could not be established."))
    return lines


def _track(live: list[dict]) -> list[str]:
    recs = sorted(_of(live, "reproducible.track_record"), key=lambda e: (e["details"].get("as_of_seq", -1), e["id"]))
    if not recs:
        return ["No track record was supplied for the system that made this, so it did not lower the level of checking."]
    e = recs[-1]
    d = e["details"]
    good, bad = d.get("n_good", 0), d.get("n_bad", 0)
    who = _md(d.get("author_system", "the author system"), 60)
    if e["outcome"] != "pass" or not isinstance(d.get("lower_bound"), (int, float)):
        return [f"{who} has no usable track record yet ({good} confirmed good, {bad} confirmed bad outcomes)."]
    text = (f"{who}: counting only accepted work that a person later confirmed, we can say with 95% confidence that its true "
            f"reliability is at least {d['lower_bound']:.0%}. That rests on {good} confirmed good and {bad} confirmed bad "
            f"outcomes (a confirmed bad one counts as ten failures, and older outcomes count for less).")
    if good + bad < 30:
        text += " That is few cases, so the figure is cautious and could move a lot."
    text += (" The card cannot recompute this; anyone can, from the public ledger, with: "
             + _md((e.get("reproduce") or {}).get("command", "see the record"), 240))
    return [text]


def _fidelity(live: list[dict]) -> str:
    rm = _of(live, "mechanical.restatement_match")
    if any(e["outcome"] == "pass" for e in rm) and not any(e["outcome"] == "fail" for e in rm):
        return ("A restatement match is present: a machine found the formal statement equivalent to a second statement "
                "written blind from the plain-language problem. That raises confidence that the statement says what the problem "
                "says; it is still not a proof of it, because both statements could misread the problem the same way.")
    if any(e["outcome"] == "fail" for e in rm):
        return "A restatement check found the formal statement NOT equivalent to a blind restatement: a person must decide which is faithful."
    if rm:
        return "A restatement check was run but could not decide, so it says nothing about whether the statement is faithful."
    return ("It is not a proof that the formal statement is faithful to the original problem: no restatement match is present, "
            "so a proof of a wrongly stated theorem would look the same here.")


def render(verdict: dict, evidence: Iterable[dict]) -> str:
    if not isinstance(verdict, dict) or verdict.get("decision") not in DECISIONS or not isinstance(verdict.get("case"), dict):
        raise ValueError("verdict must be a juridicator verdict with a known decision")
    live, digest_ok = weighed_evidence(verdict, list(evidence))
    case = verdict["case"]
    tier = verdict.get("tier")
    rate = verdict.get("audit_rate")
    out = [f"# Trust card: {_md(case['repo'], 80)} at {_md(case['head_sha'][:12], 12)}", "", f"**{DECISIONS[verdict['decision']]}**", ""]
    if verdict.get("missing"):
        out += ["Still missing: " + ", ".join(_md(m, 60) for m in verdict["missing"]) + ".", ""]
    if not digest_ok:
        out += ["> Warning: the evidence shown here does not match the evidence the judge weighed. Do not rely on this card.", ""]
    out += ["## Checks anyone can re-run", ""] + _checks(live) + [""]
    out += ["## How closely this will be re-examined", ""]
    if tier in TIERS and isinstance(rate, (int, float)):
        out.append(f"Scrutiny level {tier} ({TIERS[tier]}). {_audit_sentence(rate)}")
    else:
        out.append("The scrutiny level was not stated in the verdict.")
    unmet = verdict.get("merit_unmet") or []
    if unmet:
        out.append("The level was not lowered because: " + "; ".join(_md(u, 100) for u in unmet) + ".")
    out += ["", "## Track record of the system that made it", ""] + _track(live) + [""]
    reasons = sorted({_md(r.get("text", ""), 240) for r in verdict.get("reasons", []) if isinstance(r, dict)})
    if reasons:
        out += ["## What the judge noted", ""] + [f"- {r}" for r in reasons] + [""]
    out += ["## What this does not claim", "", f"- {_fidelity(live)}",
            "- It does not claim the content is free of error. The proof checkers are the ground truth for proofs; several "
            "independent checkers agreeing makes a hidden checker bug unlikely, not impossible.",
            "- A good track record lowers how often the work is re-examined, by one step at most. It never replaces a check.",
            "- Praise that could not be checked is listed below as noted, not weighed. It changed nothing."]
    praise = sorted((e for e in live if e["verifiability"] == "attested" and not e["kind"].startswith("manifest.")),
                    key=lambda e: e["id"])
    if praise:
        out += [f"  - Noted, not weighed: {_md(e['claim'], 200)} (by {_md(e['producer']['identity'], 60)})" for e in praise]
    else:
        out.append("  - Nothing of that kind was submitted.")
    ignored = verdict.get("ignored_evidence") or []
    if ignored:
        out.append(f"- {len(ignored)} record(s) were ignored by the judge (malformed, about another commit, duplicate, or written by "
                   "the author about their own work).")
    return "\n".join(out) + "\n"
