import unittest

from vendor.juridicator_evidence import validate
from praiser.preregistration import check_preregistration, commit_statement, normalize
from tests.helpers import CASE, HEAD, NOW, OLDER, PRAISER

STATEMENT = "theorem foo (n : Nat) :\n    n + 0 = n := by\n  sorry"


_DEFAULT = object()


def check(commitment=_DEFAULT, statement=STATEMENT, nonce="n-123", before=OLDER, head=HEAD, anc=True, case=CASE):
    commitment = commit_statement(STATEMENT, "n-123") if commitment is _DEFAULT else commitment
    return check_preregistration(commitment, statement, nonce, case, PRAISER, NOW, before, head, anc)


class Commitment(unittest.TestCase):
    def test_shape_and_determinism(self):
        c = commit_statement(STATEMENT, "n")
        self.assertRegex(c, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(c, commit_statement(STATEMENT, "n"))

    def test_whitespace_is_collapsed_and_nothing_else(self):
        base = commit_statement("theorem foo : 1 = 1", "n")
        self.assertEqual(base, commit_statement("  theorem   foo\n:\t1 = 1  ", "n"))
        for changed in ("Theorem foo : 1 = 1", "theorem foo : 1 = 2", "theorem foo : 1 = 1 -- c", "theorem foo : 1 = 1 ", "theorem foo :1 = 1"):
            if normalize(changed) == normalize("theorem foo : 1 = 1"):
                continue
            self.assertNotEqual(base, commit_statement(changed, "n"), changed)

    def test_the_nonce_matters(self):
        self.assertNotEqual(commit_statement(STATEMENT, "a"), commit_statement(STATEMENT, "b"))

    def test_empty_inputs_refused(self):
        for args in (("", "n"), ("   ", "n"), (STATEMENT, ""), (None, "n")):
            with self.assertRaises(ValueError):
                commit_statement(*args)


class Check(unittest.TestCase):
    def test_pass(self):
        ev = check()
        self.assertEqual(validate(ev), [])
        self.assertEqual((ev["kind"], ev["outcome"], ev["verifiability"]), ("mechanical.statement_preregistered", "pass", "mechanical"))
        self.assertIn("merge-base --is-ancestor", ev["reproduce"]["command"])

    def test_whitespace_reformatting_still_passes(self):
        self.assertEqual(check(statement="theorem foo (n : Nat) : n + 0 = n := by sorry")["outcome"], "pass")

    def test_an_edited_statement_fails(self):
        ev = check(statement=STATEMENT.replace("n + 0", "n + 1"))
        self.assertEqual(ev["outcome"], "fail")
        self.assertIn("do not reproduce the commitment", ev["claim"])

    def test_wrong_nonce_fails(self):
        self.assertEqual(check(nonce="other")["outcome"], "fail")

    def test_a_non_ancestor_fails_even_when_the_hash_matches(self):
        ev = check(anc=False)
        self.assertEqual(ev["outcome"], "fail")
        self.assertIn("not an ancestor", ev["claim"])

    def test_same_commit_is_not_before(self):
        ev = check(before=HEAD, anc=True)
        self.assertEqual(ev["outcome"], "fail")
        self.assertIn("same commit", ev["claim"])

    def test_unknown_ancestry_is_inconclusive(self):
        self.assertEqual(check(anc=None)["outcome"], "inconclusive")

    def test_unknown_ancestry_with_a_bad_hash_still_fails(self):
        self.assertEqual(check(anc=None, statement="other")["outcome"], "fail")

    def test_head_must_be_the_cases_commit(self):
        ev = check(head=OLDER, before="c" * 40)
        self.assertEqual(ev["outcome"], "fail")
        self.assertIn("not this case's commit", ev["claim"])

    def test_a_malformed_commitment_fails(self):
        for bad in ("sha256:abc", "abc", "", None):
            self.assertEqual(check(commitment=bad)["outcome"], "fail")

    def test_bad_arguments_are_refused(self):
        for kw in ({"before": "short"}, {"head": "zz"}, {"anc": "yes"}, {"anc": 1}):
            with self.assertRaises(ValueError):
                check(**kw)


if __name__ == "__main__":
    unittest.main()
