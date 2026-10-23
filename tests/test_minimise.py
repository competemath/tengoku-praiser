import unittest

from praiser import minimise as M
from praiser.oracle import Outcome

PROOF = """import Mathlib.Data.Nat.Defs

theorem t (a b : ℕ) (h : a ≤ b) : a ≤ b + 1 := by
  have h0 : 0 ≤ a := Nat.zero_le a
  have h1 : a ≤ b + 1 := by
    omega
  simp only [] at *
  exact h1
"""


def toolchain(requires=(), forbids=(), fail_if=lambda t: False):
    """A fake toolchain: the module compiles when every required line is present."""
    calls = []

    def run(text):
        calls.append(text)
        if fail_if(text):
            return Outcome(False, "F.lean:1:0: error: boom\n")
        return Outcome(all(r in text for r in requires) and not any(f in text for f in forbids), "")

    run.calls = calls
    return run


class Ddmin(unittest.TestCase):
    def test_finds_the_one_minimal_subset(self):
        got, stopped = M.ddmin(list(range(8)), lambda s: {2, 5} <= set(s))
        self.assertEqual((got, stopped), ([2, 5], None))

    def test_everything_needed(self):
        got, _ = M.ddmin([1, 2, 3], lambda s: set(s) == {1, 2, 3})
        self.assertEqual(got, [1, 2, 3])

    def test_a_single_needed_item(self):
        got, _ = M.ddmin(list(range(10)), lambda s: 7 in s)
        self.assertEqual(got, [7])

    def test_no_answer_stops_with_what_is_known(self):
        n = []

        def test(s):
            n.append(1)
            return None if len(n) > 2 else (3 in s)

        got, stopped = M.ddmin(list(range(8)), test)
        self.assertEqual(stopped, "no_answer")
        self.assertIn(3, got)

    def test_budget(self):
        got, stopped = M.ddmin(list(range(16)), lambda s: 3 in s, max_calls=2)
        self.assertEqual(stopped, "budget")
        self.assertIn(3, got)

    def test_result_is_one_minimal(self):
        need = {1, 4, 6}
        got, _ = M.ddmin(list(range(9)), lambda s: need <= set(s))
        self.assertEqual(sorted(got), [1, 4, 6])


class Minimise(unittest.TestCase):
    def test_redundant_steps_are_removed_and_the_patch_was_compiled(self):
        o = toolchain(requires=("have h1 : a ≤ b + 1", "omega", "exact h1"))
        res = M.minimise_proof(PROOF, "t", o)
        self.assertEqual((res["steps"], res["removed"], res["stopped"]), (4, 2, None))
        self.assertNotIn("have h0", res["patch"])
        self.assertNotIn("simp only", res["patch"])
        self.assertIn("exact h1", res["patch"])
        self.assertTrue(o(res["patch"]).ok, "the patch compiles on the same toolchain")

    def test_a_proof_with_nothing_to_remove_has_no_patch(self):
        res = M.minimise_proof(PROOF, "t", toolchain(requires=("have h0", "have h1", "simp only", "exact h1")))
        self.assertIsNone(res["patch"])
        self.assertEqual(res["removed"], 0)

    def test_the_original_must_compile(self):
        res = M.minimise_proof(PROOF, "t", toolchain(requires=("not there",)))
        self.assertEqual(res["stopped"], "original")
        self.assertIsNone(res["patch"])

    def test_no_answer(self):
        res = M.minimise_proof(PROOF, "t", lambda t: Outcome(None))
        self.assertEqual(res["stopped"], "no_answer")

    def test_budget_keeps_what_was_verified(self):
        o = toolchain(requires=("have h1", "omega", "exact h1"))
        res = M.minimise_proof(PROOF, "t", o, budget=2)
        self.assertEqual(res["stopped"], "budget")
        if res["patch"]:
            self.assertTrue(o(res["patch"]).ok)

    def test_one_step_proofs_and_term_proofs_are_left_alone(self):
        self.assertEqual(M.minimise_proof("theorem t : True := by\n  trivial\n", "t", toolchain())["steps"], 1)
        self.assertEqual(M.minimise_proof("theorem t : True := trivial\n", "t", toolchain())["steps"], 0)

    def test_unknown_theorem(self):
        self.assertEqual(M.minimise_proof(PROOF, "nope", toolchain())["stopped"], "not_found")

    def test_nested_blocks_stay_whole(self):
        src = "theorem t : True ∧ True := by\n  constructor\n  · trivial\n  · trivial\n  skip\n"
        o = toolchain(requires=("constructor", "· trivial\n  · trivial"))
        res = M.minimise_proof(src, "t", o)
        self.assertEqual(res["removed"], 1)
        self.assertNotIn("skip", res["patch"])


