# Praise rules

"Praise" in this program is evidence offered in favour of content (and of the AI system, prompts, tools and team behind it)
that a stranger can re-check. Anything else is noise, and the rules below keep it from becoming signal by accident.

## The one test

> Could someone who does not trust the author, and has only the repository, the ledger and a standard machine, re-run this
> and possibly get a different answer?

If yes, it can be `mechanical` or `reproducible` evidence and can count. If no, it is `attested`: it is recorded, shown on
the trust card under "noted, not weighed", and the juridicator gives it weight zero. This is not an insult to the claim; it
is a statement about what a decision can safely rest on.

## What is praise and what is not

| Offered as praise | Verdict | Why |
| --- | --- | --- |
| "Made by a very large model" / model size / parameter count | attested only | nobody can re-run a size and a size predicts nothing about this proof |
| The vendor's name or brand | attested only | reputation of a vendor is not a property of this commit |
| "A careful, experienced team" | attested only | no stranger can falsify it |
| A fluent, confident explanation | attested only | fluency is what language models are best at; it is uncorrelated with correctness here |
| "A senior person signed off" | attested only (`human_signoffs`) | a name in a field; a real review is a `judgment.human_review` record by a human producer, and even that can only add caution or clear a concern |
| Which model, prompts, tools and toolchain produced it | attested (declared) **and** checkable (hashes of stored files) | the declaration is attested; the hash comparison is `mechanical.provenance_consistent` |
| Two or more independent proof checkers accept it | counts | each checker is its own record; the judge counts distinct identities |
| Axioms are only the allowed ones; no `sorry` | counts | re-runnable scans |
| Jinshi soundness checks pass | counts | re-runnable tool, one record per declared check |
| Two independent rebuilds give identical output | counts | reproducible, and the runners must differ |
| The statement was committed before the proof | counts | a hash plus git ancestry |
| A blind second formalization is machine-equivalent to the original | counts | the AI only proposed; the machine decided |
| A track record | counts, with limits | computed from the public ledger from human-confirmed outcomes; see below |

## What makes praise count

1. **Re-runnable.** A `mechanical` or `reproducible` record carries `reproduce.command`. No command, no record
   (`praiser.common.make` refuses to emit a record the contract would reject).
2. **Bound to the exact commit.** Every record carries the case's `head_sha`; the judge ignores anything about another
   commit. Declarations about another commit are refused outright.
3. **Reported in full, failures included.** Declare a `manifest.declared` before results and report every kind in it. A
   failure is a record like any other. `from_jinshi` reports an undeclared check that failed, because dropping a surprise
   failure is the cherry-picking this program exists to prevent. Silence is `not_run`, never `pass`.
4. **Cannot be bought by volume.** More records of the same kind, more checkers with invented names, more cases: none of
   it adds weight by count alone (see Gaming, below).
5. **Honest about unknowns.** A checker that timed out, a rebuild from one runner, ancestry git could not answer, an empty
   declaration group: each is `inconclusive`, which raises scrutiny and never counts as a pass.

A manifest only protects results written under the *same producer identity* as the manifest (the juridicator's rule R9
matches on identity). Declare one manifest per identity: the praiser's own, and one for each tool that reports.

## Gaming and Goodhart

Reputation is the part most worth gaming, so it is the most constrained.

| Attack | Rule |
| --- | --- |
| Pile up easy cases | Exponential decay with a half-life of 200 labeled cases: total weight is bounded by about 289, so the bound cannot pass about 0.987 however many cases are added. |
| Get credit for unexamined work | An ACCEPT with no later human label counts for **nothing**. |
| Label your own work | Labels by the author system, and by any identity that produced non-human evidence in the ledger (tools, bots, reviewer AIs, the praiser), are ignored. An optional allow-list `humans` restricts labelers further and is recorded in the record, so a verifier using a different list gets a different answer. |
| Hide a bad outcome | A confirmed bad (accepted, then a human labeled it reject) counts as **ten** failures. If labelers disagree, reject wins. A snapshot older than a later confirmed bad is flagged by `verify_against_ledger`. |
| Claim a commit's credit for someone else, or share it | Credit needs a single claimant; a confirmed bad is charged to every claimant. |
| Invent a number | `reproducible.track_record` carries a command that recomputes it from the ledger; `verify_against_ledger` re-derives and compares every claimed field, the ledger head it was computed at, the labeler set and the outcome. |
| Cherry-pick which labeled cases exist | **Not yet closed.** Only labeled cases count, and nothing yet forces the sample of labeled cases to be unbiased. See `docs/IDEAS.md` (lottery-bound labels) and `SECURITY.md`. |
| Let praise buy acceptance | The praiser cannot write verdicts or labels. Merit can lower scrutiny by one step in the juridicator, only with independent checkers, a matching rebuild, consistent provenance and a track-record floor, all together. A failed mechanical check rejects regardless. |

### The track-record formula (`track/1`)

```
age(case)    = number of other labeled outcomes decided by a later label entry
weight(case) = 0.5 ** (age / 200)
good         = sum of weight over confirmed good cases
failures     = 10 * sum of weight over confirmed bad cases
lower_bound  = wilson_lower(good, good + failures)      95%; 0 when there is nothing to count
```

Wilson lower bound: `(p + z²/2n − z·sqrt((p(1−p) + z²/4n)/n)) / (1 + z²/n)` with `z = 1.96`, `p = good/n`. Known values: 9 of 10 is
about 0.596; 90 of 100 about 0.826; 0 of 0 is 0. A record is `pass` when the bound is above 0 and `inconclusive` otherwise;
it is the juridicator's policy, not this repository, that decides how high the bound must be to matter.

A `label` entry in the ledger is `{"repo", "head_sha", "label": "accept" | "reject", "by": <human identity>}`.

## What the praiser may never do

- Write a verdict, a label, or any ledger entry that gates (it emits evidence and a card; the juridicator decides).
- Emit a record stronger than its role: `author-system` evidence is attested only; the praiser's own kinds are listed in
  `docs/CONTRACT.md` of the juridicator.
- Count praise it cannot show. If a reason cannot be made falsifiable, the only legitimate move is `attested_claim`.

## Changing this file

It is human-owned (`.github/CODEOWNERS`), like the formula in `praiser/track_record.py` and the vendored contract. An AI
may suggest a change in a pull request like anyone else; it cannot merge one.
