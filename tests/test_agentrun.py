import copy
import dataclasses
import json
import unittest

from vendor.juridicator_evidence import validate
from praiser import agentrun
from praiser.agentrun import agent_contained, declared_digests, digest, tool_policy_fact, verify_agent_contained
from praiser.attest import provenance_attestation
from praiser.loaders import read_json
from praiser.common import sha256_bytes
from tests.helpers import AUTHOR, CASE, NOW, PRAISER
from tests.test_loaders_cli import Base, run
from tests.test_trustcard import card, healthy

POLICY = {"name": "reviewer", "builtin_tools": ["Read", "Grep", "Glob"], "mcp_patterns": [], "allow_shell": False}


@dataclasses.dataclass(frozen=True)
class WardenLikePolicy:
    name: str
    builtin_tools: tuple = ()
    mcp_patterns: tuple = ()
    allow_shell: bool = False
    allow_skip_permissions: bool = False
    allow_unknown_cli: bool = False
    require_limits: bool = False


def trace(**over):
    t = {"ok": True, "calls_by_tool": {"Grep": 3, "Read": 5}, "total_calls": 8, "denied": 0, "failed": 0, "unparsed_lines": 0, "events": 40,
         "init_tools": ["Glob", "Grep", "Read"], "violations": []}
    t.update(over)
    return t


def battery(statuses=None, **over):
    statuses = ["denied"] * 34 if statuses is None else statuses
    results = [{"name": "probe_%d" % i, "why": "w", "category": "c", "status": s, "expected": "denied", "ok": s == "denied", "detail": "", "needs_linux": False, "ms": 1}
               for i, s in enumerate(statuses)]
    b = {"ok": all(s == "denied" for s in statuses), "platform": "linux", "linux": True, "uid": 1001, "require_linux": True, "allow_unconfigured": False,
         "unconfigured_allowed": [], "counts": {}, "failed": [], "results": results}
    b.update(over)
    return b


def contained(t=None, b=None, policy=POLICY, **kw):
    return agent_contained(trace() if t is None else t, battery() if b is None else b, policy, CASE, PRAISER, NOW, **kw)


def violation(rule="shell-tool", severity="error", detail="Bash"):
    return {"rule": rule, "message": "m", "detail": detail, "severity": severity}


class Pass(unittest.TestCase):
    def test_a_clean_trace_and_a_fully_denied_battery_pass(self):
        r = contained()
        self.assertEqual(validate(r), [])
        self.assertEqual((r["kind"], r["verifiability"], r["outcome"]), ("mechanical.agent_contained", "mechanical", "pass"))
        self.assertIn("The agent ran contained: tool set reviewer (Glob, Grep, Read)", r["claim"])
        self.assertIn("escape battery 34/34 denied", r["claim"])
        self.assertEqual(r["subject"], {"declaration": "reviewer"})
        self.assertEqual(set(r["case"]), {"repo", "head_sha", "class"})

    def test_the_reproduce_command_is_the_exact_audit_line(self):
        r = contained(trace_path="runs/42/trace.jsonl", workspaces=["/work/checkout"])
        self.assertEqual(r["reproduce"]["command"], "python3 -m warden toolpolicy audit-trace runs/42/trace.jsonl --policy reviewer --workspace /work/checkout")
        weird = contained(trace_path="a b/trace 1.jsonl")
        self.assertIn("'a b/trace 1.jsonl'", weird["reproduce"]["command"])
        self.assertEqual(contained(command="make audit")["reproduce"]["command"], "make audit")

    def test_details_carry_the_digests_of_the_reports_and_the_policy(self):
        t, b = trace(), battery()
        d = contained(t, b)["details"]
        self.assertEqual(d["trace_report_sha256"], digest(t))
        self.assertEqual(d["selftest_report_sha256"], digest(b))
        self.assertEqual(d["tool_policy"]["sha256"], tool_policy_fact(POLICY)["sha256"])
        self.assertEqual((d["battery"]["denied"], d["battery"]["total"], d["trace"]["total_calls"]), (34, 34, 8))
        self.assertNotIn("jail_spec_sha256", d)

    def test_the_jail_spec_digest_is_recorded_when_given(self):
        spec = {"bwrap": ["--unshare-all", "--ro-bind", "/", "/"]}
        d = contained(jail_spec=spec)["details"]
        self.assertEqual(d["jail_spec_sha256"], agentrun.jail_spec_digest(spec))

    def test_a_warden_tool_policy_object_is_as_good_as_a_mapping(self):
        a = contained(policy=WardenLikePolicy("reviewer", ("Read", "Grep", "Glob")))
        self.assertEqual(a["details"]["tool_policy"]["sha256"], contained()["details"]["tool_policy"]["sha256"])
        self.assertEqual(a["outcome"], "pass")

    def test_tool_order_does_not_change_the_policy_hash_but_a_wider_set_does(self):
        reordered = dict(POLICY, builtin_tools=["Glob", "Read", "Grep"])
        self.assertEqual(tool_policy_fact(reordered)["sha256"], tool_policy_fact(POLICY)["sha256"])
        wider = dict(POLICY, builtin_tools=["Read", "Grep", "Glob", "Write"])
        self.assertNotEqual(tool_policy_fact(wider)["sha256"], tool_policy_fact(POLICY)["sha256"])

    def test_an_mcp_only_policy_with_matching_tools_passes(self):
        policy = {"name": "translator", "builtin_tools": [], "mcp_patterns": ["mcp__tengoku"]}
        t = trace(calls_by_tool={"mcp__tengoku__lookup": 2}, init_tools=["mcp__tengoku__lookup"], total_calls=2)
        r = contained(t, policy=policy)
        self.assertEqual(r["outcome"], "pass")
        self.assertIn("no built-in tools; mcp__tengoku", r["claim"])


