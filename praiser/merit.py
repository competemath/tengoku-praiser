"""Merit: results of tools that already exist (Jinshi, proof checkers, axiom and sorry scans) as evidence records.

Nothing here runs a tool. It takes what a tool printed and writes it down in the shared format, completely: every
declared check gets a record, a failure is a record, and a check that did not run is `not_run`, never a pass.

Who is who (docs/CONTRACT.md): the tools are role `tooling`; a `manifest.declared` written here is the producer's promise
of what it will report. The juridicator's rule R9 matches a manifest to results by producer *identity*, so a manifest only
protects the results written under the same identity as the manifest. Declare one manifest per identity.
"""

from __future__ import annotations

import shlex
from collections import Counter
from typing import Iterable

from vendor.juridicator_evidence import KIND

from .common import cap_command, case_ref, clip, fit_details, kind_part, make, producer_ref

STANDARD_AXIOMS = ("propext", "Classical.choice", "Quot.sound")
CHECKER_OUTCOMES = {"accept": "pass", "reject": "fail", "timeout": "inconclusive", "error": "inconclusive"}
NEVER_ALLOWED = ("sorryAx",)


# The real Jinshi executable (lakefile.jinshi.toml in the jinshi repository): one examination of one module per run.
JINSHI_COMMAND = "lake env .lake/build/bin/tengoku-jinshi --module {module} --check {check}"
# Command lines for the checkers Tengoku already runs, by the name they report under. Others get a sentence, or pass `commands`.
CHECKER_COMMANDS = {
    "lean-kernel": "lake build",
    "leanchecker": "lake env leanchecker Tengoku",
    "lean4lean": "JINSHI_LEAN4LEAN=/path/to/lean4lean python3 scripts/jinshi/run.py --round 0 --checks lean4lean --out jinshi-out",
}

def _finding(f: object) -> dict:
    if not isinstance(f, dict) or not isinstance(f.get("check"), str) or not f["check"].strip():
        raise ValueError("a Jinshi finding must be an object with a non-empty 'check'; refusing to drop it silently")
    return f


def from_jinshi(
    findings: Iterable[dict],
    case: dict,
    producer: dict,
    checks: Iterable[str],
    created: str,
    *,
    ran: Iterable[str] = (),
    command_template: str = JINSHI_COMMAND,
    module: str = "Tengoku",
) -> list[dict]:
    """One `mechanical.jinshi.<check>` record per check.

    `findings` are the dicts Jinshi prints: {check, severity, module, name, detail}. `checks` are the checks the caller
    declared it would run. A check is:
      fail      if any of its findings has severity "fail";
      pass      if it has findings but none failed, or if it has none and the caller lists it in `ran`;
      not_run   if it has no findings and the caller does not say it ran (silence is not a pass).
    A finding for a check that was not declared still gets its record, because a failure must never be dropped for
    being unexpected. `command_template` is how anyone re-runs one check (`{check}` and `{module}` are replaced, shell-quoted); the default
    is the real Jinshi executable's own command line (its `--module` and `--check` options).
    """
    findings = [_finding(f) for f in findings]
    declared = {str(c) for c in checks}
    ran_set = {str(c) for c in ran}
    by_check: dict[str, list[dict]] = {}
    for f in findings:
        by_check.setdefault(f["check"], []).append(f)
    names = sorted(declared | set(by_check))
    kinds: dict[str, str] = {}
    for name in names:
        part = kind_part(name)
        if part in kinds:
            raise ValueError(f"checks {kinds[part]!r} and {name!r} collide as kind mechanical.jinshi.{part}")
        kinds[part] = name
    case_r, prod_r = case_ref(case), producer_ref(producer)
    out = []
    for part, name in sorted(kinds.items()):
        fs = by_check.get(name, [])
        counts = Counter(str(f.get("severity", "unknown")) for f in fs)
        n_fail = counts.get("fail", 0)
        if n_fail:
            outcome, claim = "fail", f"Jinshi check {name}: {n_fail} failing finding(s) of {len(fs)}."
        elif fs:
            outcome, claim = "pass", f"Jinshi check {name}: ran, no failing finding ({len(fs)} finding(s) of lower severity)."
        elif name in ran_set:
            outcome, claim = "pass", f"Jinshi check {name}: ran and reported no finding."
        else:
            outcome, claim = "not_run", f"Jinshi check {name}: no finding and not marked as run; counted as missing."
        failing = [{"module": clip(f.get("module", ""), 100), "name": clip(f.get("name", ""), 100),
                    "detail": clip(f.get("detail", ""), 160)} for f in fs if f.get("severity") == "fail"]
        details = {"check": clip(name, 80), "counts": dict(sorted(counts.items())), "n_findings": len(fs),
                   "marked_run": name in ran_set, "failing": failing[:15]}
        out.append(make(
            case=case_r, producer=prod_r, kind=f"mechanical.jinshi.{part}", claim=clip(claim), outcome=outcome,
            verifiability="mechanical", created=created,
            reproduce={"command": cap_command(command_template.format(check=shlex.quote(name), module=shlex.quote(module)))},
            details=fit_details(details, ("failing",)),
        ))
    return out


