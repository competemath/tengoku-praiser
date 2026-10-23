"""Is it already there, would anyone use it, and are its helpers copied?

Three checks over an INDEX of statements (the tree's modules and the other bundles in the same proposal), all on text:

duplicates   the new statement against the index:
               identical          same statement up to renaming (fail)
               instance_of        an existing statement is more general: the new one is a specialisation of it (warn)
               near_duplicate     a very similar statement (token shingles, Jaccard at least NEAR) (warn)
               generalises        the new statement is more general than existing ones (info, and the merit that goes with it)
reuse        the new statement as a pattern, run over the proofs in the index: how many `have`/`show` steps in how many existing
             declarations prove an instance of it inline? Those are places a reader would have reached for it. None at all, and
             no existing statement is an instance of it, is the finding `unused` (warn): nothing in the library wants it.
hoist        helpers that two or more modules of the proposal carry as identical copies: the plan to move them to one shared
             module, and the rewritten modules. `apply_hoist` only builds the texts; the caller compiles them (oracle) before
             offering them.

Matching is on the normalised token form of leansrc (names and spelling variants removed). It is a syntactic notion of "instance":
a statement whose conclusion fits the other's pattern and which has no fewer hypotheses. It finds what a grep with the right
regular expression would, reliably and everywhere; it does not find what needs unification up to defeq, and does not claim to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import leansrc as L
from .common import sha256_bytes
from .review import finding

NEAR = 0.9
SHINGLE = 3
MIN_LITERALS = 3  # a pattern with fewer constant tokens than this matches nearly anything and is not used for instance checks
BARE = frozenset("= ≠ ≤ < ≥ > ∈ ∉ ⊆ ∣ ↔ → ∧ ∨ ¬ ( ) 0 1 2 ,".split())
MAX_EXAMPLES = 6


_VAR = re.compile(r"_[0-9]+")


@dataclass
class Entry:
    module: str
    name: str
    line: int
    kind: str
    key: str
    tokens: list
    hypotheses: int
    conclusion: list
    shingles: frozenset = field(default_factory=frozenset)
    variables: frozenset = field(default_factory=frozenset)
    consts: frozenset = field(default_factory=frozenset)  # the conclusion's tokens that are not bound variables
    literals: int = 0
    present: frozenset = field(default_factory=frozenset)  # every token of the conclusion
    context: str = ""  # what the `variable` commands in scope say, when the statement uses them
    hyp_consts: frozenset = field(default_factory=frozenset)  # constants (not bound variables) in the binders, i.e. in the hypotheses


def _conclusion(tokens: list) -> list:
    depth = 0
    for i, t in enumerate(tokens):
        if t in L.OPEN:
            depth += 1
        elif t in L.CLOSE:
            depth -= 1
        elif t == ":" and depth == 0:
            return tokens[i + 1:]
    return []


def _shingles(tokens: list) -> frozenset:
    if len(tokens) < SHINGLE:
        return frozenset([tuple(tokens)])
    return frozenset(tuple(tokens[i:i + SHINGLE]) for i in range(len(tokens) - SHINGLE + 1))


def _resolution(d: L.Decl, statement: str, declared: set) -> dict:
    """Names in the statement that are declarations of the same module in (a parent of) the declaration's namespace."""
    out = {}
    if not d.namespace:
        return out
    parts = d.namespace.split(".")
    for t in set(L.tokens(statement)):
        for k in range(len(parts), 0, -1):
            cand = ".".join(parts[:k]) + "." + t
            if cand in declared:
                out[t] = cand
                break
    return out


def _variable_context(d: L.Decl, statement: str) -> str:
    """When the statement uses a name that a `variable` command binds, what that name stands for is part of what it says."""
    if not d.variables:
        return ""
    words = set(L.tokens(statement))
    used = [v for v in d.variables if words & set(re.findall(r"[^\W\d][\w'.]*", v.split(":")[0]))]
    return (" ||var " + " ".join(" ".join(L.canonical_tokens(v)) for v in d.variables)) if used else ""


