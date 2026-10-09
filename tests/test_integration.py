"""Against the real juridicator, when a sibling checkout exists (`../tengoku-juridicator`). Skipped cleanly when it does not."""
import copy
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIBLING = os.path.join(os.path.dirname(ROOT), "tengoku-juridicator")

try:
    if os.path.isdir(os.path.join(SIBLING, "juridicator")):
        sys.path.append(SIBLING)  # appended: this repository's own packages always win
    from juridicator.evidence import validate as jvalidate
    from juridicator.ledger import Ledger, entry_hash as jentry_hash
    from juridicator.statute import decide
    HAVE = os.path.isdir(os.path.join(SIBLING, "juridicator"))
except ImportError:  # pragma: no cover
    HAVE = False

from vendor.juridicator_evidence import canonical_json, compute_id, make_evidence
from praiser import trustcard
from praiser.attest import attested_claim, check_provenance, provenance_attestation
from praiser.common import sha256_bytes
from praiser.merit import axiom_closure, from_checkers, from_jinshi, manifest, no_sorry
from praiser.preregistration import check_preregistration, commit_statement
from praiser.receipts import compare_receipts, make_receipt
from praiser.restatement import restatement_evidence
from praiser.track_record import GENESIS, entry_hash, track_record_evidence, verify_against_ledger, verify_chain
from tests.helpers import AUTHOR, CASE, H, H2, HEAD, NOW, OLDER, PRAISER, TOOLING, Chain

STANDING = {"gate_health": "ACCEPT"}
PIDENT = PRAISER["identity"]
PROMPT, TOOLS, CHAIN = b"prompt", b"tools", b"toolchain"


def judge(evidence):
    """The caller's part of the flow: it re-derived the track records from the ledger it holds and names their ids."""
    verified = [e["id"] for e in evidence if e.get("kind") == "reproducible.track_record" and e["producer"]["identity"] == PIDENT]
    return decide(CASE, evidence, None, standing=STANDING, verified=verified)


def comparable(verdict):
    """Everything in a verdict except the digest of the evidence list (which lists every record, as it should)."""
    return {k: v for k, v in verdict.items() if k != "evidence_digest"}


def author_ledger(n_good=60):
    chain = Chain()
    chain.accepted(n_good)
    return chain


def healthy_outputs(*, checkers=("lean-kernel", "lean4lean", "nanoda"), ledger=None):
    """Everything the praiser and the tooling would emit for a healthy case, manifests first."""
    ledger = ledger or author_ledger()
    decl = provenance_attestation(
        CASE, AUTHOR, model="model-x", model_family="family-a", prompt_sha256={"p.md": sha256_bytes(PROMPT)},
        tool_manifest={"t.json": sha256_bytes(TOOLS)}, toolchain={"lean-toolchain": sha256_bytes(CHAIN)},
        rubric_version="r1", human_signoffs=["alice"], created=NOW)
    prov = check_provenance(decl, {"p.md": PROMPT, "t.json": TOOLS, "lean-toolchain": CHAIN}, CASE, PRAISER, NOW)
    rebuild = compare_receipts(make_receipt("lake build", H, H2, 0, runner="runner-1"),
                               make_receipt("lake build", H, H2, 0, runner="runner-2"), CASE, PRAISER, NOW)
    track = track_record_evidence("agent-7", ledger.entries, CASE, PRAISER, NOW)
    axiom_gate = {"role": "tooling", "name": "axiom-gate", "identity": "axiom-gate"}
    sorry_gate = {"role": "tooling", "name": "sorry-gate", "identity": "sorry-gate"}
    checks = from_checkers({c: "accept" for c in checkers}, CASE, NOW)
    results = checks + [axiom_closure(["propext", "Classical.choice"], CASE, axiom_gate, NOW), no_sorry(False, CASE, sorry_gate, NOW),
                        decl, prov, rebuild, track]
    manifests = [
        manifest(CASE, PRAISER, ["mechanical.provenance_consistent", "reproducible.rebuild_match", "reproducible.track_record"], NOW),
        manifest(CASE, axiom_gate, ["mechanical.axiom_closure"], NOW),
        manifest(CASE, sorry_gate, ["mechanical.no_sorry"], NOW),
    ] + [manifest(CASE, c["producer"], ["mechanical.kernel_check"], NOW) for c in checks]
    return manifests + results


