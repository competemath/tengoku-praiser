import copy
import unittest

from vendor.juridicator_evidence import validate
from praiser.attest import attested_claim, check_provenance, combined_digest, provenance_attestation
from praiser.common import sha256_bytes
from tests.helpers import AUTHOR, CASE, NOW, OLDER, PRAISER, case

PROMPT = b"You are a careful formalizer."
TOOLS = b'{"tools": ["lake", "lean"]}'
CHAIN = b"leanprover/lean4:v4.20.0"
FILES = {"prompts/main.md": PROMPT, "tools/manifest.json": TOOLS, "lean-toolchain": CHAIN}


def attestation(**over):
    kw = dict(model="model-x-1", model_family="family-a",
              prompt_sha256={"prompts/main.md": sha256_bytes(PROMPT)},
              tool_manifest={"tools/manifest.json": sha256_bytes(TOOLS)},
              toolchain={"lean-toolchain": sha256_bytes(CHAIN)},
              rubric_version="rubric-3", human_signoffs=["alice"], created=NOW)
    kw.update(over)
    return provenance_attestation(CASE, AUTHOR, **kw)


class Attestation(unittest.TestCase):
    def test_it_is_attested_and_valid(self):
        ev = attestation()
        self.assertEqual(validate(ev), [])
        self.assertEqual((ev["kind"], ev["verifiability"], ev["outcome"]), ("attested.provenance", "attested", "pass"))
        self.assertIsNone(ev["reproduce"])

    def test_ai_fields_are_filled(self):
        ev = attestation()
        self.assertEqual(ev["ai"]["used"], True)
        self.assertEqual(ev["ai"]["role"], "proposer")
        self.assertEqual((ev["ai"]["model"], ev["ai"]["family"]), ("model-x-1", "family-a"))
        self.assertEqual(ev["ai"]["prompt_sha256"], sha256_bytes(PROMPT))

    def test_details_carry_the_declared_facts(self):
        d = attestation()["details"]
        self.assertEqual(d["prompts"], {"prompts/main.md": sha256_bytes(PROMPT)})
        self.assertEqual(d["human_signoffs"], ["alice"])
        self.assertEqual(d["rubric_version"], "rubric-3")
        self.assertIn("model", d["not_checkable"])

    def test_the_author_block_of_the_case_is_not_copied_into_the_record(self):
        self.assertEqual(set(attestation()["case"]), {"repo", "head_sha", "class"})

    def test_several_prompts_get_a_combined_digest(self):
        two = {"a.md": "1" * 64, "b.md": "2" * 64}
        self.assertEqual(combined_digest({"a.md": "1" * 64}), "1" * 64)
        self.assertNotEqual(combined_digest(two), "1" * 64)
        self.assertEqual(combined_digest(two), combined_digest(dict(reversed(list(two.items())))))
        self.assertEqual(validate(attestation(prompt_sha256=two)), [])

    def test_refuses_what_could_never_be_checked(self):
        with self.assertRaises(ValueError):
            attestation(prompt_sha256={})
        with self.assertRaises(ValueError):
            attestation(prompt_sha256={"p.md": "not-a-hash"})
        with self.assertRaises(ValueError):
            attestation(prompt_sha256=sha256_bytes(PROMPT))  # a bare hash has no stored path
        with self.assertRaises(ValueError):
            attestation(model="")
        with self.assertRaises(ValueError):
            attestation(human_signoffs="alice")

    def test_a_declaration_too_large_for_the_contract_is_refused(self):
        with self.assertRaises(ValueError):
            attestation(prompt_sha256={f"prompts/p{i}.md": sha256_bytes(str(i).encode()) for i in range(200)})

    def test_deterministic(self):
        self.assertEqual(attestation(), attestation())

    def test_unverifiable_praise_is_attested_only(self):
        ev = attested_claim(CASE, AUTHOR, "team_note", "a very careful team", NOW)
        self.assertEqual((ev["kind"], ev["verifiability"]), ("attested.team_note", "attested"))
        self.assertEqual(validate(ev), [])
        for bad in ("Team Note", "", "a.b"):
            with self.assertRaises(ValueError):
                attested_claim(CASE, AUTHOR, bad, "x", NOW)


