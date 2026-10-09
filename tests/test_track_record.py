import copy
import unittest

from vendor.juridicator_evidence import compute_id, make_evidence, validate
from praiser.track_record import (
    FAILURE_WEIGHT, GENESIS, HALF_LIFE, LedgerError, compute, entry_hash, label_body, track_record_evidence,
    verify_against_ledger, verify_chain, wilson_lower,
)
from tests.helpers import CASE, NOW, PRAISER, REPO, Chain, sha, tamper


def lb(good_weight, bad_weight=0.0):
    return round(wilson_lower(good_weight, good_weight + FAILURE_WEIGHT * bad_weight), 6)


def restamp(rec, **detail_changes):
    forged = copy.deepcopy(rec)
    forged["details"].update(detail_changes)
    forged["id"] = compute_id(forged)
    return forged


class Wilson(unittest.TestCase):
    def test_known_values(self):
        self.assertAlmostEqual(wilson_lower(9, 10), 0.596, places=3)
        self.assertAlmostEqual(wilson_lower(90, 100), 0.826, places=3)
        self.assertEqual(wilson_lower(0, 0), 0.0)

    def test_more_evidence_raises_the_bound_and_failures_lower_it(self):
        self.assertGreater(wilson_lower(100, 100), wilson_lower(10, 10))
        self.assertGreater(wilson_lower(10, 10), wilson_lower(9, 10))
        self.assertEqual(wilson_lower(0, 10), 0.0)
        self.assertLess(wilson_lower(100, 100), 1.0)

    def test_negative_n_and_fractional_counts(self):
        self.assertEqual(wilson_lower(1, -3), 0.0)
        self.assertGreater(wilson_lower(8.5, 10.5), 0.0)

    def test_constants_are_the_documented_ones(self):
        self.assertEqual((HALF_LIFE, FAILURE_WEIGHT), (200, 10))


