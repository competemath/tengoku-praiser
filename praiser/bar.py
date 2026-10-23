"""The bar: what a theorem must show before it is put into Tengoku, as a function of the reviewer's findings (praiser/reviewer.py).

Version `bar/0`, set for the first prototype of the studied lane. A person can change it by changing the tables here; the version string travels with every verdict so that two
verdicts of different bars are never compared. A verdict is one of

  accept   nothing blocks it and it shows merit
  return   something blocks it that the author can fix: the codes say what (a revision request, in the words of the notices catalogue of competemath.com)
  reject   final: it is not worth a second look (a sorry, a trusted compiler, an axiom, a statement that is already in the tree)

Blocking: any `fail` finding of a check (every `fail` the reviewer's checks emit is something a Mathlib reviewer sends a proposal back for), and an `inconclusive` finding of a check the
bar REQUIRES (a check that ran and could not decide is not a pass). `warn` and `info` findings never block; they are listed.

Merit: a theorem that blocks on nothing is accepted only if it shows at least ONE sign that the library wants it:
  reused        existing declarations of the library prove an instance of it inline (the `reuse` check)
  generalises   it states something more general than existing statements (the `dedupe` check)
  five_stars    its author's own sleep stage rated it five stars (a claim: only worth something next to a library that agrees)
  cited         another theorem of the same bundle uses it (`facts.cited_by`)
No sign, no entry: `bar.merit`, which the notice tells the author in the words "make it more general, or show a use".

Pure: findings in, verdicts out; no file, network or clock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

BAR_VERSION = "bar/0"

# a finding with one of these codes ends the matter
FINAL = frozenset({"style.sorry", "style.native_decide", "style.unverified_code", "dedupe.identical", "naming.taken"})
# checks whose `inconclusive` blocks: they ran and did not decide
REQUIRED = frozenset({"style", "naming", "docs", "dedupe", "lint", "compiler", "generalise", "minimise", "robust", "compat"})
# the code of a finding whose rule does not name it (the notices catalogue has words for these)
CODE_OF_CHECK = {"lint": "lint.env", "robust": "robust.fragile", "compat": "compat.forward", "generalise": "generalise.patch"}
CODE = re.compile(r"^[a-z][a-z0-9_]{0,30}(\.[a-z0-9_]{1,40}){0,2}$")


@dataclass
class Verdict:
    item: str
    verdict: str
    codes: list = field(default_factory=list)
    merit: list = field(default_factory=list)
    notes: list = field(default_factory=list)  # the warnings, for a person
    bar: str = BAR_VERSION

    def as_dict(self) -> dict:
        return {"item": self.item, "verdict": self.verdict, "codes": self.codes, "merit": self.merit, "notes": self.notes, "bar": self.bar}


def code_of(f: dict) -> str:
    """`style.line_length`, `dedupe.identical`, `generalise.patch`, `lint.env`: the check and its rule, in the vocabulary of the notices catalogue."""
    check = str(f.get("check", ""))
    if check in CODE_OF_CHECK:
        return CODE_OF_CHECK[check]
    rule = str(f.get("rule") or "")
    code = f"{check}.{rule}" if rule else check
    code = re.sub(r"[^a-z0-9_.]", "_", code.lower())
    return code if CODE.match(code) else (check if CODE.match(check) else "bar.other")


def merit_signs(findings: list, facts: dict) -> list:
    out = []
    if any(f.get("check") == "reuse" and f.get("rule") == "reused" for f in findings):
        out.append("reused")
    if any(f.get("check") == "dedupe" and f.get("rule") == "generalises" for f in findings):
        out.append("generalises")
    if facts.get("stars") == 5:
        out.append("five_stars")
    if isinstance(facts.get("cited_by"), int) and facts["cited_by"] >= 1:
        out.append("cited")
    return out


def decide_one(item: str, findings: list, facts: dict | None = None, ran: set | None = None) -> Verdict:
    """The verdict on one theorem from the findings about it. `ran`: the checks that ran (a required check that did not run cannot block: `not_run` is the caller's to report)."""
    facts = facts or {}
    v = Verdict(item, "accept")
    blocking: list = []
    for f in findings:
        sev, code = f.get("severity"), code_of(f)
        if sev == "fail":
            blocking.append(code)
        elif sev == "inconclusive" and (ran is None or f.get("check") in ran) and f.get("check") in REQUIRED:
            blocking.append(f"{f.get('check')}.inconclusive")
        elif sev == "warn":
            v.notes.append(code)
    blocking = sorted(set(blocking))
    v.merit = merit_signs(findings, facts)
    if any(c in FINAL for c in blocking):
        v.verdict, v.codes = "reject", [c for c in blocking if c in FINAL] + [c for c in blocking if c not in FINAL]
    elif blocking:
        v.verdict, v.codes = "return", blocking
    elif not v.merit:
        v.verdict, v.codes = "return", ["bar.merit"]
    v.notes = sorted(set(v.notes))
    return v


def decide(findings: list, items: dict, facts: dict | None = None, ran: set | None = None) -> dict:
    """Verdicts for every item. `items` maps an item (an entry id) to the module name its findings carry; `facts` maps an item to what the bar needs besides findings
    (`stars`, `cited_by`). Findings about no item (a bundle-wide finding such as a copied helper) block every item they name by module, or none."""
    out = {}
    for item, module in sorted(items.items()):
        mine = [f for f in findings if f.get("module") == module]
        out[item] = decide_one(item, mine, (facts or {}).get(item), ran)
    return out


def summary(verdicts: dict) -> dict:
    n = {"accept": 0, "return": 0, "reject": 0}
    for v in verdicts.values():
        n[v.verdict] += 1
    return {"bar": BAR_VERSION, **n}
