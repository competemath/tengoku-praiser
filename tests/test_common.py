import unittest

from vendor.juridicator_evidence import MAX_CLAIM, MAX_COMMAND, canonical_json, validate
from praiser.common import (
    cap_command, case_ref, clip, fit_details, hash_map, kind_part, make, producer_ref, require_hex64, sha256_bytes,
)
from tests.helpers import CASE, HEAD, NOW, PRAISER


class Common(unittest.TestCase):
    def test_case_ref_keeps_only_repo_commit_and_class(self):
        self.assertEqual(case_ref(CASE), {"repo": CASE["repo"], "head_sha": HEAD, "class": "content"})

    def test_case_ref_refuses_malformed_cases(self):
        for bad in ("x", None, {}, dict(CASE, head_sha="zz"), dict(CASE, head_sha="A" * 40), dict(CASE, head_sha=HEAD[:-1]),
                    dict(CASE, repo=""), dict(CASE, **{"class": None})):
            with self.assertRaises(ValueError, msg=repr(bad)):
                case_ref(bad)

    def test_producer_ref(self):
        self.assertEqual(producer_ref(dict(PRAISER, extra="x")), PRAISER)
        for bad in (None, {}, {"role": "praiser"}, dict(PRAISER, identity="")):
            with self.assertRaises(ValueError):
                producer_ref(bad)

    def test_clip_removes_control_characters_and_cuts_with_an_ellipsis(self):
        self.assertEqual(clip("a\x00b\n c"), "a b c")
        long = clip("x" * 1000)
        self.assertEqual(len(long), MAX_CLAIM)
        self.assertTrue(long.endswith("..."))
        self.assertEqual(clip("abcdef", 5), "ab...")

    def test_hex_and_hash_maps(self):
        self.assertEqual(require_hex64("a" * 64, "x"), "a" * 64)
        for bad in ("A" * 64, "a" * 63, 5, None):
            with self.assertRaises(ValueError):
                require_hex64(bad, "x")
        self.assertEqual(hash_map({"p": "a" * 64}, "x"), {"p": "a" * 64})
        for bad in ([], {"": "a" * 64}, {"p": "z"}, {5: "a" * 64}, {"a\x00": "a" * 64}):
            with self.assertRaises(ValueError):
                hash_map(bad, "x")

    def test_cap_command_never_returns_empty_or_too_long(self):
        self.assertEqual(cap_command("a   b"), "a b")
        self.assertEqual(len(cap_command("x" * 5000)), MAX_COMMAND)

    def test_kind_part(self):
        self.assertEqual(kind_part("Unused-Names 2"), "unused_names_2")
        with self.assertRaises(ValueError):
            kind_part("---")

    def test_fit_details_drops_only_the_named_bulk_and_says_so(self):
        details = {"keep": "k", "bulk": ["x" * 200] * 60, "more": ["y" * 200] * 60}
        out = fit_details(details, ("bulk", "more"))
        self.assertLessEqual(len(canonical_json(out).encode()), 8192)
        self.assertEqual(out["keep"], "k")
        self.assertEqual(out["dropped_for_size"], ["bulk", "more"][: len(out["dropped_for_size"])])
        self.assertNotIn("dropped_for_size", fit_details({"a": 1}, ("a",)))
        self.assertEqual(fit_details({"a": 1}, ("a",)), {"a": 1})

    def test_make_returns_a_valid_record_or_raises(self):
        ev = make(case=case_ref(CASE), producer=PRAISER, kind="attested.x", claim="c", outcome="pass", verifiability="attested", created=NOW)
        self.assertEqual(validate(ev), [])
        with self.assertRaises(ValueError):
            make(case=case_ref(CASE), producer=PRAISER, kind="attested.x", claim="c", outcome="great", verifiability="attested", created=NOW)

    def test_sha256_bytes(self):
        self.assertEqual(sha256_bytes(b""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


if __name__ == "__main__":
    unittest.main()
