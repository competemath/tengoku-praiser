import unittest

from praiser.oracle import Bounded, Outcome, UNDECIDED, errors, messages

OUT = """Foo.lean:3:4: warning: unused variable `x`
note: this linter can be disabled with `set_option linter.unusedVariables false`
Foo.lean:9:0: error: unknown identifier 'y'
  more detail
Foo.lean:12:2: info: hello
"""


class Messages(unittest.TestCase):
    def test_parse(self):
        ms = messages(OUT)
        self.assertEqual([(m.severity, m.line, m.col) for m in ms], [("warning", 3, 4), ("error", 9, 0), ("info", 12, 2)])
        self.assertEqual(ms[0].linter, "linter.unusedVariables")
        self.assertIn("more detail", ms[1].text)
        self.assertIsNone(ms[1].linter)

    def test_errors(self):
        self.assertEqual(len(errors(OUT)), 1)
        self.assertEqual(messages("nothing here"), [])


class Wrapper(unittest.TestCase):
    def test_remembers_answers_and_counts_real_calls(self):
        seen = []

        def oracle(t):
            seen.append(t)
            return Outcome(True, "")

        b = Bounded(oracle, 5)
        b("a"); b("a"); b("b")
        self.assertEqual((b.calls, b.hits, len(seen)), (2, 1, 2))

    def test_stops_at_the_limit_with_an_undecided_answer(self):
        b = Bounded(lambda t: Outcome(True), 2)
        self.assertTrue(b("a").ok)
        self.assertTrue(b("b").ok)
        self.assertIsNone(b("c").ok)
        self.assertTrue(b.exhausted)
        self.assertTrue(b("a").ok, "an answer already given is still given")

    def test_a_raising_oracle_is_undecided_and_not_remembered(self):
        calls = []

        def oracle(t):
            calls.append(t)
            raise RuntimeError("boom")

        b = Bounded(oracle, 5)
        self.assertEqual(b("a"), UNDECIDED)
        self.assertEqual(b("a"), UNDECIDED)
        self.assertEqual(len(calls), 2, "asking again may work")

    def test_a_non_outcome_is_undecided(self):
        self.assertIsNone(Bounded(lambda t: True, 3)("a").ok)

    def test_bad_limit(self):
        for bad in (0, -1, True, "3"):
            with self.assertRaises(ValueError):
                Bounded(lambda t: Outcome(True), bad)


if __name__ == "__main__":
    unittest.main()
