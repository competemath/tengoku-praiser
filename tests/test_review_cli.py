import json
import os
import shlex
import sys
import tempfile
import unittest

from vendor.juridicator_evidence import validate
from praiser import loaders
from praiser.cli import main
from tests.helpers import CASE, NOW, TOOLING

FAKE = r'''
import os, sys
text = open(sys.argv[1], encoding="utf-8").read()
if "SLEEP" in text:
    import time; time.sleep(30)
if "CRASH" in text:
    sys.exit(7)
if "SECRET" in text:
    print("env:" + os.environ.get("PRAISER_SECRET_TOKEN", "absent") + ":" + os.environ.get("HOME", ""))
if text.rstrip().endswith("#lint"):
    print("-- All linting checks passed!")
if "sorry" in text:
    print(sys.argv[1] + ":3:2: error: boom")
    sys.exit(1)
sys.exit(0)
'''
GOOD = """import Mathlib.Data.Nat.Defs

/-!
# Adding zero

## Main results

* `Foo.add_zero'`: adding zero does nothing.
-/

namespace Foo

/-- Adding zero on the right does nothing, in the form `a + 0 = a`. -/
theorem add_zero' (a b : ℕ) (h : a = b) : a + 0 = b := by
  have h0 : 0 ≤ a := Nat.zero_le a
  omega

end Foo
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        self.fake = os.path.join(self.dir, "fake_lean.py")
        with open(self.fake, "w", encoding="utf-8") as fh:
            fh.write(FAKE)
        self.cmd = f"{shlex.quote(sys.executable)} {shlex.quote(self.fake)}"
        os.makedirs(os.path.join(self.dir, "mods", "Studied"))
        self.write("mods/Studied/Good.lean", GOOD)
        for name, obj in (("case.json", CASE), ("producer.json", TOOLING)):
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
                json.dump(obj, fh)

    def write(self, rel, text):
        with open(os.path.join(self.dir, rel), "w", encoding="utf-8") as fh:
            fh.write(text)

    def p(self, rel):
        return os.path.join(self.dir, rel)


class Loaders(Fixture):
    def test_module_names_come_from_paths(self):
        mods = loaders.read_lean_modules([self.p("mods")])
        self.assertEqual(sorted(mods), ["Studied.Good"])
        self.assertEqual(sorted(loaders.read_lean_modules([self.p("mods/Studied/Good.lean")], root=self.p("mods"))), ["Studied.Good"])

    def test_symlinks_are_refused(self):
        os.symlink(self.p("mods/Studied/Good.lean"), self.p("mods/Studied/Link.lean"))
        with self.assertRaises(loaders.InputError):
            loaders.read_lean_modules([self.p("mods")])

    def test_a_file_outside_the_root_is_refused(self):
        self.write("outside.lean", "def x := 1\n")
        with self.assertRaises(loaders.InputError):
            loaders.read_lean_modules([self.p("outside.lean")], root=self.p("mods"))

    def test_compile_command_exit_codes(self):
        c = loaders.CommandCompile(self.cmd, timeout=20)
        ok = c("theorem t : True := trivial\n")
        self.assertEqual((ok.ok, ok.verdict), (True, True))
        bad = c("theorem t : True := sorry\n")
        self.assertEqual(bad.ok, False)
        self.assertIn("error: boom", bad.output)
        self.assertIsNone(c("-- CRASH\n").ok, "an exit status that is neither 0 nor 1 is no answer")

    def test_timeout_is_no_answer_and_kills_the_process(self):
        self.assertIsNone(loaders.CommandCompile(self.cmd, timeout=1)("-- SLEEP\n").ok)

    def test_the_environment_is_scrubbed(self):
        os.environ["PRAISER_SECRET_TOKEN"] = "hunter2"
        self.addCleanup(os.environ.pop, "PRAISER_SECRET_TOKEN", None)
        got = loaders.CommandCompile(self.cmd, timeout=20)("-- SECRET\n")
        self.assertIn("env:absent:", got.output)
        self.assertNotIn(os.path.expanduser("~"), got.output.replace("review-", ""))

    def test_a_command_that_cannot_start(self):
        self.assertIsNone(loaders.CommandCompile("/no/such/binary", timeout=5)("x").ok)

    def test_an_empty_command(self):
        with self.assertRaises(loaders.InputError):
            loaders.CommandCompile("  ")


class Cli(Fixture):
    def run_cli(self, *extra):
        out = self.p("evidence.json")
        code = main(["review", "--case", self.p("case.json"), "--producer", self.p("producer.json"), "--created", NOW, "--module", self.p("mods"),
                     "--out", out, *extra])
        data = None
        if os.path.exists(out):
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
        return code, data

    def test_text_checks_only(self):
        code, recs = self.run_cli("--checks", "style", "naming", "docs")
        self.assertEqual(code, 0)
        kinds = [r["kind"] for r in recs]
        self.assertEqual(kinds[0], "manifest.declared")
        self.assertEqual(sorted(kinds[1:]), ["mechanical.review.docs", "mechanical.review.naming", "mechanical.review.style"])
        self.assertTrue(all(validate(r) == [] for r in recs))
        self.assertEqual(recs[0]["details"]["checks"], ["mechanical.review.docs", "mechanical.review.naming", "mechanical.review.style"])

    def test_the_default_runs_everything_and_reports_what_could_not_run(self):
        code, recs = self.run_cli()
        outcomes = {r["kind"].split(".")[-1]: r["outcome"] for r in recs[1:]}
        for c in ("lint", "compiler", "generalise", "minimise", "robust", "compat"):
            self.assertEqual(outcomes[c], "not_run", c)
        self.assertEqual(len(recs), 1 + 13)

    def test_with_a_toolchain(self):
        findings = self.p("findings.json")
        patches = self.p("patches")
        code, recs = self.run_cli("--checks", "lint", "minimise", "--compile-cmd", self.cmd, "--timeout", "30", "--findings", findings,
                                  "--patches-dir", patches)
        self.assertEqual(code, 0)
        outcomes = {r["kind"].split(".")[-1]: r["outcome"] for r in recs[1:]}
        self.assertEqual(outcomes["lint"], "pass")
        self.assertIn(outcomes["minimise"], ("pass", "fail"))
        with open(findings, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["ran"], ["lint", "minimise"])
        for f in data["findings"]:
            if "patch" in f:
                self.assertTrue(os.path.exists(os.path.join(patches, f["patch"])))
        for r in recs[1:]:
            self.assertIn("--checks", r["reproduce"]["command"])
            self.assertIn("--compile-cmd", r["reproduce"]["command"])

    def test_the_reproduce_command_names_the_check(self):
        _, recs = self.run_cli("--checks", "style")
        self.assertTrue(recs[1]["reproduce"]["command"].endswith("--checks style"))

    def test_an_index_gives_duplicates(self):
        os.makedirs(self.p("tree"))
        self.write("tree/Tree.lean", "theorem tree_add_zero (n : ℕ) (m : ℕ) (h : n = m) : n + 0 = m := by\n  omega\n")
        code, recs = self.run_cli("--checks", "dedupe", "--index", self.p("tree"))
        self.assertEqual(code, 0)
        rec = {r["kind"].split(".")[-1]: r for r in recs[1:]}["dedupe"]
        self.assertEqual(rec["outcome"], "fail")

    def test_bad_input_is_exit_2(self):
        self.assertEqual(main(["review", "--case", self.p("case.json"), "--producer", self.p("producer.json"), "--created", NOW,
                               "--module", self.p("nowhere")]), 2)
        os.makedirs(self.p("empty"))
        self.assertEqual(main(["review", "--case", self.p("case.json"), "--producer", self.p("producer.json"), "--created", NOW,
                               "--module", self.p("empty")]), 2)

    def test_an_unknown_check_is_exit_2(self):
        self.assertEqual(main(["review", "--case", self.p("case.json"), "--producer", self.p("producer.json"), "--created", NOW,
                               "--module", self.p("mods"), "--checks", "vibes"]), 2)

    def test_same_input_same_bytes(self):
        _, a = self.run_cli("--checks", "style", "naming", "docs", "api")
        _, b = self.run_cli("--checks", "style", "naming", "docs", "api")
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
