import unittest

from praiser import stylelint as S
from praiser.oracle import Outcome

CLEAN = """import Mathlib.Algebra.Group.Defs
import Mathlib.Data.Nat.Defs

/-! # A clean file -/

/-- Adding zero. -/
theorem add_zero' (a : ℕ) : a + 0 = a := by
  simp
"""


def rules(text):
    return [f["rule"] for f in S.style_findings(text)]


class TextRules(unittest.TestCase):
    def test_a_clean_file_has_no_finding(self):
        self.assertEqual(S.style_findings(CLEAN), [])

    def test_whitespace(self):
        self.assertIn("trailing_whitespace", rules("theorem t : True := trivial \n"))
        self.assertIn("tab", rules("theorem t : True :=\n\ttrivial\n"))
        self.assertIn("crlf", rules("theorem t : True := trivial\r\n"))

    def test_final_newline(self):
        self.assertIn("final_newline", rules("theorem t : True := trivial"))
        self.assertIn("final_newline", rules("theorem t : True := trivial\n\n"))
        self.assertNotIn("final_newline", rules("theorem t : True := trivial\n"))
        self.assertNotIn("final_newline", rules(""))

    def test_line_length_excludes_urls(self):
        long = "-- " + "x" * 120 + "\n"
        self.assertIn("line_length", rules(long))
        self.assertNotIn("line_length", rules("-- see http://example.com/" + "x" * 120 + "\n"))
        self.assertNotIn("line_length", rules("-- " + "x" * 97 + "\n"))

    def test_isolated_by_and_dot_and_semicolon(self):
        self.assertIn("isolated_by", rules("theorem t : True :=\n  by\n  trivial\n"))
        self.assertIn("isolated_dot", rules("theorem t : True ∧ True := by\n  constructor\n  ·\n    trivial\n"))
        self.assertIn("semicolon_eol", rules("theorem t : True := by\n  skip;\n  trivial\n"))
        self.assertNotIn("isolated_by", rules("theorem t : True := by\n  trivial\n"))

    def test_dollar_lambda_and_fun_arrow(self):
        self.assertIn("dollar", rules("example : True := f $ x\n"))
        self.assertIn("lambda", rules("example := λ x ↦ x\n"))
        self.assertIn("fun_arrow", rules("example := fun x => x\n"))
        self.assertNotIn("fun_arrow", rules("example := fun x ↦ x\n"))
        self.assertNotIn("fun_arrow", rules("example := fun\n  | 0 => 1\n  | _ => 2\n"), "match arms keep =>")

    def test_ascii_symbols(self):
        for text in ("example (a b : ℕ) (h : a <= b) : a <= b := h\n", "example (p q : Prop) : p -> q := fun h => h\n"):
            self.assertIn("ascii_symbol", rules(text))
        self.assertNotIn("ascii_symbol", rules("example := a <;> b\nexample := f <$> g\nexample := x |> f\n"))

    def test_heartbeats(self):
        self.assertIn("heartbeats_unbounded", rules("set_option maxHeartbeats 0 in\ntheorem t : True := trivial\n"))
        self.assertIn("heartbeats_raised", rules("set_option maxHeartbeats 400000 in\ntheorem t : True := trivial\n"))
        self.assertNotIn("heartbeats_raised", rules("-- the search is slow\nset_option maxHeartbeats 400000 in\ntheorem t : True := trivial\n"))
        self.assertNotIn("heartbeats_raised", rules("set_option maxHeartbeats 400000 in -- slow search\ntheorem t : True := trivial\n"))
        self.assertNotIn("heartbeats_raised", rules("set_option maxHeartbeats 200000 in\ntheorem t : True := trivial\n"))

    def test_auto_implicit_and_linters_off(self):
        self.assertIn("auto_implicit", rules("set_option autoImplicit true\n"))
        self.assertIn("linter_disabled", rules("set_option linter.unusedVariables false\n"))
        self.assertNotIn("linter_disabled", rules("-- the name is used by the macro\nset_option linter.unusedVariables false\n"))

    def test_debug_commands(self):
        for c in ("#eval 1", "#check Nat", "#print Nat", "#reduce 1", "#lint"):
            self.assertIn("debug_command", rules(f"{c}\n"), c)
        self.assertNotIn("debug_command", rules("#guard 1 = 1\n"))
        self.assertNotIn("debug_command", rules("-- #eval 1\n"))

    def test_sorry_native_decide_and_unverified_code(self):
        self.assertIn("sorry", rules("theorem t : True := sorry\n"))
        self.assertIn("sorry", rules("theorem t : True := by admit\n"))
        self.assertNotIn("sorry", rules("-- sorry\ntheorem t : True := trivial\n/-- sorry -/\n"))
        self.assertNotIn("sorry", rules("theorem sorry_free : True := trivial\n"))
        self.assertIn("native_decide", rules("theorem t : 2 + 2 = 4 := by native_decide\n"))
        self.assertIn("unverified_code", rules("axiom a : False\n"))
        self.assertIn("unverified_code", rules("@[implemented_by foo] def f := 1\n"))
        self.assertNotIn("unverified_code", rules("theorem axiom_free : True := trivial\n"))

    def test_imports(self):
        self.assertIn("import_after_command", rules("def x := 1\nimport Foo\n"))
        self.assertIn("duplicate_import", rules("import Foo\nimport Foo\n"))
        self.assertIn("import_order", rules("import B\nimport A\n"))
        self.assertNotIn("import_order", rules("import A\nimport B\n"))
        self.assertIn("import_all", rules("import Mathlib\n"))
        self.assertNotIn("import_all", rules("import Mathlib.Data.Nat.Defs\n"))

    def test_open_classical_deprecated_and_todo(self):
        self.assertIn("open_classical", rules("open Classical\n"))
        self.assertNotIn("open_classical", rules("open scoped Classical\n"))
        self.assertIn("deprecated_without_date", rules("@[deprecated foo]\ntheorem t : True := trivial\n"))
        self.assertNotIn("deprecated_without_date", rules('@[deprecated foo (since := "2025-01-01")]\ntheorem t : True := trivial\n'))
        self.assertIn("todo_marker", rules("-- TODO: prove it\n"))
        self.assertNotIn("todo_marker", rules("def todo_list := 1\n"))

    def test_long_proof(self):
        body = "\n".join(f"  have h{i} : True := trivial" for i in range(60))
        self.assertIn("long_proof", rules("theorem t : True := by\n" + body + "\n  trivial\n"))

    def test_findings_are_ordered_and_carry_the_module(self):
        fs = S.style_findings("def a := 1 \ndef b := 2\t\n", module="Foo")
        self.assertEqual([f["line"] for f in fs], sorted(f["line"] for f in fs))
        self.assertTrue(all(f["module"] == "Foo" and f["check"] == "style" for f in fs))

    def test_every_rule_in_the_table_has_a_known_severity_and_is_used(self):
        for r in S.RULES.values():
            self.assertIn(r.severity, ("fail", "warn"))
        with open(S.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for rid in S.RULES:
            self.assertIn(f'"{rid}"', src.replace(f'Rule("{rid}"', "", 1), rid)


class ModuleSystem(unittest.TestCase):
    SRC = "module\n\npublic import A.B\nimport C.D\npublic import E.F\n\n/-! # T -/\n\ntheorem t : True := trivial\n"

    def test_public_imports_are_imports(self):
        self.assertNotIn("import_after_command", rules(self.SRC))
        self.assertIn("import_after_command", rules(self.SRC + "import Z\n"))

    def test_options_and_lint_go_after_the_last_public_import(self):
        out = S.options_script(self.SRC, ("linter.a",))
        self.assertLess(out.index("public import E.F"), out.index("set_option linter.a true"))
        self.assertLess(out.index("set_option linter.a true"), out.index("/-! # T -/"))

    def test_after_the_module_header_when_there_are_no_imports(self):
        out = S.options_script("module\n\ntheorem t : True := trivial\n", ("linter.a",))
        self.assertTrue(out.startswith("module\nset_option linter.a true\n"))


class Compile(unittest.TestCase):
    def test_options_go_after_the_imports(self):
        out = S.options_script(CLEAN, ("linter.a", "linter.b"))
        self.assertLess(out.index("import Mathlib.Data.Nat.Defs"), out.index("set_option linter.a true"))
        self.assertLess(out.index("set_option linter.b true"), out.index("/-! # A clean file -/"))

    def test_a_file_without_imports_gets_them_first(self):
        self.assertTrue(S.options_script("def x := 1\n", ("linter.a",)).startswith("set_option linter.a true\n"))

    def test_warnings_become_findings_named_after_their_linter(self):
        out = ("Foo.lean:7:2: warning: unused variable `h`\nnote: this linter can be disabled with `set_option linter.unusedVariables false`\n"
               "Foo.lean:9:0: warning: something else\n")
        fs = S.compile_findings(CLEAN, lambda t: Outcome(True, out), module="Foo")
        self.assertEqual([(f["name"], f["severity"], f["line"]) for f in fs],
                         [("linter.unusedVariables", "fail", 7), ("compiler_warning", "warn", 9)])

    def test_unknown_option_is_inconclusive(self):
        fs = S.compile_findings(CLEAN, lambda t: Outcome(False, "Foo.lean:3:11: error: unknown option 'linter.style.nope'\n"))
        self.assertEqual([f["severity"] for f in fs], ["inconclusive"])
        self.assertIn("unknown on this toolchain", fs[0]["detail"])

    def test_an_error_or_no_answer_is_inconclusive_not_clean(self):
        self.assertEqual(S.compile_findings(CLEAN, lambda t: Outcome(False, "F.lean:1:0: error: boom\n"))[0]["severity"], "inconclusive")
        self.assertEqual(S.compile_findings(CLEAN, lambda t: Outcome(None, ""))[0]["severity"], "inconclusive")

    def test_clean_compile_is_clean(self):
        self.assertEqual(S.compile_findings(CLEAN, lambda t: Outcome(True, "")), [])


LINT_BAD = """-- Found 2 errors in 10 declarations (plus 3 automatically generated ones) in the current file with 15 linters

/- The `docBlame` linter reports:
DEFINITIONS ARE MISSING DOCUMENTATION STRINGS: -/
#check @Foo.helper /- def missing documentation string -/

/- The `unusedArguments` linter reports:
UNUSED ARGUMENTS. -/
#check @Foo.t /- unused arguments: [2] -/
"""


class EnvLint(unittest.TestCase):
    def test_script_has_the_import_and_ends_with_lint(self):
        s = S.lint_script(CLEAN)
        self.assertIn("import Batteries.Tactic.Lint", s)
        self.assertTrue(s.rstrip().endswith("#lint"))
        self.assertTrue(S.lint_script(CLEAN, only=("simpNF", "docBlame")).rstrip().endswith("#lint only simpNF docBlame"))

    def test_passed(self):
        self.assertEqual(S.parse_lint_output("-- All linting checks passed!\n"), [])

    def test_errors_are_read_one_per_declaration(self):
        fs = S.parse_lint_output(LINT_BAD, module="Foo")
        self.assertEqual([(f["name"], f["linter"], f["severity"]) for f in fs],
                         [("Foo.helper", "docBlame", "fail"), ("Foo.t", "unusedArguments", "fail")])
        self.assertIn("missing documentation", fs[0]["detail"])

    def test_a_count_that_does_not_match_is_inconclusive(self):
        fs = S.parse_lint_output(LINT_BAD.replace("Found 2 errors", "Found 3 errors"))
        self.assertEqual(fs[-1]["severity"], "inconclusive")
        self.assertEqual(sum(f["severity"] == "fail" for f in fs), 2, "what was read is still reported")

    def test_no_summary_is_inconclusive_never_a_pass(self):
        self.assertEqual(S.parse_lint_output("")[0]["severity"], "inconclusive")
        self.assertEqual(S.parse_lint_output("something unexpected\n")[0]["severity"], "inconclusive")

    def test_a_module_that_does_not_compile_is_inconclusive(self):
        fs = S.parse_lint_output("Foo.lean:3:0: error: unknown constant\n")
        self.assertEqual(fs[0]["severity"], "inconclusive")

    def test_zero_errors_with_a_summary_is_clean(self):
        self.assertEqual(S.parse_lint_output("-- Found 0 errors in 10 declarations in the current file with 15 linters\n"), [])

    def test_run_lint_passes_the_script_to_the_oracle(self):
        seen = []

        def oracle(t):
            seen.append(t)
            return Outcome(True, "-- All linting checks passed!\n")

        self.assertEqual(S.run_lint(CLEAN, oracle), [])
        self.assertTrue(seen[0].rstrip().endswith("#lint"))
        self.assertEqual(S.run_lint(CLEAN, lambda t: Outcome(None))[0]["severity"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