class Counting(unittest.TestCase):
    def test_labelled_accepts_count_and_unlabelled_count_for_nothing(self):
        c = Chain()
        c.accepted(5, label="accept")
        c.accepted(7, label=None)
        s = compute(c.entries, "agent-7")
        self.assertEqual((s["n_good"], s["n_bad"], s["n_unlabeled"]), (5, 0, 7))
        only_unlabeled = Chain()
        only_unlabeled.accepted(30, label=None)
        s = compute(only_unlabeled.entries, "agent-7")
        self.assertEqual((s["n_good"], s["lower_bound"]), (0, 0.0))

    def test_confirmed_bad_is_counted_and_costs_ten_failures(self):
        c = Chain()
        c.accepted(20, label="accept")
        c.accepted(1, label="reject")
        s = compute(c.entries, "agent-7")
        self.assertEqual((s["n_good"], s["n_bad"]), (20, 1))
        # ages: the last outcome has age 0, the rest are older by one position each
        gw = sum(0.5 ** ((20 - i) / 200) for i in range(20))
        self.assertAlmostEqual(s["weighted_good"], gw, places=4)
        self.assertEqual(s["lower_bound"], lb(gw, 1.0))
        without_penalty = round(wilson_lower(gw, gw + 1.0), 6)
        self.assertLess(s["lower_bound"], without_penalty - 0.2)

    def test_one_bad_among_many_good_drops_the_bound_below_a_clean_record(self):
        clean, dirty = Chain(), Chain()
        clean.accepted(40)
        dirty.accepted(39)
        dirty.accepted(1, label="reject")
        self.assertGreater(compute(clean.entries, "agent-7")["lower_bound"], compute(dirty.entries, "agent-7")["lower_bound"] + 0.2)

    def test_a_label_by_the_author_is_ignored(self):
        c = Chain()
        c.accepted(10, label="accept", by="agent-7")
        s = compute(c.entries, "agent-7")
        self.assertEqual((s["n_good"], s["n_unlabeled"], s["lower_bound"]), (0, 10, 0.0))

    def test_a_self_reject_is_ignored_too(self):
        c = Chain()
        c.accepted(3, label="reject", by="agent-7")
        self.assertEqual(compute(c.entries, "agent-7")["n_bad"], 0)

    def test_labels_by_non_human_producers_are_ignored(self):
        c = Chain()
        head = c.accepted(1, label=None)[0]
        c.add("evidence", make_evidence(case={"repo": REPO, "head_sha": head, "class": "content"},
                                        producer={"role": "praiser", "name": "p", "identity": "the-praiser"},
                                        kind="attested.note", claim="x", outcome="pass", verifiability="attested", created=NOW))
        c.label(head, "accept", by="the-praiser")
        self.assertEqual(compute(c.entries, "agent-7")["n_good"], 0)
        c.label(head, "accept", by="alice")
        self.assertEqual(compute(c.entries, "agent-7")["n_good"], 1)

    def test_an_allow_list_restricts_labelers(self):
        c = Chain()
        c.accepted(4, label="accept", by="mallory")
        c.accepted(2, label="accept", by="alice")
        self.assertEqual(compute(c.entries, "agent-7")["n_good"], 6)
        s = compute(c.entries, "agent-7", humans=["alice"])
        self.assertEqual((s["n_good"], s["n_unlabeled"]), (2, 4))

    def test_a_label_before_the_accept_does_not_count(self):
        c = Chain()
        head = sha(5)
        c.provenance(head)
        c.label(head, "accept")
        c.verdict(head)
        self.assertEqual(compute(c.entries, "agent-7")["n_good"], 0)

    def test_only_a_final_accept_counts(self):
        c = Chain()
        head = sha(5)
        c.provenance(head)
        c.verdict(head, "HOLD")
        c.label(head, "accept")
        self.assertEqual(compute(c.entries, "agent-7")["n_good"], 0)
        c2 = Chain()
        c2.provenance(head)
        c2.verdict(head, "ACCEPT")
        c2.verdict(head, "REJECT")
        c2.label(head, "accept")
        self.assertEqual(compute(c2.entries, "agent-7")["n_good"], 0)

    def test_a_reject_from_any_valid_labeler_wins(self):
        c = Chain()
        head = c.accepted(1, label="accept", by="alice")[0]
        c.label(head, "reject", by="bob")
        s = compute(c.entries, "agent-7")
        self.assertEqual((s["n_good"], s["n_bad"]), (0, 1))

    def test_a_labeler_can_correct_their_own_label(self):
        c = Chain()
        head = c.accepted(1, label="reject", by="alice")[0]
        c.label(head, "accept", by="alice")
        s = compute(c.entries, "agent-7")
        self.assertEqual((s["n_good"], s["n_bad"]), (1, 0))

    def test_a_commit_claimed_by_two_systems_gives_no_credit_but_blame_is_shared(self):
        c = Chain()
        head = sha(9)
        c.provenance(head, "agent-7")
        c.provenance(head, "agent-8")
        c.verdict(head)
        c.label(head, "accept")
        for who in ("agent-7", "agent-8"):
            s = compute(c.entries, who)
            self.assertEqual((s["n_good"], s["n_ambiguous"]), (0, 1))
        c.label(head, "reject", by="bob")
        for who in ("agent-7", "agent-8"):
            self.assertEqual(compute(c.entries, who)["n_bad"], 1)

    def test_only_author_system_provenance_attributes_a_commit(self):
        c = Chain()
        head = sha(11)
        c.add("evidence", make_evidence(case={"repo": REPO, "head_sha": head, "class": "content"},
                                        producer={"role": "praiser", "name": "p", "identity": "agent-7"},
                                        kind="attested.provenance", claim="x", outcome="pass", verifiability="attested", created=NOW))
        c.verdict(head)
        c.label(head, "accept")
        self.assertEqual(compute(c.entries, "agent-7")["n_good"], 0)

    def test_other_authors_and_other_repos_do_not_mix(self):
        c = Chain()
        c.accepted(5, author="agent-8")
        self.assertEqual(compute(c.entries, "agent-7")["n_good"], 0)
        self.assertEqual(compute(c.entries, "agent-8")["n_good"], 5)
        d = Chain()
        head = sha(3)
        d.provenance(head)
        d.add("verdict", {"case": {"repo": "other/repo", "head_sha": head, "class": "content"}, "decision": "ACCEPT"})
        d.add("label", {"repo": "other/repo", "head_sha": head, "label": "accept", "by": "alice"})
        self.assertEqual(compute(d.entries, "agent-7")["n_good"], 0)

    def test_malformed_entries_and_invalid_evidence_are_skipped(self):
        c = Chain()
        c.add("label", {"repo": REPO, "head_sha": sha(1), "label": "maybe", "by": "alice"})
        c.add("label", {"repo": REPO, "head_sha": sha(1), "label": "accept", "by": ""})
        c.add("verdict", {"case": "nope", "decision": "ACCEPT"})
        c.add("verdict", {"case": {"repo": REPO, "head_sha": sha(1)}, "decision": 5})
        c.add("label", "string body")
        c.add("evidence", {"kind": "attested.provenance"})  # not valid evidence
        c.add("mystery", {"x": 1})
        s = compute(c.entries, "agent-7")
        self.assertEqual((s["n_good"], s["n_bad"], s["lower_bound"]), (0, 0, 0.0))