def from_checkers(verdicts: dict, case: dict, created: str, *, commands: dict | None = None) -> list[dict]:
    """One `mechanical.kernel_check` record PER checker, with producer.identity equal to the checker's name, so that
    independence is countable by the judge (it counts distinct identities).

    verdicts: {checker name: "accept" | "reject" | "timeout" | "error"}. accept is pass, reject is fail,
    timeout and error are inconclusive (the checker did not give an answer; that is not a pass and not a fail).
    `commands` maps a checker to the command that re-runs it. A checker without one gets a descriptive placeholder
    sentence: it satisfies the contract's "say how to reproduce" but a real pipeline should pass real commands.
    """
    if not isinstance(verdicts, dict) or not verdicts:
        raise ValueError("verdicts must name at least one checker")
    case_r = case_ref(case)
    commands = commands or {}
    out = []
    for name in sorted(verdicts):
        verdict = verdicts[name]
        if verdict not in CHECKER_OUTCOMES:
            raise ValueError(f"checker {name!r}: verdict must be one of {sorted(CHECKER_OUTCOMES)}, not {verdict!r}")
        outcome = CHECKER_OUTCOMES[verdict]
        who = {"role": "tooling", "name": clip(name, 80), "identity": clip(name, 120)}
        producer_ref(who)
        command = commands.get(name) or CHECKER_COMMANDS.get(name) or f"run the independent proof checker '{clip(name, 60)}' on this commit's compiled output"
        out.append(make(
            case=case_r, producer=who, kind="mechanical.kernel_check",
            claim=clip(f"Checker {name} {verdict}s this commit's proofs." if verdict in ("accept", "reject")
                       else f"Checker {name} gave no answer ({verdict}); that is neither a pass nor a fail."),
            outcome=outcome, verifiability="mechanical", created=created,
            reproduce={"command": cap_command(command)}, details={"verdict": verdict},
        ))
    return out


