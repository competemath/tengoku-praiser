import unittest

from praiser import docscheck as D

GOOD = """import Mathlib.Data.Nat.Defs

/-!
# Adding zero

## Main results

* `Foo.add_zero'`: adding zero does nothing.
-/

namespace Foo

/-- The sum of a number with itself. -/
def double (n : ℕ) : ℕ := n + n

/-- Adding zero does nothing, see also `Foo.double`. -/
theorem add_zero' (a b c : ℕ) (h : a = b) : a + 0 + b + c = a + b + c := by omega

end Foo
"""


def rules(src, **kw):
    return sorted({f["rule"] for f in D.check_module(src, **kw)})


class Docs(unittest.TestCase):
    def test_good_file_is_clean(self):
        self.assertEqual(D.check_module(GOOD), [])

    def test_missing_module_doc(self):
        src = GOOD[:GOOD.index("/-!")] + GOOD[GOOD.index("namespace"):]
        fs = D.check_module(src)
        self.assertIn("module_doc", {f["rule"] for f in fs})
        self.assertEqual([f["severity"] for f in fs if f["rule"] == "module_doc"], ["fail"])

    def test_module_doc_shape(self):
        no_title = GOOD.replace("# Adding zero\n", "Adding zero\n")
        self.assertIn("module_doc", rules(no_title))
        no_sections = GOOD.replace("## Main results", "## Other")
        self.assertIn("module_doc", rules(no_sections))

    def test_def_needs_a_docstring(self):
        fs = D.check_module(GOOD.replace("/-- The sum of a number with itself. -/\n", ""))
        self.assertEqual([(f["rule"], f["severity"], f["name"]) for f in fs], [("def_doc", "fail", "Foo.double")])

    def test_private_definitions_are_exempt(self):
        self.assertEqual(rules(GOOD.replace("/-- The sum of a number with itself. -/\ndef double", "private def double")), [])

    def test_theorem_doc_only_when_non_trivial(self):
        no_doc = GOOD.replace("/-- Adding zero does nothing, see also `Foo.double`. -/\n", "")
        self.assertIn("theorem_doc", rules(no_doc))
        tiny = GOOD + "theorem t : True := trivial\n"
        self.assertNotIn("theorem_doc", rules(tiny))

    def test_doc_style(self):
        self.assertIn("doc_style", rules(GOOD.replace("The sum of a number with itself.", "double")))
        self.assertIn("doc_style", rules(GOOD.replace("The sum of a number with itself.", "a double number")))
        self.assertIn("doc_style", rules(GOOD.replace("/-- The sum of a number with itself. -/", "/-- Double. -/")), "too short")

    def test_dangling_references(self):
        bad = GOOD.replace("see also `Foo.double`", "see also `Foo.missing_lemma`")
        fs = [f for f in D.check_module(bad, known=frozenset()) if f["rule"] == "dangling_ref"]
        self.assertEqual(len(fs), 1)
        self.assertIn("Foo.missing_lemma", fs[0]["detail"])
        self.assertEqual([f for f in D.check_module(bad) if f["rule"] == "dangling_ref"], [], "not judged without the library's names")

    def test_library_names_resolve_when_given(self):
        src = GOOD.replace("see also `Foo.double`", "see also `Nat.add_comm`")
        self.assertNotIn("dangling_ref", rules(src), "without the library's names nothing is judged")
        self.assertIn("dangling_ref", rules(src, known={"Nat.succ_le"}))
        self.assertNotIn("dangling_ref", rules(src, known={"Nat.add_comm"}))

    def test_plain_words_in_backticks_are_not_judged(self):
        self.assertNotIn("dangling_ref", rules(GOOD.replace("does nothing", "does `nothing` for `a + b` and `simp`"), known=frozenset()))

    def test_header_pattern(self):
        self.assertIn("header", rules(GOOD, header_pattern=r"/-\nCopyright"))
        self.assertNotIn("header", rules("/-\nCopyright (c) 2026\n-/\n" + GOOD, header_pattern=r"/-\nCopyright"))

    def test_findings_are_ordered_and_tagged(self):
        fs = D.check_module(GOOD.replace("/-- The sum of a number with itself. -/\n", "").replace("# Adding zero", "Adding zero"), module="M")
        self.assertEqual([f["line"] for f in fs], sorted(f["line"] for f in fs))
        self.assertTrue(all(f["check"] == "docs" and f["module"] == "M" for f in fs))


if __name__ == "__main__":
    unittest.main()
