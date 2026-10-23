import unittest

from praiser import dedupe as D

TREE_A = """import Mathlib.Data.Nat.Defs

namespace Tree

theorem add_zero' (a : ℕ) : a + 0 = a := by
  simp

theorem plus_one_zero (a : ℕ) : a + 1 + 0 = a + 1 := by
  simp

theorem uses_it (x y : ℕ) (h : x = y) : x + 0 + y = x + y := by
  have h0 : x + 0 = x := by simp
  omega

end Tree
"""
INDEX = D.Index.of({"Tree.A": TREE_A})


def new_module(body, name="New"):
    return f"import Mathlib.Data.Nat.Defs\n\n{body}\n"


def kinds(findings):
    return sorted((f["rule"], f["severity"]) for f in findings)


class Duplicates(unittest.TestCase):
    def run_new(self, body, **kw):
        text = new_module(body)
        return D.duplicate_findings("New", text, INDEX, **kw)

    def test_identical_up_to_renaming(self):
        fs = self.run_new("theorem my_lemma (n : ℕ) : n + 0 = n := by\n  simp")
        self.assertIn(("identical", "fail"), kinds(fs))
        self.assertEqual(fs[0]["others"], ["Tree.A:Tree.add_zero'"])

    def test_a_specialisation_of_an_existing_statement(self):
        fs = self.run_new("theorem special (b : ℕ) (h : 0 < b) : b * 2 + 0 = b * 2 := by\n  simp")
        self.assertIn(("instance_of", "warn"), kinds(fs))

    def test_fewer_hypotheses_than_the_general_one_is_not_a_specialisation(self):
        idx = D.Index.of({"G": "theorem general (a : ℕ) (h : 0 < a) : a * 3 + 0 = a * 3 := by\n  simp\n"})
        fs = D.duplicate_findings("New", new_module("theorem t (b : ℕ) : b * 3 + 0 = b * 3 := by\n  simp"), idx)
        self.assertNotIn("instance_of", [f["rule"] for f in fs])

    def test_it_generalises_existing_statements(self):
        idx = D.Index.of({"T": "theorem special (a : ℕ) : (a + 1) + 0 = a + 1 := by\n  simp\n"})
        fs = D.duplicate_findings("New", "theorem more_general (a : ℕ) : a + 0 = a := by\n  simp\n", idx)
        self.assertEqual(kinds(fs), [("generalises", "info")])

    def test_near_duplicates(self):
        long_a = "theorem big (a b c d e f g h : ℕ) : " + " + ".join("a b c d e f g h".split() * 3) + " = a"
        long_b = long_a.replace("= a", "= b")
        idx = D.Index.of({"T": long_a + " := by\n  omega\n"})
        fs = D.duplicate_findings("New", long_b + " := by\n  omega\n", idx)
        self.assertEqual(kinds(fs), [("near_duplicate", "warn")])

    def test_unrelated_statements_are_not_duplicates(self):
        self.assertEqual(self.run_new("theorem other (a b : ℕ) : a * b = b * a := by\n  ring"), [])

    def test_a_module_is_not_its_own_duplicate(self):
        alone = "theorem only_one (a : ℕ) : a * 1 = a := by\n  simp\n"
        self.assertEqual(D.duplicate_findings("Alone", alone, D.Index.of({"Alone": alone})), [])

    def test_a_pattern_that_matches_everything_is_not_used(self):
        idx = D.Index.of({"T": "theorem triv (p : Prop) (h : p) : p := h\n"})
        self.assertEqual(D.duplicate_findings("New", "theorem t (a : ℕ) (h : a = a) : a = a := h\n", idx), [])


class Namespaces(unittest.TestCase):
    TWO = ("namespace A\ndef fst (n : ℕ) : ℕ := n\ntheorem coe_fst : fst 2 = 2 := rfl\nend A\n"
           "namespace B\ndef fst (n : ℕ) : ℕ := n + 0\ntheorem coe_fst : fst 2 = 2 := rfl\nend B\n")

    def test_the_same_words_in_two_namespaces_are_not_the_same_statement(self):
        es = D.entries_of("M", self.TWO)
        self.assertEqual(len(es), 2)
        self.assertNotEqual(es[0].key, es[1].key)
        self.assertEqual(D.duplicate_findings("M", self.TWO, D.Index.of({"M": self.TWO})), [])

    def test_unqualified_names_of_other_modules_still_compare_equal(self):
        a = "namespace A\ntheorem t (n : ℕ) : n + 0 = n := by\n  simp\nend A\n"
        b = "namespace B\ntheorem u (n : ℕ) : n + 0 = n := by\n  simp\nend B\n"
        self.assertEqual(D.entries_of("X", a)[0].key, D.entries_of("Y", b)[0].key)


class Context(unittest.TestCase):
    def test_variable_context_is_part_of_the_statement(self):
        a = "section\nvariable (n : ℕ)\ntheorem t : n + 0 = n := by\n  simp\nend\n"
        b = "section\nvariable (n : ℤ)\ntheorem u : n + 0 = n := by\n  simp\nend\n"
        self.assertNotEqual(D.entries_of("X", a)[0].key, D.entries_of("Y", b)[0].key)
        c = "section\nvariable (n : ℕ)\ntheorem v : n + 0 = n := by\n  simp\nend\n"
        self.assertEqual(D.entries_of("X", a)[0].key, D.entries_of("Z", c)[0].key)

    def test_variables_leave_scope_at_end(self):
        t = "section\nvariable (n : ℕ)\ntheorem t : n + 0 = n := by\n  simp\nend\ntheorem u (n : ℕ) : n + 0 = n := by\n  simp\n"
        ds = {d.name: d for d in __import__("praiser.leansrc", fromlist=["x"]).declarations(t)}
        self.assertEqual(ds["t"].variables, ("(n : ℕ)",))
        self.assertEqual(ds["u"].variables, ())

    def test_a_specialisation_needs_the_hypotheses_to_be_about_the_same_things(self):
        general = "theorem g (a b : ℕ) (h : Foo a) : a * b + 0 = a * b := by\n  simp\n"
        other = "theorem s (a b : ℕ) (h : Bar a) : a * b + 0 = a * b := by\n  simp\n"
        idx = D.Index.of({"G": general})
        self.assertNotIn("instance_of", [f["rule"] for f in D.duplicate_findings("S", other, idx)])
        same = "theorem s (a b : ℕ) (h : Foo a) (h2 : 0 < b) : a * b + 0 = a * b := by\n  simp\n"
        self.assertIn("instance_of", [f["rule"] for f in D.duplicate_findings("S", same, idx)])