class Decay(unittest.TestCase):
    def test_older_outcomes_weigh_less_with_the_documented_half_life(self):
        c = Chain()
        c.accepted(1, author="agent-7")
        c.accepted(200, author="agent-8")
        s = compute(c.entries, "agent-7")
        self.assertAlmostEqual(s["weighted_good"], 0.5 ** (200 / HALF_LIFE), places=5)
        self.assertEqual(s["lower_bound"], lb(0.5))
        c.accepted(200, author="agent-8")
        self.assertAlmostEqual(compute(c.entries, "agent-7")["weighted_good"], 0.25, places=5)

    def test_the_newest_outcome_has_full_weight(self):
        c = Chain()
        c.accepted(1)
        self.assertEqual(compute(c.entries, "agent-7")["weighted_good"], 1.0)

    def test_volume_cannot_buy_more_than_the_documented_ceiling(self):
        c = Chain()
        c.accepted(700)
        s = compute(c.entries, "agent-7")
        self.assertEqual(s["n_good"], 700)
        self.assertLess(s["lower_bound"], 0.9875)
        self.assertGreater(s["lower_bound"], 0.95)

    def test_a_confirmed_bad_fades_slowly_but_surely(self):
        c = Chain()
        c.accepted(1, label="reject")
        recent = compute(c.entries, "agent-7")["weighted_bad"]
        c.accepted(400, author="agent-8")
        self.assertAlmostEqual(compute(c.entries, "agent-7")["weighted_bad"], recent * 0.25, places=5)


class AsOf(unittest.TestCase):
    def test_as_of_seq_looks_at_a_prefix(self):
        c = Chain()
        c.accepted(3)
        mid = len(c.entries) - 1
        c.accepted(3)
        self.assertEqual(compute(c.entries, "agent-7", as_of_seq=mid)["n_good"], 3)
        self.assertEqual(compute(c.entries, "agent-7")["n_good"], 6)
        self.assertEqual(compute(c.entries, "agent-7", as_of_seq=mid)["ledger_head"], c.entries[mid]["hash"])

    def test_empty_ledger(self):
        s = compute([], "agent-7")
        self.assertEqual((s["as_of_seq"], s["ledger_head"], s["lower_bound"]), (-1, GENESIS, 0.0))

    def test_out_of_range_refused(self):
        c = Chain()
        c.accepted(1)
        for bad in (len(c.entries), 99, -2, True):
            with self.assertRaises(LedgerError):
                compute(c.entries, "agent-7", as_of_seq=bad)

    def test_a_broken_chain_is_refused(self):
        c = Chain()
        c.accepted(3)
        with self.assertRaises(LedgerError):
            compute(tamper(c.entries, 2, decision="ACCEPT", extra=1), "agent-7")
        self.assertEqual(verify_chain(c.entries), (True, None))
        self.assertEqual(verify_chain(tamper(c.entries, 1, x=1)), (False, 1))
        self.assertEqual(verify_chain(c.entries[1:]), (False, 0))
        self.assertEqual(verify_chain(["x"]), (False, 0))

    def test_entry_hash_is_the_ledgers_formula(self):
        self.assertTrue(entry_hash(0, "evidence", {"a": 1}, GENESIS).startswith("sha256:"))
        self.assertNotEqual(entry_hash(0, "evidence", {"a": 1}, GENESIS), entry_hash(1, "evidence", {"a": 1}, GENESIS))

    def test_label_body(self):
        self.assertEqual(label_body("r", "h", "accept", "alice"), {"repo": "r", "head_sha": "h", "label": "accept", "by": "alice"})
        with self.assertRaises(ValueError):
            label_body("r", "h", "yes", "alice")


