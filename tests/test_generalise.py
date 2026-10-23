import unittest

from praiser import generalise as G
from praiser import leansrc as L
from praiser.oracle import Bounded, Outcome


def nat(accept):
    """The fake toolchain refuses every type-generalised candidate, so a test about another rung is not decided by that one."""
    return lambda text: "α" not in text and accept(text)


def oracle_for(accept):
    """A fake toolchain: the module compiles when `accept(text)` says so. No Lean anywhere."""
    calls = []

    def run(text):
        calls.append(text)
        return Outcome(True, "") if accept(text) else Outcome(False, "F.lean:3:0: error: unsolved goals\n")

    run.calls = calls
    return run


HYP = "theorem t (a b : ℕ) (h1 : 0 < a) (h2 : a ≤ b) : a ≤ b + 1 := by\n  omega\n"
LIT = "theorem t (a : ℕ) : a + 3 = 3 + a := by\n  omega\n"
TYP = "theorem t (a b : ℕ) : a + b = b + a := by\n  ring\n"


def stmt(text, name="t"):
    d = [x for x in L.declarations(text) if x.name == name][0]
    return L.statement_text(text, d)


class Rungs(unittest.TestCase):
    def test_drop_an_unused_hypothesis(self):
        o = oracle_for(nat(lambda t: "(h2 : a ≤ b)" in t and "a ≤ b + 1" in t))
        lad = G.climb(HYP, "t", o)
        self.assertEqual([s.rung for s in lad.steps], ["drop_hypothesis"])
        self.assertNotIn("h1", lad.final)
        self.assertIn("(h2 : a ≤ b)", lad.final)
        self.assertTrue(lad.final.rstrip().endswith("omega"), "the proof is untouched")

    def test_a_needed_hypothesis_stays(self):
        o = oracle_for(nat(lambda t: "(h1 : 0 < a)" in t and "(h2 : a ≤ b)" in t))
        lad = G.climb(HYP, "t", o)
        self.assertFalse(lad.improved)
        self.assertEqual(lad.final, HYP)

    def test_every_hypothesis_can_go(self):
        lad = G.climb(HYP, "t", oracle_for(nat(lambda t: True)))
        self.assertNotIn("h1", lad.final)
        self.assertNotIn("h2", lad.final)

    def test_numeral_to_variable(self):
        o = oracle_for(nat(lambda t: "a + 3 = 3 + a" in t or "a + k = k + a" in t))
        lad = G.climb(LIT, "t", o)
        self.assertEqual([s.rung for s in lad.steps], ["literal_to_variable"])
        self.assertIn("(k : ℕ)", lad.final)
        self.assertIn("a + k = k + a", lad.final)

    def test_zero_and_one_stay_numerals(self):
        lad = G.climb("theorem t (a : ℕ) : a + 1 = 1 + a := by\n  omega\n", "t", oracle_for(nat(lambda t: True)))
        self.assertNotIn("(k : ℕ)", lad.final)

    def test_type_generalisation_takes_the_weakest_class_that_compiles(self):
        def accept(text):
            if "ℕ" in text:
                return True
            return "[CommSemiring α]" in text or "IsStrictOrderedRing" in text

        lad = G.climb(TYP, "t", oracle_for(accept))
        self.assertEqual([s.rung for s in lad.steps], ["type_generalise"])
        self.assertIn("{α : Type*} [CommSemiring α]", lad.final)
        self.assertIn("(a b : α)", lad.final)
        self.assertNotIn("ℕ", lad.final)

    def test_no_class_compiles_means_no_change(self):
        lad = G.climb(TYP, "t", oracle_for(lambda t: "ℕ" in t))
        self.assertFalse(lad.improved)

    def test_weaken_a_strict_hypothesis(self):
        src = "theorem t (a b : ℕ) (h : a < b) : a ≤ b := by\n  omega\n"
        o = oracle_for(nat(lambda t: "(h : a ≤ b)" in t or "(h : a < b)" in t))
        lad = G.climb(src, "t", o)
        self.assertEqual([s.rung for s in lad.steps], ["weaken_order"])
        self.assertIn("(h : a ≤ b)", lad.final)

    def test_steps_chain_on_the_result_of_the_previous_one(self):
        src = "theorem t (a : ℕ) (h : 0 < a) : a + 3 = 3 + a := by\n  omega\n"
        lad = G.climb(src, "t", oracle_for(nat(lambda t: "a + 3 = 3 + a" in t or "a + k = k + a" in t)))
        self.assertEqual([s.rung for s in lad.steps], ["drop_hypothesis", "literal_to_variable"])
        self.assertEqual(lad.steps[-1].text, lad.final)


