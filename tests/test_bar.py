import unittest

from praiser import bar
from praiser.review import finding


def f(check, severity, rule="", module="M1", **kw):
    return finding(check, severity, "d", module=module, name=rule or check, rule=rule, **kw) if rule else finding(check, severity, "d", module=module, name=check, **kw)


class Verdicts(unittest.TestCase):
    def one(self, findings, facts=None, ran=None):
        return bar.decide_one("e1", findings, facts, ran)

    def test_clean_with_merit_is_accepted(self):
        v = self.one([f("reuse", "info", "reused")])
        self.assertEqual((v.verdict, v.codes, v.merit), ("accept", [], ["reused"]))

    def test_clean_without_merit_is_returned_with_the_merit_code(self):
        v = self.one([f("style", "warn", "fun_arrow")])
        self.assertEqual((v.verdict, v.codes), ("return", ["bar.merit"]))
        self.assertEqual(v.notes, ["style.fun_arrow"])

    def test_each_sign_of_merit_counts_alone(self):
        self.assertEqual(self.one([f("dedupe", "info", "generalises")]).verdict, "accept")
        self.assertEqual(self.one([], {"stars": 5}).merit, ["five_stars"])
        self.assertEqual(self.one([], {"cited_by": 2}).merit, ["cited"])
        self.assertEqual(self.one([], {"stars": 4, "cited_by": 0}).verdict, "return")

    def test_a_failing_finding_returns_it_with_its_code(self):
        v = self.one([f("style", "fail", "line_length"), f("naming", "fail", "placeholder"), f("reuse", "info", "reused")])
        self.assertEqual((v.verdict, v.codes), ("return", ["naming.placeholder", "style.line_length"]))

    def test_the_final_codes_reject(self):
        for check, rule in (("style", "sorry"), ("style", "native_decide"), ("style", "unverified_code"), ("dedupe", "identical"), ("naming", "taken")):
            v = self.one([f(check, "fail", rule), f("style", "fail", "line_length")])
            self.assertEqual(v.verdict, "reject", rule)
            self.assertEqual(v.codes[0], f"{check}.{rule}")
            self.assertIn("style.line_length", v.codes)

    def test_a_verified_generalisation_is_a_return(self):
        v = self.one([f("generalise", "fail", patch="theorem t : True := trivial\n"), f("reuse", "info", "reused")])
        self.assertEqual((v.verdict, v.codes), ("return", ["generalise.patch"]))

    def test_the_vocabulary_of_the_lean_checks(self):
        self.assertEqual(bar.code_of(f("lint", "fail")), "lint.env")
        self.assertEqual(bar.code_of(f("compat", "fail", "forward_break")), "compat.forward")
        self.assertEqual(bar.code_of(f("robust", "fail", "auto_implicit")), "robust.fragile")

    def test_inconclusive_blocks_only_a_check_that_ran(self):
        findings = [f("compat", "inconclusive"), f("reuse", "info", "reused")]
        self.assertEqual(self.one(findings, ran={"compat"}).codes, ["compat.inconclusive"])
        self.assertEqual(self.one(findings, ran={"style"}).verdict, "accept", "a check that did not run cannot block: the caller reports it as not run")
        self.assertEqual(self.one(findings).verdict, "return", "with no list of what ran, an inconclusive required check blocks")

    def test_every_code_is_a_valid_notice_code(self):
        rules = [("style", r) for r in ("line_length", "trailing_whitespace", "sorry", "fun_arrow")] + [("naming", "case"), ("docs", "module_doc"), ("api", "sibling"), ("dedupe", "instance_of"), ("lint", ""), ("compat", "deprecated")]
        for check, rule in rules:
            self.assertRegex(bar.code_of(f(check, "fail", rule)), bar.CODE)
        self.assertRegex(bar.code_of({"check": "Weird Check!", "rule": "x y"}), bar.CODE)

    def test_items_are_judged_by_their_own_findings(self):
        findings = [f("style", "fail", "line_length", module="M1"), f("reuse", "info", "reused", module="M2")]
        out = bar.decide(findings, {"e1": "M1", "e2": "M2"})
        self.assertEqual({k: v.verdict for k, v in out.items()}, {"e1": "return", "e2": "accept"})
        self.assertEqual(bar.summary(out), {"bar": "bar/0", "accept": 1, "return": 1, "reject": 0})

    def test_deterministic_and_versioned(self):
        a = bar.decide([f("style", "fail", "tab"), f("naming", "fail", "case")], {"e1": "M1"})
        b = bar.decide([f("naming", "fail", "case"), f("style", "fail", "tab")], {"e1": "M1"})
        self.assertEqual(a["e1"].as_dict(), b["e1"].as_dict())
        self.assertEqual(a["e1"].bar, "bar/0")


if __name__ == "__main__":
    unittest.main()
