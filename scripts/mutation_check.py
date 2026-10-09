"""Break key lines one at a time and confirm the test suite notices each break.

    python3 scripts/mutation_check.py [--juridicator ../tengoku-juridicator] [--only SUBSTRING]

For every mutant: copy the repository to a temporary directory, replace one exact snippet, run the whole suite there.
A mutant that the suite does not fail on is a SURVIVOR: a line whose behaviour no test pins down. Exit code 0 means no
survivor. The juridicator checkout is symlinked next to the copy so the integration tests run too.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (file, exact snippet, replacement, what the mutation means)
MUTANTS = [
    # attest.check_provenance
    ("praiser/attest.py", "            if got != want:", "            if False:", "check_provenance never notices a mismatch"),
    ("praiser/attest.py", "got = sha256_bytes(bytes(data)) if data is not None else None", "got = want", "check_provenance trusts the declared hash"),
    ("praiser/attest.py", '    elif empty:', '    elif False:', "an empty declaration group is a pass"),
    ("praiser/attest.py", 'GROUPS = (("prompt", "prompts"), ("tool manifest", "tool_manifest"), ("toolchain", "toolchain"))',
     'GROUPS = (("prompt", "prompts"), ("tool manifest", "tool_manifest"))', "the toolchain pin is never compared"),
    ("praiser/attest.py", "for m in mismatches[:4])", "for m in mismatches[:1])", "the claim names only the first mismatch"),
    ("praiser/attest.py", 'if declared.get("case", {}).get("head_sha") != case_ref(case)["head_sha"]:', "if False:",
     "a declaration about another commit is accepted"),
    ("praiser/attest.py", 'outcome="pass",\n        verifiability="attested",\n        created=created,\n        ai=', 'outcome="fail",\n        verifiability="attested",\n        created=created,\n        ai=',
     "the attestation stops saying pass"),
    # merit
    ("praiser/merit.py", 'n_fail = counts.get("fail", 0)', 'n_fail = 0', "Jinshi failures never fail a check"),
    ("praiser/merit.py", 'outcome, claim = "not_run", f"Jinshi', 'outcome, claim = "pass", f"Jinshi', "silence from Jinshi is a pass"),
    ("praiser/merit.py", "names = sorted(declared | set(by_check))", "names = sorted(declared)", "an undeclared failing check is dropped"),
    ("praiser/merit.py", '"timeout": "inconclusive"', '"timeout": "pass"', "a checker timeout counts as a pass"),
    ("praiser/merit.py", '"error": "inconclusive"', '"error": "pass"', "a checker error counts as a pass"),
    ("praiser/merit.py", '"reject": "fail"', '"reject": "pass"', "a rejecting checker counts as a pass"),
    ("praiser/merit.py", '"identity": clip(name, 120)}', '"identity": "checker"}', "checkers lose their separate identities"),
    ("praiser/merit.py", "extra = [a for a in used if a not in allowed_set]", "extra = []", "axiom closure never fails"),
    ("praiser/merit.py", 'NEVER_ALLOWED = ("sorryAx",)', "NEVER_ALLOWED = ()", "sorryAx may be allowed"),
    ("praiser/merit.py", '        n = 1 if findings_or_flag else 0\n        outcome = "fail" if n else "pass"', '        n = 1 if findings_or_flag else 0\n        outcome = "pass" if n else "fail"',
     "the sorry flag is inverted"),
    ("praiser/merit.py", 'details={"checks": kinds}', 'details={"checks": []}', "the manifest declares nothing"),
    # restatement
    ("praiser/restatement.py", 'OUTCOMES = {True: "pass", False: "fail", None: "inconclusive"}', 'OUTCOMES = {True: "pass", False: "pass", None: "inconclusive"}',
     "a non-equivalent restatement passes"),
    ("praiser/restatement.py", 'if not isinstance(tools, (tuple, list)) or tuple(tools) != ():', "if False:", "a backend with tools is accepted"),
    ("praiser/restatement.py", 'ai={"used": True, "role": "proposer", "model": clip(ai_model', 'ai={"used": True, "role": "reviewer", "model": clip(ai_model',
     "the AI is labelled a reviewer, not a proposer"),
    # preregistration
    ("praiser/preregistration.py", "    elif is_ancestor is False:", "    elif False:", "the ancestor requirement is dropped"),
    ("praiser/preregistration.py", "    if committed_before_sha == head_sha:", "    if False:", "a same-commit commitment counts as before"),
    ("praiser/preregistration.py", '    if head_sha != case_r["head_sha"]:', "    if False:", "the proof's commit need not be the case's commit"),
    ("praiser/preregistration.py", 'f"{DOMAIN}\\n{nonce}\\n{normalize(statement_text)}"', 'f"{DOMAIN}\\n{normalize(statement_text)}"', "the nonce is left out"),
    ("praiser/preregistration.py", "    elif is_ancestor is None:", "    elif False:", "unknown ancestry passes"),
    ("praiser/preregistration.py", 'return " ".join(statement_text.split())', "return statement_text.strip()", "whitespace is not normalized"),
    # receipts
    ("praiser/receipts.py", "elif not ra or not rb or ra == rb:", "elif False:", "the same runner twice passes"),
    ("praiser/receipts.py", "differing = [f for f in FIELDS if a[f] != b[f]]", "differing = [f for f in FIELDS[:3] if a[f] != b[f]]", "the exit code is not compared"),
    ("praiser/receipts.py", 'return receipt["receipt_sha256"] == _seal(body)', "return True", "receipts are not verified"),
    # track record
    ("praiser/track_record.py", '                res["n_unlabeled"] += 1\n                continue', '                res["events"].append((vseq, "good"))\n                continue',
     "unlabeled accepts count as good"),
    ("praiser/track_record.py", "and by not in non_human and", "and", "self-labels and labels by bots or tools count"),
    ("praiser/track_record.py", "if seq > vseq and", "if True and", "labels before the verdict count"),
    ("praiser/track_record.py", "FAILURE_WEIGHT = 10", "FAILURE_WEIGHT = 1", "a confirmed bad costs one failure, not ten"),
    ("praiser/track_record.py", "HALF_LIFE = 200", "HALF_LIFE = 10**9", "no decay"),
    ("praiser/track_record.py", "if not bad and len(who) > 1:", "if False:", "a commit claimed by two systems gives credit to both"),
    ("praiser/track_record.py", 'bad = any(label == "reject" for _, label in last.values())', 'bad = all(label == "reject" for _, label in last.values())',
     "one reject no longer makes it bad"),
    ("praiser/track_record.py", 'if key not in verdicts or verdicts[key][1] != "ACCEPT":', "if key not in verdicts:", "non-ACCEPT verdicts count"),
    ("praiser/track_record.py", 'if latest["n_bad"] > fresh["n_bad"]:', "if False:", "cherry-picked snapshots are not caught"),
    ("praiser/track_record.py", "    if not ok:\n        raise LedgerError", "    if False:\n        raise LedgerError", "a broken ledger is used anyway"),
    ("praiser/track_record.py", "        if d.get(field) != fresh[field]:", "        if False:", "forged numbers are not caught"),
    ("praiser/track_record.py", "    if lb > 0:", "    if lb >= 0:", "an empty record is a pass"),
    ("praiser/track_record.py", "(humans is None or by in humans)", "True", "the labeler allow-list is ignored"),
    ("praiser/track_record.py", 'and role == "author-system"', "", "anyone's provenance attributes the commit"),
    ("praiser/track_record.py", "    margin = z * math.sqrt(", "    margin = 0 * math.sqrt(", "the Wilson margin is dropped"),
    ("praiser/track_record.py", '    if d.get("humans") != allow:', "    if False:", "a different labeler set is not noticed"),
    ("praiser/track_record.py", 'if max_lag is not None and len(entries) - 1 - as_of > max_lag:', "if False:", "stale snapshots are accepted"),
    ("praiser/track_record.py", '    if record["outcome"] != expected:', "    if False:", "a forged outcome is not noticed"),
    # trust card
    ("praiser/trustcard.py", 'return SPECIAL.sub(r"\\\\\\1", s)', "return s", "untrusted text is not escaped"),
    ("praiser/trustcard.py", 'if any(e["outcome"] == "pass" for e in rm) and not any(e["outcome"] == "fail" for e in rm):', "if rm:",
     "any restatement check, even a failed one, supports fidelity"),
    ("praiser/trustcard.py", 'if validate(ev) or ev["id"] in ignored or ev["id"] in seen:', 'if validate(ev) or ev["id"] in seen:', "ignored records are shown"),
    ("praiser/trustcard.py", 'return live, digest == verdict.get("evidence_digest")', "return live, True", "the digest warning is dropped"),
    ("praiser/trustcard.py", '"## What this does not claim", "",', '"## Notes", "",', "the 'does not claim' section is renamed away"),
    ("praiser/trustcard.py", 'if ev["case"]["repo"] != case["repo"] or ev["case"]["head_sha"] != case["head_sha"]:', "if False:", "other commits' evidence is shown"),
    # common / loaders / cli / vendor
    ("praiser/common.py", "    if errors:\n        raise ValueError", "    if False:\n        raise ValueError", "invalid records may be emitted"),
    ("praiser/common.py", "    if not SHA40.match(out[\"head_sha\"]):", "    if False:", "a malformed commit is accepted"),
    ("praiser/loaders.py", "        if os.path.commonpath([base, full]) != base:", "        if False:", "symlinks may leave the checkout"),
    ("praiser/loaders.py", '        if os.path.isabs(p) or ".." in p.replace("\\\\", "/").split("/"):', "        if False:", "declared paths may climb out"),
    ("praiser/cli.py", "return 0 if ok else 12", "return 0", "a forged record verifies with exit 0"),
    ("vendor/juridicator_evidence.py", "MAX_CLAIM = 300", "MAX_CLAIM = 301", "the vendored contract is edited"),
    ("vendor/EVIDENCE.sha256", "ddccbc97", "ddccbc98", "the pin is edited"),
    # a second round, aimed at the edges
    ("praiser/track_record.py", "sum(1 for s in all_seqs if s > seq)", "sum(1 for s in all_seqs if s >= seq)", "the newest outcome is aged by itself"),
    ("praiser/track_record.py", "for res in derived.values()", 'for res in [derived.get(author, {"events": []})]', "age ignores other authors' outcomes"),
    ("praiser/track_record.py", "    if n <= 0:\n        return 0.0", "    if n < 0:\n        return 0.0", "wilson of nothing divides by zero"),
    ("praiser/track_record.py", "last > len(entries) - 1", "last > len(entries)", "as_of_seq may point past the ledger"),
    ("praiser/track_record.py", 'verdicts[key] = (e["seq"], body["decision"])', 'verdicts.setdefault(key, (e["seq"], body["decision"]))', "the first verdict wins, not the last"),
    ("praiser/track_record.py", "last[by] = (seq, label)", "last.setdefault(by, (seq, label))", "a labeler's first label wins, not their last"),
    ("praiser/track_record.py", "if validate(body):\n                continue", "if False:\n                continue", "invalid evidence still attributes commits"),
    ("praiser/track_record.py", 'round(lower, 6)', 'round(lower, 1)', "the bound is rounded away"),
    ("praiser/trustcard.py", "recs = sorted(_of(live, \"reproducible.track_record\"), key=lambda e: (e[\"details\"].get(\"as_of_seq\", -1), e[\"id\"]))\n    if not recs:",
     "recs = sorted(_of(live, \"reproducible.track_record\"), key=lambda e: (-e[\"details\"].get(\"as_of_seq\", -1), e[\"id\"]))\n    if not recs:", "the card shows the oldest track record"),
    ("praiser/trustcard.py", "if good + bad < 30:", "if good + bad < 3:", "few cases are not called out"),
    ("praiser/trustcard.py", "if rate >= 1:\n        return \"Every", "if rate > 1:\n        return \"Every", "full audit is described as one in one"),
    ("praiser/trustcard.py", 'e["verifiability"] == "attested" and not e["kind"].startswith("manifest.")', 'e["verifiability"] == "attested"', "manifests are listed as praise"),
    ("praiser/trustcard.py", "sorted((e for e in live", "list((e for e in live", "praise is listed in input order"),
    ("praiser/merit.py", "if not isinstance(verdicts, dict) or not verdicts:", "if False:", "no checkers at all is accepted"),
    ("praiser/merit.py", "elif name in ran_set:", "elif True:", "every silent check is a pass"),
    ("praiser/merit.py", "if not KIND.match(k) or k.startswith(\"manifest.\"):", "if not KIND.match(k):", "a manifest may declare a manifest"),
    ("praiser/receipts.py", "if not isinstance(receipt, dict) or not all(k in receipt for k in FIELDS + (\"receipt_sha256\",)):", "if False:", "an incomplete receipt crashes instead of failing"),
    ("praiser/attest.py", "if isinstance(human_signoffs, (str, bytes)):", "if False:", "a signoff string is split into letters"),
    ("praiser/attest.py", "if not prompts:", "if False:", "an attestation may declare no prompt"),
    ("praiser/restatement.py", 'if not text or len(text) > MAX_STATEMENT:', 'if False:', "empty or huge proposals are accepted"),
    ("praiser/restatement.py", 'text = "\\n".join(CONTROL.sub(" ", line).rstrip() for line in raw.splitlines()).strip()', 'text = raw.strip()', "control characters survive in a proposal"),
    ("praiser/common.py", "limit = min(limit, MAX_DETAILS_BYTES - 500)", "limit = 10**6", "details may outgrow the contract"),
    ("praiser/cli.py", "return 0 if ok else 12", "return 12", "an honest record fails verification exit code"),
    ("praiser/cli.py", "args.created, humans=humans, as_of_seq=args.as_of)", "args.created, humans=humans, as_of_seq=None)", "--as-of is ignored when emitting a record"),
    ("praiser/cli.py", "track_record.compute(entries, args.author, humans=humans, as_of_seq=args.as_of)", "track_record.compute(entries, args.author, humans=humans)", "--as-of is ignored when printing numbers"),
    ("praiser/loaders.py", "if os.path.getsize(full) > MAX_FILE:", "if False:", "huge files are read"),
    ("scripts/sync_contract.py", "    if committed != data:", "    if False:", "the sync script accepts an uncommitted contract"),
    ("scripts/sync_contract.py", 'return f"{sha256}  {SOURCE_PATH}  # tengoku-juridicator {commit}\\n"', 'return f"{sha256}  {SOURCE_PATH}\\n"', "the pin loses the commit"),
]


def run_suite(cwd: str) -> bool:
    """True when the suite passes."""
    proc = subprocess.run([sys.executable, "-W", "error::ResourceWarning", "-m", "unittest", "discover", "-s", "tests"],
                          cwd=cwd, capture_output=True, text=True, timeout=600)
    return proc.returncode == 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--juridicator", default=os.path.join(os.path.dirname(ROOT), "tengoku-juridicator"))
    ap.add_argument("--only", default="")
    args = ap.parse_args(argv)
    survivors, broken = [], []
    with tempfile.TemporaryDirectory() as tmp:
        if os.path.isdir(args.juridicator):
            os.symlink(os.path.abspath(args.juridicator), os.path.join(tmp, "tengoku-juridicator"))
        work = os.path.join(tmp, "tengoku-praiser")
        ignore = shutil.ignore_patterns(".git", "__pycache__", "*.pyc")
        shutil.copytree(ROOT, work, ignore=ignore)
        if not run_suite(work):
            print("the unmodified suite does not pass; fix that first")
            return 1
        for path, old, new, what in MUTANTS:
            if args.only not in what and args.only not in path:
                continue
            target = os.path.join(work, path)
            with open(target, encoding="utf-8") as fh:
                original = fh.read()
            if original.count(old) != 1:
                broken.append((path, what, original.count(old)))
                print(f"BROKEN MUTANT ({original.count(old)} matches): {path}: {what}")
                continue
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(original.replace(old, new))
            try:
                survived = run_suite(work)
            except subprocess.TimeoutExpired:
                survived = False
            finally:
                with open(target, "w", encoding="utf-8") as fh:
                    fh.write(original)
            print(("SURVIVED " if survived else "killed   ") + f"{path}: {what}")
            if survived:
                survivors.append((path, what))
    print(f"\n{len(MUTANTS)} mutants, {len(survivors)} survivors, {len(broken)} that did not apply")
    return 0 if not survivors and not broken else 1


if __name__ == "__main__":
    sys.exit(main())
