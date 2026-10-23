"""Reading Lean 4 source as text: comments masked, declarations found, signatures split, statements normalised and matched.

Pure functions on strings, no Lean. This is not a parser: it understands the restricted layout Mathlib style asks for
(commands start in column 0, a declaration's statement runs to its first top-level `:=`) and quietly finds nothing in
anything stranger. Every review module (style, naming, docs, dedupe, generalise, minimise ...) reads source through here, so
one set of tests pins what "a declaration", "its statement" and "the same statement" mean.

Offsets are character offsets into the ORIGINAL text. `mask` keeps the length, so an offset found in the masked text is
valid in the original and an edit can be spliced in with `splice`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

OPEN = "([{⟨⦃"
CLOSE = ")]}⟩⦄"
PAIR = dict(zip(OPEN, CLOSE))
CLOSER_TO_OPENER = dict(zip(CLOSE, OPEN))
CHAR_LITERAL = re.compile(r"'(?:[^'\\\n]|\\(?:x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.))'")


@dataclass(frozen=True)
class Span:
    kind: str  # doc (/-- -/), mod (/-! -/), block (/- -/), line (--), str, char
    start: int
    end: int


def spans(text: str) -> list[Span]:
    """Every comment, string literal and character literal, in order. Block comments nest; an unterminated one runs to the end."""
    out: list[Span] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and text.startswith("/-", i):
            kind = "doc" if text.startswith("/--", i) else "mod" if text.startswith("/-!", i) else "block"
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith("/-", j):
                    depth += 1
                    j += 2
                elif text.startswith("-/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            out.append(Span(kind, i, j))
            i = j
        elif c == "-" and text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(Span("line", i, j))
            i = j
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(Span("str", i, j))
            i = j
        elif c == "'" and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "_'")):
            m = CHAR_LITERAL.match(text, i)
            if m:
                out.append(Span("char", i, m.end()))
                i = m.end()
            else:
                i += 1
        else:
            i += 1
    return out


def mask(text: str) -> str:
    """The text with every comment, string and character literal blanked to spaces (newlines kept): same length, same offsets."""
    chars = list(text)
    for s in spans(text):
        for k in range(s.start, s.end):
            if chars[k] != "\n":
                chars[k] = " "
    return "".join(chars)


def splice(text: str, start: int, end: int, new: str) -> str:
    return text[:start] + new + text[end:]


def line_of(text: str, offset: int) -> int:
    """1-based line number of a character offset."""
    return text.count("\n", 0, max(0, offset)) + 1


def matching_close(text: str, i: int) -> int:
    """Index of the bracket closing the one at `i` (an opener), or -1. `text` should already be masked."""
    depth = 0
    for k in range(i, len(text)):
        ch = text[k]
        if ch in OPEN:
            depth += 1
        elif ch in CLOSE:
            depth -= 1
            if depth == 0:
                return k
    return -1


def top_level(text: str, token: str, start: int = 0) -> int:
    """First index at bracket depth 0 where `token` starts (and, for `:`, is not part of `:=`), or -1. `text` should be masked."""
    depth = 0
    k = start
    while k < len(text):
        ch = text[k]
        if ch in OPEN:
            depth += 1
        elif ch in CLOSE:
            depth = max(0, depth - 1)
        elif depth == 0 and text.startswith(token, k):
            if token == ":" and text[k + 1:k + 2] == "=":
                k += 2
                continue
            return k
        k += 1
    return -1


# ------------------------------------------------------------------------------------------------------------------ imports

# `import X`, and the module system's `public import X`, `meta import X`, `import all X`; the `module` header line.
IMPORT_RE = re.compile(r"(?m)^(?:(?:public|meta|private)[ \t]+)*import(?:[ \t]+all)?[ \t]+(\S+)[ \t]*$")
MODULE_RE = re.compile(r"(?m)^module[ \t]*$")


def import_end(text: str) -> int:
    """Offset just after the last import line (or the `module` header when there are no imports); 0 when there is neither."""
    masked = mask(text)
    end = 0
    for m in list(MODULE_RE.finditer(masked)) + list(IMPORT_RE.finditer(masked)):
        end = max(end, m.end())
    return end


# --------------------------------------------------------------------------------------------------------- declarations

DECL_KINDS = ("theorem", "lemma", "def", "abbrev", "instance", "structure", "class", "inductive", "example", "axiom", "opaque")
COMMAND_WORDS = DECL_KINDS + (
    "namespace", "section", "end", "open", "variable", "universe", "import", "set_option", "attribute", "macro", "syntax", "notation",
    "infix", "infixl", "infixr", "prefix", "postfix", "local", "scoped", "mutual", "deriving", "initialize", "elab", "omit", "include",
    "private", "protected", "noncomputable", "unsafe", "partial", "nonrec", "export", "run_cmd", "in", "module", "public",
)
COMMAND_START = re.compile(r"^(?:@\[|#|(?:" + "|".join(COMMAND_WORDS) + r")(?![\w'.]))", re.M)
DECL_HEAD = re.compile(
    r"\A(?P<attrs>(?:@\[(?:[^\]]|\n)*\]\s*)*)"
    r"(?P<mods>(?:(?:private|protected|noncomputable|unsafe|partial|nonrec)\s+)*)"
    r"(?P<kind>" + "|".join(DECL_KINDS) + r")(?![\w'.])\s*"
)
NAME_AT = re.compile(r"[^\s:({\[⦃⟨]+")
ATTRS_ONLY = re.compile(r"(?:@\[(?:[^\]]|\n)*\]|private|protected|noncomputable|unsafe|partial|nonrec|\s)*\Z")
VARIABLE_CMD = re.compile(r"\Avariable\b")
NAMESPACE_CMD = re.compile(r"\A(namespace|section|end)(?:\s+([^\s]+))?")


@dataclass
class Binder:
    bracket: str  # "(", "{", "[", "⦃"
    names: tuple
    typ: str

    def render(self) -> str:
        close = PAIR[self.bracket]
        inner = (" ".join(self.names) + " : " if self.names else "") + self.typ if self.typ else " ".join(self.names)
        return f"{self.bracket}{inner}{close}"


@dataclass
class Decl:
    kind: str
    name: str | None
    namespace: str
    full_name: str | None
    attrs: str
    private: bool
    protected: bool
    start: int  # offset of the first character of the command (attributes included, docstring excluded)
    end: int
    line: int  # 1-based line of the declaration keyword
    end_line: int
    doc: str | None
    doc_span: tuple | None
    stmt_span: tuple  # (start, end) of the text between the keyword and the first top-level `:=`, `where` or `|`
    body_span: tuple | None  # after the `:=`
    name_span: tuple | None
    text: str = ""
    variables: tuple = ()  # the `variable` binders in scope at this declaration, rendered

    @property
    def is_theorem(self) -> bool:
        return self.kind in ("theorem", "lemma")


def _decl_end_trim(masked: str, start: int, end: int) -> int:
    while end > start and masked[end - 1].isspace():
        end -= 1
    return end


def declarations(text: str) -> list[Decl]:
    """Every declaration, in order, with its namespace, docstring, statement span and body span."""
    masked = mask(text)
    raw = [m.start() for m in COMMAND_START.finditer(masked)]
    cs: list[int] = []
    for pos in raw:  # attributes and modifiers on their own lines belong to the declaration that follows
        if cs and ATTRS_ONLY.match(masked[cs[-1]:pos]):
            continue
        cs.append(pos)
    docs = [s for s in spans(text) if s.kind == "doc"]
    # A command that follows modifiers or attributes on its own line starts at the first of them; a `local`/`in` prefix is ignored here.
    stack: list[tuple[str, str]] = []  # (kind, name)
    frames: list[list] = [[]]  # `variable` binders per open namespace or section; frames[0] is the file
    ns = ""
    out: list[Decl] = []

    def docs_before(pos: int):
        for d in docs:
            if d.end <= pos and not masked[d.end:pos].strip() and not text[d.end:pos].strip():
                return d
        return None

    bounds = []  # (start, end) of each command, with an attached docstring cut off the previous command
    for idx, s in enumerate(cs):
        e = cs[idx + 1] if idx + 1 < len(cs) else len(text)
        d = docs_before(e) if idx + 1 < len(cs) else None
        if d is not None and d.start >= s:
            e = d.start
        bounds.append((s, _decl_end_trim(masked, s, e)))
    for s, e in bounds:
        chunk = masked[s:e]
        m_ns = NAMESPACE_CMD.match(chunk)
        if m_ns:
            kw, nm = m_ns.group(1), m_ns.group(2)
            if kw == "namespace" and nm:
                stack.append(("namespace", nm))
                frames.append([])
            elif kw == "section":
                stack.append(("section", nm or ""))
                frames.append([])
            elif kw == "end" and stack:
                stack.pop()
                frames.pop()
            ns = ".".join(n for k, n in stack if k == "namespace")
            continue
        m_var = VARIABLE_CMD.match(chunk)
        if m_var:
            _, vb, _ = signature("v " + chunk[m_var.end():].strip() + " : _")
            frames[-1].extend(vb)
            continue
        m = DECL_HEAD.match(chunk)
        if not m:
            continue
        kind = m.group("kind")
        kw_end = s + m.end()
        nm = NAME_AT.match(masked, kw_end)
        name = nm.group(0) if nm and kind not in ("example",) else None
        if name and name.startswith(":"):
            name = None
        name_span = (nm.start(), nm.end()) if name else None
        # the statement runs from the keyword to the first top-level `:=`, `where` or `|`
        rest = masked[kw_end:e]
        cut = len(rest)
        body_start = None
        k = top_level(rest, ":=")
        if k >= 0:
            cut = k
            body_start = kw_end + k + 2
        for token in (" where", "\nwhere", "\n  |", "\n|", " |"):
            k2 = top_level(rest, token)
            if 0 <= k2 < cut:
                cut = k2
                body_start = None
        full = None
        if name:
            full = name[len("_root_."):] if name.startswith("_root_.") else (f"{ns}.{name}" if ns else name)
        doc = docs_before(s)
        private = "private" in m.group("mods").split()
        out.append(Decl(
            kind=kind, name=name, namespace=ns, full_name=full, attrs=m.group("attrs").strip(), private=private,
            protected="protected" in m.group("mods").split(), start=s, end=e, line=line_of(text, s + m.start("kind")),
            end_line=line_of(text, max(s, e - 1)), doc=(text[doc.start + 3:doc.end - 2].strip() if doc else None),
            doc_span=((doc.start, doc.end) if doc else None), stmt_span=(kw_end, kw_end + cut),
            body_span=((body_start, e) if body_start is not None else None), name_span=name_span, text=text[s:e],
            variables=tuple(b.render() for frame in frames for b in frame)))
    return out


def statement_text(text: str, d: Decl) -> str:
    """The masked statement of a declaration: name, binders and conclusion, comments removed."""
    return mask(text)[d.stmt_span[0]:d.stmt_span[1]].strip()


def body_text(text: str, d: Decl) -> str:
    if d.body_span is None:
        return ""
    return mask(text)[d.body_span[0]:d.body_span[1]].strip()


# ------------------------------------------------------------------------------------------------------------ signatures

def _binder_from(bracket: str, inner: str) -> Binder:
    k = top_level(inner, ":")
    if k < 0:
        if bracket == "[":
            return Binder(bracket, (), inner.strip())
        return Binder(bracket, tuple(inner.split()), "")
    left, right = inner[:k].strip(), inner[k + 1:].strip()
    j = top_level(right, ":=")
    if j >= 0:
        right = right[:j].strip()
    return Binder(bracket, tuple(left.split()), right)


def signature(statement: str, has_name: bool = True) -> tuple:
    """(name, binders, conclusion) of a masked statement `name {binders} : conclusion`. conclusion is None when there is no colon."""
    s = statement.strip()
    name = None
    pos = 0
    if has_name:
        m = NAME_AT.match(s)
        if m and s[0] not in OPEN:
            name, pos = m.group(0), m.end()
            if name.endswith(".") and s[pos:pos + 1] == "{":  # `foo.{u}`: the universe list, not part of the name
                close = matching_close(s, pos)
                if close >= 0:
                    name, pos = name[:-1], close + 1
    binders: list[Binder] = []
    while pos < len(s):
        while pos < len(s) and s[pos].isspace():
            pos += 1
        if pos >= len(s):
            break
        ch = s[pos]
        if ch in "({[⦃":
            close = matching_close(s, pos)
            if close < 0:
                return name, binders, None
            binders.append(_binder_from(ch, s[pos + 1:close]))
            pos = close + 1
        elif ch == ":" and s[pos + 1:pos + 2] != "=":
            return name, binders, s[pos + 1:].strip()
        else:
            return name, binders, None
    return name, binders, None


# ------------------------------------------------------------------------------------------------------------- tokens

TOKEN = re.compile(r"\s*(?:(?P<id>[^\W\d][\w.'!?]*|\d+(?:\.\d+)?)|(?P<op><->|<=|>=|->|=>|:=|!=|<-|\|>\.|\.\.|.))", re.S)
BINDER_SYMBOLS = {"∀", "∃", "∃!", "fun", "λ", "∑", "∏", "⋃", "⋂", "Σ", "∫", "Π"}
STOPPERS = {",", ":", "∈", "in", "=>", "↦", "∣", ")", "∉", "<", "≤", "≥", ">", "=", "∧", "→"}
SYMBOL_MAP = {"->": "→", "<=": "≤", ">=": "≥", "!=": "≠", "<->": "↔", "=>": "↦", "<-": "←", "fun": "fun", "λ": "fun", "ℕ": "ℕ"}
ALIASES = {"Nat": "ℕ", "Int": "ℤ", "Rat": "ℚ", "Real": "ℝ", "Complex": "ℂ"}


def tokens(text: str) -> list[str]:
    out = []
    for m in TOKEN.finditer(text):
        t = m.group("id") or m.group("op")
        if t is not None and not t.isspace():
            out.append(t)
    return out


def canonical_tokens(text: str) -> list[str]:
    """Tokens with ASCII spellings unified (`<=` is `≤`, `->` is `→`, `fun`/`λ`, `=>`/`↦`, `Nat`/`ℕ`)."""
    out = []
    for t in tokens(text):
        t = SYMBOL_MAP.get(t, t)
        t = ALIASES.get(t, t)
        out.append(t)
    return out


def bound_names(toks: list[str]) -> list[str]:
    """Names introduced by `∀ ∃ fun ∑ ...` in order of appearance (an approximation: see the module docstring)."""
    names: list[str] = []
    i = 0
    while i < len(toks):
        if toks[i] in BINDER_SYMBOLS:
            i += 1
            while i < len(toks) and toks[i] not in {",", "↦", "∈", "in", "∉"}:
                t = toks[i]
                if t == "(" or t == "{" or t == "[" or t == "⦃":
                    i += 1
                    while i < len(toks) and toks[i] not in (":", ")", "}", "]", "⦄"):
                        if re.match(r"^[^\W\d][\w'₀-₉]*$", toks[i]):
                            names.append(toks[i])
                        i += 1
                    depth = 0
                    while i < len(toks) and not (toks[i] in (")", "}", "]", "⦄") and depth == 0):
                        depth += 1 if toks[i] in OPEN else -1 if toks[i] in CLOSE else 0
                        i += 1
                    i += 1
                    continue
                if t == ":":
                    # a type ascription ends the list: skip it up to the comma
                    depth = 0
                    while i < len(toks) and not (toks[i] in {",", "↦"} and depth == 0):
                        depth += 1 if toks[i] in OPEN else -1 if toks[i] in CLOSE else 0
                        i += 1
                    break
                if re.match(r"^[^\W\d][\w'₀-₉]*$", t) and t not in BINDER_SYMBOLS:
                    names.append(t)
                i += 1
        else:
            i += 1
    return names


@dataclass
class Normal:
    """A statement with every bound name replaced by its position: equal `key`s mean equal up to renaming."""
    tokens: list
    key: str
    hypotheses: int
    names: dict = field(default_factory=dict)


def normalise(statement: str, has_name: bool = True, resolve: dict | None = None) -> Normal | None:
    """The statement in a form that ignores the declaration's name, what the variables and hypotheses are called, and spelling
    variants of the same symbol. `resolve` maps a name used in the statement to the name it stands for in the declaration's namespace
    (`fst` to `RingHom.fst`), so two statements that read the same but mean different things do not look equal. None when it does
    not parse as `name binders : conclusion`."""
    name, binders, concl = signature(statement, has_name)
    if concl is None:
        return None
    rename: dict[str, str] = {}
    counter = 0

    def fresh(n: str) -> None:
        nonlocal counter
        if n not in rename:
            rename[n] = f"_{counter}"
            counter += 1

    for b in binders:
        for n in b.names:
            fresh(n)
    for b in binders:
        for n in bound_names(canonical_tokens(b.typ)):
            fresh(n)
    for n in bound_names(canonical_tokens(concl)):
        fresh(n)
    out: list[str] = []
    hyps = 0
    resolve = resolve or {}

    def sub(t: str) -> str:
        return rename[t] if t in rename else resolve.get(t, t)

    for b in binders:
        tk = [sub(t) for t in canonical_tokens(b.typ)]
        if b.bracket == "[":
            out += ["[", *tk, "]"]
        else:
            copies = max(1, len(b.names))
            for _ in range(copies):
                out += [b.bracket, "_:", *tk, PAIR[b.bracket]]
            if b.names and all(re.match(r"^h", n) for n in b.names):
                hyps += copies
    out += [":"] + [sub(t) for t in canonical_tokens(concl)]
    return Normal(out, " ".join(out), hyps, rename)


# --------------------------------------------------------------------------------------------------------------- matching

def match(pattern: list[str], target: list[str], variables: set, max_arg: int = 14, max_steps: int = 20000) -> dict | None:
    """Match `pattern` against all of `target`: a pattern variable stands for any run of tokens (balanced in brackets); anything
    else must be equal. Returns the binding or None. Bounded twice (`max_arg` tokens per variable, `max_steps` recursive steps),
    so it cannot blow up: hitting either bound is "no match", never a wrong match."""
    steps = 0

    def balanced(seg: list[str]) -> bool:
        depth = 0
        for t in seg:
            if t in OPEN:
                depth += 1
            elif t in CLOSE:
                depth -= 1
                if depth < 0:
                    return False
        return depth == 0

    def wrapped(seg: list[str]) -> bool:
        return len(seg) >= 2 and seg[0] == "(" and seg[-1] == ")" and balanced(seg[1:-1])

    def forms(seg: list[str]) -> list:
        """A bound term also matches itself with one pair of parentheses added or removed: `(a + 1)` is `a + 1`."""
        out = [seg, ["("] + seg + [")"]]
        if wrapped(seg):
            out.append(seg[1:-1])
        return out

    def go(pi: int, ti: int, env: dict) -> dict | None:
        nonlocal steps
        steps += 1
        if steps > max_steps:
            return None
        if pi == len(pattern):
            return env if ti == len(target) else None
        p = pattern[pi]
        if p in variables:
            if p in env:
                for form in forms(env[p]):
                    if target[ti:ti + len(form)] == form:
                        got = go(pi + 1, ti + len(form), env)
                        if got is not None:
                            return got
                return None
            follower = pattern[pi + 1] if pi + 1 < len(pattern) and pattern[pi + 1] not in variables else None
            last = pi + 1 == len(pattern)
            top = len(target) - ti if last else min(max_arg, len(target) - ti)
            if last and top > 4 * max_arg:
                return None
            for length in range(1, top + 1):
                if follower is not None and (ti + length >= len(target) or target[ti + length] != follower):
                    continue
                seg = target[ti:ti + length]
                if not balanced(seg):
                    continue
                got = go(pi + 1, ti + length, {**env, p: seg})
                if got is not None:
                    return got
            return None
        if ti < len(target) and target[ti] == p:
            return go(pi + 1, ti + 1, env)
        return None

    return go(0, 0, {})


# ----------------------------------------------------------------------------------------------------------------- proofs

CONTINUATION = re.compile(r"(?:\||<;>|else\b|then\b|termination_by\b|decreasing_by\b|where\b)")


def tactic_steps(body: str) -> list[tuple]:
    """(start, end) offsets of the top-level steps of a `by` block inside `body` (a masked body starting at `by` or after it).
    A step is a line at the block's own indentation together with the deeper lines that follow it. A one-line `by` is one step."""
    m = re.match(r"\s*by\b", body)
    start = m.end() if m else 0
    block = body[start:]
    lines = block.split("\n")
    if len(lines) <= 1 or not any(ln.strip() for ln in lines[1:]):
        return [(start, len(body))] if block.strip() else []
    # the block is the lines after the first; their minimum indentation is the step column
    indents = [len(ln) - len(ln.lstrip()) for ln in lines[1:] if ln.strip()]
    col = min(indents)
    steps: list[tuple] = []
    pos = start + len(lines[0]) + 1
    cur = None
    for ln in lines[1:]:
        width = len(ln) + 1
        if ln.strip():
            ind = len(ln) - len(ln.lstrip())
            if ind == col and not CONTINUATION.match(ln.lstrip()):
                if cur is not None:
                    steps.append((cur, pos))
                cur = pos
        pos += width
    if cur is not None:
        steps.append((cur, min(pos, len(body))))
    if lines[0].strip():  # `:= by simp` followed by an indented continuation is one inseparable step
        return [(start, len(body))]
    return steps