class Evidence(unittest.TestCase):
    def build(self, n=40):
        c = Chain()
        c.accepted(n)
        return c

    def test_a_record_with_the_required_details(self):
        c = self.build()
        rec = track_record_evidence("agent-7", c.entries, CASE, PRAISER, NOW)
        self.assertEqual(validate(rec), [])
        self.assertEqual((rec["kind"], rec["verifiability"], rec["outcome"]), ("reproducible.track_record", "reproducible", "pass"))
        d = rec["details"]
        for k in ("lower_bound", "n_good", "n_bad", "as_of_seq"):
            self.assertIn(k, d)
        self.assertEqual(d["as_of_seq"], len(c.entries) - 1)
        self.assertEqual(d["author_system"], "agent-7")
        self.assertIn("python3 -m praiser track-record", rec["reproduce"]["command"])
        self.assertIn("--author agent-7", rec["reproduce"]["command"])
        self.assertIn(f"--as-of {d['as_of_seq']}", rec["reproduce"]["command"])

    def test_the_author_name_is_shell_quoted_in_the_command(self):
        c = Chain()
        c.accepted(2, author="agent; rm -rf /")
        rec = track_record_evidence("agent; rm -rf /", c.entries, CASE, PRAISER, NOW)
        self.assertIn("'agent; rm -rf /'", rec["reproduce"]["command"])

    def test_no_outcomes_is_inconclusive(self):
        rec = track_record_evidence("agent-7", [], CASE, PRAISER, NOW)
        self.assertEqual(rec["outcome"], "inconclusive")
        self.assertEqual(validate(rec), [])
        c = Chain()
        c.accepted(10, label=None)
        self.assertEqual(track_record_evidence("agent-7", c.entries, CASE, PRAISER, NOW)["outcome"], "inconclusive")

    def test_a_poor_record_is_still_a_pass_with_a_low_bound(self):
        c = Chain()
        c.accepted(30)
        c.accepted(1, label="reject")
        rec = track_record_evidence("agent-7", c.entries, CASE, PRAISER, NOW)
        self.assertEqual(rec["outcome"], "pass")
        self.assertLess(rec["details"]["lower_bound"], 0.9)

    def test_deterministic(self):
        c = self.build()
        self.assertEqual(track_record_evidence("agent-7", c.entries, CASE, PRAISER, NOW), track_record_evidence("agent-7", c.entries, CASE, PRAISER, NOW))

    def test_bad_author_refused(self):
        with self.assertRaises(ValueError):
            track_record_evidence("", [], CASE, PRAISER, NOW)


