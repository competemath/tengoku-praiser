import unittest

from vendor.juridicator_evidence import validate
from praiser import review as R
from tests.helpers import CASE, NOW, TOOLING


def cmd(check):
    return f"python3 -m praiser review --checks {check}"


def one(findings, checks, **kw):
    out = R.from_findings(findings, CASE, TOOLING, checks, NOW, command_for=cmd, **kw)
    return {e["kind"]: e for e in out}


def f(check, severity, **kw):
    return R.finding(check, severity, kw.pop("detail", "d"), **kw)


class Findings(unittest.TestCase):
    def test_severity_is_checked(self):
        with self.assertRaises(ValueError):
            R.finding("style", "bad", "x")
        with self.assertRaises(ValueError):
            R.finding("", "fail", "x")

    def test_detail_is_clipped_to_one_line(self):
        x = R.finding("style", "warn", "a\nb\x00" + "c" * 400)
        self.assertNotIn("\n", x["detail"])
        self.assertLessEqual(len(x["detail"]), 300)


class Records(unittest.TestCase):
    def test_one_valid_record_per_check(self):
        out = one([f("style", "warn")], ["style", "naming"], ran=["naming"])
        self.assertEqual(sorted(out), ["mechanical.review.naming", "mechanical.review.style"])
        for ev in out.values():
            self.assertEqual(validate(ev), [])
            self.assertEqual(ev["verifiability"], "mechanical")
            self.assertTrue(ev["reproduce"]["command"].startswith("python3 -m praiser review"))

    def test_outcomes(self):
        out = one([f("a", "fail"), f("a", "warn"), f("b", "warn"), f("c", "inconclusive"), f("d", "fail"), f("d", "inconclusive")],
                  ["a", "b", "c", "d", "e", "g"], ran=["g"])
        got = {k.split(".")[-1]: e["outcome"] for k, e in out.items()}
        self.assertEqual(got, {"a": "fail", "b": "pass", "c": "inconclusive", "d": "fail", "e": "not_run", "g": "pass"})

    def test_silence_is_not_a_pass(self):
        self.assertEqual(one([], ["style"])["mechanical.review.style"]["outcome"], "not_run")

    def test_inconclusive_is_never_a_pass(self):
        e = one([f("style", "inconclusive", detail="no answer")], ["style"], ran=["style"])["mechanical.review.style"]
        self.assertEqual(e["outcome"], "inconclusive")
        self.assertIn("not a pass", e["claim"])

    def test_unexpected_checks_are_still_recorded(self):
        self.assertIn("mechanical.review.surprise", one([f("surprise", "fail")], ["style"]))

    def test_patches_are_hashed_not_embedded(self):
        patch = "theorem t : True := trivial\n"
        e = one([f("generalise", "fail", name="t", patch=patch)], ["generalise"])["mechanical.review.generalise"]
        row = e["details"]["failing"][0]
        self.assertEqual(row["patch_bytes"], len(patch))
        self.assertEqual(len(row["patch_sha256"]), 64)
        self.assertNotIn(patch, str(e))

    def test_details_stay_inside_the_contract(self):
        many = [f("style", "fail", name=f"n{i}", line=i, detail="x" * 160) for i in range(400)]
        e = one(many, ["style"])["mechanical.review.style"]
        self.assertEqual(validate(e), [])
        self.assertEqual(e["details"]["n_findings"], 400)

    def test_colliding_check_names_are_refused(self):
        with self.assertRaises(ValueError):
            one([], ["a-b", "a_b"])

    def test_a_malformed_finding_is_refused_not_dropped(self):
        for bad in ({"severity": "fail"}, {"check": "x", "severity": "loud"}, "text"):
            with self.assertRaises(ValueError):
                R.from_findings([bad], CASE, TOOLING, ["x"], NOW, command_for=cmd)

    def test_ids_are_stable(self):
        a = one([f("style", "warn", name="x", line=2)], ["style"])
        b = one([f("style", "warn", name="x", line=2)], ["style"])
        self.assertEqual({k: v["id"] for k, v in a.items()}, {k: v["id"] for k, v in b.items()})

    def test_digest_is_order_independent(self):
        x, y = f("style", "warn", name="x", line=1), f("naming", "fail", name="y", line=2)
        self.assertEqual(R.findings_digest([x, y]), R.findings_digest([y, x]))
        self.assertNotEqual(R.findings_digest([x]), R.findings_digest([x, y]))

    def test_command_template(self):
        self.assertEqual(R.command_template("run {check}")("a b"), "run 'a b'")


if __name__ == "__main__":
    unittest.main()
