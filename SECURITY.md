# Security: the praiser's threat model and residual risks

Written the way the juridicator writes its own: what is defended, and what is not solved. The juridicator's
[`docs/SECURITY.md`](https://github.com/competemath/tengoku-juridicator/blob/main/docs/SECURITY.md) is the program-level
document; this one covers what is specific here. Nothing has been through an outside audit. It is a seed.

## What is protected

The meaning of "this reason for trust is checkable": that a record marked `mechanical` or `reproducible` really can be re-run
and really matches what it says; and that a number called a track record really is what the ledger gives.

## Who is assumed hostile or unreliable

The author system (will overstate, may plant text), any praiser tool (may be compromised), the people who label (may be
careless or colluding), a rebuild runner (may report what it wishes), any text that ends up on a trust card.

## Defences

| Threat | Defence | Where |
| --- | --- | --- |
| Praise outweighs a failure | the praiser cannot write verdicts; a failed mechanical check rejects; attested weighs zero | juridicator R0, R1; `test_integration.py` |
| Fabricated praise changes the result | proven by test: the same evidence set plus fabricated attested records gives an identical verdict (apart from the evidence digest) | `tests/test_integration.py` |
| Declaration does not match what is stored | prompts, tool manifest and toolchain pin are hashed from the stored files and compared | `attest.check_provenance` |
| Invented track record | recomputed from the hash-chained ledger; `verify_against_ledger` catches a changed number, ledger head, labeler set, outcome, or a snapshot that predates a later confirmed bad outcome | `track_record.py` |
| Reputation by volume or easy cases | decay with a half-life of 200, bound below about 0.987, a confirmed bad costs ten failures, unlabeled accepts count for nothing | `track_record.py` |
| Self-labeling | labels by the author system, tools, bots, reviewer AIs and the praiser are ignored; optional allow-list recorded in the record | `track_record.py` |
| Selective reporting by the praiser | declare a manifest first; `from_jinshi` also reports undeclared failures; silence is `not_run` | `merit.py`, juridicator R9 |
| The same runner counted twice | a rebuild comparison from one runner (or with no runner named) is `inconclusive` | `receipts.py` |
| Statement fitted to the proof | the commitment must be recorded in a strict ancestor of the proof's commit; the same commit is not before | `preregistration.py` |
| Untrusted text on the trust card | control characters stripped, Markdown and HTML punctuation escaped; the card says when the evidence shown does not match the judge's digest | `trustcard.py` |
| A file path in a declaration reads something else | absolute paths, `..` segments and symlinks out of the checkout are refused | `loaders.read_files_under` |
| The vendored contract drifts | pinned hash, test fails on any difference, sync script refuses an uncommitted source | `tests/test_vendor.py`, `scripts/sync_contract.py` |
| A backend with tools | refused before the call | `restatement.propose_restatement` |

## Residual risks (not solved)

- **P1 A compromised praiser tool can emit false mechanical passes.** A `mechanical` record is only as honest as its
  producer. Mitigations: the judge re-runs the mechanical checks it can; checkers are separate producers whose agreement
  is counted and whose disagreement escalates; every record carries the command that reproduces it. Unsolved: the juridicator
  does not yet verify a track record; it reads `details.lower_bound` as written. A forged record that is well formed was
  observed to lower the tier in the juridicator when written by hand (`verify_against_ledger` catches it, but nothing calls it
  in the decision path yet).
- **P2 Producer identity is a string.** Independence of checkers, the author system a commit is credited to, and "different
  runners" are all string comparisons. A compromised workflow can use another name, or an author can invent checker names; a
  name can also be used to frame someone (a confirmed bad is charged to every identity that claimed a commit). Closing this
  needs signed records or distinct bot identities.
- **P3 Selective labeling.** Only labeled cases count, so a labeler who looks only at convenient cases produces a spotless
  record while bad accepts stay unexamined. The decay, the ten-failure penalty and "reject wins" bound the damage of a
  mistake, not of selection. The fix is `docs/IDEAS.md` idea 1 (lottery-bound labels).
- **P4 Labels are not signed.** A `label` entry names a human by string. Anyone who can append to the ledger can mint labels,
  and a labeler can mint identities to age an honest author's record (age counts other authors' labeled outcomes). The
  optional `humans` allow-list narrows this and is recorded; it is not on by default.
- **P5 A valid chain is not the real ledger.** `verify_against_ledger` checks the record against the ledger it is given and
  that the chain is internally consistent. It does not know that this ledger is the published one. Compare `ledger_head` in
  the record with the published head (juridicator R4) before relying on it.
- **P6 Provenance proves file equality, not use.** Matching hashes show the stored prompt, tool manifest and toolchain pin are
  the ones declared; they do not show the model was given that prompt, and the model name, family, rubric version and sign-offs
  cannot be checked at all (they are listed as `not_checked`).
- **P7 Receipts are what the runner says.** `env_digest` and `stdout_digest` are computed by whoever runs the build. Two
  honest, independent runners agreeing is strong; two names for one machine is not. The check cannot tell.
- **P8 Restatement shares blind spots, and a mismatch is ambiguous.** A blind restatement by the same model family tends to
  repeat the original misreading, which makes agreement weaker evidence (the program-level R2). A mismatch means one of the
  two statements is wrong, not necessarily the original; under the juridicator's default `blocking` policy a `fail` here
  rejects the content, so a bad restatement can cost a good translation a re-run.
- **P9 Ancestry is supplied by the caller.** `is_ancestor` comes from git in the caller's environment. A rewritten or
  force-pushed history, or a caller who simply passes `True`, defeats the check; the record contains the two commits and the
  command so a reviewer can redo it. Unknown ancestry is `inconclusive`, never a pass.
- **P10 The card is a rendering, not a boundary.** Escaping is tested against the common Markdown and HTML injections;
  Markdown renderers differ. The card must not be used to decide anything.
- **P11 Some command lines are still guesses.** The Jinshi command, the `lean-kernel`, `leanchecker` and `lean4lean`
  checker commands and the sorry scan are real. The axiom scan (`scripts/print_axioms.lean`) and the commands for other
  checkers such as `nanoda` are not known to this repository: pass the real ones (`command=`, `commands=`), or the record is
  checkable only in principle.
- **P12 Tuning the allowed axioms.** `axiom_closure` takes its allowed set as a parameter because a toolchain's real baseline
  includes more than three names. A permissive set passes everything. It is recorded in the record, and `sorryAx` cannot be in
  it, but a reviewer has to look at the set.
- **P13 Containment evidence is as honest as the run that produced it.** `agent_contained` weighs two reports it is handed. It cannot
  tell that the trace is the whole trace, that the battery ran as the agent's identity inside the jail the agent used, or that the
  jail specification whose digest was declared is the one that was built; the digests let a holder of the stored originals notice a
  swap, no one else. A passing battery proves the probed vectors were closed on that runner that day (warden `SECURITY.md`, 4); a clean
  trace shows what this run did, not what the agent could have done. It is a reason to lower scrutiny at most, like every other
  record here, and a failure rejects.
