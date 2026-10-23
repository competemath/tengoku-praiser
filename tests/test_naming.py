import unittest

from praiser import leansrc as L
from praiser import naming as N


def sug(stmt):
    return N.suggest(stmt)


def check(src, taken=frozenset()):
    return N.check_module(src, taken)


def rules(src, **kw):
    return sorted({f["rule"] for f in check(src, **kw)})


class Suggest(unittest.TestCase):
    def test_equalities_name_the_left_side(self):
        self.assertEqual(sug("t (a : ℕ) : a + 0 = a")[0], "add_zero")
        self.assertIn("mul_one", sug("t (a : ℕ) : a * 1 = a"))

    def test_hypotheses_follow_of(self):
        self.assertEqual(sug("t (a b c : ℕ) (h1 : a ≤ b) (h2 : b < c) : a < c")[0], "lt_of_le_of_lt")

    def test_iff(self):
        self.assertEqual(sug("t (a b : ℕ) : a ≤ b ↔ a < b + 1")[0], "le_iff_lt_add_one")

    def test_binary_and_unary_minus(self):
        self.assertIn("neg", N.describe(L.canonical_tokens("- a")))
        self.assertIn("sub", N.describe(L.canonical_tokens("a - b")))

    def test_named_functions(self):
        self.assertIn("card", sug("t (s : Finset ℕ) : Finset.card s = Finset.card s")[0])

    def test_nothing_for_unreadable(self):
        self.assertEqual(sug("t (a : ℕ)"), [])

    def test_deterministic(self):
        s = "t (a b : ℕ) (h : a ∣ b) : a ≤ b ∨ b = 0"
        self.assertEqual(sug(s), sug(s))


class Checks(unittest.TestCase):
    def test_a_good_name_has_no_finding(self):
        self.assertEqual(check("theorem add_zero' (a : ℕ) : a + 0 = a := by simp\n"), [])
        self.assertEqual(check("theorem lt_of_le_of_lt' {a b c : ℕ} (h1 : a ≤ b) (h2 : b < c) : a < c := lt_of_le_of_lt h1 h2\n"), [])

    def test_case(self):
        self.assertIn("case", rules("theorem AddZero (a : ℕ) : a + 0 = a := by simp\n"))
        self.assertIn("case", rules("theorem add_zero_ (a : ℕ) : a + 0 = a := by simp\n"))
        self.assertIn("case", rules("structure my_struct where\n  x : ℕ\n"))
        self.assertIn("case", rules("class Foo_bar (α : Type) where\n  x : α\n"))
        self.assertEqual(rules("structure MyStruct where\n  x : ℕ\n"), [])
        self.assertIn("case", rules("def foo_bar (n : ℕ) : ℕ := n\n"))
        self.assertNotIn("case", rules("def fooBar (n : ℕ) : ℕ := n\n"))
        self.assertIn("case", rules("def is_good (n : ℕ) : Prop := n = 0\n"))
        self.assertNotIn("case", rules("def IsGood (n : ℕ) : Prop := n = 0\n"))

    def test_a_namespaced_type_in_a_theorem_name_is_fine(self):
        self.assertNotIn("case", rules("theorem Nat.succ_le_iff' {a b : ℕ} : a.succ ≤ b ↔ a < b := Nat.succ_le\n"))

    def test_placeholders_and_machine_names(self):
        for bad in ("lemma1", "aux", "helper_2", "foo", "thm_3", "main", "step", "S3f9a1c2b7d4e", "claim"):
            self.assertIn("placeholder", rules(f"theorem {bad} (a : ℕ) : a + 0 = a := by simp\n"), bad)
        self.assertNotIn("placeholder", rules("theorem add_zero_comm (a : ℕ) : a + 0 = a := by simp\n"))

    def test_numbered(self):
        self.assertIn("numbered", rules("theorem add_zero_2 (a : ℕ) : a + 0 = a := by simp\n"))

    def test_a_misleading_name(self):
        self.assertIn("misleading", rules("theorem mul_comm' (a b : ℕ) : a + b = b + a := by omega\n"))
        self.assertNotIn("misleading", rules("theorem add_comm' (a b : ℕ) : a + b = b + a := by omega\n"))
        self.assertNotIn("misleading", rules("theorem sq_nonneg' (a : ℤ) : 0 ≤ a ^ 2 := by positivity\n"))

    def test_a_silent_name(self):
        self.assertIn("silent", rules("theorem fermat_like (a b : ℕ) : a + b = b + a := by omega\n"))
        self.assertNotIn("silent", rules("theorem add_comm' (a b : ℕ) : a + b = b + a := by omega\n"))

    def test_taken_and_duplicate_components(self):
        src = "namespace Foo\ntheorem add_zero' (a : ℕ) : a + 0 = a := by simp\nend Foo\n"
        self.assertIn("taken", rules(src, taken={"Foo.add_zero'"}))
        self.assertNotIn("taken", rules(src))
        self.assertIn("dup_namespace", rules("namespace Foo\ntheorem Foo.add_zero' (a : ℕ) : a + 0 = a := by simp\nend Foo\n"))

    def test_variable_names(self):
        self.assertIn("variable_name", rules("theorem add_zero' (number : ℕ) : number + 0 = number := by simp\n"))
        self.assertNotIn("variable_name", rules("theorem add_zero' (n : ℕ) : n + 0 = n := by simp\n"))

    def test_findings_carry_name_line_and_module(self):
        fs = N.check_module("def addTwo (n : ℕ) : ℕ := n + 2\n\ntheorem lemma1 : True := trivial\n", module="Foo")
        self.assertEqual((fs[0]["name"], fs[0]["line"], fs[0]["module"], fs[0]["check"]), ("lemma1", 3, "Foo", "naming"))

    def test_unnamed_declarations_are_skipped(self):
        self.assertEqual(check("instance : Inhabited ℕ := ⟨0⟩\nexample : 1 = 1 := rfl\n"), [])


if __name__ == "__main__":
    unittest.main()
