# tengoku-praiser

One program in three repositories, for deciding whether AI-generated content should be trusted into Tengoku:

| Repository | Role | One line |
| --- | --- | --- |
| [tengoku-wounder](https://github.com/competemath/tengoku-wounder) | challenge | tries to find how bad content would slip through; keeps the gate honest |
| **tengoku-praiser** (this one) | credibility | gathers reasons to trust content that anyone can re-check |
| [tengoku-juridicator](https://github.com/competemath/tengoku-juridicator) | decision | weighs both with a fixed statute, history and a tightly leashed AI |

"Praise" here is not flattery. It is evidence a stranger can re-run, offered in favour of content, and of the AI system,
prompts, tools and team behind it. The juridicator gives praise nobody can check a weight of zero, lets checkable merit
lower scrutiny by one step at most, and never lets any amount of it outweigh a failed check. So this repository turns every
legitimate reason for trust into a *falsifiable* evidence record, and is ruthless about what is not falsifiable: it records
it, labels it attested, and expects it to be ignored.

Praise is bound by the same honesty rule as the wounder: declare a manifest of what will be reported, report every result,
failures included, never drop a bad one.

Read `docs/PRAISE-RULES.md` first (what counts and what does not), then `docs/AI-USE.md`, `SECURITY.md` (what is defended
and what is not) and `docs/IDEAS.md` (what is not built yet).

## What is here

| Module | What it turns into evidence | Kind it emits |
| --- | --- | --- |
| `praiser/attest.py` | which prompts, tools and toolchain made this: the declaration, and a check of the declared hashes against stored files | `attested.provenance`, `mechanical.provenance_consistent` |
| `praiser/merit.py` | Jinshi findings, proof-checker verdicts (one record per checker), axiom closure, no `sorry`, and the manifest | `mechanical.jinshi.<check>`, `mechanical.kernel_check`, `mechanical.axiom_closure`, `mechanical.no_sorry`, `manifest.declared` |
| `praiser/restatement.py` | a blind second formalization proposed by an AI, compared by a machine | `mechanical.restatement_match` |
| `praiser/preregistration.py` | the statement was committed before the proof existed | `mechanical.statement_preregistered` |
| `praiser/receipts.py` | two independent rebuilds agree | `reproducible.rebuild_match` |
| `praiser/track_record.py` | a reliability bound recomputed from the public ledger, and a re-deriver that catches a forged one | `reproducible.track_record` |
| `praiser/trustcard.py` | a plain-language Markdown card for a theorem or pull request | (not evidence; reads a verdict and evidence) |
| `praiser/cli.py` | `python -m praiser ...` | |

The logic modules are pure: no file, network or clock access, no AI. `praiser/loaders.py` and `praiser/cli.py` are the only
code that touches files. `tests/test_hygiene.py` enforces that.

## Use

```bash
python3 -m praiser hash-files --root checkout prompts/main.md tools/manifest.json lean-toolchain
python3 -m praiser attest --case case.json --producer author.json --spec spec.json --created 2026-10-09T00:00:00Z --out provenance.json
python3 -m praiser check-provenance --declared provenance.json --root checkout --case case.json --producer praiser.json --created ...
python3 -m praiser track-record --ledger ledger.jsonl --author agent-7                       # print the numbers
python3 -m praiser track-record --ledger ledger.jsonl --author agent-7 --case case.json --producer praiser.json --created ...
python3 -m praiser track-record --ledger ledger.jsonl --verify record.json                   # exit 12 if forged or stale
python3 -m praiser card --verdict verdict.json --evidence evidence/ --out card.md
python3 -m praiser manifest --case case.json --producer praiser.json --checks reproducible.rebuild_match --created ...
python3 -m praiser check-prereg ... ; python3 -m praiser compare-receipts a.json b.json --case ... 
python3 -m unittest discover -s tests
```

Exit codes: 0 ok, 2 bad input (`track-record --verify` also exits 12 when the record does not match the ledger). Nothing reads
a clock: every command that stamps a record takes `--created`.

Standard library only; Python 3.12; no network; no Lean is built or run; no AI is called anywhere.

## The contract

The only thing shared with the juridicator is the evidence record. `vendor/juridicator_evidence.py` is a byte-for-byte copy of
the juridicator's `juridicator/evidence.py`, pinned in `vendor/EVIDENCE.sha256`; a test fails if the copy and the pin
disagree. `python3 scripts/sync_contract.py --from ../tengoku-juridicator` refreshes both, and refuses a checkout whose
`evidence.py` is not the committed one. Import it as `from vendor.juridicator_evidence import make_evidence, validate`.

## Checking the tests themselves

`python3 scripts/mutation_check.py` breaks 89 key lines one at a time (make `check_provenance` always pass, count unlabeled
accepts, drop the ancestor requirement, ignore self-labels, ...) and confirms the suite fails each time.
`tests/test_integration.py` runs against a sibling `../tengoku-juridicator` checkout when there is one and skips cleanly when
there is not (as in CI).

## Status

A seed. The evidence builders, the track-record formula and re-deriver, and the trust card are real and tested; signing,
the lottery-bound labels in `docs/IDEAS.md`, and the live pipeline are not built. Private while it matures.