class Fail(unittest.TestCase):
    def test_an_error_level_violation_in_the_trace_fails(self):
        r = contained(trace(ok=False, violations=[violation(), violation("shell-command", detail="curl x")]))
        self.assertEqual((validate(r), r["outcome"]), ([], "fail"))
        self.assertIn("2 trace violation(s)", r["claim"])
        self.assertIn("shell-tool", r["claim"])

    def test_a_probe_the_agent_could_do_fails_and_is_named(self):
        statuses = ["denied"] * 33 + ["allowed"]
        r = contained(b=battery(statuses))
        self.assertEqual(r["outcome"], "fail")
        self.assertIn("1 of 34 escape probes allowed: probe_33", r["claim"])

    def test_the_batterys_own_ok_is_not_believed(self):
        r = contained(b=battery(["denied", "allowed"], ok=True, failed=[]))
        self.assertEqual(r["outcome"], "fail")

    def test_a_trace_audited_against_a_more_lenient_policy_cannot_pass(self):
        """The audit said ok, but the run used Bash and the declared policy has none: caught here, from the declared policy."""
        r = contained(trace(calls_by_tool={"Bash": 4, "Read": 1}, init_tools=["Bash", "Read"], total_calls=5, ok=True))
        self.assertEqual(r["outcome"], "fail")
        self.assertIn("tool-outside-declared-policy", r["claim"])
        self.assertEqual(contained(trace(init_tools=["Read", "WebFetch"]))["outcome"], "fail")

    def test_a_report_that_differs_from_the_declared_digest_fails(self):
        r = contained(declared={"trace_report_sha256": sha256_bytes(b"some other trace report")})
        self.assertEqual(r["outcome"], "fail")
        self.assertEqual(r["details"]["declared_mismatch"], ["trace_report_sha256"])
        r = contained(declared={"tool_policy_sha256": digest(dict(POLICY, builtin_tools=["Read"]))})
        self.assertEqual(r["outcome"], "fail")
        self.assertEqual(contained(jail_spec={"a": 1}, declared={"jail_spec_sha256": agentrun.jail_spec_digest({"a": 2})})["outcome"], "fail")
        # declared but not supplied is not a match either
        self.assertEqual(contained(declared={"jail_spec_sha256": agentrun.jail_spec_digest({"a": 2})})["outcome"], "fail")

    def test_a_declaration_that_matches_changes_nothing(self):
        t, b = trace(), battery()
        r = contained(t, b, declared={"trace_report_sha256": digest(t), "selftest_report_sha256": digest(b),
                                      "tool_policy_sha256": tool_policy_fact(POLICY)["sha256"]})
        self.assertEqual(r["outcome"], "pass")


