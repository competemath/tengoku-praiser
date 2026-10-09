import unittest

from vendor.juridicator_evidence import validate
from praiser.merit import axiom_closure, from_checkers, from_jinshi, manifest, no_sorry
from tests.helpers import CASE, HEAD, NOW, TOOLING


def finding(check, severity="fail", module="Foo.Bar", name="thm", detail="bad"):
    return {"check": check, "severity": severity, "module": module, "name": name, "detail": detail}


class Jinshi(unittest.TestCase):
    def run_it(self, findings, checks, **kw):
        return {e["kind"]: e for e in from_jinshi(findings, CASE, TOOLING, checks, NOW, **kw)}

    def test_one_record_per_declared_check_all_valid(self):
        out = self.run_it([finding("axioms", "warn")], ["axioms", "universes"], ran=["universes"])
        self.assertEqual(sorted(out), ["mechanical.jinshi.axioms", "mechanical.jinshi.universes"])
        for ev in out.values():
            self.assertEqual(validate(ev), [])
            self.assertEqual(ev["verifiability"], "mechanical")
            self.assertTrue(ev["reproduce"]["command"])

    def test_any_fail_severity_fails_that_check_only(self):
        out = self.run_it([finding("axioms", "fail"), finding("axioms", "warn"), finding("universes", "warn")], ["axioms", "universes"])
        self.assertEqual(out["mechanical.jinshi.axioms"]["outcome"], "fail")
        self.assertEqual(out["mechanical.jinshi.universes"]["outcome"], "pass")
        d = out["mechanical.jinshi.axioms"]["details"]
        self.assertEqual(d["counts"], {"fail": 1, "warn": 1})
        self.assertEqual(d["failing"][0]["module"], "Foo.Bar")

    def test_findings_that_are_not_failures_pass_with_counts(self):
        ev = self.run_it([finding("a", "warn"), finding("a", "info")], ["a"])["mechanical.jinshi.a"]
        self.assertEqual(ev["outcome"], "pass")
        self.assertEqual(ev["details"]["n_findings"], 2)

    def test_no_findings_is_not_a_pass_unless_marked_as_run(self):
        self.assertEqual(self.run_it([], ["a"])["mechanical.jinshi.a"]["outcome"], "not_run")
        self.assertEqual(self.run_it([], ["a"], ran=["a"])["mechanical.jinshi.a"]["outcome"], "pass")
        self.assertEqual(self.run_it([], ["a", "b"], ran=["a"])["mechanical.jinshi.b"]["outcome"], "not_run")

    def test_an_undeclared_failing_check_is_still_reported(self):
        out = self.run_it([finding("surprise", "fail")], ["a"], ran=["a"])
        self.assertEqual(out["mechanical.jinshi.surprise"]["outcome"], "fail")

    def test_findings_without_a_check_are_refused_not_dropped(self):
        with self.assertRaises(ValueError):
            from_jinshi([{"severity": "fail"}], CASE, TOOLING, ["a"], NOW)
        with self.assertRaises(ValueError):
            from_jinshi(["fail"], CASE, TOOLING, ["a"], NOW)

    def test_check_names_are_made_into_kinds_and_collisions_refused(self):
        out = self.run_it([], ["Unused-Names"], ran=["Unused-Names"])
        self.assertIn("mechanical.jinshi.unused_names", out)
        self.assertEqual(out["mechanical.jinshi.unused_names"]["details"]["check"], "Unused-Names")
        with self.assertRaises(ValueError):
            from_jinshi([], CASE, TOOLING, ["a-b", "a_b"], NOW)

    def test_command_template(self):
        ev = self.run_it([], ["a"], ran=["a"], command_template="jinshi run {check} --strict")["mechanical.jinshi.a"]
        self.assertEqual(ev["reproduce"]["command"], "jinshi run a --strict")

    def test_many_failures_stay_inside_the_size_limit(self):
        fs = [finding("a", "fail", module="M" * 90, name="n" * 90, detail="d" * 400) for _ in range(200)]
        ev = self.run_it(fs, ["a"])["mechanical.jinshi.a"]
        self.assertEqual(validate(ev), [])
        self.assertEqual(ev["details"]["counts"]["fail"], 200)

    def test_deterministic_and_order_independent(self):
        fs = [finding("a"), finding("b", "warn")]
        self.assertEqual(from_jinshi(fs, CASE, TOOLING, ["a", "b"], NOW), from_jinshi(fs[::-1], CASE, TOOLING, ["b", "a"], NOW))


class Checkers(unittest.TestCase):
    def test_one_record_per_checker_with_identity_equal_to_name(self):
        evs = from_checkers({"lean-kernel": "accept", "lean4lean": "accept", "nanoda": "reject"}, CASE, NOW)
        self.assertEqual(sorted(e["producer"]["identity"] for e in evs), ["lean-kernel", "lean4lean", "nanoda"])
        self.assertEqual(len({e["producer"]["identity"] for e in evs}), 3)
        for e in evs:
            self.assertEqual(validate(e), [])
            self.assertEqual((e["kind"], e["producer"]["role"]), ("mechanical.kernel_check", "tooling"))
            self.assertEqual(e["producer"]["name"], e["producer"]["identity"])

    def test_outcomes(self):
        evs = {e["producer"]["identity"]: e["outcome"] for e in from_checkers(
            {"a": "accept", "b": "reject", "c": "timeout", "d": "error"}, CASE, NOW)}
        self.assertEqual(evs, {"a": "pass", "b": "fail", "c": "inconclusive", "d": "inconclusive"})

    def test_same_subject_for_every_checker_so_disagreement_is_visible(self):
        evs = from_checkers({"a": "accept", "b": "reject"}, CASE, NOW)
        self.assertEqual({repr(e["subject"]) for e in evs}, {"None"})

    def test_unknown_verdicts_and_empty_input_refused(self):
        with self.assertRaises(ValueError):
            from_checkers({"a": "maybe"}, CASE, NOW)
        with self.assertRaises(ValueError):
            from_checkers({}, CASE, NOW)

    def test_commands(self):
        evs = from_checkers({"a": "accept", "b": "accept"}, CASE, NOW, commands={"a": "checker-a --all"})
        by = {e["producer"]["identity"]: e for e in evs}
        self.assertEqual(by["a"]["reproduce"]["command"], "checker-a --all")
        self.assertTrue(by["b"]["reproduce"]["command"])