class Honesty(unittest.TestCase):
    def test_the_original_must_compile(self):
        lad = G.climb(HYP, "t", oracle_for(lambda t: False))
        self.assertEqual(lad.stopped, "original")
        self.assertFalse(lad.improved)

    def test_sorry_is_not_compiling(self):
        o = lambda t: Outcome(True, "F.lean:1:0: warning: declaration uses 'sorry'\n")
        self.assertEqual(G.climb(HYP, "t", o).stopped, "original")

    def test_no_answer_is_not_an_answer(self):
        lad = G.climb(HYP, "t", lambda t: Outcome(None))
        self.assertEqual(lad.stopped, "no_answer")
        self.assertFalse(lad.improved)

    def test_budget_stops_the_climb_and_keeps_what_was_verified(self):
        o = oracle_for(nat(lambda t: True))
        lad = G.climb(HYP, "t", o, budget=2)
        self.assertEqual(lad.stopped, "budget")
        self.assertEqual(len(lad.steps), 1)
        self.assertEqual(lad.steps[0].text, lad.final)
        self.assertLessEqual(len(o.calls), 2)

    def test_a_shared_bounded_oracle_is_respected(self):
        b = Bounded(oracle_for(nat(lambda t: True)), 3)
        G.climb(HYP, "t", b)
        self.assertEqual(b.calls, 3)

    def test_unknown_or_ambiguous_names(self):
        self.assertEqual(G.climb(HYP, "nope", oracle_for(lambda t: True)).stopped, "not_found")
        two = HYP + "\n" + HYP
        self.assertEqual(G.climb(two, "t", oracle_for(lambda t: True)).stopped, "ambiguous")

    def test_deterministic(self):
        a = G.climb(HYP, "t", oracle_for(nat(lambda t: "(h2 : a ≤ b)" in t)))
        b = G.climb(HYP, "t", oracle_for(nat(lambda t: "(h2 : a ≤ b)" in t)))
        self.assertEqual((a.final, [s.rung for s in a.steps]), (b.final, [s.rung for s in b.steps]))


class AsFindings(unittest.TestCase):
    def test_a_verified_patch_is_a_fail_with_the_patch(self):
        fs = G.findings(HYP, oracle_for(nat(lambda t: "(h2 : a ≤ b)" in t)), module="M")
        self.assertEqual(len(fs), 1)
        self.assertEqual((fs[0]["check"], fs[0]["severity"], fs[0]["name"], fs[0]["module"]), ("generalise", "fail", "t", "M"))
        self.assertNotIn("h1", fs[0]["patch"])
        self.assertEqual(fs[0]["steps"], ["drop_hypothesis"])

    def test_nothing_to_generalise_is_silent(self):
        self.assertEqual(G.findings(HYP, oracle_for(lambda t: t == HYP)), [])

    def test_inconclusive_when_there_is_no_answer(self):
        fs = G.findings(HYP, lambda t: Outcome(None))
        self.assertEqual([f["severity"] for f in fs], ["inconclusive"])

    def test_only_the_named_theorems(self):
        two = HYP + "\ntheorem u (a b : ℕ) (h1 : 0 < a) (h2 : a ≤ b) : a ≤ b + 1 := by\n  omega\n"
        fs = G.findings(two, oracle_for(nat(lambda t: True)), names={"u"})
        self.assertEqual({f["name"] for f in fs}, {"u"})


if __name__ == "__main__":
    unittest.main()