class Inconclusive(unittest.TestCase):
    def test_a_denied_attempt_is_not_a_pass(self):
        r = contained(trace(violations=[violation("tool-not-in-policy", "warn", "Bash")], denied=1))
        self.assertEqual((validate(r), r["outcome"]), ([], "inconclusive"))
        self.assertIn("1 denied attempt(s)", r["claim"])

    def test_probes_that_did_not_apply_or_could_not_run_are_not_a_pass(self):
        for statuses in (["denied"] * 30 + ["na"] * 4, ["denied"] * 33 + ["error"]):
            r = contained(b=battery(statuses))
            self.assertEqual(r["outcome"], "inconclusive", statuses)
            self.assertIn("escape battery 3", r["claim"])

    def test_a_partial_or_unconfigured_battery_is_not_a_pass(self):
        self.assertEqual(contained(b=battery(partial=True))["outcome"], "inconclusive")
        self.assertEqual(contained(b=battery(unconfigured_allowed=["probe_9"]))["outcome"], "inconclusive")
        self.assertEqual(contained(b=battery([]))["outcome"], "inconclusive")

    def test_an_empty_trace_that_listed_no_violation_is_not_a_pass(self):
        self.assertEqual(contained(trace(events=0, total_calls=0, calls_by_tool={}, init_tools=None))["outcome"], "inconclusive")
        self.assertEqual(contained(trace(ok=False))["outcome"], "inconclusive")


class AbsentEvidence(unittest.TestCase):
    def test_a_missing_report_is_not_run_never_a_pass(self):
        for t, b, said in ((None, battery(), "trace audit"), (trace(), None, "escape battery"), (None, None, "trace audit and escape battery")):
            r = agent_contained(t, b, POLICY, CASE, PRAISER, NOW)
            self.assertEqual((validate(r), r["outcome"]), ([], "not_run"))
            self.assertTrue(r["claim"].startswith("No containment evidence: " + said), r["claim"])
            self.assertEqual(r["details"]["trace_report_sha256"] is None, t is None)

    def test_malformed_input_is_refused_loudly(self):
        for t, b in (({}, battery()), ({"violations": "x"}, battery()), (trace(violations=[{"rule": "r", "severity": "fatal"}]), battery()),
                     (trace(events="3"), battery()), (trace(), {"results": [{"name": "a", "status": "maybe"}]}), (trace(), {}), ([], battery())):
            with self.assertRaises(ValueError):
                contained(t, b)
        for policy in ({}, {"name": ""}, {"name": "p", "builtin_tools": "Read"}, {"name": "p", "allow_shell": "yes"}, "reviewer", None):
            with self.assertRaises(ValueError):
                contained(policy=policy)
        with self.assertRaises(ValueError):
            contained(declared={"trace_report_sha256": "not-a-hash"})
        with self.assertRaises(ValueError):
            contained(declared={"model": "x" * 64})


class ForgedDigests(unittest.TestCase):
    def test_a_record_verifies_against_the_stored_reports(self):
        t, b = trace(), battery()
        self.assertEqual(verify_agent_contained(contained(t, b), t, b, POLICY), [])

    def test_a_swapped_report_is_detected(self):
        t, b = trace(), battery()
        record = contained(t, b)
        other = trace(total_calls=9)
        problems = verify_agent_contained(record, other, b, POLICY)
        self.assertTrue(any("trace_report_sha256" in p for p in problems), problems)
        problems = verify_agent_contained(record, t, battery(["denied"] * 33 + ["allowed"]), POLICY)
        self.assertTrue(any("selftest_report_sha256" in p for p in problems) and any("says pass" in p for p in problems), problems)

    def test_a_forged_digest_in_the_record_is_detected(self):
        t, b = trace(), battery()
        record = copy.deepcopy(contained(t, b))
        record["details"]["trace_report_sha256"] = sha256_bytes(b"a clean trace that never existed")
        self.assertTrue(any("trace_report_sha256" in p for p in verify_agent_contained(record, t, b, POLICY)))
        record = copy.deepcopy(contained(t, b))
        record["details"]["tool_policy"]["sha256"] = tool_policy_fact(dict(POLICY, builtin_tools=["Read"]))["sha256"]
        self.assertTrue(any("tool policy hash" in p for p in verify_agent_contained(record, t, b, POLICY)))

    def test_a_different_policy_or_jail_spec_is_detected(self):
        t, b = trace(), battery()
        record = contained(t, b, jail_spec={"a": 1})
        self.assertEqual(verify_agent_contained(record, t, b, POLICY, jail_spec={"a": 1}), [])
        self.assertTrue(verify_agent_contained(record, t, b, POLICY, jail_spec={"a": 2}))
        self.assertTrue(verify_agent_contained(record, t, b, dict(POLICY, builtin_tools=["Read", "Grep", "Glob", "Bash"], allow_shell=True)))

    def test_a_record_that_claims_a_better_outcome_than_the_reports_support_is_detected(self):
        t, b = trace(violations=[violation()]), battery()
        honest = contained(t, b)
        self.assertEqual(honest["outcome"], "fail")
        lie = copy.deepcopy(honest)
        lie["outcome"] = "pass"
        self.assertTrue(any("the record says pass" in p for p in verify_agent_contained(lie, t, b, POLICY)))

    def test_not_a_containment_record_or_unreadable_reports(self):
        self.assertEqual(verify_agent_contained({"kind": "mechanical.other", "details": {}}, trace(), battery(), POLICY), ["not a mechanical.agent_contained record"])
        self.assertTrue(verify_agent_contained(contained(), {}, battery(), POLICY)[0].startswith("the stored reports or policy cannot be read"))


