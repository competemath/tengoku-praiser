"""Names: Mathlib's naming conventions as checks, and a deterministic suggester that says what the name should have been.

A name is checked three ways, none of which needs Lean:
  case         theorems and lemmas are snake_case, data-valued definitions lowerCamelCase, types, structures, classes and
               Prop-valued definitions UpperCamelCase (the namespace part of a name may be a type, so it is exempt).
  placeholder  `lemma1`, `aux`, `step_3`, `foo`, a hash: names that say nothing, or that a machine made.
  meaning      what the name says against what the statement says. The statement's operators and constants are turned into
               the words Mathlib uses (`+` add, `≤` le, `∣` dvd, `∑` sum ...). A name that mentions an operation the
               statement never uses is misleading; a name that shares nothing with the statement's own operators says
               nothing about it.

`suggest` builds the name Mathlib's conventions give: describe the conclusion, then `_of_` each hypothesis in order, `_iff_`
across an iff. It is a suggestion to put next to the actual name, not an oracle: a correct name can differ from it.
"""

from __future__ import annotations

import re

from . import leansrc as L
from .review import finding

WORDS = {
    "+": "add", "*": "mul", "/": "div", "^": "pow", "⁻¹": "inv", "∣": "dvd", "≤": "le", "<": "lt", "≥": "ge", ">": "gt", "=": "eq",
    "≠": "ne", "∈": "mem", "∉": "not_mem", "⊆": "subset", "⊂": "ssubset", "∪": "union", "∩": "inter", "∅": "empty", "∑": "sum",
    "∏": "prod", "¬": "not", "∧": "and", "∨": "or", "↔": "iff", "→": "imp", "∀": "forall", "∃": "exists", "∘": "comp", "⌊": "floor",
    "⌈": "ceil", "√": "sqrt", "≡": "modEq", "%": "mod", "•": "smul", "⊔": "sup", "⊓": "inf", "⊤": "top", "⊥": "bot", "⋃": "iUnion",
    "⋂": "iInter", "ℕ": "nat", "ℤ": "int", "ℚ": "rat", "ℝ": "real", "ℂ": "complex", "0": "zero", "1": "one", "2": "two", "3": "three",
    "4": "four",
}
# Words a name may use for a symbol besides the main one (a name using any of these counts as mentioning the symbol).
SYNONYMS = {
    "add": {"add", "succ", "sum", "plus"}, "mul": {"mul", "two_mul", "sq", "prod", "smul", "pow", "mul_self", "double"},
    "pow": {"pow", "sq", "npow", "zpow", "exp", "cube"}, "sub": {"sub", "tsub", "neg", "cancel"}, "div": {"div", "inv", "ediv"},
    "le": {"le", "lt", "mono", "monotone", "nonneg", "nonpos", "ge", "antitone", "min", "max", "abs", "bound", "upper", "lower"},
    "lt": {"lt", "le", "pos", "neg", "strict", "gt", "ne"}, "eq": {"eq", "ne", "iff", "comm", "assoc", "self", "def", "cancel", "inj",
                                                                    "left", "right", "zero", "one", "of"},
    "dvd": {"dvd", "div", "mod", "gcd", "lcm", "coprime", "prime", "factor"}, "mem": {"mem", "in", "subset", "exists", "card", "mem"},
    "sum": {"sum", "add", "range", "finset", "card"}, "prod": {"prod", "mul", "factorial", "fact", "pow", "range", "finset"},
}
IDENT = re.compile(r"^[^\W\d][\w.'!?]*$")
LOWER_SNAKE = re.compile(r"^[a-z_][a-zA-Z0-9_']*$")
UPPER_CAMEL = re.compile(r"^[A-Z][A-Za-z0-9']*$")
PLACEHOLDER = re.compile(
    r"^(?:lemma|lem|thm|theorem|claim|aux|auxiliary|helper|tmp|temp|test|foo|bar|baz|qux|main|step|prop|proposition|fact|result|proof|key|"
    r"corollary|cor|obs|observation|ex|example|(?:my|new)_?(?:lemma|theorem|thm|aux|helper|fact)|todo|stuff|x|y|z|a|b|c|h|t)[_0-9]*$", re.I)
NUMBERED = re.compile(r"(?:^|_)(?:\d+|[ivx]+)$")
HASHY = re.compile(r"(?:^|_)(?=\w*\d)[0-9a-f]{8,}(?:_|$)|^[A-Za-z]?[0-9a-f]{10,}$")
RELATIONS = ("↔", "→", "∧", "∨", "=", "≠", "≤", "<", "≥", ">", "∣", "∈", "∉", "⊆", "⊂", "≡")
SHORT_TYPE = {"ℕ": "n m k", "ℤ": "a b c n m k", "ℝ": "x y z a b c", "ℚ": "q r a b c", "Prop": "p q r"}


