# Ideas not yet built

Reasons to trust AI-made Lean content that are worth building and are not here. Each says how it would be falsifiable: what
a stranger re-runs, and what result would show the reason was wrong. Quality over count; six, ordered by how much they
change the picture.

## 1. Lottery-bound labels (audit-complete track records)

**The gap.** Today only human-labeled cases count, and an unexamined accept counts for nothing. That stops grinding but
leaves selection: if only convenient cases get labeled, good ones are labeled and a bad one is simply never looked at, and the
record looks perfect.
**Idea.** A case may count toward a track record only if it was *selected by the audit lottery* (the salt is committed as a
hash before the batch and revealed afterwards), or if its label is a reject. Selection is then not the author's or
labeler's choice, and a bad accept has the same chance of being drawn as a good one, so the observed rate estimates the true
rate.
**Falsifiable by.** Recomputing the draw from the revealed salt and the public case ids: a counted case that was not drawn
and is not a reject falsifies the record. A record with no draws unlabeled falsifies it too (a drawn case that was never
labeled is itself reported, as unexamined, and counts as a failure of the labelers, not a pass).

## 2. Non-vacuity witnesses

**The gap.** A theorem with contradictory hypotheses, or about a definition that is accidentally empty, is proved
"successfully" and says nothing. This is one of the commonest ways a mistranslated statement slips through.
**Idea.** For each declared theorem, emit a kernel-checked witness that its hypotheses are jointly satisfiable (an `example`
that builds a concrete instance), and a second witness that dropping each hypothesis one at a time makes the statement false
or unprovable by a fixed-budget automation pass (so no hypothesis is decorative). AI may propose the witnesses; the kernel
decides.
**Falsifiable by.** Re-running the kernel on the witness file. A hypothesis set with no witness, or a witness the kernel
rejects, is a visible failure; so is a "necessary" hypothesis whose removal leaves the statement provable.

## 3. Worked examples from the source text

**The gap.** Misformalized definitions usually disagree with the source on small cases, but nobody checks small cases.
**Idea.** The source (paper, textbook, OEIS entry) contains examples: "the first values are 1, 1, 2, 5, 14", "this graph has
chromatic number 3". Extract them as `example : f 4 = 14 := by decide`-style goals, with the source location and quote hash in
the record. AI proposes the extraction (as data); the kernel or `decide` decides each.
**Falsifiable by.** Re-running the file. A definition that fails the source's own example is wrong or mistranslated. Coverage is
reported too (examples found, examples formalized), so omission cannot be hidden.

## 4. Additive-only certificate

**The gap.** The risk of a pull request is as much in what it changes elsewhere as in what it adds: a new simp rule, instance
or notation can silently alter existing proofs and statements.
**Idea.** Emit a diff of the library's exported surface before and after the change: the type of every pre-existing declaration,
and every global-effect attribute (simp rule, instance with its priority, notation, macro) added. A purely additive and local
change has an empty diff, which is a strong, boring, cheap-to-check reason to lower scrutiny.
**Falsifiable by.** Exporting both commits and diffing. Any pre-existing type that differs, or any global attribute not
listed, falsifies it. The export, the diff and the list are all deterministic.

## 5. Scored forecasts from the author system

**The gap.** An AI's own confidence is attested, so it is ignored, though it is information.
**Idea.** Before the checks run, the author system commits (by hash, like a pre-registration) a probability for each case that
it will survive an independent audit. Outcomes arrive from the lottery in idea 1; forecasts are scored with a proper scoring
rule (Brier or log score) and a calibration curve. A system whose stated 90% means 90% earns the right to have its *doubt*
used to route audits (spend scrutiny where it says it is unsure); it never earns acceptance.
**Falsifiable by.** Recomputing the score from committed hashes and ledger labels. A system that is overconfident or
uninformative scores worse than a constant guess, and the record shows it.

## 6. Anchor bridges and N-version translation

**The gap.** The blind restatement in `restatement.py` compares two AI formalizations of a problem statement. Where a
human-written formal statement already exists (another library, an earlier version), a stronger comparison is available.
**Idea.** Ask the AI to propose a bridge proof of equivalence between the translated statement and the human-written anchor,
and have the kernel check it. Independently, have two systems from different model families translate the same source and
check their statements pairwise by machine. Agreement across families is evidence that is not just one model's blind spot
repeated; disagreement is the most useful signal the process can produce.
**Falsifiable by.** The kernel re-checking the bridge; the pairwise comparison re-run. A bridge that does not check, or a
pair that disagrees, is a failure on the record, not a drop.
