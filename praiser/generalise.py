"""The generalisation ladder: is there a more general statement the same proof still proves?

A Mathlib reviewer's most common request on a new lemma is "this holds more generally". The ladder asks the compiler. For one
theorem it builds candidate statements, from the cheapest rung up, puts each in the module in place of the original with the
ORIGINAL PROOF, and asks the oracle whether the module still compiles. A candidate that compiles is a verified patch: the
text of the module that was checked, not a suggestion. Nothing is proposed that was not compiled.

Rungs (each is a pure text edit of the statement; the oracle is the only judge):
  drop_hypothesis     remove the i-th named hypothesis binder. If it compiles the hypothesis was unused.
  literal_to_variable replace a numeral by a fresh natural-number variable `(k : ℕ)`.
  type_generalise     replace a concrete number type (ℕ ℤ ℚ ℝ) by a type variable with the weakest class bundle that still compiles,
                      walking CLASS_LADDER from weakest to strongest and keeping the first that compiles.
  weaken_order        replace `<` in a hypothesis by `≤` (a weaker hypothesis).

A rung that does not compile leaves the statement alone. The ladder is greedy and order-dependent: it applies a verified rung
to the statement and continues from the result, and records the order, so the final patch is reproducible from the original.
Each oracle call is counted against a budget; running out is `inconclusive` (the ladder stopped, what it verified so far stands).

The class names are Mathlib's current ones and live in one table (`CLASS_LADDER`). A toolchain that renames a class makes that
rung fail to compile, which is the safe direction: the ladder finds less, it never claims more. Run on the toolchain the
library builds with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import leansrc as L
from .oracle import Bounded, Compile
from .review import finding

# Weakest to strongest. The first bundle that compiles wins. `{a}` is the type variable.
CLASS_LADDER = {
    "ℕ": (("Semiring", "[Semiring {a}]"), ("CommSemiring", "[CommSemiring {a}]"),
          ("StrictOrderedSemiring", "[Semiring {a}] [PartialOrder {a}] [IsStrictOrderedRing {a}]"),
          ("LinearOrderedSemiring", "[Semiring {a}] [LinearOrder {a}] [IsStrictOrderedRing {a}]")),
    "ℤ": (("Ring", "[Ring {a}]"), ("CommRing", "[CommRing {a}]"),
          ("OrderedRing", "[Ring {a}] [PartialOrder {a}] [IsOrderedRing {a}]"),
          ("LinearOrderedRing", "[Ring {a}] [LinearOrder {a}] [IsStrictOrderedRing {a}]")),
    "ℚ": (("DivisionRing", "[DivisionRing {a}]"), ("Field", "[Field {a}]"),
          ("LinearOrderedField", "[Field {a}] [LinearOrder {a}] [IsStrictOrderedRing {a}]")),
    "ℝ": (("Field", "[Field {a}]"), ("LinearOrderedField", "[Field {a}] [LinearOrder {a}] [IsStrictOrderedRing {a}]")),
}
TYPE_VAR = "α"
MAX_RUNGS = 24
FRESH = "k"


@dataclass
class Step:
    rung: str
    detail: str
    text: str  # the module that compiled


@dataclass
class Ladder:
    name: str
    steps: list = field(default_factory=list)
    final: str = ""  # the module text after every verified step
    stopped: str | None = None  # why it stopped early: "budget", "no_answer"
    calls: int = 0

    @property
    def improved(self) -> bool:
        return bool(self.steps)


def _fresh_name(statement: str) -> str:
    used = set(L.tokens(statement))
    for cand in (FRESH, "k'", "m", "j", "l", "p"):
        if cand not in used:
            return cand
    return "k₀"


def _with_statement(text: str, d: L.Decl, statement: str) -> str:
    return L.splice(text, d.stmt_span[0], d.stmt_span[1], " " + statement.strip() + " ")


def _drop(statement: str, i: int) -> str | None:
    _, binders, _ = L.signature(statement)
    spans, depth, start = [], 0, -1
    colon = L.top_level(statement, ":")
    limit = len(statement) if colon < 0 else colon
    for k in range(limit):
        ch = statement[k]
        if ch in L.OPEN:
            if depth == 0 and ch == "(":
                start = k
            depth += 1
        elif ch in L.CLOSE:
            depth = max(0, depth - 1)
            if depth == 0 and ch == ")" and start >= 0:
                inner = statement[start + 1:k].strip()
                if re.match(r"^h[\w']*(?:\s+h[\w']*)*\s*:", inner):
                    spans.append((start, k + 1))
                start = -1
    if not 0 <= i < len(spans):
        return None
    a, b = spans[i]
    return re.sub(r"[ \t]{2,}", " ", statement[:a].rstrip() + " " + statement[b:].lstrip()).strip()


def _hypothesis_count(statement: str) -> int:
    i = 0
    while _drop(statement, i) is not None:
        i += 1
    return i


def _numerals(statement: str) -> list:
    """The distinct numerals other than 0 and 1, in order of first appearance."""
    seen: list = []
    for m in re.finditer(r"(?<![\w.'])[0-9]+(?![\w.'])", statement):
        if m.group(0) not in ("0", "1") and m.group(0) not in seen:
            seen.append(m.group(0))
    return seen


def _literal_variable(statement: str, k: int) -> str | None:
    """Replace EVERY occurrence of the k-th distinct numeral by a fresh variable and bind it before the colon."""
    nums = _numerals(statement)
    if not 0 <= k < len(nums) or L.top_level(statement, ":") < 0:
        return None
    fresh = _fresh_name(statement)
    new = re.sub(r"(?<![\w.'])" + re.escape(nums[k]) + r"(?![\w.'])", fresh, statement)
    colon = L.top_level(new, ":")
    return new[:colon].rstrip() + f" ({fresh} : ℕ) " + new[colon:].lstrip()


def _type_generalise(statement: str, type_name: str, bundle: str) -> str | None:
    pattern = re.compile(r"(?<![\w.'])" + re.escape(type_name) + r"(?![\w.'])")
    colon = L.top_level(statement, ":")
    if colon < 0 or not pattern.search(statement):
        return None
    replaced = pattern.sub(TYPE_VAR, statement)
    if TYPE_VAR in L.tokens(statement):
        return None
    colon = L.top_level(replaced, ":")
    binders = "{" + TYPE_VAR + " : Type*} " + bundle.format(a=TYPE_VAR)
    name_end = L.NAME_AT.match(replaced.strip())
    if name_end is None:
        return None
    s = replaced.strip()
    return s[:name_end.end()] + " " + binders + s[name_end.end():]


def _weaken(statement: str, k: int) -> str | None:
    _, binders, _ = L.signature(statement)
    spans = []
    colon = L.top_level(statement, ":")
    limit = len(statement) if colon < 0 else colon
    for m in re.finditer(r"(?<![-=<|$*>;])<(?![-;|$*>=])", statement[:limit]):
        spans.append(m.start())
    if not 0 <= k < len(spans):
        return None
    p = spans[k]
    return statement[:p] + "≤" + statement[p + 1:]


def _candidates(statement: str):
    """(rung, detail, new statement) in ladder order, for the statement as it stands."""
    for i in range(_hypothesis_count(statement)):
        new = _drop(statement, i)
        if new:
            yield "drop_hypothesis", f"hypothesis #{i}", new
    for k in range(len(_numerals(statement))):
        new = _literal_variable(statement, k)
        if new:
            yield "literal_to_variable", f"numeral {_numerals(statement)[k]}", new
    for t, ladder in CLASS_LADDER.items():
        for cls, bundle in ladder:
            new = _type_generalise(statement, t, bundle)
            if new:
                yield "type_generalise", f"{t} to {cls}", new
    for k in range(len(re.findall(r"<", statement))):
        new = _weaken(statement, k)
        if new:
            yield "weaken_order", f"comparison #{k}", new


def climb(text: str, name: str, oracle: Compile, budget: int = 40) -> Ladder:
    """Run the ladder on one theorem of `text` (by full name or last component). The original must compile first: if the oracle says it does
    not, nothing is concluded (`stopped = "original"`)."""
    bounded = oracle if isinstance(oracle, Bounded) else Bounded(oracle, budget)
    ladder = Ladder(name=name, final=text)
    decls = [d for d in L.declarations(text) if d.is_theorem and name in (d.full_name, d.name)]
    if len(decls) != 1:
        ladder.stopped = "not_found" if not decls else "ambiguous"
        return ladder
    base = bounded(text)
    if base.verdict is None:
        ladder.stopped = "no_answer"
        ladder.calls = bounded.calls
        return ladder
    if base.verdict is False:
        ladder.stopped = "original"
        ladder.calls = bounded.calls
        return ladder
    current = text
    type_done: set = set()
    for _ in range(MAX_RUNGS):
        d = next((x for x in L.declarations(current) if x.is_theorem and name in (x.full_name, x.name)), None)
        if d is None:
            break
        statement = L.statement_text(current, d)
        progressed = False
        for rung, detail, new in _candidates(statement):
            if rung == "type_generalise":
                if detail.split(" to ")[0] in type_done:
                    continue
            candidate = _with_statement(current, d, new)
            got = bounded(candidate)
            if got.verdict is None:
                ladder.stopped = "budget" if bounded.exhausted else "no_answer"
                ladder.final, ladder.calls = current, bounded.calls
                return ladder
            if got.verdict:
                ladder.steps.append(Step(rung, detail, candidate))
                current = candidate
                progressed = True
                if rung == "type_generalise":
                    type_done.add(detail.split(" to ")[0])
                break
        if not progressed:
            break
    ladder.final, ladder.calls = current, bounded.calls
    return ladder


def findings(text: str, oracle: Compile, names=None, budget_per_theorem: int = 40, module: str = "") -> list:
    """Findings for every theorem (or `names`): a verified patch is a `fail` (return the proposal with the patch), no patch is silent.
    A ladder that could not run is `inconclusive`."""
    out = []
    for d in L.declarations(text):
        if not d.is_theorem or not d.name or (names is not None and d.full_name not in names and d.name not in names):
            continue
        lad = climb(text, d.full_name or d.name, Bounded(oracle, budget_per_theorem), budget_per_theorem)
        label = d.full_name or d.name
        if lad.stopped in ("no_answer", "budget"):
            out.append(finding("generalise", "inconclusive",
                               ("the toolchain gave no answer" if lad.stopped == "no_answer" else "the oracle budget ran out") +
                               (f" after {len(lad.steps)} verified step(s)" if lad.steps else ""), name=label, line=d.line, module=module))
        if lad.stopped == "original":
            out.append(finding("generalise", "inconclusive", "the original does not compile, so nothing can be compared", name=label,
                               line=d.line, module=module))
            continue
        if lad.improved:
            what = "; ".join(f"{s.rung}: {s.detail}" for s in lad.steps)
            out.append(finding("generalise", "fail", f"a more general statement compiles with the same proof ({what})", name=label,
                               line=d.line, module=module, patch=lad.final, steps=[s.rung for s in lad.steps]))
    return out