def snake(word: str) -> str:
    """`Finset.card` -> `card`, `StrictMono` -> `strictMono`. The last component, first letter lowered."""
    last = word.split(".")[-1]
    return last[:1].lower() + last[1:] if last else last


def symbol_words(tokens: list) -> list:
    """The words for the operators and named constants in a token list, in order, without repeats."""
    out: list = []
    for t in tokens:
        w = WORDS.get(t)
        if w is None and IDENT.match(t) and ("." in t or t[:1].isupper()) and not t.startswith("_"):
            w = snake(t)
        if w is None and re.fullmatch(r"[0-9]+", t):
            w = None
        if w and w not in out:
            out.append(w)
    return out


def _top(tokens: list, ops) -> int:
    depth = 0
    for i, t in enumerate(tokens):
        if t in L.OPEN:
            depth += 1
        elif t in L.CLOSE:
            depth -= 1
        elif depth == 0 and t in ops:
            return i
    return -1


def describe(tokens: list) -> str:
    """A snake_case description of a term or proposition from its top-level structure. Variables are left out."""
    tokens = [t for t in tokens]
    for rel in (("↔",), ("→",), ("∧",), ("∨",), ("=", "≠", "≤", "<", "≥", ">", "∣", "∈", "∉", "⊆", "⊂", "≡")):
        i = _top(tokens, rel)
        if i > 0:
            op = WORDS.get(tokens[i], tokens[i])
            left, right = describe(tokens[:i]), describe(tokens[i + 1:])
            if tokens[i] == "=":
                return "_".join(x for x in (left, "eq" if right else "", right) if x) if right else left
            return "_".join(x for x in (left, op, right) if x)
    if tokens and tokens[0] == "¬":
        return "not_" + describe(tokens[1:])
    if tokens and tokens[0] in ("∑", "∏"):
        return WORDS[tokens[0]]
    parts: list = []
    for i, t in enumerate(tokens):
        w = WORDS.get(t)
        if t in ("-",) and (i == 0 or tokens[i - 1] in L.OPEN or tokens[i - 1] in WORDS or tokens[i - 1] == "-"):
            w = "neg"
        elif t == "-":
            w = "sub"
        if w is None and IDENT.match(t) and ("." in t or t[:1].isupper()) and not t.startswith("_"):
            w = snake(t)
        if w is None and IDENT.match(t) and len(t) > 3 and t.islower() and t not in ("fun", "True", "False"):
            w = snake(t)  # a named function such as `gcd`, `exp`, `card`
        if w and (not parts or parts[-1] != w):
            parts.append(w)
    return "_".join(parts)


def hypothesis_binders(binders: list) -> list:
    out = []
    for b in binders:
        if b.bracket == "(" and b.names and b.typ and any(t in b.typ for t in RELATIONS + ("¬", "∀", "∃")):
            out.append(b)
        elif b.bracket == "(" and b.names and all(re.match(r"^h", n) for n in b.names) and b.typ:
            out.append(b)
    return out


def suggest(statement: str, limit: int = 3) -> list:
    """Candidate names for a statement (`name binders : conclusion`), best first. Empty when it cannot be read."""
    _, binders, concl = L.signature(statement)
    if concl is None:
        return []
    toks = L.canonical_tokens(concl)
    main = describe(toks)
    hyps = [describe(L.canonical_tokens(b.typ)) for b in hypothesis_binders(binders)]
    hyps = [h for h in hyps if h]
    cands: list = []
    if main:
        base = main
        cands.append(base + "".join(f"_of_{h}" for h in hyps))
        if hyps:
            cands.append(base + f"_of_{hyps[0]}")
        cands.append(base)
        # a short form: the operator words of the left of a relation only (`add_zero` rather than `add_zero_eq`)
        head = describe(toks[:_top(toks, RELATIONS)]) if _top(toks, RELATIONS) > 0 else ""
        if head and head != base:
            cands.append(head + "".join(f"_of_{h}" for h in hyps[:1]))
    seen, out = set(), []
    for c in cands:
        c = re.sub(r"_+", "_", c).strip("_")
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out[:limit]


def _components(name: str):
    parts = name.split(".")
    return parts[:-1], parts[-1]


