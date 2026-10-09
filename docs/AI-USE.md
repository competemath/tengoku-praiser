# How AI is used in the praiser

The rules for AI in this program are written in the juridicator's policy,
[`docs/AI-USE.md`](https://github.com/competemath/tengoku-juridicator/blob/main/docs/AI-USE.md), and bind this repository
too. In particular: AI proposes, machines dispose; everything AI-made is labeled; no tools, no network, no secrets; AI cannot
write the rules. This file says only what that means here.

## What the praiser's AI interface may do

**Exactly one thing: propose a second, blind formalization of a problem, as data. A machine then checks it.**

- `praiser.restatement.propose_restatement(backend, problem_text)` builds a prompt from the plain-language problem and
  nothing else (the original formal statement is never in it), calls the backend the *caller* supplies, and returns
  `{statement, prompt_sha256, model, family}`. Nothing in this package constructs a backend; none ships; tests use a plain
  fake object, not an AI.
- The proposed statement is cleaned (control characters removed, length capped) and is only ever written to a file and
  handed to a deterministic checker. It is never executed here.
- `restatement_evidence` records what the *machine* said (`equivalent` true, false or unknown becomes pass, fail or
  inconclusive). The record's `ai` field says an AI was used, as `proposer`, with its model, family and prompt hash. The AI's
  opinion about equivalence is not an input.

## Rules enforced by code and tests

| Rule | Where |
| --- | --- |
| A backend must expose `tools == ()`; read from the object, not a flag; refused before it is called; a backend that does not say is refused too | `restatement.propose_restatement`, `tests/test_restatement.py` |
| No module calls an AI; none imports an AI vendor library; only the standard library is imported | `tests/test_hygiene.py` |
| No clock, no network, no files in the logic modules | `tests/test_hygiene.py` |
| Every record that involves AI says so: `ai.used`, `role`, `model`, `family`, `prompt_sha256` | `restatement.restatement_evidence`, `attest.provenance_attestation` |
| The AI never decides a fact: provenance is hashes, the track record is arithmetic over the ledger, the card is a template | the modules themselves |
| The AI cannot write a verdict, a label or this repository's rules | role limits; `.github/CODEOWNERS` |

## What the AI is never asked to do here

Decide that a restatement is equivalent. Judge a track record. Write or edit the trust card (it is a deterministic template; a
sentence on it that came from a record is escaped and labeled "noted, not weighed"). Choose which evidence the judge sees.
Read credentials, run commands or browse.

## The author's AI is a subject, not a tool

`attested.provenance` records that the content was made with an AI (`ai.used` true, role `proposer`, the declared model and
prompt hash). That is information about the subject. It is attested, and the part of it that can be checked (the hashes of
stored prompts, tool manifest and toolchain pin) becomes a separate mechanical record.
