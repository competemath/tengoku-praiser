"""The reviewer: every check over the modules of a proposal, as one list of findings and one record per check.

`review(modules, ...)` runs the checks it is asked for, and for each says whether it RAN. A check that needs a compiler and was
given none does not run and is `not_run`: absence of evidence is never a pass. Checks:

  text only    style  naming  docs  api  dedupe  reuse  hoist
  needs Lean   lint  compiler  generalise  minimise  robust  compat      (a primary toolchain; compat also a forward one)

The compiler is an oracle (oracle.py) and is only ever asked about whole modules. One global budget caps the calls of the whole
review; each theorem also has its own. Findings are sorted so that two runs on the same input are byte for byte equal
(`review.findings_digest` compares them).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import apigaps, compat, dedupe, docscheck, generalise, leansrc as L, minimise, naming, stylelint
from .oracle import Bounded, Compile
from .review import from_findings

TEXT_CHECKS = ("style", "naming", "docs", "api", "dedupe", "reuse", "hoist")
LEAN_CHECKS = ("lint", "compiler", "generalise", "minimise", "robust", "compat")
ALL_CHECKS = TEXT_CHECKS + LEAN_CHECKS
DEFAULT_TOTAL_CALLS = 600
DEFAULT_PER_THEOREM = 60


@dataclass
class Result:
    findings: list = field(default_factory=list)
    ran: list = field(default_factory=list)
    requested: list = field(default_factory=list)
    calls: int = 0
    exhausted: bool = False

    def patches(self) -> list:
        return [f for f in self.findings if isinstance(f.get("patch"), str)]


def _key(f: dict):
    return (f["check"], f.get("module", ""), f.get("line", 0), f.get("name", ""), f.get("rule", ""), f.get("detail", ""))


def review(
    modules: dict,
    *,
    checks=ALL_CHECKS,
    primary: Compile | None = None,
    forward: Compile | None = None,
    index: dedupe.Index | None = None,
    known=frozenset(),
    taken=frozenset(),
    header_pattern: str | None = None,
    total_calls: int = DEFAULT_TOTAL_CALLS,
    per_theorem: int = DEFAULT_PER_THEOREM,
    compat_severity: str = "warn",
) -> Result:
    unknown = [c for c in checks if c not in ALL_CHECKS]
    if unknown:
        raise ValueError(f"unknown check(s): {', '.join(unknown)}")
    res = Result(requested=sorted(set(checks)))
    wanted = set(checks)
    bounded = Bounded(primary, total_calls) if primary is not None else None
    fwd = Bounded(forward, total_calls) if forward is not None else None
    names = {m: [d.full_name for d in L.declarations(t) if d.full_name] for m, t in modules.items()}
    own = {n for ns in names.values() for n in ns}
    library = set(known) | set(taken)
    if wanted & {"dedupe", "reuse"}:
        ix = dedupe.Index()
        if index is not None:
            ix.entries, ix.by_key, ix.texts = list(index.entries), {k: list(v) for k, v in index.by_key.items()}, dict(index.texts)
            ix._inline = dict(index._inline)
        for m in sorted(modules):
            ix.add(m, modules[m])
    ran: set = set()
    out: list = []
    for module in sorted(modules):
        text = modules[module]
        if "style" in wanted:
            out += stylelint.style_findings(text, module)
            ran.add("style")
        if "naming" in wanted:
            out += naming.check_module(text, taken=library, module=module)
            ran.add("naming")
        if "docs" in wanted:
            out += docscheck.check_module(text, known=(library | own) if library else None, header_pattern=header_pattern, module=module)
            ran.add("docs")
        if "api" in wanted:
            out += apigaps.check_module(text, known=library | (own - set(names[module])), module=module)
            ran.add("api")
        if "dedupe" in wanted:
            out += dedupe.duplicate_findings(module, text, ix)
            ran.add("dedupe")
        if "reuse" in wanted:
            out += dedupe.reuse_findings(module, text, ix)
            ran.add("reuse")
        if bounded is not None:
            if "lint" in wanted:
                out += stylelint.run_lint(text, bounded, module=module)
                ran.add("lint")
            if "compiler" in wanted:
                out += stylelint.compile_findings(text, bounded, module=module)
                ran.add("compiler")
            if "generalise" in wanted:
                out += generalise.findings(text, bounded, budget_per_theorem=per_theorem, module=module)
                ran.add("generalise")
            if wanted & {"minimise", "robust"}:
                for f in minimise.findings(text, bounded, budget_per_theorem=per_theorem, module=module):
                    if f["check"] in wanted:
                        out.append(f)
                ran |= wanted & {"minimise", "robust"}
            if "compat" in wanted and fwd is not None:
                out += compat.forward_compat(text, bounded, fwd, severity=compat_severity, module=module)
                ran.add("compat")
    if "hoist" in wanted:
        out += dedupe.hoist_findings(modules)
        ran.add("hoist")
    out.sort(key=_key)
    res.findings, res.ran = out, sorted(ran)
    if bounded is not None:
        res.calls, res.exhausted = bounded.calls, bounded.exhausted
    return res


def evidence(result: Result, case: dict, producer: dict, created: str, command_for) -> list:
    """One `mechanical.review.<check>` record per requested check."""
    return from_findings(result.findings, case, producer, result.requested, created, ran=result.ran, command_for=command_for)
