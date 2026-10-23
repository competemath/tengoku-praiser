"""Documentation: the module docstring, a docstring on every definition, docstrings that say something, references that resolve.

What Mathlib's `docBlame` linter and its reviewers ask of the text around the code, as findings (check `docs`). No Lean needed:

  module_doc      a `/-! ... -/` after the imports (fail when missing), opening with a `# Title` (warn), and, once the file has
                  declarations, saying what they are (a `## Main results` or `## Main definitions` section; warn)
  def_doc         a public definition, structure, class or inductive without a docstring (fail)
  theorem_doc     a public theorem whose statement is not trivial and has no docstring (warn)
  doc_style       a docstring that does not start with a capital letter or end with a full stop, is under 12 characters, or only
                  repeats the declaration's name (warn)
  dangling_ref    a name in backticks that resolves to no declaration of this module or of the library (warn); judged only when the
                  library's names are given (`known`), because a reference into another module cannot otherwise be told from a mistake.
                  Only dotted, underscored or capitalised names are judged, so `x` and `a + b` are left alone.
  header          the file does not start with the expected header (only when a pattern is given)
"""

from __future__ import annotations

import re

from . import leansrc as L
from .review import finding

MIN_DOC = 12
TRIVIAL_TOKENS = 6
REFERENCE = re.compile(r"`([^`\n]+)`")
NAME_LIKE = re.compile(r"^[A-Za-z_][\w.'!?]*$")
NOT_NAMES = {
    "simp", "omega", "ring", "rfl", "by", "fun", "Prop", "Type", "Sort", "Nat", "Int", "Real", "Set", "Finset", "List", "True", "False",
    "sorry", "decide", "linarith", "nlinarith", "norm_num", "exact", "intro", "apply", "rw", "have", "let", "theorem", "lemma", "def",
    "structure", "class", "instance", "namespace", "section", "open", "import", "simp_all", "aesop", "positivity", "tauto", "Lean", "Mathlib",
}
HEADING = re.compile(r"^#{1,6}\s+\S", re.M)


def _f(sev: str, rule: str, detail: str, name: str = "", line: int = 0) -> dict:
    return finding("docs", sev, detail, name=name or rule, line=line, rule=rule)


def module_docstrings(text: str):
    return [s for s in L.spans(text) if s.kind == "mod"]


def _judged(ref: str) -> bool:
    return bool(NAME_LIKE.match(ref)) and ref not in NOT_NAMES and ("." in ref or "_" in ref or ref[:1].isupper())


def _resolves(ref: str, local: set, known) -> bool:
    if ref in local or any(n == ref or n.endswith("." + ref) for n in local):
        return True
    return ref in known or any(k.endswith("." + ref) for k in known)


def check_module(text: str, known=None, header_pattern: str | None = None, module: str = "") -> list:
    out: list = []
    decls = L.declarations(text)
    mods = module_docstrings(text)
    public = [d for d in decls if not d.private and d.name]
    if header_pattern and not re.match(header_pattern, text):
        out.append(_f("fail", "header", "the file does not start with the expected header", line=1))
    if decls and not mods:
        out.append(_f("fail", "module_doc", "no module docstring (`/-! ... -/`)", line=1))
    elif mods:
        doc = text[mods[0].start + 3:mods[0].end - 2]
        line = L.line_of(text, mods[0].start)
        first = next((ln for ln in doc.strip().splitlines() if ln.strip()), "")
        if not first.lstrip().startswith("# "):
            out.append(_f("warn", "module_doc", "the module docstring does not open with a `# Title`", line=line))
        if public and not re.search(r"^#{2,}\s*Main (?:results|definitions|statements)", doc, re.M | re.I):
            out.append(_f("warn", "module_doc", "the module docstring has no `## Main results` / `## Main definitions` section", line=line))
        first_decl = min((d.start for d in decls), default=None)
        if first_decl is not None and mods[0].start > first_decl:
            out.append(_f("warn", "module_doc", "the module docstring comes after the first declaration", line=line))
    local = {d.full_name for d in decls if d.full_name} | {d.name for d in decls if d.name}
    for d in public:
        name = d.full_name or d.name
        if d.kind in ("def", "abbrev", "structure", "class", "inductive") and d.doc is None:
            out.append(_f("fail", "def_doc", f"public {d.kind} without a docstring", name, d.line))
        elif d.is_theorem and d.doc is None:
            stmt = L.statement_text(text, d)
            _, _, concl = L.signature(stmt)
            if concl is not None and len(L.tokens(concl)) > TRIVIAL_TOKENS:
                out.append(_f("warn", "theorem_doc", "theorem with a non-trivial statement and no docstring", name, d.line))
        if d.doc is not None:
            doc = " ".join(d.doc.split())
            short = d.name.split(".")[-1]
            if len(doc) < MIN_DOC:
                out.append(_f("warn", "doc_style", "the docstring is too short to say anything", name, d.line))
            elif doc.replace("_", " ").lower().rstrip(".") == short.replace("_", " ").lower():
                out.append(_f("warn", "doc_style", "the docstring only repeats the name", name, d.line))
            elif not (doc[0].isupper() or doc[0] in "`$∀∃(" or doc[0].isdigit()) or not doc.endswith((".", ":", "?", "!", "$", "`", ")")):
                out.append(_f("warn", "doc_style", "start a docstring with a capital and end it with a full stop", name, d.line))
    if known is not None:  # without the library's names a reference into another module cannot be told from a mistake
        docs = [(s, text[s.start:s.end]) for s in L.spans(text) if s.kind in ("doc", "mod")]
        for s, body in docs:
            for ref in sorted({r.strip() for r in REFERENCE.findall(body)}):
                if _judged(ref) and not _resolves(ref, local, known):
                    out.append(_f("warn", "dangling_ref", f"`{ref}` is not a declaration of this module or the library", line=L.line_of(text, s.start)))
    out.sort(key=lambda f: (f["line"], f["rule"], f["name"]))
    return [dict(f, module=module) if module else f for f in out]
