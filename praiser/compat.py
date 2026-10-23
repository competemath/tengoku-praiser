"""Forward compatibility: does the module still compile on the next toolchain, and does it use anything already on its way out?

Tengoku pins one Lean and Mathlib and moves them in bumps. A lemma that compiles today and breaks on the next release is a
maintenance cost the proposer can see in advance, and a lemma written against a deprecated name is already late. Two oracles are
asked, the toolchain the tree builds with (`primary`) and the one it will move to (`forward`):

  deprecated   a warning that a name is deprecated, on either toolchain (fail on the primary: the replacement is named in the
               message and the fix is a rename)
  forward      the module does not compile on `forward`. Each error is classified (removed name, missing instance, tactic that
               no longer closes the goal, type mismatch, syntax) so the fix is findable. Severity is a parameter: the bar is the
               statute's to set; the default is `warn`.
  drift        the elaborated statement (`#check @name` printed on both toolchains) differs between them. A warning, because a
               renamed instance changes the text without changing the meaning.

The module has to compile on the primary first. No answer from `forward` is `inconclusive`: an unavailable toolchain is never a pass.
"""

from __future__ import annotations

import re

from . import leansrc as L
from .oracle import Compile, errors, messages
from .review import finding

DEPRECATED = re.compile(r"`([^`]+)` has been deprecated(?:,? use `([^`]+)` instead)?")
CATEGORIES = (
    ("removed", re.compile(r"unknown (?:identifier|constant|namespace)|invalid field|unknown declaration", re.I)),
    ("instance", re.compile(r"failed to synthesize|typeclass instance problem|instance .* not found", re.I)),
    ("tactic", re.compile(r"(?:linarith|nlinarith|omega|simp|ring|norm_num|positivity|aesop|decide|polyrith|field_simp) failed|"
                          r"simp made no progress|unsolved goals|ring_nf failed|no progress", re.I)),
    ("type", re.compile(r"type mismatch|application type mismatch|expected type|has type", re.I)),
    ("syntax", re.compile(r"unexpected token|parse error|expected '", re.I)),
)
MAX_REPORTED = 12


def classify(message: str) -> str:
    for name, pattern in CATEGORIES:
        if pattern.search(message):
            return name
    return "other"


def deprecations(output: str) -> list:
    """[(old, new or None, line)] for each deprecation warning in an oracle's output."""
    out = []
    for m in messages(output):
        d = DEPRECATED.search(m.text)
        if d:
            out.append((d.group(1), d.group(2), m.line))
    return out


def probe(text: str, name: str) -> str:
    """The module with a `#check` of the declaration's elaborated type appended."""
    return text.rstrip("\n") + f"\n\nset_option pp.explicit true in\n#check @{name}\n"


def _signature_of(output: str) -> str | None:
    infos = [m for m in messages(output) if m.severity == "info"]
    return " ".join(infos[-1].text.split()) if infos else None


def forward_compat(text: str, primary: Compile, forward: Compile, names=None, severity: str = "warn", module: str = "") -> list:
    """Findings (check `compat`). `names` limits the statement-drift probe to those theorems (default: all theorems)."""
    p = primary(text)
    if p.verdict is None:
        return [finding("compat", "inconclusive", "the primary toolchain gave no answer", name="primary", module=module)]
    if p.verdict is False:
        return [finding("compat", "inconclusive", "the module does not compile on the primary toolchain, so nothing can be compared",
                        name="primary", module=module)]
    out: list = []
    for old, new, line in deprecations(p.output):
        out.append(finding("compat", "fail", f"`{old}` is deprecated" + (f"; use `{new}`" if new else ""), name=old, line=line, module=module,
                           rule="deprecated", replacement=new))
    f = forward(text)
    if f.verdict is None:
        out.append(finding("compat", "inconclusive", "the forward toolchain gave no answer; that is not a pass", name="forward", module=module))
        return out
    seen = {d[0] for d in deprecations(p.output)}
    for old, new, line in deprecations(f.output):
        if old not in seen:
            out.append(finding("compat", "warn", f"`{old}` is deprecated on the forward toolchain" + (f"; use `{new}`" if new else ""), name=old,
                               line=line, module=module, rule="deprecated_soon", replacement=new))
    if f.verdict is False:
        errs = errors(f.output)
        if not errs:  # a sorry the primary did not report, or an exit status without a message
            out.append(finding("compat", severity, "the module does not compile on the forward toolchain (no error message was captured)",
                               name="forward", module=module, rule="forward_break"))
        for m in errs[:MAX_REPORTED]:
            first = m.text.splitlines()[0] if m.text else "error"
            out.append(finding("compat", severity, f"on the forward toolchain ({classify(m.text)}): {first}", name=classify(m.text), line=m.line,
                               module=module, rule="forward_break", category=classify(m.text)))
        if len(errs) > MAX_REPORTED:
            out.append(finding("compat", severity, f"{len(errs) - MAX_REPORTED} more errors on the forward toolchain", name="forward", module=module,
                               rule="forward_break"))
        return out
    for d in L.declarations(text):
        if not d.is_theorem or not d.name or (names is not None and d.full_name not in names and d.name not in names):
            continue
        label = d.full_name or d.name
        a, b = primary(probe(text, label)), forward(probe(text, label))
        sa, sb = _signature_of(a.output), _signature_of(b.output)
        if a.verdict is None or b.verdict is None or sa is None or sb is None:
            out.append(finding("compat", "inconclusive", "the statement could not be printed on both toolchains", name=label, line=d.line,
                               module=module, rule="drift"))
        elif sa != sb:
            out.append(finding("compat", "warn", "the statement elaborates differently on the forward toolchain", name=label, line=d.line,
                               module=module, rule="drift"))
    return out