def entries_of(module: str, text: str, kinds=("theorem", "lemma")) -> list:
    out = []
    decls = L.declarations(text)
    declared = {d.full_name for d in decls if d.full_name}
    for d in decls:
        if d.kind not in kinds or not d.name:
            continue
        stmt = L.statement_text(text, d)
        norm = L.normalise(stmt, resolve=_resolution(d, stmt, declared))
        if norm is None:
            continue
        context = _variable_context(d, stmt)
        key = norm.key + context
        concl = _conclusion(norm.tokens)
        head = norm.tokens[: len(norm.tokens) - len(concl)]
        hyp = frozenset(t for t in head if not _VAR.fullmatch(t) and t not in BARE and t not in ("_:", "[", "]", "{", "}", "⦃", "⦄", ":"))
        variables = frozenset(t for t in norm.tokens if _VAR.fullmatch(t))
        consts = frozenset(t for t in concl if not _VAR.fullmatch(t))
        out.append(Entry(module, d.full_name or d.name, d.line, d.kind, key, norm.tokens, norm.hypotheses, concl, _shingles(norm.tokens),
                         variables, consts, sum(1 for t in concl if not _VAR.fullmatch(t)), frozenset(concl), context, hyp))
    return out


class Index:
    def __init__(self):
        self.entries: list = []
        self.by_key: dict = {}
        self.texts: dict = {}
        self._inline: dict = {}

    def inline(self, module: str) -> list:
        """[(owner declaration name, line, tokens)] for every inline statement of a module, computed once."""
        if module not in self._inline:
            text = self.texts[module]
            owners = L.declarations(text)
            rows = []
            for offset, line, toks in inline_statements(text):
                if len(toks) > 80:
                    continue
                owner = next((d for d in owners if d.start <= offset < d.end), None)
                rows.append(((owner.full_name or owner.name) if owner and (owner.full_name or owner.name) else "?", line, toks))
            self._inline[module] = rows
        return self._inline[module]

    def add(self, module: str, text: str) -> None:
        self._inline.pop(module, None)
        self.texts[module] = text
        for e in entries_of(module, text):
            self.entries.append(e)
            self.by_key.setdefault(e.key, []).append(e)

    @classmethod
    def of(cls, modules: dict):
        ix = cls()
        for name in sorted(modules):
            ix.add(name, modules[name])
        return ix


def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def is_instance(general: Entry, specific: Entry) -> bool:
    """`specific` is a specialisation of `general`: its conclusion fits general's conclusion as a pattern, and it has at least as many hypotheses."""
    if general.literals < MIN_LITERALS or not general.conclusion or general.key == specific.key or not (general.consts - BARE):
        return False
    if specific.hypotheses < general.hypotheses or not general.consts <= specific.present:
        return False
    if general.context != specific.context or not general.hyp_consts <= (specific.hyp_consts | specific.present):
        return False  # a different `variable` context, or hypotheses the specific statement does not even mention
    return L.match(general.conclusion, specific.conclusion, general.variables) is not None


def duplicates(new: Entry, index: Index, self_module: str | None = None) -> list:
    """[(kind, existing entry)] for one new statement. Entries of `self_module` are skipped (a module is not its own duplicate)."""
    out = []
    for e in index.by_key.get(new.key, []):
        if e.module != self_module or e.name != new.name:
            out.append(("identical", e))
    seen = {id(e) for _, e in out}
    for e in index.entries:
        if id(e) in seen or (e.module == self_module and e.name == new.name):
            continue
        if e.key == new.key:
            continue
        if is_instance(e, new):
            out.append(("instance_of", e))
        elif is_instance(new, e):
            out.append(("generalises", e))
        elif jaccard(new.shingles, e.shingles) >= NEAR and new.context == e.context:
            out.append(("near_duplicate", e))
    return out


SEVERITY = {"identical": "fail", "instance_of": "warn", "near_duplicate": "warn", "generalises": "info"}
SENTENCE = {
    "identical": "is the same statement as", "instance_of": "is a specialisation of", "near_duplicate": "is almost the same statement as",
    "generalises": "generalises",
}


