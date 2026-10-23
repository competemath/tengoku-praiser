"""The compile oracle: what the reviewer's checks ask a Lean toolchain, and what they do with the answer.

The checks never run Lean. They are handed an oracle, a function from the full text of a module to an `Outcome`, and they
decide nothing the oracle did not say. `ok` is True (compiled, no error), False (an error), or None (the toolchain gave no
answer: a timeout, a crash, a budget that ran out). None is never read as either: every check turns it into `inconclusive`.

The real oracle lives in `loaders.py` (it runs a command on a file); this module is only the vocabulary, plus a wrapper that
counts and caps the calls so no check can run away, and one that remembers answers so a check never pays twice for one text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .common import sha256_bytes


@dataclass(frozen=True)
class Outcome:
    ok: bool | None
    output: str = ""

    @property
    def decided(self) -> bool:
        return self.ok is not None

    @property
    def verdict(self) -> bool | None:
        """True only for a module that compiled with no error and no `sorry`; False for an error or a sorry; None for no answer."""
        if self.ok is None:
            return None
        return bool(self.ok) and not SORRY.search(self.output)


Compile = Callable[[str], Outcome]

UNDECIDED = Outcome(None, "")
MESSAGE = re.compile(r"^(?P<file>[^\n:]*):(?P<line>\d+):(?P<col>\d+): (?P<sev>error|warning|info)(?:\([^)]*\))?: ", re.M)
SORRY = re.compile(r"declaration uses ['`\"]?sorry['`\"]?")
LINTER_NOTE = re.compile(r"set_option (linter\.[\w.]+) false")


@dataclass(frozen=True)
class Message:
    severity: str
    line: int
    col: int
    text: str
    linter: str | None = None


def messages(output: str) -> list[Message]:
    """The messages in Lean's command-line output: `file:line:col: severity: text` and the lines that follow it."""
    heads = list(MESSAGE.finditer(output))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(output)
        text = output[m.end():end].strip()
        note = LINTER_NOTE.search(text)
        out.append(Message(m.group("sev"), int(m.group("line")), int(m.group("col")), text, note.group(1) if note else None))
    return out


def errors(output: str) -> list[Message]:
    return [m for m in messages(output) if m.severity == "error"]


class BudgetExceeded(RuntimeError):
    pass


class Bounded:
    """Wrap an oracle: remember answers by text, count real calls, and stop (with `UNDECIDED`) after `limit` of them."""

    def __init__(self, oracle: Compile, limit: int):
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        self.oracle, self.limit, self.calls, self.hits, self.exhausted = oracle, limit, 0, 0, False
        self._seen: dict[str, Outcome] = {}

    def __call__(self, text: str) -> Outcome:
        key = sha256_bytes(text.encode("utf-8"))
        if key in self._seen:
            self.hits += 1
            return self._seen[key]
        if self.calls >= self.limit:
            self.exhausted = True
            return UNDECIDED
        self.calls += 1
        try:
            got = self.oracle(text)
        except Exception:  # an oracle that breaks has not answered
            got = UNDECIDED
        if not isinstance(got, Outcome):
            got = UNDECIDED
        if got.ok is not None:  # an undecided answer is never remembered: asking again may work
            self._seen[key] = got
        return got
