import unittest

from vendor.juridicator_evidence import validate
from praiser import reviewer as V
from praiser.oracle import Outcome
from tests.helpers import CASE, NOW, TOOLING

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
BAD = """import Mathlib.Data.Nat.Defs
theorem lemma1 (n : ℕ) : n + 0 = n := by
  sorry
"""


def toolchain(text):
    return Outcome("sorry" not in text, "-- All linting checks passed!\n" if text.rstrip().endswith("#lint") else "")


def run(modules, **kw):
    return V.review(modules, **kw)


def codes(res, check):
    return sorted({(f.get("rule") or f["name"], f["severity"]) for f in res.findings if f["check"] == check})


class Review(unittest.TestCase):
    def test_text_checks_run_without_a_compiler_and_lean_checks_do_not(self):
        res = run({"Good": GOOD})
        self.assertEqual(res.ran, sorted(V.TEXT_CHECKS))
        self.assertEqual(res.requested, sorted(V.ALL_CHECKS))
        recs = {e["kind"]: e for e in V.evidence(res, CASE, TOOLING, NOW, lambda c: f"review {c}")}
        for c in V.LEAN_CHECKS:
            self.assertEqual(recs[f"mechanical.review.{c}"]["outcome"], "not_run", c)
        for e in recs.values():
            self.assertEqual(validate(e), [])

    def test_a_bad_module_is_caught_by_the_text_checks(self):
        res = run({"Bad": BAD}, checks=V.TEXT_CHECKS)
        self.assertIn(("sorry", "fail"), codes(res, "style"))
        self.assertIn(("placeholder", "fail"), codes(res, "naming"))
        self.assertIn(("module_doc", "fail"), codes(res, "docs"))

    def test_lean_checks_run_with_a_toolchain(self):
        res = run({"Good": GOOD}, primary=toolchain, checks=("lint", "compiler", "minimise"))
        self.assertEqual(res.ran, ["compiler", "lint", "minimise"])
        self.assertGreater(res.calls, 0)

    def test_compat_needs_both_toolchains(self):
        self.assertNotIn("compat", run({"Good": GOOD}, primary=toolchain, checks=("compat",)).ran)
        self.assertIn("compat", run({"Good": GOOD}, primary=toolchain, forward=toolchain, checks=("compat",)).ran)

    def test_cross_module_duplicates_are_found(self):
        a = "theorem first (a : ℕ) : a * 1 + 0 = a * 1 := by\n  simp\n"
        b = "theorem second (n : ℕ) : n * 1 + 0 = n * 1 := by\n  simp\n"
        res = run({"A": a, "B": b}, checks=("dedupe",))
        self.assertEqual(sorted((f["module"], f["rule"]) for f in res.findings), [("A", "identical"), ("B", "identical")])

    def test_the_tree_index_is_not_mutated(self):
        from praiser import dedupe
        ix = dedupe.Index.of({"Tree": "theorem t (a : ℕ) : a * 1 + 0 = a * 1 := by\n  simp\n"})
        before = (len(ix.entries), len(ix.texts))
        res = run({"New": "theorem u (n : ℕ) : n * 1 + 0 = n * 1 := by\n  simp\n"}, checks=("dedupe",), index=ix)
        self.assertEqual([f["rule"] for f in res.findings], ["identical"])
        self.assertEqual((len(ix.entries), len(ix.texts)), before)

    def test_copied_helpers_across_modules(self):
        h = "theorem Foo.helper (n : ℕ) : n + 0 = n := by\n  simp\n"
        res = run({"A": h + "\ntheorem a_only (n : ℕ) : n = n := rfl\n", "B": h}, checks=("hoist",))
        self.assertEqual([f["rule"] for f in res.findings], ["copied_helper"])

    def test_unknown_check(self):
        with self.assertRaises(ValueError):
            run({"A": GOOD}, checks=("style", "vibes"))

    def test_deterministic(self):
        from praiser.review import findings_digest
        a = run({"Good": GOOD, "Bad": BAD}, primary=toolchain, checks=V.TEXT_CHECKS + ("lint", "minimise"))
        b = run({"Bad": BAD, "Good": GOOD}, primary=toolchain, checks=V.TEXT_CHECKS + ("lint", "minimise"))
        self.assertEqual(findings_digest(a.findings), findings_digest(b.findings))
        self.assertEqual(a.findings, b.findings)

    def test_global_budget(self):
        calls = []

        def counting(text):
            calls.append(1)
            return Outcome(True, "")

        res = run({"Good": GOOD}, primary=counting, checks=("generalise", "minimise", "robust"), total_calls=5)
        self.assertLessEqual(len(calls), 5)
        self.assertTrue(res.exhausted)
        self.assertTrue(any(f["severity"] == "inconclusive" for f in res.findings), "running out of budget is reported, not hidden")

    def test_patches_are_collected(self):
        def tc(text):
            return Outcome(True, "")

        res = run({"Good": GOOD}, primary=tc, checks=("minimise",))
        self.assertTrue(all(isinstance(f["patch"], str) for f in res.patches()))

    def test_the_whole_thing_is_evidence(self):
        res = run({"Good": GOOD, "Bad": BAD}, primary=toolchain, forward=toolchain)
        recs = V.evidence(res, CASE, TOOLING, NOW, lambda c: f"review {c}")
        self.assertEqual(len(recs), len(V.ALL_CHECKS))
        self.assertTrue(all(validate(e) == [] for e in recs))


if __name__ == "__main__":
    unittest.main()
