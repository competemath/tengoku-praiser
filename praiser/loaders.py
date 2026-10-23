"""Thin loaders: the only place that touches files. The logic modules never import this."""

from __future__ import annotations

import glob
import json
import os
import shlex
import signal
import subprocess
import tempfile

from .oracle import Outcome, UNDECIDED

MAX_FILE = 16 * 1024 * 1024
MAX_LEAN_FILE = 2 * 1024 * 1024
MAX_OUTPUT = 256 * 1024
KEEP_ENV = ("PATH", "LANG", "LC_ALL", "TZ", "ELAN_HOME", "LAKE_HOME")


class InputError(ValueError):
    """Bad input from the outside world (unreadable file, wrong shape, path that escapes the checkout)."""


def read_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc


def read_records(paths: list[str]) -> list:
    """Records from .json files (an object or a list) and .jsonl files; a directory contributes its .json/.jsonl files."""
    files: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "*.json")) + glob.glob(os.path.join(p, "*.jsonl")))
        else:
            files.append(p)
    out: list = []
    for f in files:
        if f.endswith(".jsonl"):
            out += read_ledger(f)
        else:
            data = read_json(f)
            out += data if isinstance(data, list) else [data]
    return out


def read_ledger(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except (OSError, ValueError) as exc:
        raise InputError(f"cannot read ledger {path}: {exc}") from exc


def read_files_under(root: str, paths) -> dict[str, bytes]:
    """{declared path: bytes} for the declared paths that exist as regular files inside `root`. A path that is absolute,
    climbs out with `..`, or resolves (through a symlink) outside the root is an error, not a silent skip: a declaration
    must not be able to make the checker read something else. A path that simply is not there is left out, and the check
    reports it as "not stored"."""
    base = os.path.realpath(root)
    if not os.path.isdir(base):
        raise InputError(f"{root} is not a directory")
    out: dict[str, bytes] = {}
    for p in paths:
        if os.path.isabs(p) or ".." in p.replace("\\", "/").split("/"):
            raise InputError(f"declared path {p!r} is not a path inside the checkout")
        full = os.path.realpath(os.path.join(base, p))
        if os.path.commonpath([base, full]) != base:
            raise InputError(f"declared path {p!r} resolves outside the checkout")
        if os.path.isfile(full):
            if os.path.getsize(full) > MAX_FILE:
                raise InputError(f"{p} is larger than {MAX_FILE} bytes")
            with open(full, "rb") as fh:
                out[p] = fh.read()
    return out


def write_json(obj, path: str | None) -> None:
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if not path or path == "-":
        print(text, end="")
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


def read_lean_modules(paths: list[str], root: str | None = None) -> dict[str, str]:
    """{module name: text} for `.lean` files given directly or found under a directory (symlinks are not followed). The name is the
    path under `root` (default: the directory given, or the file's directory) with `/` as `.` and no extension."""
    out: dict[str, str] = {}
    for p in paths:
        if os.path.isdir(p):
            base = root or p
            files = []
            for dirpath, dirnames, filenames in os.walk(p, followlinks=False):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                files += [os.path.join(dirpath, f) for f in sorted(filenames) if f.endswith(".lean")]
        else:
            base = root or os.path.dirname(os.path.abspath(p))
            files = [p]
        for f in files:
            if os.path.islink(f):
                raise InputError(f"{f} is a symlink; refusing to read through it")
            if os.path.getsize(f) > MAX_LEAN_FILE:
                raise InputError(f"{f} is larger than {MAX_LEAN_FILE} bytes")
            rel = os.path.relpath(os.path.abspath(f), os.path.abspath(base))
            if rel.startswith(".."):
                raise InputError(f"{f} is outside {base}")
            name = rel[:-5].replace(os.sep, ".")
            if name in out:
                raise InputError(f"two files are both module {name}")
            try:
                with open(f, encoding="utf-8") as fh:
                    out[name] = fh.read()
            except (OSError, UnicodeDecodeError) as exc:
                raise InputError(f"cannot read {f}: {exc}") from exc
    return out


class CommandCompile:
    """The compile oracle as a command. The module text is written to `Review.lean` in a scratch directory and the command is run as
    `cmd <path>`: exit 0 is "compiled" (its output kept, warnings included), exit 1 is "an error" (its output kept), anything else,
    a command that cannot start, or a timeout is "no answer". The environment is scrubbed (no tokens, a scratch HOME), the process
    group is killed on timeout, and output is bounded.

    THIS IS NOT A SANDBOX. Lean runs the code in the file it elaborates (`run_cmd`, `elab`, `#eval`, macros), and the file is a
    stranger's. Run the reviewer where a hostile module can do no harm: a runner with no secrets and egress blocked, which is what
    the Tengoku sandbox's CI is.
    """

    def __init__(self, cmd: str, timeout: float = 600.0):
        if not isinstance(cmd, str) or not cmd.strip():
            raise InputError("an empty compile command")
        self.argv = shlex.split(cmd)
        self.timeout = timeout

    def __call__(self, text: str) -> Outcome:
        with tempfile.TemporaryDirectory(prefix="review-") as scratch:
            path = os.path.join(scratch, "Review.lean")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
            env.update({"HOME": scratch, "TMPDIR": scratch})
            with tempfile.TemporaryFile() as out:
                try:
                    proc = subprocess.Popen(self.argv + [path], cwd=scratch, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                            stderr=subprocess.STDOUT, start_new_session=True)
                except (OSError, ValueError):
                    return UNDECIDED
                timed_out = False
                try:
                    proc.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    if timed_out:
                        proc.kill()
                proc.wait()
                out.seek(0)
                output = out.read(MAX_OUTPUT).decode("utf-8", "replace")
        if timed_out or proc.returncode not in (0, 1):
            return UNDECIDED
        return Outcome(proc.returncode == 0, output)


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