class Verify(unittest.TestCase):
    def setUp(self):
        self.c = Chain()
        self.c.accepted(40)
        self.rec = track_record_evidence("agent-7", self.c.entries, CASE, PRAISER, NOW)

    def check(self, rec=None, entries=None, **kw):
        return verify_against_ledger(rec or self.rec, entries or self.c.entries, **kw)

    def test_an_honest_record_verifies(self):
        self.assertEqual(self.check(), (True, []))

    def test_a_forged_lower_bound_is_caught_even_with_a_valid_id(self):
        forged = restamp(self.rec, lower_bound=0.99)
        self.assertEqual(validate(forged), [])
        ok, problems = self.check(forged)
        self.assertFalse(ok)
        self.assertTrue(any("lower_bound" in p for p in problems), problems)

    def test_forged_counts_and_head_are_caught(self):
        for field, value in (("n_good", 400), ("n_bad", 0 if self.rec["details"]["n_bad"] else 1), ("weighted_good", 399.0),
                             ("ledger_head", "sha256:" + "1" * 64)):
            ok, problems = self.check(restamp(self.rec, **{field: value}))
            self.assertFalse(ok, field)
            self.assertTrue(any(field in p for p in problems), (field, problems))

    def test_a_forged_outcome_is_caught(self):
        forged = copy.deepcopy(self.rec)
        forged["outcome"] = "inconclusive"
        forged["id"] = compute_id(forged)
        self.assertFalse(self.check(forged)[0])

    def test_a_record_for_a_ledger_state_that_does_not_exist(self):
        ok, problems = self.check(restamp(self.rec, as_of_seq=5000))
        self.assertFalse(ok)
        self.assertIn("outside the ledger", " ".join(problems))
        self.assertFalse(self.check(restamp(self.rec, as_of_seq="x"))[0])
        self.assertFalse(self.check(restamp(self.rec, author_system=None))[0])

    def test_a_record_that_is_not_valid_evidence_is_caught(self):
        forged = copy.deepcopy(self.rec)
        forged["details"]["lower_bound"] = 0.99  # id no longer matches
        ok, problems = self.check(forged)
        self.assertFalse(ok)
        self.assertIn("id does not match", " ".join(problems))
        self.assertFalse(self.check("nope")[0])

    def test_the_wrong_kind_is_caught(self):
        other = make_evidence(case={"repo": REPO, "head_sha": CASE["head_sha"], "class": "content"}, producer=PRAISER,
                              kind="attested.note", claim="x", outcome="pass", verifiability="attested", created=NOW)
        self.assertEqual(self.check(other), (False, ["not a track record"]))

    def test_a_tampered_ledger_is_caught(self):
        ok, problems = self.check(entries=tamper(self.c.entries, 1, x=1))
        self.assertFalse(ok)
        self.assertIn("hash chain", " ".join(problems))

    def test_cherry_picking_an_old_snapshot_before_a_bad_outcome_is_caught(self):
        self.c.accepted(1, label="reject")
        ok, problems = self.check()
        self.assertFalse(ok)
        self.assertIn("after the snapshot", " ".join(problems))

    def test_a_later_good_outcome_does_not_invalidate_an_old_snapshot(self):
        self.c.accepted(5)
        self.assertEqual(self.check(), (True, []))

    def test_max_lag(self):
        self.c.accepted(5)
        self.assertEqual(self.check(max_lag=100)[0], True)
        ok, problems = self.check(max_lag=3)
        self.assertFalse(ok)
        self.assertIn("old", " ".join(problems))

    def test_labelers_must_match_the_verifiers_allow_list(self):
        ok, problems = self.check(humans=["alice"])
        self.assertFalse(ok)
        self.assertIn("accepted labelers", " ".join(problems))
        rec = track_record_evidence("agent-7", self.c.entries, CASE, PRAISER, NOW, humans=["alice"])
        self.assertEqual(verify_against_ledger(rec, self.c.entries, humans=["alice"]), (True, []))
        self.assertFalse(verify_against_ledger(rec, self.c.entries)[0])
        self.assertEqual(rec["details"]["humans"], ["alice"])

    def test_a_record_cannot_claim_labels_from_people_the_verifier_does_not_accept(self):
        c = Chain()
        c.accepted(40, by="mallory")
        rec = track_record_evidence("agent-7", c.entries, CASE, PRAISER, NOW)
        self.assertGreater(rec["details"]["lower_bound"], 0.9)
        self.assertFalse(verify_against_ledger(rec, c.entries, humans=["alice"])[0])


if __name__ == "__main__":
    unittest.main()