def duplicate_findings(module: str, text: str, index: Index, module_label: str = "") -> list:
    out = []
    for new in entries_of(module, text):
        found = duplicates(new, index, self_module=module)
        for kind in ("identical", "instance_of", "near_duplicate", "generalises"):
            hits = [e for k, e in found if k == kind]
            if not hits:
                continue
            shown = ", ".join(f"{e.name} ({e.module})" for e in hits[:3]) + (f" and {len(hits) - 3} more" if len(hits) > 3 else "")
            out.append(finding("dedupe", SEVERITY[kind], f"{new.name} {SENTENCE[kind]} {shown}", name=new.name, line=new.line,
                               module=module_label or module, rule=kind, others=[f"{e.module}:{e.name}" for e in hits[:MAX_EXAMPLES]]))
    return out


# --------------------------------------------------------------------------------------------------------------------- reuse

HAVE = re.compile(r"(?<![\w'.])(?:have|show|suffices)\s+(?:[\w'.]+\s*)?(?:\([^)]*\)\s*)*:\s*", re.S)


SHOW = re.compile(r"(?<![\w'.])show\s+")


def _stated(masked: str, start: int) -> tuple:
    """(proposition text, end offset) of the statement beginning at `start`: up to `:=`, ` from `, ` by`, a newline or the closing bracket."""
    depth = 0
    k = start
    while k < len(masked):
        ch = masked[k]
        if ch in L.OPEN:
            depth += 1
        elif ch in L.CLOSE:
            depth -= 1
            if depth < 0:
                break
        elif depth == 0 and (masked.startswith(":=", k) or masked.startswith(" from ", k) or masked.startswith(" by", k) or ch == "\n"):
            break
        k += 1
    return masked[start:k].strip(), k


def inline_statements(text: str):
    """(offset, line, tokens of the stated proposition) for each `have h : P :=`, `suffices h : P`, `show P from/by`, in the masked text."""
    masked = L.mask(text)
    found = []
    for m in HAVE.finditer(masked):
        found.append((m.start(), _stated(masked, m.end())[0]))
    for m in SHOW.finditer(masked):
        found.append((m.start(), _stated(masked, m.end())[0]))
    for offset, stmt in sorted(found):
        if stmt:
            yield offset, L.line_of(text, offset), L.canonical_tokens(stmt)


def reuse_report(new: Entry, index: Index, exclude_module: str | None = None) -> dict:
    """{"inline": [(module, declaration, line)], "instances": [Entry names], "modules": n, "declarations": n}."""
    out: dict = {"inline": [], "instances": [], "modules": 0, "declarations": 0}
    if new.literals < MIN_LITERALS or not new.conclusion:
        out["too_generic"] = True
        return out
    variables = set(new.variables)
    mods, decls = set(), set()
    for module in sorted(index.texts):
        if module == exclude_module:
            continue
        for label, line, toks in index.inline(module):
            if not new.consts <= set(toks):
                continue
            if L.match(new.conclusion, toks, variables) is not None:
                out["inline"].append((module, label, line))
                mods.add(module)
                decls.add((module, label))
    for e in index.entries:
        if e.module != exclude_module and is_instance(new, e):
            out["instances"].append(f"{e.module}:{e.name}")
    out["modules"], out["declarations"] = len(mods), len(decls)
    return out


def reuse_findings(module: str, text: str, index: Index, module_label: str = "") -> list:
    out = []
    for new in entries_of(module, text):
        rep = reuse_report(new, index, exclude_module=module)
        if rep.get("too_generic"):
            continue
        if rep["inline"] or rep["instances"]:
            ex = ", ".join(f"{m}:{n}" for m, n, _ in rep["inline"][:3])
            out.append(finding("reuse", "info",
                               f"{new.name}: {rep['declarations']} existing declaration(s) in {rep['modules']} module(s) prove an instance inline" +
                               (f" ({ex})" if ex else "") + (f"; {len(rep['instances'])} existing statement(s) are instances of it" if rep["instances"] else ""),
                               name=new.name, line=new.line, module=module_label or module, rule="reused",
                               inline_declarations=rep["declarations"], inline_modules=rep["modules"], instances=len(rep["instances"])))
        else:
            out.append(finding("reuse", "warn", f"{new.name}: nothing in the index proves an instance of it inline or states one", name=new.name,
                               line=new.line, module=module_label or module, rule="unused"))
    return out


