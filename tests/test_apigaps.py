import unittest

from praiser import apigaps as A


def rules(src, **kw):
    return sorted((f["rule"], f["severity"]) for f in A.check_module(src, **kw))


class Siblings(unittest.TestCase):
    def test_left_without_right(self):
        src = "theorem mul_le_mul_left' (a b c : ℕ) (h : a ≤ b) : c * a ≤ c * b := Nat.mul_le_mul_left c h\n"
        fs = A.check_module(src)
        self.assertEqual([(f["rule"], f["severity"]) for f in fs], [("sibling", "warn")])
        self.assertIn("mul_le_mul_right'", fs[0]["detail"])

    def test_both_present(self):
        src = ("theorem mul_le_mul_left' (a b c : ℕ) (h : a ≤ b) : c * a ≤ c * b := Nat.mul_le_mul_left c h\n"
               "theorem mul_le_mul_right' (a b c : ℕ) (h : a ≤ b) : a * c ≤ b * c := Nat.mul_le_mul_right c h\n")
        self.assertEqual(rules(src), [])

    def test_the_counterpart_in_the_library_counts(self):
        src = "theorem mul_le_mul_left' (a b c : ℕ) (h : a ≤ b) : c * a ≤ c * b := Nat.mul_le_mul_left c h\n"
        self.assertEqual(rules(src, known={"mul_le_mul_right'"}), [])

    def test_sibling_in_the_middle_of_a_name(self):
        gaps = A.sibling_gaps({"foo_left_iff"})
        self.assertEqual([(g[0], g[1]) for g in gaps], [("foo_left_iff", "foo_right_iff")])

    def test_namespace_is_respected(self):
        gaps = A.sibling_gaps({"A.foo_left"}, known={"B.foo_right"})
        self.assertEqual(len(gaps), 1)

    def test_nonneg_pos_is_only_info(self):
        gaps = A.sibling_gaps({"foo_nonneg"})
        self.assertEqual([g[2] for g in gaps], ["info"])


class Definitions(unittest.TestCase):
    def test_a_definition_nobody_uses(self):
        src = "/-- Doubling. -/\ndef double (n : ℕ) : ℕ := n + n\n\ntheorem unrelated (a : ℕ) : a + 0 = a := by\n  simp\n"
        self.assertIn(("def_api", "warn"), rules(src))

    def test_a_definition_with_a_lemma(self):
        src = "/-- Doubling. -/\ndef double (n : ℕ) : ℕ := n + n\n\ntheorem double_eq (n : ℕ) : double n = 2 * n := by\n  unfold double\n  omega\n"
        self.assertNotIn(("def_api", "warn"), rules(src))

    def test_private_definitions_are_exempt(self):
        self.assertEqual(rules("private def double (n : ℕ) : ℕ := n + n\n"), [])

    def test_a_predicate_wants_a_characterisation(self):
        src = "def IsBig (n : ℕ) : Prop := 10 < n\n\ntheorem isBig_ten : IsBig 11 := by\n  unfold IsBig\n  omega\n"
        self.assertIn(("def_api", "info"), rules(src))
        self.assertNotIn(("def_api", "info"), rules(src + "\ntheorem isBig_iff (n : ℕ) : IsBig n ↔ 10 < n := Iff.rfl\n"))

    def test_a_structure_wants_ext(self):
        src = "structure Pt where\n  x : ℕ\n  y : ℕ\n"
        self.assertIn(("def_api", "warn"), rules(src))
        self.assertNotIn(("def_api", "warn"), rules("@[ext]\n" + src))
        self.assertNotIn(("def_api", "warn"), rules(src + "\ntheorem Pt.ext (p q : Pt) (hx : p.x = q.x) (hy : p.y = q.y) : p = q := by\n  cases p\n  cases q\n  simp_all\n"))


class Forms(unittest.TestCase):
    def test_ge_and_gt_conclusions(self):
        self.assertIn(("form", "warn"), rules("theorem t (a b : ℕ) (h : b ≤ a) : a ≥ b := h\n"))
        self.assertIn(("form", "warn"), rules("theorem t (a b : ℕ) (h : b < a) : a > b := h\n"))
        self.assertNotIn(("form", "warn"), rules("theorem t (a b : ℕ) (h : a ≥ b) : b ≤ a := h\n"), "only the conclusion is judged")

    def test_negated_equality_and_membership(self):
        self.assertIn(("form", "warn"), rules("theorem t (a b : ℕ) (h : a < b) : ¬ a = b := by omega\n"))
        self.assertNotIn(("form", "warn"), rules("theorem t (a b : ℕ) (h : a < b) : a ≠ b := by omega\n"))
        self.assertIn(("form", "warn"), rules("theorem t (s : Set ℕ) (h : 3 ∉ s) : ¬ 3 ∈ s := h\n"))

    def test_succ_and_named_universes(self):
        self.assertIn(("form", "warn"), rules("theorem t (n : ℕ) : Nat.succ n = n + 1 := rfl\n"))
        self.assertIn(("form", "warn"), rules("theorem t {α : Type u} (a : α) : a = a := rfl\n"))
        self.assertNotIn(("form", "warn"), rules("theorem t {α : Type*} (a : α) : a = a := rfl\n"))

    def test_findings_are_ordered_and_tagged(self):
        fs = A.check_module("theorem a (x y : ℕ) (h : y ≤ x) : x ≥ y := h\ntheorem b {α : Type u} (a : α) : a = a := rfl\n", module="M")
        self.assertEqual([f["line"] for f in fs], sorted(f["line"] for f in fs))
        self.assertTrue(all(f["check"] == "api" and f["module"] == "M" for f in fs))


if __name__ == "__main__":
    unittest.main()
