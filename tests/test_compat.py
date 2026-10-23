import unittest

from praiser import compat as C
from praiser.oracle import Outcome

SRC = "import Mathlib.Data.Nat.Defs\n\ntheorem t (a : ℕ) : a + 0 = a := by\n  simp\n"


def tool(ok=True, output="", check="Foo.t : ∀ (a : ℕ), a + 0 = a"):
    """A fake toolchain; a probed module (one with `#check`) answers with the declaration's printed type."""
    def run(text):
        if "#check @" in text:
            return Outcome(ok, f"Foo.lean:9:0: info: {check}\n")
        return Outcome(ok, output)
    return run


class Compat(unittest.TestCase):
    def test_clean_on_both_toolchains(self):
        self.assertEqual(C.forward_compat(SRC, tool(), tool()), [])

    def test_primary_must_compile(self):
        fs = C.forward_compat(SRC, tool(ok=False), tool())
        self.assertEqual([(f["severity"], f["name"]) for f in fs], [("inconclusive", "primary")])
        self.assertEqual(C.forward_compat(SRC, lambda t: Outcome(None), tool())[0]["severity"], "inconclusive")

    def test_no_answer_from_the_forward_toolchain_is_not_a_pass(self):
        fs = C.forward_compat(SRC, tool(), lambda t: Outcome(None))
        self.assertEqual([f["severity"] for f in fs], ["inconclusive"])

    def test_a_deprecated_name_on_the_primary_is_a_fail_with_the_replacement(self):
        out = "Foo.lean:4:2: warning: `Nat.foo` has been deprecated, use `Nat.bar` instead\n"
        fs = C.forward_compat(SRC, tool(output=out), tool())
        self.assertEqual([(f["rule"], f["severity"], f["replacement"]) for f in fs], [("deprecated", "fail", "Nat.bar")])

    def test_a_name_deprecated_only_on_the_forward_toolchain_is_a_warning(self):
        out = "Foo.lean:4:2: warning: `Nat.foo` has been deprecated, use `Nat.bar` instead\n"
        fs = C.forward_compat(SRC, tool(), tool(output=out))
        self.assertEqual([(f["rule"], f["severity"]) for f in fs], [("deprecated_soon", "warn")])

    def test_forward_errors_are_classified(self):
        out = ("Foo.lean:4:2: error: unknown identifier 'Nat.gone'\n"
               "Foo.lean:5:2: error: linarith failed to find a contradiction\n"
               "Foo.lean:6:2: error: failed to synthesize\n  Foo ℕ\n")
        fs = C.forward_compat(SRC, tool(), tool(ok=False, output=out))
        self.assertEqual([f["category"] for f in fs], ["removed", "tactic", "instance"])
        self.assertTrue(all(f["severity"] == "warn" and f["rule"] == "forward_break" for f in fs))

    def test_severity_is_a_parameter(self):
        out = "Foo.lean:4:2: error: unknown identifier 'x'\n"
        fs = C.forward_compat(SRC, tool(), tool(ok=False, output=out), severity="fail")
        self.assertEqual(fs[0]["severity"], "fail")

    def test_a_failure_without_a_message_is_still_reported(self):
        fs = C.forward_compat(SRC, tool(), tool(ok=False, output=""))
        self.assertEqual([f["rule"] for f in fs], ["forward_break"])

    def test_many_errors_are_capped_but_counted(self):
        out = "".join(f"Foo.lean:{i}:0: error: unknown identifier 'x{i}'\n" for i in range(1, 30))
        fs = C.forward_compat(SRC, tool(), tool(ok=False, output=out))
        self.assertEqual(len(fs), C.MAX_REPORTED + 1)
        self.assertIn("more errors", fs[-1]["detail"])

    def test_statement_drift(self):
        fs = C.forward_compat(SRC, tool(check="Foo.t : ∀ (a : ℕ), a + 0 = a"), tool(check="Foo.t : ∀ (a : ℕ), 0 + a = a"))
        self.assertEqual([(f["rule"], f["severity"], f["name"]) for f in fs], [("drift", "warn", "t")])

    def test_whitespace_is_not_drift(self):
        self.assertEqual(C.forward_compat(SRC, tool(check="Foo.t :\n  ∀ (a : ℕ), a + 0 = a"), tool(check="Foo.t : ∀ (a : ℕ),   a + 0 = a")), [])

    def test_an_unprintable_statement_is_inconclusive(self):
        def silent(text):
            return Outcome(True, "")

        fs = C.forward_compat(SRC, tool(), silent)
        self.assertEqual([f["rule"] for f in fs], ["drift"])
        self.assertEqual(fs[0]["severity"], "inconclusive")

    def test_classify_other(self):
        self.assertEqual(C.classify("something odd"), "other")


if __name__ == "__main__":
    unittest.main()
