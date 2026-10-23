"""API: is the set of statements a library would want here, and are they stated the way Mathlib states them?

A new definition is not finished until it has its lemmas, and a new lemma has siblings. This is the reviewer's "where is the
`_right` version?" and "what can I do with this definition?" as findings (check `api`), on text only:

  sibling      `X_left` without `X_right` (or the reverse) in the module, the tree or the other bundles (warn). The pairs are a
               table (`SIBLINGS`), so the convention is data. An `_iff` form next to an `_of_` form is not demanded.
  def_api      a definition no theorem of the module mentions (warn); a structure without an `ext` lemma (warn); a Prop-valued
               definition without a characterisation (`foo_iff`, `foo_def`; info)
  form         statements written against Mathlib's forms: a conclusion with `≥` or `>` (state it with `≤`/`<`), `¬ a = b`
               (`a ≠ b`), `¬ x ∈ s` (`x ∉ s`), `Nat.succ n` (`n + 1`), `Type u` in a binder (`Type*`) (warn)
"""

from __future__ import annotations

import re

from . import leansrc as L
from .review import finding

# (a, b, severity, anywhere): the pair is found in any word of the name, or only as the last word when `anywhere` is False
SIBLINGS = (("_left", "_right", "warn", True), ("_nonneg", "_pos", "info", False), ("_nonpos", "_neg", "info", False))
TOKEN_WORD = re.compile(r"[^\W\d][\w.'!?]*")


def _f(sev: str, rule: str, detail: str, name: str, line: int) -> dict:
    return finding("api", sev, detail, name=name, line=line, rule=rule)


def sibling_gaps(names: set, known=frozenset()) -> list:
    """[(present, missing, severity)] for names (full names) whose paired sibling exists nowhere in `names` or `known`.
    The pair is found by word: `foo_left'` pairs with `foo_right'`, `foo_left_iff` with `foo_right_iff`."""
    universe = set(names) | set(known)
    out = set()
    for n in sorted(names):
        head, dot, last = n.rpartition(".")
        base = last.rstrip("'")
        primes = last[len(base):]
        words = base.split("_")
        for a, b, sev, anywhere in SIBLINGS:
            for x, y in ((a.strip("_"), b.strip("_")), (b.strip("_"), a.strip("_"))):
                if x in words and (anywhere or (words[-1] == x and len(words) > 1)):
                    i = words.index(x) if anywhere else len(words) - 1
                    other = head + dot + "_".join(words[:i] + [y] + words[i + 1:]) + primes
                    if other not in universe:
                        out.add((n, other, sev))
    return sorted(out)


def check_module(text: str, known=frozenset(), module: str = "") -> list:
    out: list = []
    decls = L.declarations(text)
    names = {d.full_name for d in decls if d.full_name and d.is_theorem and not d.private}
    by_name = {d.full_name: d for d in decls if d.full_name}
    for present, missing, sev in sibling_gaps(names, known):
        d = by_name[present]
        out.append(_f(sev, "sibling", f"{present} has no `{missing.split('.')[-1]}` counterpart in the module or the library", present, d.line))
    statements = {d.full_name: L.statement_text(text, d) for d in decls if d.full_name}
    all_tokens = {t for s in statements.values() for t in TOKEN_WORD.findall(s)}
    theorem_text = " ".join(statements[d.full_name] for d in decls if d.is_theorem and d.full_name in statements)
    mentioned = set(TOKEN_WORD.findall(theorem_text))
    for d in decls:
        if not d.name or d.private:
            continue
        short = d.name.split(".")[-1]
        if d.kind in ("def", "abbrev") and not any(t == short or t.endswith("." + short) for t in mentioned):
            out.append(_f("warn", "def_api", f"no theorem of the module mentions the definition `{short}`: a definition comes with its lemmas",
                          d.full_name or d.name, d.line))
        if d.kind == "def":
            _, _, concl = L.signature(statements[d.full_name]) if d.full_name in statements else (None, None, None)
            if concl is not None and concl.strip() == "Prop":
                lower = short[:1].lower() + short[1:]
                wanted = {f"{x}_{y}" for x in (short, lower) for y in ("iff", "def", "iff_def")}
                if not any(n.split(".")[-1] in wanted for n in names | set(known)):
                    out.append(_f("info", "def_api", f"the predicate `{short}` has no characterisation lemma (`{short}_iff` or `{short}_def`)",
                                  d.full_name or d.name, d.line))
        if d.kind == "structure":
            has_ext = "ext" in d.attrs or any(n.split(".")[-1] in ("ext", "ext_iff") and n.startswith(d.full_name or "\0") for n in names | set(known))
            if not has_ext and "@[ext" not in text[max(0, d.start - 40):d.start + 1]:
                out.append(_f("warn", "def_api", f"the structure `{short}` has no `ext` lemma", d.full_name or d.name, d.line))
    for d in decls:
        if not d.is_theorem or not d.full_name:
            continue
        stmt = statements[d.full_name]
        _, binders, concl = L.signature(stmt)
        if concl is not None:
            top = L.canonical_tokens(concl)
            depth, flat = 0, []
            for t in top:
                depth += 1 if t in L.OPEN else -1 if t in L.CLOSE else 0
                if depth == 0:
                    flat.append(t)
            if any(t in ("≥", ">") for t in flat):
                out.append(_f("warn", "form", "state the conclusion with `≤` / `<`, not `≥` / `>`", d.full_name, d.line))
            if re.match(r"^¬\s*\(?[^()]*?(?<![<>≤≥≠])=[^=]", concl.strip()):
                out.append(_f("warn", "form", "write `a ≠ b`, not `¬ a = b`", d.full_name, d.line))
        if re.search(r"¬\s*\(?\s*[\w.']+\s*∈", stmt):
            out.append(_f("warn", "form", "write `x ∉ s`, not `¬ x ∈ s`", d.full_name, d.line))
        if re.search(r"(?<![\w'])(?:Nat\.)?succ\s+[\w(]", stmt) or re.search(r"\.succ\b", stmt):
            out.append(_f("warn", "form", "write `n + 1`, not `Nat.succ n`", d.full_name, d.line))
        if re.search(r"Type\s+(?:u|v|w|_)\b|Sort\s+(?:u|v|w)\b", stmt):
            out.append(_f("warn", "form", "write `Type*` rather than a named universe", d.full_name, d.line))
    out.sort(key=lambda f: (f["line"], f["rule"], f["name"]))
    return [dict(f, module=module) if module else f for f in out]