class Reuse(unittest.TestCase):
    def test_inline_uses_are_counted(self):
        new = D.entries_of("New", "theorem add_zero_new (n : ℕ) : n + 0 = n := by\n  simp\n")[0]
        rep = D.reuse_report(new, INDEX, exclude_module="New")
        self.assertEqual((rep["modules"], rep["declarations"]), (1, 1))
        self.assertEqual(rep["inline"][0][:2], ("Tree.A", "Tree.uses_it"))
        self.assertGreaterEqual(len(rep["instances"]), 1, "plus_one_zero is an instance")

    def test_findings_reused_and_unused(self):
        used = D.reuse_findings("New", "theorem add_zero_new (n : ℕ) : n + 0 = n := by\n  simp\n", INDEX)
        self.assertEqual([(f["rule"], f["severity"]) for f in used], [("reused", "info")])
        self.assertEqual(used[0]["inline_declarations"], 1)
        unused = D.reuse_findings("New", "theorem weird (n : ℕ) : n ^ 7 % 13 = n ^ 7 % 13 := by\n  rfl\n", INDEX)
        self.assertEqual([(f["rule"], f["severity"]) for f in unused], [("unused", "warn")])

    def test_too_generic_statements_are_skipped(self):
        self.assertEqual(D.reuse_findings("New", "theorem g (p : Prop) (h : p) : p := h\n", INDEX), [])

    def test_inline_statement_forms(self):
        text = ("theorem t : True := by\n  have h : a + 0 = a := by simp\n  have : b = c := rfl\n  have h2 (x : ℕ) : x ≤ x := le_refl x\n"
                "  show d ≤ e from foo\n")
        got = [" ".join(toks) for _, _, toks in D.inline_statements(text)]
        self.assertEqual(got, ["a + 0 = a", "b = c", "x ≤ x", "d ≤ e"])

    def test_comments_are_not_statements(self):
        self.assertEqual(list(D.inline_statements("-- have h : a = a := rfl\n/- have h : b = b := rfl -/\n")), [])


HELP = """/-- A helper. -/
theorem helper (n : ℕ) : n + 0 = n := by
  simp"""
MOD1 = f"import Mathlib.Data.Nat.Defs\n\nnamespace Foo\n\n{HELP}\n\ntheorem one (n : ℕ) : n + 0 + 0 = n := by\n  simp [helper]\n\nend Foo\n"
MOD2 = f"import Mathlib.Data.Nat.Defs\nimport Mathlib.Data.Int.Defs\n\nnamespace Foo\n\n{HELP}\n\ntheorem two (n : ℕ) : 0 + n = n := by\n  simp\n\nend Foo\n"


class Hoist(unittest.TestCase):
    def test_plan_finds_identical_copies_only(self):
        plan = D.hoist_plan({"A": MOD1, "B": MOD2})
        self.assertEqual([(p["name"], p["modules"]) for p in plan], [("Foo.helper", ["A", "B"])])
        different = MOD2.replace("  simp\n\ntheorem two", "  omega\n\ntheorem two")
        self.assertEqual(D.hoist_plan({"A": MOD1, "B": different}), [])
        self.assertEqual(D.hoist_plan({"A": MOD1}), [])

    def test_unique_declarations_are_not_helpers(self):
        self.assertNotIn("Foo.one", [p["name"] for p in D.hoist_plan({"A": MOD1, "B": MOD2})])

    def test_apply_moves_the_helper_and_adds_the_import(self):
        plan = D.hoist_plan({"A": MOD1, "B": MOD2})
        out = D.apply_hoist({"A": MOD1, "B": MOD2}, "Common", plan)
        self.assertNotIn("theorem helper", out["A"])
        self.assertNotIn("theorem helper", out["B"])
        self.assertIn("theorem one", out["A"])
        self.assertIn("import Common", out["A"])
        self.assertIn("import Common", out["B"])
        self.assertTrue(out["Common"].startswith("import Mathlib.Data.Int.Defs\nimport Mathlib.Data.Nat.Defs\n"))
        self.assertIn("namespace Foo", out["Common"])
        self.assertIn("/-- A helper. -/\ntheorem helper", out["Common"])
        self.assertEqual(out["Common"].count("theorem helper"), 1)

    def test_findings(self):
        fs = D.hoist_findings({"A": MOD1, "B": MOD2})
        self.assertEqual([(f["rule"], f["severity"], f["copies"]) for f in fs], [("copied_helper", "warn", 2)])

    def test_fingerprint_ignores_layout(self):
        self.assertEqual(D.fingerprint(MOD1), D.fingerprint(MOD1.replace("  simp\n\ntheorem one", "  simp   \n\n\ntheorem one")))
        self.assertNotEqual(D.fingerprint(MOD1), D.fingerprint(MOD2))


if __name__ == "__main__":
    unittest.main()