class ProvenanceFacts(unittest.TestCase):
    def attestation(self, **extra):
        return provenance_attestation(CASE, AUTHOR, model="m", model_family="f", prompt_sha256={"p.md": "1" * 64}, tool_manifest={"t.json": "2" * 64},
                                      toolchain={"lean-toolchain": "3" * 64}, rubric_version="r1", human_signoffs=["alice"], created=NOW, **extra)

    def test_without_the_new_facts_the_record_is_exactly_what_it_was(self):
        plain = self.attestation()
        self.assertNotIn("tool_policy", plain["details"])
        self.assertNotIn("jail_spec_sha256", plain["details"])
        self.assertEqual(plain["id"], self.attestation(tool_policy=None, jail_spec_sha256=None)["id"])

    def test_the_policy_name_and_hash_and_the_jail_digest_are_declared_facts(self):
        spec = agentrun.jail_spec_digest({"bwrap": ["--unshare-all"]})
        att = self.attestation(tool_policy=POLICY, jail_spec_sha256=spec)
        self.assertEqual(validate(att), [])
        self.assertEqual(att["details"]["tool_policy"], tool_policy_fact(POLICY))
        self.assertEqual(att["details"]["jail_spec_sha256"], spec)
        self.assertEqual(att["verifiability"], "attested")
        self.assertNotEqual(att["id"], self.attestation()["id"])
        self.assertEqual(declared_digests(att), {"tool_policy_sha256": tool_policy_fact(POLICY)["sha256"], "jail_spec_sha256": spec})

    def test_a_bad_jail_digest_or_policy_is_refused(self):
        with self.assertRaises(ValueError):
            self.attestation(jail_spec_sha256="nope")
        with self.assertRaises(ValueError):
            self.attestation(tool_policy={"name": ""})

    def test_the_declaration_is_checked_against_the_reports(self):
        spec = {"bwrap": ["--unshare-all"]}
        att = self.attestation(tool_policy=POLICY, jail_spec_sha256=agentrun.jail_spec_digest(spec))
        ok = contained(jail_spec=spec, declared=declared_digests(att))
        self.assertEqual(ok["outcome"], "pass")
        wider = dict(POLICY, builtin_tools=["Read", "Grep", "Glob", "Write"])
        self.assertEqual(contained(policy=wider, jail_spec=spec, declared=declared_digests(att))["outcome"], "fail")
        self.assertEqual(contained(jail_spec={"bwrap": []}, declared=declared_digests(att))["outcome"], "fail")
        self.assertEqual(declared_digests({}), {})
        self.assertEqual(declared_digests(self.attestation()), {})


class TrustCard(unittest.TestCase):
    def test_without_containment_evidence_the_card_is_unchanged(self):
        text = card(healthy())
        self.assertNotIn("ontain", text)
        self.assertNotIn("escape battery", text)

    def test_a_pass_says_the_agent_ran_contained(self):
        text = card(healthy() + [contained()])
        self.assertIn("- The agent ran contained: tool set reviewer \\(Glob, Grep, Read\\), escape battery 34/34 denied.", text)

    def test_a_failure_and_a_missing_report_are_not_dressed_up(self):
        failed = card(healthy() + [contained(trace(violations=[violation()]))])
        self.assertIn("- The agent was NOT shown to be contained: Not contained", failed)
        self.assertNotIn("ran contained", failed)
        silent = card(healthy() + [agent_contained(None, battery(), POLICY, CASE, PRAISER, NOW)])
        self.assertIn("- No containment evidence: No containment evidence: trace audit not supplied", silent)
        partial = card(healthy() + [contained(b=battery(["denied"] * 30 + ["na"] * 4))])
        self.assertIn("- No containment evidence: Containment not shown", partial)

    def test_a_record_whose_counts_contradict_its_outcome_is_not_shown_as_a_pass(self):
        record = copy.deepcopy(contained())
        record["details"]["battery"]["denied"] = 20
        # recompute the id so the card keeps it (a forged record that is internally well formed)
        from vendor.juridicator_evidence import compute_id
        record["id"] = compute_id(record)
        text = card(healthy() + [record])
        self.assertIn("its own counts do not show every probe denied", text)
        self.assertNotIn("- The agent ran contained", text)

    def test_markdown_in_a_policy_name_cannot_plant_a_link_or_a_tag(self):
        evil = dict(POLICY, name="x<script>[y](http://e.example)")
        text = card(healthy() + [contained(policy=evil)])
        self.assertNotIn("<script>", text)
        self.assertNotIn("[y](http", text)


