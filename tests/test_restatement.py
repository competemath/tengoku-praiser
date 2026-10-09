import unittest

from vendor.juridicator_evidence import validate
from praiser.restatement import PROMPT, ToolsNotAllowed, blind_prompt, propose_restatement, restatement_evidence
from tests.helpers import CASE, H, NOW, PRAISER


def make(equivalent, **kw):
    args = dict(ai_model="model-y-2", ai_family="family-b", prompt_sha256=H, equivalent=equivalent,
                checker_command="lake exe equiv orig.lean second.lean", created=NOW)
    args.update(kw)
    return restatement_evidence(CASE, PRAISER, **args)


class Evidence(unittest.TestCase):
    def test_outcomes(self):
        self.assertEqual([make(v)["outcome"] for v in (True, False, None)], ["pass", "fail", "inconclusive"])

    def test_record_shape_and_ai_is_only_a_proposer(self):
        ev = make(True)
        self.assertEqual(validate(ev), [])
        self.assertEqual((ev["kind"], ev["verifiability"]), ("mechanical.restatement_match", "mechanical"))
        self.assertEqual(ev["ai"], {"used": True, "role": "proposer", "model": "model-y-2", "family": "family-b", "prompt_sha256": H})
        self.assertEqual(ev["details"]["compared_by"], "machine")

    def test_reproduce_command_is_the_checker_command(self):
        self.assertEqual(make(True)["reproduce"]["command"], "lake exe equiv orig.lean second.lean")

    def test_truthy_values_are_not_booleans(self):
        for bad in (1, 0, "yes", "True", [], {}):
            with self.assertRaises(ValueError):
                make(bad)

    def test_refuses_a_missing_command_or_bad_hash(self):
        for kw in ({"checker_command": ""}, {"checker_command": "   "}, {"prompt_sha256": "abc"}, {"original_statement_sha256": "x"}):
            with self.assertRaises(ValueError):
                make(True, **kw)

    def test_statement_hashes_are_recorded_when_given(self):
        ev = make(True, original_statement_sha256=H, second_statement_sha256="e" * 64)
        self.assertEqual(ev["details"]["second_statement_sha256"], "e" * 64)


class FakeBackend:
    model = "fake-model"
    family = "fake-family"
    tools = ()

    def __init__(self, reply="theorem t : 1 + 1 = 2 := by sorry"):
        self.reply, self.prompts = reply, []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return self.reply


class Interface(unittest.TestCase):
    def test_returns_data_with_the_hash_of_the_blind_prompt(self):
        b = FakeBackend()
        out = propose_restatement(b, "Show that 1+1=2.")
        self.assertEqual(out["statement"], "theorem t : 1 + 1 = 2 := by sorry")
        self.assertEqual((out["model"], out["family"]), ("fake-model", "fake-family"))
        self.assertEqual(b.prompts, [blind_prompt("Show that 1+1=2.")])
        import hashlib
        self.assertEqual(out["prompt_sha256"], hashlib.sha256(b.prompts[0].encode()).hexdigest())

    def test_the_prompt_is_blind(self):
        self.assertNotIn("original", PROMPT.split("--- problem ---")[0].replace("existing formalization", ""))
        self.assertIn("must not ask", PROMPT)

    def test_a_backend_with_any_tool_is_refused_before_it_is_called(self):
        for tools in (("shell",), ["x"], None, "bash"):
            b = FakeBackend()
            b.tools = tools
            with self.assertRaises(ToolsNotAllowed):
                propose_restatement(b, "problem")
            self.assertEqual(b.prompts, [])

    def test_a_backend_that_does_not_say_is_refused(self):
        class Silent:
            model, family = "m", "f"

            def complete(self, prompt):
                raise AssertionError("must not be called")

        with self.assertRaises(ToolsNotAllowed):
            propose_restatement(Silent(), "problem")

    def test_output_is_cleaned_and_bounded(self):
        out = propose_restatement(FakeBackend("theorem t\x00 : True := by\x1b sorry\n"), "p")
        self.assertNotIn("\x00", out["statement"])
        self.assertNotIn("\x1b", out["statement"])
        for bad in ("", "   ", "x" * 30_000, 5):
            with self.assertRaises(ValueError):
                propose_restatement(FakeBackend(bad), "p")

    def test_empty_problem_refused(self):
        with self.assertRaises(ValueError):
            propose_restatement(FakeBackend(), "  ")


if __name__ == "__main__":
    unittest.main()