def axiom_closure(
    axioms: Iterable[str] | None,
    case: dict,
    producer: dict,
    created: str,
    allowed: Iterable[str] = STANDARD_AXIOMS,
    *,
    command: str = "lake env lean --run scripts/print_axioms.lean",  # a guess: pass the toolchain's real scan (SECURITY.md P11)
) -> dict:
    """`mechanical.axiom_closure`: pass when every axiom the proofs depend on is in `allowed`, else fail naming the others.

    `allowed` is a parameter on purpose. The three classical axioms (propext, Classical.choice, Quot.sound) are what a
    reader expects, but the real baseline of a given toolchain also contains a few compiler-internal names, and a gate
    that hard-coded the three produced false failures in a real incident. Calibrate `allowed` once per toolchain from a
    declaration known to be fine, pin it next to the toolchain file, and note that the allowed set is written into the
    record's details, so a permissive set is visible to whoever reads it. `sorryAx` can never be allowed: that would
    turn this check into a way to launder unfinished proofs. `axioms=None` means the scan did not run (not_run).
    """
    allowed_set = {str(a) for a in allowed}
    for bad in NEVER_ALLOWED:
        if bad in allowed_set:
            raise ValueError(f"{bad} can never be an allowed axiom")
    if axioms is None:
        outcome, claim, used, extra = "not_run", "The axiom scan did not run; counted as missing.", [], []
    else:
        used = sorted({str(a) for a in axioms})
        extra = [a for a in used if a not in allowed_set]
        if extra:
            outcome = "fail"
            claim = clip("Depends on axioms outside the allowed set: " + ", ".join(extra[:8]) + (" ..." if len(extra) > 8 else ""))
        else:
            outcome, claim = "pass", f"Depends only on allowed axioms ({len(used)} used)."
    return make(
        case=case_ref(case), producer=producer_ref(producer), kind="mechanical.axiom_closure", claim=claim,
        outcome=outcome, verifiability="mechanical", created=created, reproduce={"command": cap_command(command)},
        details=fit_details({"axioms": used[:100], "outside_allowed": extra[:100], "allowed": sorted(allowed_set)[:50]},
                            ("allowed", "axioms")),
    )


def no_sorry(
    findings_or_flag: Iterable[dict] | bool | None,
    case: dict,
    producer: dict,
    created: str,
    *,
    command: str = "grep -rnE '\\b(sorry|admit)\\b' --include='*.lean' .",
) -> dict:
    """`mechanical.no_sorry`.

    `findings_or_flag` is either a list of findings from the scan (dicts; any with severity "fail", or with no severity,
    is an occurrence), or a bool where True means *a sorry was found* (not "the code is clean"), or None when the scan
    did not run. An empty list is a clean scan.
    """
    if findings_or_flag is None:
        outcome, claim, n = "not_run", "The sorry scan did not run; counted as missing.", None
    elif isinstance(findings_or_flag, bool):
        n = 1 if findings_or_flag else 0
        outcome = "fail" if n else "pass"
        claim = "A sorry or admit was found." if n else "No sorry or admit was found."
    else:
        fs = list(findings_or_flag)
        for f in fs:
            if not isinstance(f, dict):
                raise ValueError("sorry findings must be objects")
        n = sum(1 for f in fs if f.get("severity", "fail") == "fail")
        outcome = "fail" if n else "pass"
        claim = f"{n} occurrence(s) of sorry or admit found." if n else "No sorry or admit was found."
    return make(
        case=case_ref(case), producer=producer_ref(producer), kind="mechanical.no_sorry", claim=claim, outcome=outcome,
        verifiability="mechanical", created=created, reproduce={"command": cap_command(command)},
        details={"occurrences": n},
    )


def manifest(case: dict, producer: dict, checks: Iterable[str], created: str) -> dict:
    """`manifest.declared`: the kinds this producer promises to report, written BEFORE the results. The juridicator holds
    the case (rule R9) when a promised kind is missing from this producer's reports. Always attested by construction."""
    kinds = sorted({str(c) for c in checks})
    if not kinds:
        raise ValueError("a manifest that promises nothing protects nothing")
    for k in kinds:
        if not KIND.match(k) or k.startswith("manifest."):
            raise ValueError(f"{k!r} is not a reportable kind")
    return make(
        case=case_ref(case), producer=producer_ref(producer), kind="manifest.declared",
        claim=clip(f"Will report {len(kinds)} check(s): " + ", ".join(kinds)), outcome="pass", verifiability="attested",
        created=created, details={"checks": kinds},
    )