class Cli(Base):
    def files(self, t=None, b=None):
        return ["--trace-report", self.write("trace.json", trace() if t is None else t),
                "--selftest-report", self.write("selftest.json", battery() if b is None else b),
                "--policy", self.write("policy.json", POLICY)]

    def test_agent_contained_writes_a_valid_record_and_exits_zero_even_for_a_failure(self):
        for t, outcome in ((None, "pass"), (trace(violations=[violation()]), "fail")):
            out = self.path("rec-%s.json" % outcome)
            code, _, err = run("agent-contained", *self.base_args(), *self.files(t), "--trace-path", "t.jsonl", "--workspace", "/w", "--out", out)
            self.assertEqual((code, err), (0, ""))
            rec = read_json(out)
            self.assertEqual((validate(rec), rec["outcome"]), ([], outcome))
            self.assertEqual(rec["reproduce"]["command"], "python3 -m warden toolpolicy audit-trace t.jsonl --policy reviewer --workspace /w")

    def test_a_missing_report_file_argument_is_not_run(self):
        out = self.path("rec.json")
        code, _, _ = run("agent-contained", *self.base_args(), "--policy", self.write("policy.json", POLICY), "--out", out)
        self.assertEqual((code, read_json(out)["outcome"]), (0, "not_run"))

    def test_declared_digests_come_from_a_provenance_record(self):
        att = provenance_attestation(CASE, AUTHOR, model="m", model_family="f", prompt_sha256={"p.md": "1" * 64}, tool_manifest={"t": "2" * 64},
                                     toolchain={"c": "3" * 64}, rubric_version="r", human_signoffs=[], created=NOW, tool_policy=dict(POLICY, builtin_tools=["Read"]))
        out = self.path("rec.json")
        code, _, _ = run("agent-contained", *self.base_args(), *self.files(), "--declared", self.write("att.json", att), "--out", out)
        self.assertEqual(code, 0)
        self.assertEqual(read_json(out)["outcome"], "fail")      # the declared policy hash is not the policy the reports were judged under

    def test_verify_exits_twelve_when_the_record_does_not_match_the_stored_reports(self):
        out = self.path("rec.json")
        run("agent-contained", *self.base_args(), *self.files(), "--out", out)
        code, stdout, _ = run("agent-contained", *self.base_args(), *self.files(), "--verify", out)
        self.assertEqual((code, json.loads(stdout)["ok"]), (0, True))
        code, stdout, _ = run("agent-contained", *self.base_args(), *self.files(t=trace(total_calls=99)), "--verify", out)
        self.assertEqual(code, 12)
        self.assertIn("trace_report_sha256", json.loads(stdout)["problems"][0])

    def test_attest_can_carry_the_tool_policy_and_the_jail_digest(self):
        spec = {"model": "m", "model_family": "f", "prompt_sha256": {"p.md": "1" * 64}, "tool_manifest": {"t": "2" * 64}, "toolchain": {"c": "3" * 64},
                "rubric_version": "r", "human_signoffs": [], "tool_policy": POLICY, "jail_spec_sha256": "4" * 64}
        out = self.path("att.json")
        code, _, _ = run("attest", *self.base_args(), "--spec", self.write("spec.json", spec), "--out", out)
        self.assertEqual(code, 0)
        self.assertEqual(read_json(out)["details"]["tool_policy"]["name"], "reviewer")

    def test_bad_input_exits_two(self):
        code, _, err = run("agent-contained", *self.base_args(), "--policy", self.write("p.json", {"name": ""}))
        self.assertEqual(code, 2)
        self.assertIn("bad input", err)


if __name__ == "__main__":
    unittest.main()