def fabricated_praise():
    """What a self-interested party might add: all attested, all glowing, none checkable."""
    fakes = [
        attested_claim(CASE, PRAISER, "praise", "the most reliable system ever built; 99.99% correct", NOW),
        attested_claim(CASE, AUTHOR, "team_note", "a world-class, extremely careful team", NOW),
        make_evidence(case={k: CASE[k] for k in ("repo", "head_sha", "class")}, producer=PRAISER, kind="attested.track_record",
                      claim="flawless record", outcome="pass", verifiability="attested", created=NOW, details={"lower_bound": 1.0}),
        make_evidence(case={k: CASE[k] for k in ("repo", "head_sha", "class")}, producer={"role": "praiser", "name": "x", "identity": "extra-checker"},
                      kind="attested.kernel_check", claim="independently verified", outcome="pass", verifiability="attested", created=NOW),
    ]
    return fakes


@unittest.skipUnless(HAVE, "no sibling tengoku-juridicator checkout (as in CI)")
class AgainstTheJuridicator(unittest.TestCase):
    def test_every_kind_of_record_validates_under_the_juridicators_validate(self):
        chain = author_ledger(5)
        records = healthy_outputs(ledger=chain) + fabricated_praise() + [
            restatement_evidence(CASE, PRAISER, ai_model="m", ai_family="f", prompt_sha256=H, equivalent=True, checker_command="c", created=NOW),
            check_preregistration(commit_statement("s", "n"), "s", "n", CASE, PRAISER, NOW, OLDER, HEAD, True),
            axiom_closure(["bad"], CASE, TOOLING, NOW), no_sorry(True, CASE, TOOLING, NOW),
        ] + from_jinshi([{"check": "a", "severity": "fail", "module": "M", "name": "n", "detail": "d"}], CASE, TOOLING, ["a", "b"], NOW)
        self.assertGreater(len(records), 15)
        for r in records:
            self.assertEqual(jvalidate(r), [], r["kind"])

    def test_a_healthy_set_with_independent_checkers_is_accepted_at_the_lower_tier(self):
        verdict = judge(healthy_outputs())
        self.assertEqual(verdict["decision"], "ACCEPT", verdict["reasons"])
        self.assertEqual(verdict["tier"], 0)
        self.assertEqual(verdict["merit_unmet"], [])
        self.assertEqual(verdict["ignored_evidence"], [])

    def test_with_only_two_checkers_it_is_accepted_but_not_at_the_lower_tier(self):
        verdict = judge(healthy_outputs(checkers=("lean-kernel", "lean4lean")))
        self.assertEqual(verdict["decision"], "ACCEPT", verdict["reasons"])
        self.assertEqual(verdict["tier"], 1)
        self.assertTrue(any("2 of 3 independent checkers" in u for u in verdict["merit_unmet"]))

    def test_fabricated_attested_records_change_nothing(self):
        for checkers in (("lean-kernel", "lean4lean", "nanoda"), ("lean-kernel", "lean4lean")):
            base = healthy_outputs(checkers=checkers)
            plain = judge(base)
            padded = judge(base + fabricated_praise())
            self.assertEqual(comparable(plain), comparable(padded), checkers)
            self.assertNotEqual(plain["evidence_digest"], padded["evidence_digest"])  # they were seen, and weighed at zero

    def test_praise_cannot_outweigh_a_failed_check(self):
        failed = from_jinshi([{"check": "axioms", "severity": "fail", "module": "M", "name": "n", "detail": "d"}],
                             CASE, TOOLING, ["axioms"], NOW)
        verdict = judge(healthy_outputs() + fabricated_praise() + failed)
        self.assertEqual(verdict["decision"], "REJECT")

    def test_two_tools_that_disagree_about_axioms_send_the_case_to_a_person(self):
        other = {"role": "tooling", "name": "axiom-gate-2", "identity": "axiom-gate-2"}
        verdict = judge(healthy_outputs() + [axiom_closure(["myOwnAxiom"], CASE, other, NOW)])
        self.assertEqual(verdict["decision"], "ESCALATE")

    def test_a_declared_check_that_is_not_reported_holds_the_case(self):
        extra = manifest(CASE, PRAISER, ["mechanical.restatement_match"], NOW)
        verdict = judge(healthy_outputs() + [extra])
        self.assertEqual(verdict["decision"], "HOLD")
        self.assertIn("mechanical.restatement_match", verdict["missing"])
        verdict = judge(healthy_outputs() + [extra, restatement_evidence(
            CASE, PRAISER, ai_model="m", ai_family="f", prompt_sha256=H, equivalent=True, checker_command="c", created=NOW)])
        self.assertEqual(verdict["decision"], "ACCEPT")

    def test_an_unlabeled_or_inconclusive_record_never_lowers_scrutiny(self):
        chain = Chain()
        chain.accepted(60, label=None)
        verdict = judge(healthy_outputs(ledger=chain))
        self.assertEqual(verdict["decision"], "ACCEPT")
        self.assertGreaterEqual(verdict["tier"], 1)

    def test_a_forged_track_record_is_caught_by_re_derivation(self):
        chain = Chain()
        chain.accepted(8)  # an honest, thin record
        chain.accepted(1, label="reject")
        honest = track_record_evidence("agent-7", chain.entries, CASE, PRAISER, NOW)
        self.assertEqual(verify_against_ledger(honest, chain.entries), (True, []))
        forged = copy.deepcopy(honest)
        forged["details"]["lower_bound"] = 0.99
        forged["id"] = compute_id(forged)
        self.assertEqual(jvalidate(forged), [], "the forgery is well formed, so only re-derivation can catch it")
        ok, problems = verify_against_ledger(forged, chain.entries)
        self.assertFalse(ok)
        self.assertTrue(any("lower_bound" in p for p in problems))

    def test_the_real_ledger_and_this_repositorys_hash_agree(self):
        body = {"a": [1, 2], "b": "ü"}
        self.assertEqual(entry_hash(3, "label", body, GENESIS), jentry_hash(3, "label", body, GENESIS))
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(os.path.join(tmp, "ledger.jsonl"))
            for entry in author_ledger(3).entries:
                ledger.append(entry["kind"], entry["body"])
            entries = ledger.entries()
            self.assertEqual(verify_chain(entries), (True, None))
            self.assertEqual(ledger.verify(), (True, None))
            self.assertEqual(entries, author_ledger(3).entries)
            entries[2]["body"] = dict(entries[2]["body"], decision="REJECT")
            self.assertEqual(verify_chain(entries)[0], False)

    def test_a_track_record_from_a_ledger_written_by_the_real_judge_flow(self):
        """Verdicts as the juridicator CLI writes them (evidence entries, then the verdict dict), then a human label."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(os.path.join(tmp, "ledger.jsonl"))
            for n in range(12):
                head = f"{n + 1:040x}"
                case = dict(CASE, head_sha=head)
                evidence = healthy_outputs(ledger=author_ledger(1))
                evidence = [make_evidence(**{**{k: e[k] for k in ("producer", "kind", "claim", "outcome", "verifiability", "created", "subject", "reproduce", "ai", "details")},
                                             "case": {"repo": CASE["repo"], "head_sha": head, "class": "content"}}) for e in evidence]
                for e in evidence:
                    ledger.append("evidence", e)
                verdict = decide(case, evidence, None, standing=STANDING)
                self.assertEqual(verdict["decision"], "ACCEPT", verdict["reasons"])
                ledger.append("verdict", verdict)
                ledger.append("label", {"repo": CASE["repo"], "head_sha": head, "label": "accept", "by": "alice"})
            entries = ledger.entries()
            record = track_record_evidence("agent-7", entries, CASE, PRAISER, NOW)
            self.assertEqual((record["details"]["n_good"], record["details"]["n_bad"]), (12, 0))
            self.assertEqual(verify_against_ledger(record, entries), (True, []))

    def test_the_trust_card_matches_the_real_verdicts_evidence_digest(self):
        base = healthy_outputs()
        selfish = make_evidence(case={k: CASE[k] for k in ("repo", "head_sha", "class")},
                                producer={"role": "tooling", "name": "agent-7", "identity": "agent-7"},
                                kind="mechanical.kernel_check", claim="I verified my own work", outcome="pass",
                                verifiability="mechanical", created=NOW, reproduce={"command": "true"})
        stale = from_checkers({"old-checker": "accept"}, dict(CASE, head_sha=OLDER), NOW)
        evidence = base + fabricated_praise() + [selfish] + stale
        verdict = judge(evidence)
        self.assertEqual(len(verdict["ignored_evidence"]), 2)
        text = trustcard.render(verdict, evidence)
        self.assertNotIn("Warning", text)
        self.assertIn("accepted it (3): lean-kernel, lean4lean, nanoda.", text)
        self.assertIn("Scrutiny level 0", text)
        self.assertIn("Noted, not weighed: the most reliable system ever built", text)
        self.assertNotIn("old-checker", text)
        self.assertEqual(text, trustcard.render(verdict, list(reversed(evidence))))


class WithoutASibling(unittest.TestCase):
    def test_the_praisers_own_checks_run_without_the_juridicator(self):
        records = healthy_outputs()
        self.assertTrue(all(isinstance(canonical_json(r), str) for r in records))


if __name__ == "__main__":
    unittest.main()
