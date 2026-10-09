"""Agent containment: a reason to trust one agent run that a stranger can re-check.

A change written or reviewed by an AI agent is only as trustworthy as the confinement that agent ran in. `agent_contained` turns
two reports that tengoku-warden produces into one `mechanical.agent_contained` record: the trace audit of the run (`python3 -m
warden toolpolicy audit-trace`: every tool the agent used, every path it read, checked against a tool policy) and the escape
battery that ran as the agent's identity before it started (`python3 -m warden selftest --json`). It passes only if the trace has
no violation AND every probe of the battery was denied, and it carries the sha-256 of both reports and of the tool policy, so
anyone holding the stored reports can recompute the digests (`verify_agent_contained`) and re-run the audit on the stored trace.

The other half is a declaration. `tool_policy_fact` and `jail_spec_digest` produce the facts that `attest.provenance_attestation`
records in its declared facts (the tool-policy name and hash, the jail specification's digest); `declared_digests` reads them back,
and `agent_contained(..., declared=...)` fails when the reports it was given do not match what was declared. A declaration the
reports contradict is not a harmless mistake.

Credit: Tau Ceti Project. TauCetiReview PR #123 (2026-08-21) is the reason the trace is audited at all: its Claude reviewer was
launched with `--allowedTools` alone and had Bash for about 79 days (295 Bash calls in 427 traced calls), found by a one-off analysis
of 20 runs. TauCeti `pr-build.yml` (PR #5800) is the model for the escape battery: nine probes that abort the job when the sandbox is
not enforcing; TauCetiWorker's startup preflight proves the sandbox is present, not that it confines (report-worker-claims.md
items 1.5 and 1.6). Both are warden modules (`toolpolicy`, `selftest`); this module only weighs what they report.

What we do differently: the audit and the battery become evidence on every run, bound to the commit and re-runnable, not a one-off
analysis or an abort in a build log; "contained" requires both (a clean trace in a jail that leaks proves little, and a perfect jail
with a trace that used a shell proves little); the tool set the trace is checked against is recomputed here from the declared
policy, so an audit run against a lenient policy cannot pass; and a report that does not match the digest someone declared is a
`fail`. HONEST LIMITS: a passing battery proves the probed vectors were closed on that runner on that day; a clean trace shows what
this run did, not what the agent could have done; the reports are produced by whoever ran the audit, and the digests make a swap
detectable only for someone who holds the stored originals.

Pure: no file, clock, network or AI. The caller reads the JSON reports and passes them in.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import shlex
from typing import Any, Mapping, Sequence

from vendor.juridicator_evidence import HEX64, canonical_json

from .common import cap_command, case_ref, clip, fit_details, make, producer_ref, sha256_bytes

KIND = "mechanical.agent_contained"
SHELL_TOOLS = frozenset({"Bash", "BashOutput", "KillShell", "KillBash"})
SEVERITIES = ("error", "warn")
STATUSES = ("denied", "allowed", "na", "error")
POLICY_FLAGS = ("allow_shell", "allow_skip_permissions", "allow_unknown_cli", "require_limits")
DECLARED_KEYS = ("tool_policy_sha256", "jail_spec_sha256", "trace_report_sha256", "selftest_report_sha256")
LIMITS = [
    "a passing battery proves the probed escape vectors were closed on that runner on that day, not that none exists",
    "a clean trace shows what this run did, not what the agent could have done",
    "the reports come from whoever ran the audit; digests detect a swap only for a holder of the stored originals",
]


def digest(obj: Any) -> str:
    """sha-256 of the canonical JSON of a report, policy or jail specification (the digest every record here quotes)."""
    return sha256_bytes(canonical_json(obj).encode("utf-8"))


# ---------------------------------------------------------------- the tool policy

def _names(value: Any, what: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(x, str) and x.strip() for x in value):
        raise ValueError(f"{what} must be a list of tool names")
    return sorted({x.strip() for x in value})


def normalize_policy(policy: Any) -> dict:
    """The tool policy as a plain dict with exactly the fields that matter: name, builtin_tools, mcp_patterns and the four flags.
    A dataclass instance (warden's `ToolPolicy`) is accepted as well as a mapping."""
    if dataclasses.is_dataclass(policy) and not isinstance(policy, type):
        policy = dataclasses.asdict(policy)
    if not isinstance(policy, Mapping):
        raise ValueError("policy must be a mapping with name, builtin_tools and mcp_patterns")
    name = policy.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("policy needs a name")
    out = {"name": clip(name.strip(), 60), "builtin_tools": _names(policy.get("builtin_tools", []), "builtin_tools"),
           "mcp_patterns": _names(policy.get("mcp_patterns", []), "mcp_patterns")}
    for flag in POLICY_FLAGS:
        value = policy.get(flag, False)
        if not isinstance(value, bool):
            raise ValueError(f"policy {flag} must be true or false")
        out[flag] = value
    return out


def tool_set_text(policy: Mapping) -> str:
    """`reviewer (Read, Grep, Glob)`, or `translator (no built-in tools; mcp__tengoku)`."""
    builtin = ", ".join(policy["builtin_tools"]) or "no built-in tools"
    mcp = "; ".join(policy["mcp_patterns"])
    return f"{policy['name']} ({builtin}{'; ' + mcp if mcp else ''})"


def tool_policy_fact(policy: Any) -> dict:
    """What a provenance declaration records about the tool policy: its name, the tool set in words, and its hash."""
    pol = normalize_policy(policy)
    return {"name": pol["name"], "tool_set": clip(tool_set_text(pol), 200), "sha256": digest(pol)}


def jail_spec_digest(spec: Any) -> str:
    """The digest of a jail specification (any JSON object that fully describes how the jail was built)."""
    if not isinstance(spec, (Mapping, list)):
        raise ValueError("a jail specification must be a JSON object or list")
    return digest(spec)


def declared_digests(provenance: Mapping) -> dict:
    """The declared containment facts of an `attested.provenance` record, in the form `agent_contained(declared=...)` takes."""
    d = provenance.get("details") if isinstance(provenance, Mapping) else None
    if not isinstance(d, Mapping):
        return {}
    out = {}
    if isinstance(d.get("tool_policy"), Mapping) and isinstance(d["tool_policy"].get("sha256"), str):
        out["tool_policy_sha256"] = d["tool_policy"]["sha256"]
    if isinstance(d.get("jail_spec_sha256"), str):
        out["jail_spec_sha256"] = d["jail_spec_sha256"]
    return out


def _allowed_by(name: str, policy: Mapping) -> bool:
    base = name.strip().split("(", 1)[0]
    if base.startswith("mcp__"):
        return any(base == p or base.startswith(p + "__") or fnmatch.fnmatchcase(base, p) for p in policy["mcp_patterns"])
    if base in SHELL_TOOLS:
        return bool(policy["allow_shell"]) and base in policy["builtin_tools"]
    return base in policy["builtin_tools"]


# ---------------------------------------------------------------- the two reports

def _count(report: Mapping, key: str, what: str) -> int:
    value = report.get(key, 0)
    if type(value) is not int or value < 0:
        raise ValueError(f"{what}.{key} must be a whole number")
    return value


def summarize_trace(report: Any, policy: Mapping) -> dict:
    """What matters in a warden trace-audit report, and every reason it is not clean. Raises ValueError on a malformed report."""
    if not isinstance(report, Mapping) or not isinstance(report.get("violations"), list):
        raise ValueError("the trace report must be the object `warden toolpolicy audit-trace` writes (with a violations list)")
    violations = []
    for v in report["violations"]:
        if not isinstance(v, Mapping) or not isinstance(v.get("rule"), str) or v.get("severity") not in SEVERITIES:
            raise ValueError("a trace violation needs a rule and a severity of error or warn")
        violations.append({"rule": clip(v["rule"], 60), "severity": v["severity"], "detail": clip(v.get("detail", ""), 80)})
    calls = report.get("calls_by_tool", {})
    if not isinstance(calls, Mapping) or not all(isinstance(k, str) and type(n) is int and n >= 0 for k, n in calls.items()):
        raise ValueError("trace.calls_by_tool must map tool names to counts")
    init = report.get("init_tools")
    if init is not None and not (isinstance(init, list) and all(isinstance(t, str) for t in init)):
        raise ValueError("trace.init_tools must be a list of tool names or null")
    outside = sorted({t for t in list(calls) + list(init or []) if not _allowed_by(t, policy)})
    for t in outside:  # the audit may have been run against a more lenient policy than the declared one
        violations.append({"rule": "tool-outside-declared-policy", "severity": "error", "detail": clip(t, 80)})
    return {
        "events": _count(report, "events", "trace"), "total_calls": _count(report, "total_calls", "trace"),
        "calls_by_tool": dict(sorted(calls.items())[:30]), "init_tools": sorted(init)[:40] if init is not None else None,
        "n_errors": sum(v["severity"] == "error" for v in violations), "n_warnings": sum(v["severity"] == "warn" for v in violations),
        "violations": violations[:20], "report_ok": report.get("ok"),
    }


def summarize_battery(report: Any) -> dict:
    """What matters in a warden escape-battery report. The report's own `ok` is not believed: statuses are counted."""
    if not isinstance(report, Mapping) or not isinstance(report.get("results"), list):
        raise ValueError("the selftest report must be the object `warden selftest --json` writes (with a results list)")
    statuses, allowed = [], []
    for r in report["results"]:
        if not isinstance(r, Mapping) or r.get("status") not in STATUSES or not isinstance(r.get("name"), str):
            raise ValueError("a selftest result needs a name and a status of denied, allowed, na or error")
        statuses.append(r["status"])
        if r["status"] == "allowed":
            allowed.append(clip(r["name"], 60))
    unconfigured = report.get("unconfigured_allowed") or []
    if not isinstance(unconfigured, list):
        raise ValueError("selftest.unconfigured_allowed must be a list")
    return {
        "total": len(statuses), "denied": statuses.count("denied"), "allowed": statuses.count("allowed"), "na": statuses.count("na"),
        "error": statuses.count("error"), "partial": bool(report.get("partial")), "unconfigured_allowed": [clip(x, 60) for x in unconfigured[:20]],
        "failed": allowed[:20],
    }


# ---------------------------------------------------------------- the record

def audit_command(policy_name: str, trace_path: str, workspaces: Sequence[str] = (), report_path: str | None = None) -> str:
    """The exact line that re-runs the trace audit on the stored trace."""
    parts = ["python3", "-m", "warden", "toolpolicy", "audit-trace", trace_path, "--policy", policy_name]
    for w in workspaces:
        parts += ["--workspace", w]
    if report_path:
        parts += ["--json", report_path]
    return " ".join(shlex.quote(p) for p in parts)


def _mismatches(declared: Mapping | None, actual: Mapping[str, str | None]) -> list[str]:
    out = []
    for key, want in (declared or {}).items():
        if key not in DECLARED_KEYS:
            raise ValueError(f"declared may only hold {', '.join(DECLARED_KEYS)}")
        if not isinstance(want, str) or not HEX64.match(want):
            raise ValueError(f"declared {key} must be a sha-256")
        if actual.get(key) != want:
            out.append(key)
    return out


def agent_contained(
    trace_report: Mapping | None,
    selftest_report: Mapping | None,
    policy: Any,
    case: dict,
    producer: dict,
    created: str,
    *,
    jail_spec: Mapping | Sequence | None = None,
    declared: Mapping | None = None,
    trace_path: str = "trace.jsonl",
    workspaces: Sequence[str] = (),
    command: str | None = None,
) -> dict:
    """`mechanical.agent_contained` from a trace audit report and an escape-battery report.

    pass          the trace audit lists no violation (and says something happened) AND every probe of the battery was `denied`
                  (and the run was not partial); nothing that was declared contradicts the reports;
    fail          an error-level trace violation (a tool outside the declared policy counts), a probe the agent could do, or a
                  report whose digest differs from the one declared;
    inconclusive  nothing failed, but it is not shown: a warn-level attempt the platform denied, a probe that did not apply or
                  could not run, a partial or unconfigured battery, an empty trace;
    not_run       a report was not supplied at all ("no containment evidence"; silence is never a pass).

    `declared` may hold `tool_policy_sha256`, `jail_spec_sha256`, `trace_report_sha256`, `selftest_report_sha256` (from a
    provenance declaration or a manifest). `trace_path` and `workspaces` shape the reproduce command (the audit line over the
    stored trace); pass `command` to override it. Raises ValueError on a malformed report or policy.
    """
    pol = normalize_policy(policy)
    fact = {"name": pol["name"], "tool_set": clip(tool_set_text(pol), 200), "sha256": digest(pol),
            "builtin_tools": pol["builtin_tools"], "mcp_patterns": pol["mcp_patterns"]}
    trace = summarize_trace(trace_report, pol) if trace_report is not None else None
    battery = summarize_battery(selftest_report) if selftest_report is not None else None
    actual = {"tool_policy_sha256": fact["sha256"],
              "jail_spec_sha256": jail_spec_digest(jail_spec) if jail_spec is not None else None,
              "trace_report_sha256": digest(trace_report) if trace_report is not None else None,
              "selftest_report_sha256": digest(selftest_report) if selftest_report is not None else None}
    wrong = _mismatches(declared, actual)

    if trace is None or battery is None:
        outcome = "not_run"
        missing = [n for n, r in (("trace audit", trace), ("escape battery", battery)) if r is None]
        claim = clip("No containment evidence: " + " and ".join(missing) + " not supplied.")
    elif trace["n_errors"] or battery["allowed"] or wrong:
        outcome = "fail"
        why = []
        if trace["n_errors"]:
            rules = sorted({v["rule"] for v in trace["violations"] if v["severity"] == "error"})
            why.append(f"{trace['n_errors']} trace violation(s): {', '.join(rules[:4])}")
        if battery["allowed"]:
            why.append(f"{battery['allowed']} of {battery['total']} escape probes allowed: {', '.join(battery['failed'][:4])}")
        if wrong:
            why.append("the reports do not match what was declared: " + ", ".join(wrong))
        claim = clip("Not contained: " + "; ".join(why) + ".")
    elif (trace["n_warnings"] or trace["events"] == 0 or trace["report_ok"] is False or battery["total"] == 0
          or battery["denied"] != battery["total"] or battery["partial"] or battery["unconfigured_allowed"]):
        outcome = "inconclusive"
        why = []
        if trace["n_warnings"]:
            why.append(f"{trace['n_warnings']} denied attempt(s) in the trace")
        if trace["events"] == 0 or trace["report_ok"] is False:
            why.append("the trace audit is empty or not ok")
        if battery["denied"] != battery["total"] or battery["total"] == 0:
            why.append(f"escape battery {battery['denied']}/{battery['total']} denied ({battery['na']} not applicable, {battery['error']} could not run)")
        if battery["partial"] or battery["unconfigured_allowed"]:
            why.append("the battery was partial or had unconfigured probes")
        claim = clip("Containment not shown: " + "; ".join(why) + ".")
    else:
        outcome = "pass"
        claim = clip(f"The agent ran contained: tool set {fact['tool_set']}, escape battery {battery['denied']}/{battery['total']} denied, "
                     f"{trace['total_calls']} traced call(s) with no violation.")

    details = {"tool_policy": fact, "trace_report_sha256": actual["trace_report_sha256"], "selftest_report_sha256": actual["selftest_report_sha256"],
               "trace": trace, "battery": battery, "limits": LIMITS}
    if actual["jail_spec_sha256"]:
        details["jail_spec_sha256"] = actual["jail_spec_sha256"]
    if wrong:
        details["declared_mismatch"] = wrong
    how = command or audit_command(pol["name"], trace_path, workspaces)
    return make(
        case=case_ref(case), producer=producer_ref(producer), kind=KIND, claim=claim, outcome=outcome, verifiability="mechanical",
        created=created, subject={"declaration": pol["name"]}, reproduce={"command": cap_command(how)},
        details=fit_details(details, ("limits",)),
    )


def verify_agent_contained(record: Mapping, trace_report: Mapping | None, selftest_report: Mapping | None, policy: Any, *,
                           jail_spec: Mapping | Sequence | None = None, declared: Mapping | None = None) -> list[str]:
    """Reasons a `mechanical.agent_contained` record does not match the stored reports and policy (empty means it does).

    Recomputes every digest the record quotes and the outcome itself. A forged or swapped report, a different policy, or a record
    whose outcome the reports do not support is listed."""
    if not isinstance(record, Mapping) or record.get("kind") != KIND or not isinstance(record.get("details"), Mapping):
        return ["not a mechanical.agent_contained record"]
    d = record["details"]
    try:
        rebuilt = agent_contained(trace_report, selftest_report, policy, record["case"], record["producer"], record["created"],
                                  jail_spec=jail_spec, declared=declared, command=(record.get("reproduce") or {}).get("command") or "x")
    except (ValueError, KeyError, TypeError) as exc:
        return [f"the stored reports or policy cannot be read: {exc}"]
    problems = []
    rd = rebuilt["details"]
    for key in ("trace_report_sha256", "selftest_report_sha256"):
        if d.get(key) != rd[key]:
            problems.append(f"{key} in the record is not the digest of the stored report")
    if (d.get("tool_policy") or {}).get("sha256") != rd["tool_policy"]["sha256"]:
        problems.append("the record's tool policy hash is not the hash of the policy given")
    if d.get("jail_spec_sha256") != rd.get("jail_spec_sha256"):
        problems.append("jail_spec_sha256 in the record is not the digest of the jail specification given")
    if record.get("outcome") != rebuilt["outcome"]:
        problems.append(f"the record says {record.get('outcome')} but the stored reports give {rebuilt['outcome']}")
    return problems


def line_for_card(record: Mapping) -> tuple[str, dict]:
    """(outcome, the few facts the trust card shows) from a record, defensively: every value may be untrusted."""
    d = record.get("details") if isinstance(record.get("details"), Mapping) else {}
    battery = d.get("battery") if isinstance(d.get("battery"), Mapping) else {}
    policy = d.get("tool_policy") if isinstance(d.get("tool_policy"), Mapping) else {}
    denied, total = battery.get("denied"), battery.get("total")
    return record.get("outcome", ""), {
        "tool_set": policy.get("tool_set") if isinstance(policy.get("tool_set"), str) else policy.get("name", "unknown"),
        "denied": denied if type(denied) is int else None, "total": total if type(total) is int else None,
    }