def check_declaration(text: str, d: L.Decl, taken=frozenset()) -> list:
    """Findings for one declaration: case, placeholder, numbered, hash-like, misleading, silent, taken, dup namespace, variables."""
    if not d.name:
        return []
    ns, last = _components(d.name)
    full = d.full_name or d.name
    out = []
    stmt = L.statement_text(text, d)
    _, binders, concl = L.signature(stmt)

    def add(sev, rule, detail):
        out.append(finding("naming", sev, detail, name=full, line=d.line, rule=rule))

    if d.is_theorem:
        if not last[:1].islower() and last[:1] != "_":
            add("fail", "case", "a theorem is snake_case: its name starts with a lowercase letter")
        elif "__" in last or last.endswith("_") or last.startswith("_"):
            add("fail", "case", "a name has no doubled, leading or trailing underscore")
    elif d.kind in ("structure", "class", "inductive"):
        if not UPPER_CAMEL.match(last):
            add("fail", "case", f"a {d.kind} is UpperCamelCase")
    elif d.kind in ("def", "abbrev"):
        prop = concl is not None and concl.strip() == "Prop"
        if prop and not UPPER_CAMEL.match(last):
            add("warn", "case", "a definition of a Prop-valued predicate is UpperCamelCase")
        elif not prop and "_" in last.strip("_"):
            add("warn", "case", "a definition of data is lowerCamelCase, not snake_case")
    if not last.isascii():
        add("warn", "ascii", "non-ASCII name")
    if PLACEHOLDER.match(last):
        add("fail", "placeholder", "the name says nothing about the statement")
    elif HASHY.search(last):
        add("fail", "placeholder", "the name looks machine-made (a hash or long hex run)")
    elif NUMBERED.search(last) and d.is_theorem:
        add("warn", "numbered", "a numbered name does not say what differs from its siblings")
    comps = full.split(".")
    if any(x == y for x, y in zip(comps, comps[1:])):
        add("warn", "dup_namespace", "a name component is repeated (`Foo.Foo.bar`)")
    if full in taken:
        add("fail", "taken", "a declaration with this name already exists in the library")
    if d.is_theorem and concl is not None:
        body = " ".join([b.typ for b in binders] + [concl])  # the statement without the declaration's own name
        statement_words = set(symbol_words(L.canonical_tokens(body)))
        lowered = {w.lower() for w in re.split(r"_", re.sub(r"(?<=[a-z])(?=[A-Z])", "_", last)) if w}
        for op in sorted(lowered & set(SYMBOL_OPS)):
            if not (_mentions(body, op) or statement_words & SYNONYMS.get(op, set())):
                add("warn", "misleading", f"the name says `{op}` but the statement has no such operation")
        top_words = set(symbol_words(L.canonical_tokens(concl)))
        named = {t.lower() for t in L.tokens(concl) if IDENT.match(t) and len(t) > 2 and t not in {n for bd in binders for n in bd.names}}
        vocab = set(top_words) | named
        for w in top_words:
            vocab |= SYNONYMS.get(w, set())
        flat = last.lower().replace("_", "")
        if top_words and not any(w.lower().replace("_", "") in flat for w in vocab if len(w) > 1):
            add("warn", "silent", f"the name shares no word with the statement's own operators ({', '.join(sorted(top_words)[:4])})")
    for b in binders or []:
        if b.bracket in "({⦃" and b.typ.strip() in SHORT_TYPE:
            for n in b.names:
                if len(n) > 3 and re.fullmatch(r"[a-z]+", n) and not n.startswith("inst"):
                    add("warn", "variable_name", f"`{n}` is long for a {b.typ} variable; Mathlib uses {SHORT_TYPE[b.typ.strip()]}")
    return out


SYMBOL_OPS = ("add", "mul", "sub", "div", "pow", "dvd", "sum", "prod", "inv", "neg", "mod", "abs", "gcd", "lcm", "sqrt", "exp", "log", "card",
              "floor", "ceil", "factorial", "choose")
OP_SYMBOLS = {"add": ("+",), "mul": ("*", "•"), "sub": ("-",), "div": ("/",), "pow": ("^",), "dvd": ("∣",), "sum": ("∑",), "prod": ("∏",),
              "inv": ("⁻¹", "/"), "neg": ("-",), "mod": ("%", "≡"), "abs": ("|", "abs"), "sqrt": ("√", "sqrt"), "floor": ("⌊", "floor"),
              "ceil": ("⌈", "ceil"), "card": ("#", "‖"), "gcd": ("gcd",), "exp": ("exp",)}


def _mentions(statement: str, op: str) -> bool:
    """The statement uses the operation: its symbol, or an identifier that contains the word (`fgAdd`, `Finset.card`, `HAdd`)."""
    if any(sym in statement for sym in OP_SYMBOLS.get(op, ())):
        return True
    return any(op in t.lower() for t in L.tokens(statement) if IDENT.match(t))


def check_module(text: str, taken=frozenset(), module: str = "") -> list:
    out = []
    for d in L.declarations(text):
        out += [dict(f, module=module) if module else f for f in check_declaration(text, d, taken)]
    return out