# --------------------------------------------------------------------------------------------------------------------- hoist

def _body_key(text: str, d: L.Decl) -> str:
    return " ".join(L.body_text(text, d).split())


def hoist_plan(modules: dict) -> list:
    """Helpers (declarations with a name) that appear identically (same full name, same normalised statement, same proof) in two or
    more modules: [{"name", "modules", "kind", "bytes"}], sorted by name."""
    seen: dict = {}
    for module in sorted(modules):
        text = modules[module]
        for d in L.declarations(text):
            if not d.name or not d.full_name or d.kind in ("example", "instance") or d.body_span is None:
                continue
            norm = L.normalise(L.statement_text(text, d)) if d.is_theorem else None
            key = (d.full_name, d.kind, norm.key if norm else " ".join(L.statement_text(text, d).split()), _body_key(text, d))
            seen.setdefault(key, []).append((module, d))
    plan = []
    for (name, kind, _, _), where in sorted(seen.items(), key=lambda kv: kv[0][0]):
        mods = sorted({m for m, _ in where})
        if len(mods) >= 2:
            plan.append({"name": name, "kind": kind, "modules": mods, "bytes": sum(len(d.text) for _, d in where[1:])})
    return plan


def apply_hoist(modules: dict, shared_name: str, plan: list) -> dict:
    """The modules with the planned helpers moved to a new module `shared_name` (returned under that key) and an `import` added
    to each module that lost one. Only whole declarations whose namespace is the file's own are moved; imports of the shared module come
    last in the import block. The result is TEXT: compile it before it is offered."""
    names = {p["name"] for p in plan}
    out = dict(modules)
    moved: list = []
    imports: set = set()
    for module in sorted(modules):
        text = modules[module]
        cut = []
        for d in L.declarations(text):
            if d.full_name in names and d.body_span is not None:
                cut.append(d)
                if not any(m[0] == d.full_name for m in moved):
                    moved.append((d.full_name, d.namespace, d.kind, text[(d.doc_span[0] if d.doc_span else d.start):d.end]))
        for d in sorted(cut, key=lambda x: x.start, reverse=True):
            a = d.doc_span[0] if d.doc_span else d.start
            text = text[:a] + text[d.end:].lstrip("\n")
        if cut:
            text = _add_import(text, shared_name)
        out[module] = text
        for m in L.IMPORT_RE.finditer(L.mask(modules[module])):
            imports.add(m.group(1))
    body = []
    by_ns: dict = {}
    for name, ns, kind, src in moved:
        by_ns.setdefault(ns, []).append(src)
    for ns in sorted(by_ns):
        block = "\n\n".join(s.rstrip() for s in by_ns[ns])
        body.append(f"namespace {ns}\n\n{block}\n\nend {ns}" if ns else block)
    shared = "\n".join(f"import {i}" for i in sorted(imports)) + "\n\n" + "\n\n".join(body) + "\n"
    out[shared_name] = shared
    return out


def _add_import(text: str, shared: str) -> str:
    end = L.import_end(text)
    line = f"import {shared}"
    if not end:
        return line + "\n\n" + text
    return text[:end] + "\n" + line + text[end:]


def hoist_findings(modules: dict, shared_name: str = "Common") -> list:
    plan = hoist_plan(modules)
    out = []
    for p in plan:
        out.append(finding("hoist", "warn", f"{p['name']} is copied identically into {len(p['modules'])} modules ({', '.join(p['modules'][:3])}"
                           + (", ..." if len(p["modules"]) > 3 else "") + f"); move it to one shared module", name=p["name"],
                           module=p["modules"][0], rule="copied_helper", copies=len(p["modules"]), bytes=p["bytes"]))
    return out


def fingerprint(text: str) -> str:
    """A hash of the whole module's declarations (statements and proofs, normalised): two bundles with equal fingerprints are copies."""
    parts = []
    for d in L.declarations(text):
        parts.append(" ".join(L.statement_text(text, d).split()) + "|" + _body_key(text, d))
    return sha256_bytes("\n".join(parts).encode("utf-8"))
