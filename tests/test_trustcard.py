import random
import unittest

from vendor.juridicator_evidence import canonical_json, make_evidence, sha256_text
from praiser import trustcard
from praiser.attest import attested_claim, check_provenance, provenance_attestation
from praiser.common import sha256_bytes
from praiser.merit import axiom_closure, from_checkers, from_jinshi, no_sorry
from praiser.receipts import compare_receipts, make_receipt
from praiser.restatement import restatement_evidence
from praiser.track_record import track_record_evidence
from tests.helpers import AUTHOR, CASE, H, H2, HEAD, NOW, OLDER, PRAISER, TOOLING, Chain, case


def digest(evs):
    return "sha256:" + sha256_text(canonical_json(sorted({e["id"] for e in evs})))


def verdict_for(evs, decision="ACCEPT", tier=0, rate=0.05, **over):
    v = {"case": {"repo": CASE["repo"], "head_sha": HEAD, "class": "content"}, "decision": decision, "tier": tier,
         "audit_rate": rate, "reasons": [], "missing": [], "merit_unmet": [], "ignored_evidence": [],
         "evidence_digest": digest(evs)}
    v.update(over)
    return v


def provenance_pass():
    files = {"p.md": b"prompt"}
    decl = provenance_attestation(CASE, AUTHOR, model="m", model_family="f", prompt_sha256={"p.md": sha256_bytes(b"prompt")},
                                  tool_manifest={"t.json": sha256_bytes(b"t")}, toolchain={"lean-toolchain": sha256_bytes(b"c")},
                                  rubric_version="r1", human_signoffs=["alice"], created=NOW)
    files.update({"t.json": b"t", "lean-toolchain": b"c"})
    return decl, check_provenance(decl, files, CASE, PRAISER, NOW)


def rebuild(outcome="pass"):
    a = make_receipt("lake build", H, H2, 0, runner="r1")
    b = make_receipt("lake build", H, H2, 0 if outcome != "fail" else 1, runner="r2" if outcome != "inconclusive" else "r1")
    return compare_receipts(a, b, CASE, PRAISER, NOW)


def track(n_good=40):
    c = Chain()
    c.accepted(n_good)
    return track_record_evidence("agent-7", c.entries, CASE, PRAISER, NOW)


def healthy():
    decl, prov = provenance_pass()
    return (from_checkers({"lean-kernel": "accept", "lean4lean": "accept", "nanoda": "accept"}, CASE, NOW)
            + [axiom_closure(["propext", "Quot.sound"], CASE, TOOLING, NOW), no_sorry(False, CASE, TOOLING, NOW), decl, prov,
               rebuild(), track()])


def card(evs, **kw):
    return trustcard.render(verdict_for(evs, **kw), evs)