class Check(unittest.TestCase):
    def run_check(self, files=None, declared=None, **kw):
        declared = declared or attestation()
        return check_provenance(declared, FILES if files is None else files, CASE, PRAISER, NOW, **kw)

    def test_everything_matches(self):
        ev = self.run_check()
        self.assertEqual(validate(ev), [])
        self.assertEqual((ev["kind"], ev["verifiability"], ev["outcome"]), ("mechanical.provenance_consistent", "mechanical", "pass"))
        self.assertEqual(ev["details"]["n_checked"], 3)

    def test_accepts_the_record_or_just_its_details(self):
        rec = attestation()
        self.assertEqual(self.run_check(declared=rec)["outcome"], "pass")
        self.assertEqual(self.run_check(declared=rec["details"])["outcome"], "pass")

    def test_a_changed_prompt_fails_and_is_named(self):
        ev = self.run_check(files=dict(FILES, **{"prompts/main.md": b"a different prompt"}))
        self.assertEqual(ev["outcome"], "fail")
        self.assertIn("prompts/main.md", ev["claim"])
        self.assertNotIn("lean-toolchain", ev["claim"])
        self.assertNotIn("tools/manifest.json", ev["claim"])
        self.assertEqual([m["path"] for m in ev["details"]["mismatches"]], ["prompts/main.md"])

    def test_a_changed_tool_manifest_fails_and_is_named(self):
        ev = self.run_check(files=dict(FILES, **{"tools/manifest.json": b"{}"}))
        self.assertEqual(ev["outcome"], "fail")
        self.assertIn("tool manifest tools/manifest.json", ev["claim"])
        self.assertNotIn("prompts/main.md", ev["claim"])

    def test_a_changed_toolchain_fails_and_is_named(self):
        ev = self.run_check(files=dict(FILES, **{"lean-toolchain": b"leanprover/lean4:v9"}))
        self.assertEqual(ev["outcome"], "fail")
        self.assertIn("toolchain lean-toolchain", ev["claim"])

    def test_every_mismatch_is_named_not_only_the_first(self):
        ev = self.run_check(files={"prompts/main.md": b"x", "tools/manifest.json": b"y", "lean-toolchain": b"z"})
        for path in ("prompts/main.md", "tools/manifest.json", "lean-toolchain"):
            self.assertIn(path, ev["claim"])
        self.assertEqual(ev["details"]["n_mismatched"], 3)

    def test_a_declared_file_that_is_not_stored_fails(self):
        files = {k: v for k, v in FILES.items() if k != "lean-toolchain"}
        ev = self.run_check(files=files)
        self.assertEqual(ev["outcome"], "fail")
        self.assertIn("not stored", ev["claim"])

    def test_a_matching_hash_under_another_path_does_not_count(self):
        files = {"prompts/main.md": PROMPT, "tools/manifest.json": TOOLS, "other-name": CHAIN}
        self.assertEqual(self.run_check(files=files)["outcome"], "fail")

    def test_extra_stored_files_are_irrelevant(self):
        self.assertEqual(self.run_check(files=dict(FILES, extra=b"x"))["outcome"], "pass")

    def test_an_empty_group_is_inconclusive_not_a_pass(self):
        ev = self.run_check(declared=attestation(tool_manifest={}))
        self.assertEqual(ev["outcome"], "inconclusive")
        self.assertIn("tool manifest", ev["claim"])

    def test_a_mismatch_beats_an_empty_group(self):
        ev = self.run_check(declared=attestation(tool_manifest={}), files=dict(FILES, **{"prompts/main.md": b"x"}))
        self.assertEqual(ev["outcome"], "fail")

    def test_it_says_how_to_recompute(self):
        cmd = self.run_check()["reproduce"]["command"]
        self.assertIn("check-provenance", cmd)
        self.assertIn("sha256sum", cmd)
        self.assertIn("lean-toolchain", cmd)
        self.assertEqual(self.run_check(command="make provenance")["reproduce"]["command"], "make provenance")

    def test_unverifiable_fields_are_listed_as_not_checked(self):
        self.assertIn("human_signoffs", self.run_check()["details"]["not_checked"])

    def test_declaration_about_another_commit_is_refused(self):
        other = provenance_attestation(case(OLDER), AUTHOR, model="m", model_family="f",
                                       prompt_sha256={"p": "1" * 64}, tool_manifest={}, toolchain={}, rubric_version="r",
                                       human_signoffs=[], created=NOW)
        with self.assertRaises(ValueError):
            check_provenance(other, FILES, CASE, PRAISER, NOW)

    def test_wrong_kind_and_wrong_shapes_are_refused(self):
        rec = attestation()
        with self.assertRaises(ValueError):
            check_provenance(dict(rec, kind="attested.other"), FILES, CASE, PRAISER, NOW)
        with self.assertRaises(ValueError):
            check_provenance("nope", FILES, CASE, PRAISER, NOW)
        with self.assertRaises(ValueError):
            check_provenance(rec, {"prompts/main.md": "text, not bytes"}, CASE, PRAISER, NOW)
        broken = copy.deepcopy(rec)
        broken["details"]["prompts"] = {"p": "short"}
        with self.assertRaises(ValueError):
            check_provenance(broken, FILES, CASE, PRAISER, NOW)

    def test_claim_and_details_stay_inside_the_contract_with_many_mismatches(self):
        many = {f"prompts/p{i}.md": sha256_bytes(str(i).encode()) for i in range(40)}
        decl = attestation(prompt_sha256=many)
        ev = check_provenance(decl, {}, CASE, PRAISER, NOW)
        self.assertEqual(validate(ev), [])
        self.assertEqual(ev["outcome"], "fail")
        self.assertIn("more", ev["claim"])
        self.assertEqual(ev["details"]["n_mismatched"], 42)


if __name__ == "__main__":
    unittest.main()
