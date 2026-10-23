"""Proofs: how much of it is needed, and does it survive being moved off the author's own settings?

minimise     delta-debugging (ddmin) over the top-level tactic steps of a theorem's `by` block, with the compiler as the test.
             The result is 1-minimal for the steps tried: removing any one more step breaks it. Every removal is compiled, so
             the patch is a module that was checked. Also: does one cheap automation close the theorem by itself?
robust       the module recompiled under the settings a library has and an author's machine may not: without the file's
             `set_option`s (each blamed by name), with `autoImplicit` off, with half the heartbeat budget on the theorem. A proof
             that only works on its author's settings is fragile, and a library inherits the fragility.

Neither runs Lean: both take the oracle (oracle.py). "Does not compile" is judged only from a decided oracle answer; no answer is
`inconclusive`. A step budget bounds the compiler calls; running out stops the search and keeps what was verified.
"""

from __future__ import annotations

import re
from typing import Callable

from . import leansrc as L
from .oracle import Bounded, Compile
from .review import finding

CLOSERS = ("omega", "simp", "ring", "decide", "norm_num", "positivity", "linarith", "aesop")
HALF_BEATS = 100000


def ddmin(items: list, test: Callable[[list], bool | None], max_calls: int = 200) -> tuple:
    """Zeller's ddmin. `test(subset)` is True when the subset still passes, False when it fails, None when there is no answer.
    Returns (minimal subset, stopped) where stopped is None or "no_answer"/"budget". The input itself must pass."""
    calls = 0
    n = 2
    current = list(items)
    while len(current) >= 2:
        size = max(1, len(current) // n)
        chunks = [current[i:i + size] for i in range(0, len(current), size)]
        reduced = False
        for i in range(len(chunks)):
            complement = [x for j, c in enumerate(chunks) if j != i for x in c]
            if not complement:
                continue
            if calls >= max_calls:
                return current, "budget"
            calls += 1
            got = test(complement)
            if got is None:
                return current, "no_answer"
            if got:
                current, n, reduced = complement, max(n - 1, 2), True
                break
        if not reduced:
            if n >= len(current):
                break
            n = min(len(current), n * 2)
    return current, None


def _theorem(text: str, name: str):
    found = [d for d in L.declarations(text) if d.is_theorem and name in (d.full_name, d.name)]
    return found[0] if len(found) == 1 else None


def _steps(text: str, d: L.Decl) -> list:
    """Absolute (start, end) offsets of the proof's top-level tactic steps; [] when the proof is not a `by` block."""
    if d.body_span is None:
        return []
    masked = L.mask(text)
    body = masked[d.body_span[0]:d.body_span[1]]
    if not re.match(r"\s*by\b", body):
        return []
    base = d.body_span[0]
    return [(base + a, base + b) for a, b in L.tactic_steps(body)]


def _rebuild(text: str, steps: list, keep: list) -> str:
    """The module with the proof reduced to the kept steps (indices into `steps`, in order)."""
    first, last = steps[0][0], steps[-1][1]
    body = "".join(text[steps[i][0]:steps[i][1]] for i in keep)
    if body and not body.endswith("\n") and text[steps[-1][1] - 1:steps[-1][1]] == "\n":
        body += "\n"
    return L.splice(text, first, last, body)


def minimise_proof(text: str, name: str, oracle: Compile, budget: int = 120) -> dict:
    """{"patch", "removed", "steps", "stopped", "calls"}. `patch` is the module with the redundant steps removed (None when none)."""
    bounded = oracle if isinstance(oracle, Bounded) else Bounded(oracle, budget)
    out = {"patch": None, "removed": 0, "steps": 0, "stopped": None, "calls": 0}
    d = _theorem(text, name)
    if d is None:
        out["stopped"] = "not_found"
        return out
    steps = _steps(text, d)
    out["steps"] = len(steps)
    if len(steps) < 2:
        return out
    base = bounded(text)
    if base.verdict is None:
        out["stopped"] = "no_answer"
        out["calls"] = bounded.calls
        return out
    if base.verdict is False:
        out["stopped"] = "original"
        out["calls"] = bounded.calls
        return out
    idx = list(range(len(steps)))
    kept, stopped = ddmin(idx, lambda keep: bounded(_rebuild(text, steps, keep)).verdict, max_calls=budget)
    out["calls"] = bounded.calls
    out["stopped"] = "budget" if stopped == "no_answer" and bounded.exhausted else stopped
    if len(kept) < len(steps):
        out["patch"] = _rebuild(text, steps, kept)
        out["removed"] = len(steps) - len(kept)
    return out


def automation_closes(text: str, name: str, oracle: Compile, closers=CLOSERS, budget: int = 12) -> tuple:
    """(closer, patch) for the first single tactic that proves the theorem on its own, or (None, None). Needs the original to
    compile; an undecided answer ends the search quietly (it is reported by `minimise_proof`)."""
    bounded = oracle if isinstance(oracle, Bounded) else Bounded(oracle, budget)
    d = _theorem(text, name)
    if d is None or d.body_span is None:
        return None, None
    masked_body = L.mask(text)[d.body_span[0]:d.body_span[1]].strip()
    for tac in closers:
        if masked_body == f"by {tac}" or masked_body == f"by\n  {tac}":
            return None, None  # it already is that
        candidate = L.splice(text, d.body_span[0], d.body_span[1], f" by {tac}")
        if bounded(candidate).verdict:
            return tac, candidate
    return None, None


# ----------------------------------------------------------------------------------------------------------- robustness

SET_OPTION_IN = re.compile(r"set_option[ \t]+([\w.]+)[ \t]+\S+[ \t]+in[ \t]*\n?")
SET_OPTION_LINE = re.compile(r"(?m)^set_option[ \t]+([\w.]+)[ \t]+\S+[ \t]*\n")


def _without_option(text: str, option: str) -> str:
    masked = L.mask(text)
    pieces = []
    for pat in (SET_OPTION_IN, SET_OPTION_LINE):
        for m in pat.finditer(masked):
            if m.group(1) == option:
                pieces.append((m.start(), m.end()))
    for a, b in sorted(pieces, reverse=True):
        text = L.splice(text, a, b, "")
    return text


def options_used(text: str) -> list:
    masked = L.mask(text)
    seen: list = []
    for pat in (SET_OPTION_IN, SET_OPTION_LINE):
        for m in pat.finditer(masked):
            if m.group(1) not in seen:
                seen.append(m.group(1))
    return seen


def robustness(text: str, name: str, oracle: Compile, budget: int = 20, module: str = "") -> list:
    """Findings (check `robust`). The original must compile first; the perturbations are only run then."""
    bounded = oracle if isinstance(oracle, Bounded) else Bounded(oracle, budget)
    d = _theorem(text, name)
    out: list = []
    label = name
    if d is None:
        return out
    base = bounded(text)
    if base.verdict is None:
        return [finding("robust", "inconclusive", "the toolchain gave no answer", name=label, line=d.line, module=module)]
    if base.verdict is False:
        return [finding("robust", "inconclusive", "the original does not compile, so nothing can be compared", name=label, line=d.line, module=module)]

    def ask(candidate: str):
        got = bounded(candidate)
        return got.verdict

    # 1. each set_option, removed on its own: a proof that needs one of them says so
    for opt in options_used(text):
        got = ask(_without_option(text, opt))
        if got is None:
            out.append(finding("robust", "inconclusive", f"no answer with `{opt}` removed", name=label, line=d.line, module=module))
            break
        if got is False:
            sev = "warn"
            out.append(finding("robust", sev, f"the module needs `set_option {opt}`; a library inherits what the author's settings hide",
                               name=label, line=d.line, module=module, rule="needs_option"))
    # 2. the library's own defaults for implicit variables
    if "autoImplicit" not in options_used(text):
        got = ask(_after_imports(text, "set_option autoImplicit false\nset_option relaxedAutoImplicit false"))
        if got is False:
            out.append(finding("robust", "fail", "the module only compiles with `autoImplicit` on: a misspelled variable would be a new implicit",
                               name=label, line=d.line, module=module, rule="auto_implicit"))
        elif got is None:
            out.append(finding("robust", "inconclusive", "no answer with `autoImplicit` off", name=label, line=d.line, module=module))
    # 3. half the heartbeats on the theorem itself
    if "maxHeartbeats" not in options_used(text):
        halved = L.splice(text, d.start, d.start, f"set_option maxHeartbeats {HALF_BEATS} in\n")
        got = ask(halved)
        if got is False:
            out.append(finding("robust", "warn", f"the theorem does not compile with maxHeartbeats {HALF_BEATS}: it is close to the default limit",
                               name=label, line=d.line, module=module, rule="heartbeats_margin"))
        elif got is None:
            out.append(finding("robust", "inconclusive", "no answer with half the heartbeats", name=label, line=d.line, module=module))
    return out


def _after_imports(text: str, block: str) -> str:
    end = L.import_end(text)
    return text[:end] + ("\n" if end else "") + block + "\n" + text[end:]


def findings(text: str, oracle: Compile, names=None, budget_per_theorem: int = 120, module: str = "") -> list:
    """`minimise` findings (a removable step or a one-tactic proof is a `warn` carrying the verified patch) and `robust` findings."""
    out: list = []
    for d in L.declarations(text):
        if not d.is_theorem or not d.name or (names is not None and d.full_name not in names and d.name not in names):
            continue
        label = d.full_name or d.name
        bounded = Bounded(oracle, budget_per_theorem)
        res = minimise_proof(text, label, bounded, budget_per_theorem)
        if res["stopped"] in ("no_answer", "budget"):
            out.append(finding("minimise", "inconclusive", f"the search stopped ({res['stopped']}) after {res['calls']} compiler calls",
                               name=label, line=d.line, module=module))
        if res["patch"]:
            out.append(finding("minimise", "warn", f"{res['removed']} of {res['steps']} tactic steps are not needed", name=label, line=d.line,
                               module=module, patch=res["patch"]))
        closer, patch = automation_closes(text, label, bounded)
        if closer:
            out.append(finding("minimise", "warn", f"`{closer}` alone proves it: a one-line proof, and a statement to ask about", name=label,
                               line=d.line, module=module, patch=patch, closer=closer))
        out += robustness(text, label, bounded, module=module)
    return out
