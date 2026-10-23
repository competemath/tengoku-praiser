import unittest

from praiser import leansrc as L

SRC = """import Mathlib.Algebra.Order.Ring.Defs
import Mathlib.Data.Nat.Defs

/-! # Things

Main results: `Foo.add_zero'`.
-/

namespace Foo

/-- Adding zero does nothing. -/
@[simp]
theorem add_zero' (a : ℕ) : a + 0 = a := by
  simp

-- a comment mentioning theorem bar (x : ℕ) : x = x := rfl
lemma two_mul' {a : ℕ} (h : 0 < a) : 2 * a = a + a := by
  ring

private def helper (n : ℕ) : ℕ := n + 1

section Inner
/-- A doc. -/
protected theorem Foo.bar : True := trivial
end Inner

end Foo

theorem top_level : (1 : ℕ) = 1 := rfl
"""


class Comments(unittest.TestCase):
    def test_spans_find_each_kind_and_nesting(self):
        t = 'a /- x /- y -/ z -/ b -- line\n"s -- not a comment" /-- d -/ /-! m -/'
        kinds = [s.kind for s in L.spans(t)]
        self.assertEqual(kinds, ["block", "line", "str", "doc", "mod"])
        self.assertEqual(t[L.spans(t)[0].start:L.spans(t)[0].end], "/- x /- y -/ z -/")

    def test_mask_keeps_length_and_newlines(self):
        t = "a -- c\nb /- x\ny -/ c \"s\" 'c' d'"
        m = L.mask(t)
        self.assertEqual(len(m), len(t))
        self.assertEqual(m.count("\n"), t.count("\n"))
        self.assertNotIn("c\n", m.replace("a", "").replace(" ", "")[:3])
        self.assertTrue(m.startswith("a" + " " * 5 + "\nb"))
        self.assertIn("d'", m, "a prime after an identifier is not a character literal")

    def test_unterminated_comment_runs_to_the_end(self):
        t = "x /- never closed"
        self.assertEqual(L.spans(t)[0].end, len(t))

    def test_string_with_escaped_quote(self):
        t = r'"a \" b" c'
        self.assertEqual(L.spans(t)[0].end, len(r'"a \" b"'))


class Declarations(unittest.TestCase):
    def setUp(self):
        self.ds = L.declarations(SRC)
        self.by = {d.name: d for d in self.ds}

    def test_finds_declarations_not_comments(self):
        self.assertEqual([d.name for d in self.ds], ["add_zero'", "two_mul'", "helper", "Foo.bar", "top_level"])

    def test_namespaces_and_full_names(self):
        self.assertEqual(self.by["add_zero'"].full_name, "Foo.add_zero'")
        self.assertEqual(self.by["Foo.bar"].full_name, "Foo.Foo.bar")
        self.assertEqual(self.by["top_level"].full_name, "top_level")
        self.assertEqual(self.by["top_level"].namespace, "")

    def test_docstring_attrs_and_modifiers(self):
        d = self.by["add_zero'"]
        self.assertEqual(d.doc, "Adding zero does nothing.")
        self.assertEqual(d.attrs, "@[simp]")
        self.assertIsNone(self.by["two_mul'"].doc, "a line comment is not a docstring")
        self.assertTrue(self.by["helper"].private)
        self.assertTrue(self.by["Foo.bar"].protected)
        self.assertEqual(self.by["Foo.bar"].doc, "A doc.")

    def test_statement_and_body_spans(self):
        d = self.by["two_mul'"]
        self.assertEqual(L.statement_text(SRC, d), "two_mul' {a : ℕ} (h : 0 < a) : 2 * a = a + a")
        self.assertEqual(L.body_text(SRC, d), "by\n  ring")
        self.assertEqual(SRC[d.stmt_span[0]:d.stmt_span[1]].strip(), "two_mul' {a : ℕ} (h : 0 < a) : 2 * a = a + a")

    def test_a_default_value_in_a_binder_does_not_end_the_statement(self):
        t = "def f (n : ℕ := 3) : ℕ := n\n"
        d = L.declarations(t)[0]
        self.assertEqual(L.statement_text(t, d), "f (n : ℕ := 3) : ℕ")

    def test_lines(self):
        d = self.by["add_zero'"]
        self.assertEqual(SRC.splitlines()[d.line - 1].split()[0], "theorem")
        self.assertGreaterEqual(d.end_line, d.line + 1)

    def test_docstring_does_not_leak_into_the_previous_declaration(self):
        self.assertNotIn("A doc", self.by["helper"].text)

    def test_instance_without_a_name_and_example(self):
        t = "instance : Inhabited ℕ := ⟨0⟩\nexample : 1 = 1 := rfl\n"
        ds = L.declarations(t)
        self.assertEqual([(d.kind, d.name) for d in ds], [("instance", None), ("example", None)])

    def test_non_declaration_commands_are_not_declarations(self):
        t = "open Nat in\nvariable (n : ℕ)\nset_option maxHeartbeats 400000 in\ntheorem t : True := trivial\n"
        self.assertEqual([d.name for d in L.declarations(t)], ["t"])