class Sections(unittest.TestCase):
    def test_accept_card_says_who_agreed_what_axioms_rebuild_and_provenance(self):
        text = card(healthy())
        self.assertIn("This content was accepted", text)
        self.assertIn("accepted it (3): lean-kernel, lean4lean, nanoda", text)
        self.assertIn("Axioms used: Quot.sound, propext", text)
        self.assertIn("no unfinished proofs (sorry) were found", text)
        self.assertIn("Independent rebuild: yes, two different runners", text)
        self.assertIn("the stored prompts, tool manifest and toolchain files match", text)
        self.assertIn("## What this does not claim", text)

    def test_every_decision_has_a_plain_sentence(self):
        for d, phrase in (("ACCEPT", "accepted"), ("HOLD", "on hold"), ("ESCALATE", "needs a person"), ("REJECT", "rejected")):
            self.assertIn(phrase, card(healthy(), decision=d))

    def test_missing_items_are_listed(self):
        self.assertIn("Still missing: mechanical.no\\_sorry.", card(healthy(), decision="HOLD", missing=["mechanical.no_sorry"]))

    def test_dissenting_and_silent_checkers_are_named(self):
        evs = from_checkers({"a": "accept", "b": "reject", "c": "timeout"}, CASE, NOW)
        text = card(evs, decision="ESCALATE")
        self.assertIn("accepted it (1): a", text)
        self.assertIn("REJECTED it: b", text)
        self.assertIn("gave no answer: c", text)

    def test_no_checkers_axioms_rebuild_or_provenance(self):
        text = card([], decision="HOLD")
        self.assertIn("accepted it (0): none", text)
        self.assertIn("no axiom check was reported", text)
        self.assertIn("Independent rebuild: none was reported", text)
        self.assertIn("not checked against stored files", text)

    def test_failed_axiom_rebuild_and_provenance_are_loud(self):
        decl, _ = provenance_pass()
        bad_prov = check_provenance(decl, {}, CASE, PRAISER, NOW)
        evs = [axiom_closure(["propext", "weirdAxiom"], CASE, TOOLING, NOW), rebuild("fail"), bad_prov, no_sorry(True, CASE, TOOLING, NOW)]
        text = card(evs, decision="REJECT")
        self.assertIn("outside the allowed list: weirdAxiom", text)
        self.assertIn("NO, the rebuilds differ (exit\\_code)", text)
        self.assertIn("does NOT match", text)
        self.assertIn("WERE found", text)

    def test_rebuild_from_one_runner_is_not_shown_as_independent(self):
        self.assertIn("could not be told apart as independent", card([rebuild("inconclusive")]))

    def test_jinshi_results(self):
        evs = from_jinshi([{"check": "axioms", "severity": "fail", "module": "M", "name": "n", "detail": "d"}], CASE, TOOLING,
                          ["axioms", "universes", "stale"], NOW, ran=["universes"])
        text = card(evs, decision="REJECT")
        self.assertIn("passed: universes; failed: axioms; not run or undecided: stale", text)

    def test_tier_and_audit_chance_in_words(self):
        self.assertIn("Scrutiny level 0 (light", card(healthy(), tier=0, rate=0.05))
        self.assertIn("About 1 in 20 acceptances", card(healthy(), tier=0, rate=0.05))
        self.assertIn("About 1 in 5 acceptances", card(healthy(), tier=1, rate=0.2))
        self.assertIn("Every acceptance at this level is re-examined", card(healthy(), tier=3, rate=1.0))
        self.assertIn("The level was not lowered because: 2 of 3 independent checkers", card(healthy(), merit_unmet=["2 of 3 independent checkers"]))

    def test_missing_tier_is_stated_not_invented(self):
        v = verdict_for([], tier=None, rate=None)
        self.assertIn("scrutiny level was not stated", trustcard.render(v, []))

    def test_preregistration_line(self):
        from praiser.preregistration import check_preregistration, commit_statement
        ev = check_preregistration(commit_statement("s", "n"), "s", "n", CASE, PRAISER, NOW, OLDER, HEAD, True)
        self.assertIn("Statement fixed before the proof: yes", card([ev]))


class TrackRecord(unittest.TestCase):
    def test_in_words_with_uncertainty_and_how_to_recompute(self):
        text = card([track(40)])
        self.assertIn("95% confidence", text)
        self.assertIn("at least 91%", text)
        self.assertIn("40 confirmed good and 0 confirmed bad", text)
        self.assertIn("python3 -m praiser track-record", text)

    def test_the_newest_snapshot_is_the_one_shown(self):
        c = Chain()
        c.accepted(20)
        old = track_record_evidence("agent-7", c.entries, CASE, PRAISER, NOW)
        c.accepted(30)
        new = track_record_evidence("agent-7", c.entries, CASE, PRAISER, NOW)
        for evs in ([old, new], [new, old]):
            text = card(evs)
            self.assertIn("50 confirmed good", text)
            self.assertNotIn("20 confirmed good", text)

    def test_few_cases_are_called_out(self):
        self.assertIn("few cases", card([track(5)]))
        self.assertNotIn("few cases", card([track(60)]))

    def test_no_usable_record(self):
        c = Chain()
        c.accepted(5, label=None)
        self.assertIn("no usable track record", card([track_record_evidence("agent-7", c.entries, CASE, PRAISER, NOW)]))

    def test_absent(self):
        self.assertIn("No track record was supplied", card([]))