class Axioms(unittest.TestCase):
    def test_standard_axioms_pass(self):
        ev = axiom_closure(["propext", "Classical.choice", "Quot.sound"], CASE, TOOLING, NOW)
        self.assertEqual((ev["outcome"], ev["kind"]), ("pass", "mechanical.axiom_closure"))
        self.assertEqual(validate(ev), [])

    def test_no_axioms_at_all_passes(self):
        self.assertEqual(axiom_closure([], CASE, TOOLING, NOW)["outcome"], "pass")

    def test_an_extra_axiom_fails_and_is_named(self):
        ev = axiom_closure(["propext", "myAxiom", "Other.axiom"], CASE, TOOLING, NOW)
        self.assertEqual(ev["outcome"], "fail")
        self.assertIn("myAxiom", ev["claim"])
        self.assertIn("Other.axiom", ev["claim"])
        self.assertNotIn("propext", ev["claim"])
        self.assertEqual(ev["details"]["outside_allowed"], ["Other.axiom", "myAxiom"])

    def test_allowed_set_is_a_parameter_and_is_recorded(self):
        ev = axiom_closure(["propext", "Toolchain.internal"], CASE, TOOLING, NOW, allowed=("propext", "Toolchain.internal"))
        self.assertEqual(ev["outcome"], "pass")
        self.assertIn("Toolchain.internal", ev["details"]["allowed"])
        self.assertEqual(axiom_closure(["Toolchain.internal"], CASE, TOOLING, NOW)["outcome"], "fail")

    def test_sorry_ax_can_never_be_allowed_and_always_fails(self):
        with self.assertRaises(ValueError):
            axiom_closure([], CASE, TOOLING, NOW, allowed=("propext", "sorryAx"))
        self.assertEqual(axiom_closure(["sorryAx"], CASE, TOOLING, NOW)["outcome"], "fail")

    def test_scan_that_did_not_run_is_not_run(self):
        self.assertEqual(axiom_closure(None, CASE, TOOLING, NOW)["outcome"], "not_run")

    def test_has_a_command(self):
        self.assertTrue(axiom_closure([], CASE, TOOLING, NOW, command="lake exe axioms")["reproduce"]["command"] == "lake exe axioms")


class NoSorry(unittest.TestCase):
    def test_flag_true_means_a_sorry_was_found(self):
        self.assertEqual(no_sorry(True, CASE, TOOLING, NOW)["outcome"], "fail")
        self.assertEqual(no_sorry(False, CASE, TOOLING, NOW)["outcome"], "pass")

    def test_findings(self):
        self.assertEqual(no_sorry([], CASE, TOOLING, NOW)["outcome"], "pass")
        self.assertEqual(no_sorry([finding("sorry")], CASE, TOOLING, NOW)["outcome"], "fail")
        self.assertEqual(no_sorry([finding("sorry", "info")], CASE, TOOLING, NOW)["outcome"], "pass")
        self.assertEqual(no_sorry([{"module": "M"}], CASE, TOOLING, NOW)["outcome"], "fail")
        self.assertEqual(no_sorry([finding("sorry"), finding("sorry")], CASE, TOOLING, NOW)["details"]["occurrences"], 2)

    def test_none_is_not_run(self):
        ev = no_sorry(None, CASE, TOOLING, NOW)
        self.assertEqual((ev["outcome"], ev["kind"]), ("not_run", "mechanical.no_sorry"))
        self.assertEqual(validate(ev), [])

    def test_bad_findings_refused(self):
        with self.assertRaises(ValueError):
            no_sorry(["sorry"], CASE, TOOLING, NOW)


class Manifest(unittest.TestCase):
    def test_declares_the_kinds(self):
        ev = manifest(CASE, TOOLING, ["mechanical.no_sorry", "mechanical.axiom_closure", "mechanical.no_sorry"], NOW)
        self.assertEqual(validate(ev), [])
        self.assertEqual(ev["kind"], "manifest.declared")
        self.assertEqual(ev["verifiability"], "attested")
        self.assertEqual(ev["details"]["checks"], ["mechanical.axiom_closure", "mechanical.no_sorry"])

    def test_refuses_empty_and_malformed(self):
        for bad in ([], ["NotAKind"], ["manifest.declared"]):
            with self.assertRaises(ValueError):
                manifest(CASE, TOOLING, bad, NOW)

    def test_binds_to_the_head(self):
        self.assertEqual(manifest(CASE, TOOLING, ["mechanical.no_sorry"], NOW)["case"]["head_sha"], HEAD)


if __name__ == "__main__":
    unittest.main()
