"""Mathlib's two kinds of linters, as findings.

1. Text rules (`style_findings`): what Mathlib's style linters catch by reading the file as text: whitespace, line length, an
   isolated `by` or `·`, a trailing `;`, `$` and `λ`, debug commands, `sorry`, `native_decide`, `set_option maxHeartbeats`,
   imports out of order. No Lean needed. Each rule has an id, a severity and a sentence; `RULES` is the table, so the bar is
   one place to read and to change. The rules are modelled on Mathlib's style guide and linters; they are this module's own
   implementation and not a copy of Mathlib's script, so they can be stricter or looser than Mathlib at the edges.

2. Environment linters (`lint_script`, `parse_lint_output`): Batteries' `#lint` (`unusedArguments`, `docBlame`, `defLemma`,
   `dupNamespace`, `simpNF`, `checkUnivs` ...) needs Lean. The text of the module with `#lint` appended is compiled by the
   oracle; the output is parsed into one finding per reported declaration. Anything this module does not understand in the
   output is `inconclusive`, never a pass: a count of errors that does not match the entries found, an output without the
   linter's summary line, a module that did not compile.

Compiler messages from the style options Mathlib offers (`linter.style.*`, `linter.flexible`, `linter.unusedTactic` ...) are
read the same way (`compile_findings`), and an option the toolchain does not know is `inconclusive` rather than skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import leansrc as L
from .oracle import Compile, Outcome, errors, messages
from .review import finding

LINE_LIMIT = 100
LONG_FILE = 1500
LONG_PROOF_LINES = 50
DEFAULT_HEARTBEATS = 200000
DEBUG_COMMANDS = ("#eval", "#check", "#print", "#reduce", "#synth", "#find", "#exit", "#help", "#lint", "#simp", "#norm_num", "#whnf", "#unfold")


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    text: str


RULES = {r.id: r for r in (
    Rule("trailing_whitespace", "fail", "line ends with whitespace"),
    Rule("tab", "fail", "line contains a tab"),
    Rule("crlf", "fail", "file has Windows line endings"),
    Rule("line_length", "fail", f"line is longer than {LINE_LIMIT} characters"),
    Rule("final_newline", "fail", "file must end with exactly one newline"),
    Rule("long_file", "warn", f"file is longer than {LONG_FILE} lines"),
    Rule("isolated_by", "fail", "`by` alone on a line: put it at the end of the previous line"),
    Rule("isolated_dot", "fail", "`·` alone on a line: put the tactic after it"),
    Rule("semicolon_eol", "fail", "line ends with `;`"),
    Rule("dollar", "warn", "use `<|` instead of `$`"),
    Rule("lambda", "warn", "use `fun`, not `λ`"),
    Rule("fun_arrow", "warn", "use `fun x ↦ e`; keep `=>` for match arms"),
    Rule("ascii_symbol", "warn", "use the unicode symbol (`→ ≤ ≥ ↔ ≠`) Mathlib uses"),
    Rule("heartbeats_unbounded", "fail", "`set_option maxHeartbeats 0` removes the time limit"),
    Rule("heartbeats_raised", "warn", f"`maxHeartbeats` above {DEFAULT_HEARTBEATS} needs a comment saying why"),
    Rule("auto_implicit", "fail", "`autoImplicit true` hides misspelled variables"),
    Rule("linter_disabled", "warn", "a linter is switched off; say why in a comment"),
    Rule("debug_command", "fail", "debugging command left in a library file"),
    Rule("sorry", "fail", "`sorry` or `admit`"),
    Rule("native_decide", "fail", "`native_decide` / `ofReduceBool` trusts the compiler"),
    Rule("unverified_code", "fail", "`axiom`, `unsafe`, `implemented_by`, `extern` or `csimp` puts something outside the kernel"),
    Rule("import_after_command", "fail", "`import` after the first command"),
    Rule("duplicate_import", "fail", "the same module is imported twice"),
    Rule("import_order", "warn", "imports are not in alphabetical order"),
    Rule("import_all", "warn", "`import Mathlib` pulls in everything; import what the file uses"),
    Rule("open_classical", "warn", "`open Classical` changes elaboration for the whole file; use `open scoped Classical` or `classical`"),
    Rule("deprecated_without_date", "warn", "`@[deprecated]` without `(since := ...)`"),
    Rule("todo_marker", "warn", "TODO / FIXME / HACK left in a comment"),
    Rule("long_proof", "warn", f"proof is longer than {LONG_PROOF_LINES} lines: split it into lemmas"),
)}
ASCII_SYMBOLS = ((re.compile(r"(?<![-<|=>$*;:])<->(?![>])"), "↔"), (re.compile(r"(?<![-<|=>$*;:.])->(?![>])"), "→"),
                 (re.compile(r"(?<![-<|=$*;:])<=(?![>=])"), "≤"), (re.compile(r"(?<![-<|=>$*;:])>=(?![>=])"), "≥"),
                 (re.compile(r"!="), "≠"))
UNVERIFIED = re.compile(r"(?<![\w.'])(?:axiom|unsafe|implemented_by|extern|csimp)(?![\w.'])")


def _f(rule: str, line: int, detail: str = "", name: str = "") -> dict:
    r = RULES[rule]
    return finding("style", r.severity, f"{r.text}" + (f": {detail}" if detail else ""), name=name or rule, line=line, rule=rule)


def style_findings(text: str, module: str = "") -> list[dict]:
    """Every text rule that fires, with its line. Deterministic and in order of line, then rule."""
    out: list[dict] = []
    raw_lines = text.split("\n")
    masked_lines = L.mask(text).split("\n")
    if "\r" in text:
        out.append(_f("crlf", 1))
    if text and (not text.endswith("\n") or text.endswith("\n\n")):
        out.append(_f("final_newline", len(raw_lines)))
    if len(raw_lines) > LONG_FILE + 1:
        out.append(_f("long_file", len(raw_lines), f"{len(raw_lines)} lines"))
    seen_imports: dict[str, int] = {}
    last_import = ""
    commands_started = False
    for n, (raw, code) in enumerate(zip(raw_lines, masked_lines), start=1):
        raw = raw.rstrip("\r")
        if raw != raw.rstrip():
            out.append(_f("trailing_whitespace", n))
        if "\t" in raw:
            out.append(_f("tab", n))
        if len(raw) > LINE_LIMIT and "http" not in raw:
            out.append(_f("line_length", n, f"{len(raw)}"))
        stripped = code.strip()
        m_imp = L.IMPORT_RE.match(stripped)
        if m_imp:
            mod = m_imp.group(1)
            if commands_started:
                out.append(_f("import_after_command", n, mod))
            if mod in seen_imports:
                out.append(_f("duplicate_import", n, mod))
            elif last_import and mod < last_import:
                out.append(_f("import_order", n, f"{mod} after {last_import}"))
            seen_imports.setdefault(mod, n)
            last_import = mod
            if mod == "Mathlib":
                out.append(_f("import_all", n))
        elif stripped and stripped != "module":
            commands_started = True
        if stripped == "by":
            out.append(_f("isolated_by", n))
        if stripped in ("·", "."):
            out.append(_f("isolated_dot", n))
        if stripped.endswith(";"):
            out.append(_f("semicolon_eol", n))
        if re.search(r"\s\$\s", " " + code + " "):
            out.append(_f("dollar", n))
        if re.search(r"(?<![\w'])λ(?![\w'])", code):
            out.append(_f("lambda", n))
        if re.search(r"(?<![\w'.])fun\b(?!\s*\|)[^|\n]*?=>", code):
            out.append(_f("fun_arrow", n))
        for pattern, nice in ASCII_SYMBOLS:
            if pattern.search(code):
                out.append(_f("ascii_symbol", n, f"use {nice}"))
                break
        m_hb = re.search(r"set_option\s+maxHeartbeats\s+(\d+)", code)
        if m_hb:
            beats = int(m_hb.group(1))
            if beats == 0:
                out.append(_f("heartbeats_unbounded", n))
            elif beats > DEFAULT_HEARTBEATS and "--" not in raw and not (n > 1 and "--" in raw_lines[n - 2]):
                out.append(_f("heartbeats_raised", n, str(beats)))
        if re.search(r"set_option\s+autoImplicit\s+true", code):
            out.append(_f("auto_implicit", n))
        if re.search(r"set_option\s+linter\.[\w.]+\s+false", code) and "--" not in raw and not (n > 1 and "--" in raw_lines[n - 2]):
            out.append(_f("linter_disabled", n))
        if any(stripped.startswith(c) and not re.match(r"\w", stripped[len(c):len(c) + 1] or " ") for c in DEBUG_COMMANDS):
            out.append(_f("debug_command", n, stripped.split()[0]))
        if re.search(r"(?<![\w.'])(?:sorry|admit)(?![\w.'])", code):
            out.append(_f("sorry", n))
        if re.search(r"(?<![\w.'])(?:native_decide|ofReduceBool)(?![\w.'])", code):
            out.append(_f("native_decide", n))
        if UNVERIFIED.search(code):
            out.append(_f("unverified_code", n, UNVERIFIED.search(code).group(0)))
        if re.search(r"@\[[^\]]*\bdeprecated\b(?![^\]]*since)", code):
            out.append(_f("deprecated_without_date", n))
    for s in L.spans(text):
        if s.kind in ("line", "block", "doc", "mod") and re.search(r"\b(TODO|FIXME|XXX|HACK)\b", text[s.start:s.end]):
            out.append(_f("todo_marker", L.line_of(text, s.start)))
    for m in re.finditer(r"(?m)^open[ \t]+(?!scoped\b)(?:[\w.]+[ \t]+)*Classical(?:[ \t]+[\w.]+)*[ \t]*$", L.mask(text)):
        out.append(_f("open_classical", L.line_of(text, m.start())))
    for d in L.declarations(text):
        if d.body_span and d.end_line - d.line > LONG_PROOF_LINES:
            out.append(_f("long_proof", d.line, f"{d.end_line - d.line + 1} lines", name=d.full_name or ""))
    out.sort(key=lambda f: (f["line"], f["rule"], f["name"]))
    return [dict(f, module=module) if module else f for f in out]


# ---------------------------------------------------------------------------------------------------- compiler options

STYLE_OPTIONS = (
    "linter.style.longLine", "linter.style.cdot", "linter.style.dollarSyntax", "linter.style.lambdaSyntax", "linter.style.multiGoal",
    "linter.style.missingEnd", "linter.style.setOption", "linter.style.openClassical", "linter.flexible", "linter.unusedTactic",
    "linter.unusedVariables", "linter.hashCommand", "linter.oldObtain", "linter.deprecated",
)
def insert_after_imports(text: str, lines: list[str]) -> str:
    """Put `lines` after the last import (or the `module` header), or at the top when there is neither."""
    end = L.import_end(text)
    block = "\n".join(lines) + "\n"
    if not end:
        return block + text
    return text[:end] + "\n" + block + text[end:]


def options_script(text: str, options: tuple = STYLE_OPTIONS) -> str:
    return insert_after_imports(text, [f"set_option {o} true" for o in options])


def compile_findings(text: str, oracle: Compile, options: tuple = STYLE_OPTIONS, module: str = "") -> list[dict]:
    """Compile the module with the style options on; every warning becomes a finding named after its linter. An unknown option,
    an error, or no answer is `inconclusive`, because then the options did not run."""
    got = oracle(options_script(text, options))
    return compile_output_findings(got, module)


def compile_output_findings(got: Outcome, module: str = "", check: str = "compiler") -> list[dict]:
    if not got.decided:
        return [finding(check, "inconclusive", "the toolchain gave no answer", name="compile", module=module)]
    errs = errors(got.output)
    if errs:
        unknown = [m for m in errs if "unknown option" in m.text or "unknown linter" in m.text]
        detail = unknown[0].text.splitlines()[0] if unknown else errs[0].text.splitlines()[0]
        why = "a style option is unknown on this toolchain" if unknown else "the module did not compile with the style options on"
        return [finding(check, "inconclusive", f"{why}: {detail}", name="compile", line=errs[0].line, module=module)]
    out = []
    for m in messages(got.output):
        if m.severity == "warning":
            out.append(finding(check, "fail" if m.linter else "warn", m.text.splitlines()[0] if m.text else "warning",
                               name=m.linter or "compiler_warning", line=m.line, module=module))
    return out


# ----------------------------------------------------------------------------------------------------------------- #lint

LINT_IMPORT = "import Batteries.Tactic.Lint"
LINT_HEADER = re.compile(r"-- Found (\d+) errors? in (\d+) declarations?.*? with (\d+) linters?")
LINT_PASSED = "-- All linting checks passed!"
LINT_SECTION = re.compile(r"/- The `([^`]+)` linter reports:\n(.*?) -/\n(.*?)(?=\n/- The `|\Z)", re.S)
LINT_ENTRY = re.compile(r"^#check @?(\S+) /- (.*) -/\s*$", re.M)


def lint_script(text: str, only: tuple = ()) -> str:
    """The module with Batteries' lint import added after its imports and `#lint` as the last command (`#lint only a b` when `only`)."""
    body = insert_after_imports(text, [LINT_IMPORT]).rstrip("\n")
    return body + "\n\n#lint" + (" only " + " ".join(only) if only else "") + "\n"