class WhatThisDoesNotClaim(unittest.TestCase):
    def test_fidelity_not_claimed_without_a_restatement_match(self):
        text = card(healthy())
        self.assertIn("not a proof that the formal statement is faithful", text)
        self.assertIn("no restatement match is present", text)

    def test_with_a_passing_restatement_match_it_still_is_not_a_proof(self):
        rm = restatement_evidence(CASE, PRAISER, ai_model="m", ai_family="f", prompt_sha256=H, equivalent=True, checker_command="c", created=NOW)
        text = card(healthy() + [rm])
        self.assertIn("A restatement match is present", text)
        self.assertIn("still not a proof", text)
        self.assertNotIn("no restatement match is present", text)

    def test_failed_or_undecided_restatement(self):
        for eq, phrase in ((False, "NOT equivalent"), (None, "could not decide")):
            rm = restatement_evidence(CASE, PRAISER, ai_model="m", ai_family="f", prompt_sha256=H, equivalent=eq, checker_command="c", created=NOW)
            self.assertIn(phrase, card([rm]))

    def test_unchecked_praise_is_listed_as_noted_not_weighed(self):
        praise = attested_claim(CASE, AUTHOR, "team", "a world-class careful team", NOW)
        text = card(healthy() + [praise])
        self.assertIn("Noted, not weighed: a world-class careful team (by agent-7)", text)
        self.assertIn("It changed nothing", text)
        self.assertIn("Nothing of that kind was submitted", card(healthy()[:3]))

    def test_a_manifest_is_a_promise_not_praise(self):
        from praiser.merit import manifest
        text = card(healthy() + [manifest(CASE, PRAISER, ["mechanical.no_sorry"], NOW)])
        self.assertNotIn("Will report", text)

    def test_the_provenance_declaration_is_noted_not_weighed_too(self):
        text = card(healthy())
        self.assertIn("Noted, not weighed: Declared, not verified", text)

    def test_ignored_records_are_counted_and_not_shown(self):
        fake = make_evidence(case=case(), producer={"role": "tooling", "name": "agent-7", "identity": "agent-7"},
                             kind="mechanical.kernel_check", claim="I checked my own work", outcome="pass",
                             verifiability="mechanical", created=NOW, reproduce={"command": "x"})
        evs = healthy()
        v = verdict_for(evs, ignored_evidence=[{"id": fake["id"], "why": "the author cannot vouch for their own work"}])
        text = trustcard.render(v, evs + [fake])
        self.assertNotIn("Warning", text)
        self.assertIn("accepted it (3): lean-kernel, lean4lean, nanoda.", text)
        self.assertIn("1 record(s) were ignored", text)

    def test_evidence_about_another_commit_is_not_shown(self):
        other = from_checkers({"stranger": "accept"}, case(OLDER), NOW)
        text = trustcard.render(verdict_for(healthy()), healthy() + other)
        self.assertNotIn("stranger", text)


class Safety(unittest.TestCase):
    def test_untrusted_text_cannot_plant_links_html_or_headings(self):
        evil = attested_claim(CASE, AUTHOR, "note", "[click](http://evil.example) <script>alert(1)</script> # heading `code` *bold*\x00\x1b", NOW)
        text = card([evil])
        line = [ln for ln in text.splitlines() if "Noted, not weighed" in ln][0]
        self.assertNotIn("<script>", line)
        self.assertNotIn("](http", line)
        self.assertIn("\\[click\\]\\(http", line)
        self.assertIn("\\<script\\>", line)
        self.assertNotIn("\x00", text)
        self.assertNotIn("\x1b", text)

    def test_a_malicious_checker_name_is_escaped_and_cannot_break_the_line(self):
        evs = from_checkers({"x\n## Fake heading <b>": "accept"}, CASE, NOW)
        text = card(evs)
        self.assertNotIn("\n## Fake heading", text)
        self.assertIn("\\#\\# Fake heading \\<b\\>", text)

    def test_reasons_are_escaped(self):
        text = card(healthy(), reasons=[{"rule": "R1", "text": "see [x](http://e) now", "evidence": []}])
        self.assertIn("see \\[x\\]\\(http://e\\) now", text)


class Determinism(unittest.TestCase):
    def test_same_text_in_any_order(self):
        evs = healthy() + [attested_claim(CASE, AUTHOR, "note", "n", NOW)]
        first = card(evs)
        for seed in range(5):
            shuffled = evs[:]
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(card(shuffled), first)

    def test_duplicates_are_shown_once(self):
        evs = healthy()
        self.assertEqual(card(evs + evs), card(evs))

    def test_a_card_that_does_not_match_the_judges_evidence_warns(self):
        evs = healthy()
        v = verdict_for(evs)
        text = trustcard.render(v, evs[:-1])
        self.assertIn("does not match the evidence the judge weighed", text)
        self.assertNotIn("Warning", trustcard.render(v, evs))

    def test_invalid_records_are_not_shown_and_trip_the_warning(self):
        evs = healthy()
        broken = dict(evs[0], claim="tampered")
        text = trustcard.render(verdict_for(evs), [broken] + evs[1:])
        self.assertIn("Warning", text)
        self.assertNotIn("tampered", text)

    def test_bad_verdicts_are_refused(self):
        for bad in (None, {}, {"decision": "MAYBE", "case": {}}, {"decision": "ACCEPT"}):
            with self.assertRaises(ValueError):
                trustcard.render(bad, [])

    def test_ends_with_a_newline_and_has_no_jargon_words(self):
        text = card(healthy())
        self.assertTrue(text.endswith("\n"))
        for word in ("mechanical", "attested", "verifiability", "R7", "R9"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
