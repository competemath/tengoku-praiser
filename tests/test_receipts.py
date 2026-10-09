import unittest

from vendor.juridicator_evidence import validate
from praiser.receipts import compare_receipts, digest_env, digest_of, make_receipt, verify_receipt
from tests.helpers import CASE, H, H2, NOW, PRAISER

CMD = "lake build Tengoku"


def receipt(**over):
    kw = dict(command=CMD, env_digest=H, stdout_digest=H2, exit_code=0, runner="runner-1")
    kw.update(over)
    return make_receipt(**kw)


def cmp(a, b):
    return compare_receipts(a, b, CASE, PRAISER, NOW)


class Receipts(unittest.TestCase):
    def test_a_receipt_has_a_self_hash_that_verifies(self):
        r = receipt()
        self.assertTrue(verify_receipt(r))
        self.assertRegex(r["receipt_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(r, receipt())

    def test_any_field_change_changes_the_hash(self):
        base = receipt()["receipt_sha256"]
        for over in ({"command": "x"}, {"env_digest": "1" * 64}, {"stdout_digest": "1" * 64}, {"exit_code": 1}, {"runner": "r2"}):
            self.assertNotEqual(base, receipt(**over)["receipt_sha256"], over)

    def test_a_tampered_receipt_does_not_verify(self):
        r = receipt()
        self.assertFalse(verify_receipt(dict(r, exit_code=1)))
        self.assertFalse(verify_receipt({}))
        self.assertFalse(verify_receipt("x"))

    def test_bad_receipt_inputs_refused(self):
        for over in ({"command": ""}, {"env_digest": "x"}, {"stdout_digest": "x"}, {"exit_code": "0"}, {"exit_code": True}):
            with self.assertRaises(ValueError):
                receipt(**over)

    def test_digest_helpers(self):
        self.assertEqual(digest_of(b"x"), digest_of(b"x"))
        self.assertNotEqual(digest_of(b"x"), digest_of(b"y"))
        self.assertEqual(digest_env({"a": 1, "b": 2}), digest_env({"b": 2, "a": 1}))


class Compare(unittest.TestCase):
    def test_two_independent_runners_that_agree_pass(self):
        ev = cmp(receipt(runner="r1"), receipt(runner="r2"))
        self.assertEqual(validate(ev), [])
        self.assertEqual((ev["kind"], ev["verifiability"], ev["outcome"]), ("reproducible.rebuild_match", "reproducible", "pass"))
        self.assertIn(CMD, ev["reproduce"]["command"])

    def test_each_differing_field_fails_and_is_named(self):
        for field, over in (("command", {"command": "lake build"}), ("env_digest", {"env_digest": "1" * 64}),
                            ("stdout_digest", {"stdout_digest": "1" * 64}), ("exit_code", {"exit_code": 1})):
            ev = cmp(receipt(runner="r1"), receipt(runner="r2", **over))
            self.assertEqual(ev["outcome"], "fail", field)
            self.assertIn(field, ev["claim"])
            self.assertEqual(ev["details"]["differing"], [field])

    def test_several_differences_are_all_named(self):
        ev = cmp(receipt(runner="r1"), receipt(runner="r2", exit_code=1, stdout_digest="1" * 64))
        self.assertIn("stdout_digest", ev["claim"])
        self.assertIn("exit_code", ev["claim"])

    def test_same_runner_twice_is_inconclusive(self):
        ev = cmp(receipt(runner="r1"), receipt(runner="r1"))
        self.assertEqual(ev["outcome"], "inconclusive")
        self.assertIn("same runner twice proves little", ev["claim"])

    def test_a_missing_runner_cannot_prove_independence(self):
        self.assertEqual(cmp(receipt(runner=None), receipt(runner="r2"))["outcome"], "inconclusive")
        self.assertEqual(cmp(receipt(runner=None), receipt(runner=None))["outcome"], "inconclusive")

    def test_a_difference_is_a_fail_even_from_one_runner(self):
        self.assertEqual(cmp(receipt(runner="r1"), receipt(runner="r1", exit_code=2))["outcome"], "fail")

    def test_a_tampered_receipt_is_refused(self):
        with self.assertRaises(ValueError):
            cmp(receipt(runner="r1"), dict(receipt(runner="r2"), stdout_digest="1" * 64))


if __name__ == "__main__":
    unittest.main()
