import contextlib
import io
import json
import os
import tempfile
import unittest

from vendor.juridicator_evidence import validate
from praiser import cli
from praiser.common import sha256_bytes
from praiser.loaders import InputError, read_files_under, read_json, read_ledger, read_records
from praiser.preregistration import commit_statement
from praiser.receipts import make_receipt
from praiser.track_record import track_record_evidence
from tests.helpers import CASE, H, H2, HEAD, NOW, OLDER, PRAISER, Chain


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:  # argparse
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, content, binary=False):
        with open(self.path(name), "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as fh:
            fh.write(content if binary else (content if isinstance(content, str) else json.dumps(content)))
        return self.path(name)

    def base_args(self):
        return ["--case", self.write("case.json", CASE), "--producer", self.write("producer.json", PRAISER), "--created", NOW]


class Loaders(Base):
    def test_read_json_errors_are_input_errors(self):
        for content in ("{not json", ""):
            with self.assertRaises(InputError):
                read_json(self.write("bad.json", content))
        with self.assertRaises(InputError):
            read_json(self.path("missing.json"))

    def test_records_from_files_lists_and_directories(self):
        self.write("a.json", {"x": 1})
        self.write("b.json", [{"y": 2}, {"z": 3}])
        self.write("c.jsonl", '{"w": 4}\n\n{"v": 5}\n')
        self.assertEqual(len(read_records([self.dir])), 5)
        self.assertEqual(read_records([self.path("a.json")]), [{"x": 1}])

    def test_ledger_reader(self):
        self.write("l.jsonl", '{"seq": 0}\n')
        self.assertEqual(read_ledger(self.path("l.jsonl")), [{"seq": 0}])
        with self.assertRaises(InputError):
            read_ledger(self.path("nope.jsonl"))
        self.write("m.jsonl", "not json\n")
        with self.assertRaises(InputError):
            read_ledger(self.path("m.jsonl"))

    def test_files_under_reads_existing_and_skips_missing(self):
        os.makedirs(self.path("sub"))
        self.write("sub/p.md", b"hello", binary=True)
        self.assertEqual(read_files_under(self.dir, ["sub/p.md", "absent.md"]), {"sub/p.md": b"hello"})

    def test_files_under_refuses_escapes(self):
        self.write("ok.txt", "x")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        with open(os.path.join(outside.name, "secret"), "w", encoding="utf-8") as fh:
            fh.write("s")
        os.symlink(os.path.join(outside.name, "secret"), self.path("link"))
        os.makedirs(self.path("sub"))
        for bad in ("../x", "a/../../x", "/etc/passwd", "link", "sub/../ok.txt"):
            with self.assertRaises(InputError, msg=bad):
                read_files_under(self.dir, [bad])
        with self.assertRaises(InputError):
            read_files_under(self.path("not-a-dir"), ["x"])


class Limits(Base):
    def test_a_file_over_the_size_limit_is_refused(self):
        from unittest import mock
        from praiser import loaders

        self.write("big.bin", b"x" * 10, binary=True)
        with mock.patch.object(loaders, "MAX_FILE", 5):
            with self.assertRaises(InputError):
                read_files_under(self.dir, ["big.bin"])
        self.assertEqual(len(read_files_under(self.dir, ["big.bin"])["big.bin"]), 10)


class Commands(Base):
    def test_attest_then_check_provenance(self):
        os.makedirs(self.path("repo/prompts"))
        self.write("repo/prompts/p.md", b"prompt", binary=True)
        self.write("repo/lean-toolchain", b"lc", binary=True)
        self.write("repo/tools.json", b"{}", binary=True)
        code, out, _ = run("hash-files", "--root", self.path("repo"), "prompts/p.md", "lean-toolchain", "tools.json")
        self.assertEqual(code, 0)
        hashes = json.loads(out)
        self.assertEqual(hashes["prompts/p.md"], sha256_bytes(b"prompt"))
        spec = self.write("spec.json", {
            "model": "m", "model_family": "f", "rubric_version": "r", "human_signoffs": ["alice"],
            "prompt_sha256": {"prompts/p.md": hashes["prompts/p.md"]}, "tool_manifest": {"tools.json": hashes["tools.json"]},
            "toolchain": {"lean-toolchain": hashes["lean-toolchain"]}})
        att = self.path("att.json")
        self.assertEqual(run("attest", *self.base_args(), "--spec", spec, "--out", att)[0], 0)
        rec = read_json(att)
        self.assertEqual(validate(rec), [])
        self.assertEqual(rec["kind"], "attested.provenance")
        chk = self.path("chk.json")
        self.assertEqual(run("check-provenance", *self.base_args(), "--declared", att, "--root", self.path("repo"), "--out", chk)[0], 0)
        self.assertEqual(read_json(chk)["outcome"], "pass")
        with open(self.path("repo/prompts/p.md"), "wb") as fh:
            fh.write(b"changed")
        self.assertEqual(run("check-provenance", *self.base_args(), "--declared", att, "--root", self.path("repo"), "--out", chk)[0], 0)
        self.assertEqual(read_json(chk)["outcome"], "fail")

    def test_check_provenance_refuses_a_declaration_that_climbs_out(self):
        decl = {"prompts": {"../../etc/passwd": "a" * 64}, "tool_manifest": {}, "toolchain": {}}
        code, _, err = run("check-provenance", *self.base_args(), "--declared", self.write("d.json", decl), "--root", self.dir)
        self.assertEqual(code, 2)
        self.assertIn("bad input", err)

    def test_manifest(self):
        code, out, _ = run("manifest", *self.base_args(), "--checks", "mechanical.no_sorry", "mechanical.axiom_closure")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["details"]["checks"], ["mechanical.axiom_closure", "mechanical.no_sorry"])
        self.assertEqual(run("manifest", *self.base_args(), "--checks", "Not A Kind")[0], 2)

    def test_track_record_stats_evidence_and_verify(self):
        c = Chain()
        c.accepted(40)
        ledger = self.write("ledger.jsonl", "".join(json.dumps(e) + "\n" for e in c.entries))
        code, out, _ = run("track-record", "--ledger", ledger, "--author", "agent-7")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["n_good"], 40)
        rec_path = self.path("rec.json")
        self.assertEqual(run("track-record", "--ledger", ledger, "--author", "agent-7", *self.base_args(), "--out", rec_path)[0], 0)
        self.assertEqual(read_json(rec_path)["kind"], "reproducible.track_record")
        code, out, _ = run("track-record", "--ledger", ledger, "--verify", rec_path)
        self.assertEqual((code, json.loads(out)["ok"]), (0, True))
        forged = read_json(rec_path)
        forged["details"]["lower_bound"] = 0.99
        from vendor.juridicator_evidence import compute_id
        forged["id"] = compute_id(forged)
        code, out, _ = run("track-record", "--ledger", ledger, "--verify", self.write("forged.json", forged))
        self.assertEqual((code, json.loads(out)["ok"]), (12, False))

    def test_as_of_applies_to_numbers_and_to_records(self):
        c = Chain()
        c.accepted(6)
        mid = len(c.entries) - 1
        c.accepted(6)
        ledger = self.write("ledger.jsonl", "".join(json.dumps(e) + "\n" for e in c.entries))
        self.assertEqual(json.loads(run("track-record", "--ledger", ledger, "--author", "agent-7", "--as-of", str(mid))[1])["n_good"], 6)
        out = self.path("r.json")
        run("track-record", "--ledger", ledger, "--author", "agent-7", "--as-of", str(mid), *self.base_args(), "--out", out)
        self.assertEqual((read_json(out)["details"]["n_good"], read_json(out)["details"]["as_of_seq"]), (6, mid))

    def test_the_command_in_a_record_reproduces_its_numbers(self):
        c = Chain()
        c.accepted(12)
        ledger = self.write("ledger.jsonl", "".join(json.dumps(e) + "\n" for e in c.entries))
        rec = track_record_evidence("agent-7", c.entries, CASE, PRAISER, NOW)
        argv = rec["reproduce"]["command"].split(" # ")[0].split()[3:]  # drop "python3 -m praiser"
        argv[argv.index("--ledger") + 1] = ledger
        code, out, _ = run(*argv)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["lower_bound"], rec["details"]["lower_bound"])

    def test_track_record_needs_an_author_and_complete_options(self):
        ledger = self.write("ledger.jsonl", "")
        self.assertEqual(run("track-record", "--ledger", ledger)[0], 2)
        self.assertEqual(run("track-record", "--ledger", ledger, "--author", "a", "--case", self.write("c.json", CASE))[0], 2)
        self.assertEqual(run("track-record", "--ledger", self.path("absent.jsonl"), "--author", "a")[0], 2)
        c = Chain()
        c.accepted(1)
        broken = [dict(e, body={"x": 1}) for e in c.entries]
        bad = self.write("bad.jsonl", "".join(json.dumps(e) + "\n" for e in broken))
        self.assertEqual(run("track-record", "--ledger", bad, "--author", "agent-7")[0], 2)

    def test_check_prereg(self):
        statement = self.write("s.txt", "theorem t : True := trivial")
        commitment = commit_statement("theorem t : True := trivial", "nn")
        args = ["check-prereg", *self.base_args(), "--commitment", commitment, "--statement", statement, "--nonce", "nn",
                "--committed-in", OLDER, "--head", HEAD]
        code, out, _ = run(*args, "--is-ancestor", "yes")
        self.assertEqual((code, json.loads(out)["outcome"]), (0, "pass"))
        self.assertEqual(json.loads(run(*args, "--is-ancestor", "no")[1])["outcome"], "fail")
        self.assertEqual(json.loads(run(*args, "--is-ancestor", "unknown")[1])["outcome"], "inconclusive")
        self.assertEqual(run(*args, "--is-ancestor", "maybe")[0], 2)
        missing = [a if a != statement else self.path("nope.txt") for a in args]
        self.assertEqual(run(*missing, "--is-ancestor", "yes")[0], 2)

    def test_compare_receipts(self):
        a = self.write("a.json", make_receipt("lake build", H, H2, 0, runner="r1"))
        b = self.write("b.json", make_receipt("lake build", H, H2, 0, runner="r2"))
        code, out, _ = run("compare-receipts", *self.base_args(), a, b)
        self.assertEqual((code, json.loads(out)["outcome"]), (0, "pass"))
        tampered = self.write("t.json", dict(make_receipt("lake build", H, H2, 0, runner="r2"), exit_code=1))
        self.assertEqual(run("compare-receipts", *self.base_args(), a, tampered)[0], 2)

    def test_card(self):
        from praiser.merit import from_checkers
        from tests.test_trustcard import verdict_for

        evs = from_checkers({"lean-kernel": "accept"}, CASE, NOW)
        ev_path = self.write("ev.json", evs)
        out_path = self.path("card.md")
        code, _, _ = run("card", "--verdict", self.write("v.json", verdict_for(evs)), "--evidence", ev_path, "--out", out_path)
        self.assertEqual(code, 0)
        with open(out_path, encoding="utf-8") as fh:
            self.assertIn("lean-kernel", fh.read())
        code, out, _ = run("card", "--verdict", self.write("v2.json", verdict_for(evs)), "--evidence", ev_path)
        self.assertIn("# Trust card", out)
        self.assertEqual(run("card", "--verdict", self.write("v3.json", {"decision": "NOPE"}), "--evidence", ev_path)[0], 2)

    def test_bad_arguments_exit_2(self):
        self.assertEqual(run()[0], 2)
        self.assertEqual(run("nonsense")[0], 2)
        self.assertEqual(run("attest", *self.base_args(), "--spec", self.write("s.json", []))[0], 2)
        self.assertEqual(run("attest", *self.base_args(), "--spec", self.write("s2.json", {}))[0], 2)
        self.assertEqual(run("manifest", "--case", self.path("nope.json"), "--producer", self.path("p"), "--created", NOW, "--checks", "x.y")[0], 2)

    def test_help_exits_zero(self):
        self.assertEqual(run("--help")[0], 0)

    def test_no_clock_is_read_so_runs_are_repeatable(self):
        args = ["manifest", *self.base_args(), "--checks", "mechanical.no_sorry"]
        self.assertEqual(run(*args)[1], run(*args)[1])


if __name__ == "__main__":
    unittest.main()


class VerifiedId(Base):
    def test_verify_prints_the_id_only_when_the_ledger_reproduces_the_record(self):
        chain = Chain()
        chain.accepted(12)
        ledger = self.write("l.jsonl", "".join(json.dumps(e) + "\n" for e in chain.entries))
        rec = track_record_evidence("agent-7", chain.entries, CASE, PRAISER, NOW)
        good = self.write("good.json", rec)
        code, out, _ = run("track-record", "--ledger", ledger, "--verify", good)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["verified_id"], rec["id"])
        forged = dict(rec, details=dict(rec["details"], lower_bound=0.99))
        bad = self.write("bad.json", forged)
        code, out, _ = run("track-record", "--ledger", ledger, "--verify", bad)
        self.assertEqual(code, 12)
        self.assertIsNone(json.loads(out)["verified_id"])