def parse_lint_output(output: str, module: str = "") -> list[dict]:
    """One `lint` finding per declaration a linter reports. If the output cannot be reconciled with its own summary the answer is
    `inconclusive`: a pass is only ever "the tool said all checks passed"."""
    errs = errors(output)
    if errs:
        return [finding("lint", "inconclusive", "the module did not compile, so #lint did not run: " + errs[0].text.splitlines()[0],
                        name="compile", line=errs[0].line, module=module)]
    if LINT_PASSED in output:
        return []
    header = LINT_HEADER.search(output)
    if not header:
        return [finding("lint", "inconclusive", "no #lint summary in the output", name="lint_output", module=module)]
    expected = int(header.group(1))
    found: list[dict] = []
    for m in LINT_SECTION.finditer(output):
        linter, what = m.group(1), " ".join(m.group(2).split())
        for e in LINT_ENTRY.finditer(m.group(3)):
            found.append(finding("lint", "fail", f"{linter}: {what.rstrip(':').lower()}: {' '.join(e.group(2).split())}", name=e.group(1),
                                 module=module, linter=linter))
    if expected and len(found) != expected:
        found.append(finding("lint", "inconclusive", f"#lint reported {expected} errors and {len(found)} were read", name="lint_output", module=module))
    elif not expected and not found:
        return []
    return found


def run_lint(text: str, oracle: Compile, only: tuple = (), module: str = "") -> list[dict]:
    got = oracle(lint_script(text, only))
    if not got.decided:
        return [finding("lint", "inconclusive", "the toolchain gave no answer", name="compile", module=module)]
    return parse_lint_output(got.output, module)