class Automation(unittest.TestCase):
    def test_finds_the_first_closer_that_compiles(self):
        o = toolchain(requires=("by simp",))
        self.assertEqual(M.automation_closes(PROOF, "t", o)[0], "simp")

    def test_already_that_closer(self):
        self.assertEqual(M.automation_closes("theorem t : True := by simp\n", "t", toolchain(requires=("by simp",))), (None, None))

    def test_none_closes(self):
        self.assertEqual(M.automation_closes(PROOF, "t", toolchain(requires=("have h1",))), (None, None))


OPTS = """import Mathlib.Data.Nat.Defs

set_option maxHeartbeats 400000 in
theorem t (a b : ℕ) (h : a ≤ b) : a ≤ b + 1 := by
  omega
"""


class Robust(unittest.TestCase):
    def rules(self, text, o):
        return sorted(f["rule"] if "rule" in f else f["severity"] for f in M.robustness(text, "t", o))

    def test_a_robust_proof_has_no_finding(self):
        self.assertEqual(M.robustness(OPTS, "t", toolchain()), [])

    def test_needs_an_option(self):
        o = toolchain(fail_if=lambda t: "maxHeartbeats 400000" not in t)
        fs = M.robustness(OPTS, "t", o)
        self.assertEqual([(f["rule"], f["severity"]) for f in fs], [("needs_option", "warn")])
        self.assertIn("maxHeartbeats", fs[0]["detail"])

    def test_auto_implicit_reliance_is_a_fail(self):
        o = toolchain(fail_if=lambda t: "autoImplicit false" in t)
        fs = M.robustness(OPTS, "t", o)
        self.assertIn(("auto_implicit", "fail"), [(f["rule"], f["severity"]) for f in fs])

    def test_heartbeat_margin(self):
        o = toolchain(fail_if=lambda t: "maxHeartbeats 100000" in t)
        src = OPTS.replace("set_option maxHeartbeats 400000 in\n", "")
        fs = M.robustness(src, "t", o)
        self.assertEqual([f["rule"] for f in fs], ["heartbeats_margin"])

    def test_an_original_that_does_not_compile_is_inconclusive(self):
        fs = M.robustness(OPTS, "t", toolchain(requires=("zzz",)))
        self.assertEqual([f["severity"] for f in fs], ["inconclusive"])

    def test_no_answer_is_inconclusive(self):
        fs = M.robustness(OPTS, "t", lambda t: Outcome(None))
        self.assertEqual([f["severity"] for f in fs], ["inconclusive"])

    def test_options_used(self):
        self.assertEqual(M.options_used("set_option a.b 1 in\nset_option c true\nset_option a.b 2 in\n"), ["a.b", "c"])

    def test_without_option_removes_both_forms(self):
        text = "set_option a 1\nset_option b 2 in\ntheorem t : True := trivial\n"
        self.assertEqual(M._without_option(text, "a"), "set_option b 2 in\ntheorem t : True := trivial\n")
        self.assertEqual(M._without_option(text, "b"), "set_option a 1\ntheorem t : True := trivial\n")


class AsFindings(unittest.TestCase):
    def test_patches_are_warnings_with_the_patch(self):
        o = toolchain(requires=("have h1", "omega", "exact h1"))
        fs = M.findings(PROOF, o, module="M")
        mins = [f for f in fs if f["check"] == "minimise"]
        self.assertEqual([f["severity"] for f in mins], ["warn"])
        self.assertIn("patch", mins[0])
        self.assertEqual(mins[0]["module"], "M")

    def test_a_shared_budget_per_theorem(self):
        o = toolchain(requires=("have h1", "omega", "exact h1"))
        M.findings(PROOF, o, budget_per_theorem=6)
        self.assertLessEqual(len(o.calls), 6)


if __name__ == "__main__":
    unittest.main()