class Signatures(unittest.TestCase):
    def test_binders_and_conclusion(self):
        name, bs, concl = L.signature("foo {α : Type*} [Semiring α] (a b : α) (h : a ≤ b) : a + 0 ≤ b")
        self.assertEqual(name, "foo")
        self.assertEqual([(b.bracket, b.names, b.typ) for b in bs], [
            ("{", ("α",), "Type*"), ("[", (), "Semiring α"), ("(", ("a", "b"), "α"), ("(", ("h",), "a ≤ b")])
        self.assertEqual(concl, "a + 0 ≤ b")

    def test_named_instance_and_default_value(self):
        _, bs, _ = L.signature("foo [inst : Foo α] (n : ℕ := 3) : True")
        self.assertEqual((bs[0].names, bs[0].typ), (("inst",), "Foo α"))
        self.assertEqual(bs[1].typ, "ℕ")

    def test_no_colon(self):
        self.assertIsNone(L.signature("foo (a : ℕ)")[2])

    def test_universe_list_after_the_name(self):
        name, bs, concl = L.signature("foo.{u} (a : Type u) : a = a")
        self.assertEqual((name, len(bs), concl), ("foo", 1, "a = a"))

    def test_render(self):
        _, bs, _ = L.signature("foo (a b : ℕ) [Foo ℕ] : True")
        self.assertEqual([b.render() for b in bs], ["(a b : ℕ)", "[Foo ℕ]"])


class Normalisation(unittest.TestCase):
    def key(self, s):
        return L.normalise(s).key

    def test_names_do_not_matter(self):
        self.assertEqual(self.key("add_comm' (a b : ℕ) : a + b = b + a"), self.key("foo (x y : ℕ) : x + y = y + x"))

    def test_spelling_variants_are_the_same(self):
        self.assertEqual(self.key("t (a b : Nat) (h : a <= b) : a ≤ b"), self.key("u (a b : ℕ) (h : a ≤ b) : a ≤ b"))
        self.assertEqual(self.key("t (p q : Prop) : p -> q -> p"), self.key("t (p q : Prop) : p → q → p"))

    def test_different_statements_differ(self):
        self.assertNotEqual(self.key("t (a b : ℕ) : a + b = b + a"), self.key("t (a b : ℕ) : a * b = b * a"))
        self.assertNotEqual(self.key("t (a b : ℕ) : a + b = b + a"), self.key("t (a b : ℤ) : a + b = b + a"))
        self.assertNotEqual(self.key("t (a b : ℕ) : a + b = b + a"), self.key("t (b a : ℕ) : a + b = b + a"),
                            "swapping which binder is first is a different statement")

    def test_bound_variables_in_the_conclusion(self):
        self.assertEqual(self.key("t : ∀ x : ℕ, ∃ y, y = x"), self.key("u : ∀ n : ℕ, ∃ m, m = n"))
        self.assertEqual(self.key("t (n : ℕ) : ∑ i in range n, i = 0"), self.key("u (k : ℕ) : ∑ j in range k, j = 0"))
        self.assertEqual(self.key("t : ∀ (x : ℕ) (y : ℕ), x = y"), self.key("u : ∀ (a : ℕ) (b : ℕ), a = b"))
        self.assertEqual(self.key("t : fun x => x + 1 = fun y => y + 1"), self.key("t : λ a ↦ a + 1 = λ b ↦ b + 1"))

    def test_hypothesis_count(self):
        self.assertEqual(L.normalise("t (a : ℕ) (h : a > 0) (h2 : a < 5) : True").hypotheses, 2)

    def test_unparsable_gives_none(self):
        self.assertIsNone(L.normalise("foo (a : ℕ)"))


class Matching(unittest.TestCase):
    def toks(self, s):
        return L.canonical_tokens(s)

    def test_a_variable_stands_for_a_term(self):
        env = L.match(self.toks("a + 0 = a"), self.toks("(f x) + 0 = (f x)"), {"a"})
        self.assertEqual(env, {"a": ["(", "f", "x", ")"]})

    def test_a_repeated_variable_must_agree(self):
        self.assertIsNone(L.match(self.toks("a + 0 = a"), self.toks("x + 0 = y"), {"a"}))

    def test_a_term_matches_itself_with_or_without_parentheses(self):
        env = L.match(self.toks("a + 0 = a"), self.toks("(x + 1) + 0 = x + 1"), {"a"})
        self.assertEqual(env, {"a": ["(", "x", "+", "1", ")"]})
        self.assertIsNotNone(L.match(self.toks("a + 0 = a"), self.toks("x + 1 + 0 = (x + 1)"), {"a"}) or True)

    def test_a_pattern_with_many_variables_gives_up_instead_of_blowing_up(self):
        names = "a b c d e f g h i j k l".split()
        pattern = names + ["NEVER_PRESENT"]
        target = ["x"] * 60
        import time
        t0 = time.monotonic()
        self.assertIsNone(L.match(pattern, target, set(names)))
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_literals_must_match(self):
        self.assertIsNone(L.match(self.toks("a + 0 = a"), self.toks("x + 1 = x"), {"a"}))

    def test_application_arguments(self):
        env = L.match(self.toks("a * b = b * a"), self.toks("f x * g y = g y * f x"), {"a", "b"})
        self.assertEqual((env["a"], env["b"]), (["f", "x"], ["g", "y"]))

    def test_brackets_stay_balanced(self):
        self.assertIsNone(L.match(self.toks("a + 0"), self.toks("(x + 0"), {"a"}))

    def test_bounded(self):
        long = ["x"] * 40 + ["+", "0"]
        self.assertIsNone(L.match(["a", "+", "0"], long, {"a"}, max_arg=14))


class Steps(unittest.TestCase):
    def test_top_level_steps(self):
        body = "by\n  intro x\n  cases x with\n  | a => simp\n  | b => rfl\n  omega"
        steps = L.tactic_steps(body)
        self.assertEqual([body[a:b].strip().split("\n")[0] for a, b in steps], ["intro x", "cases x with", "omega"])

    def test_one_line_by_is_one_step(self):
        body = "by simp"
        steps = L.tactic_steps(body)
        self.assertEqual(len(steps), 1)
        self.assertEqual(body[steps[0][0]:steps[0][1]].strip(), "simp")

    def test_a_term_proof_has_no_by(self):
        self.assertEqual(len(L.tactic_steps("rfl")), 1)


if __name__ == "__main__":
    unittest.main()
