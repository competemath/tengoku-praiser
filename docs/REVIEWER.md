# The reviewer's mechanical checks

What a Mathlib reviewer does by reading a pull request, as checks anyone can re-run. Each check turns Lean source (and, for
some, a compiler's answer) into findings, and `python3 -m praiser review` turns the findings into one
`mechanical.review.<check>` evidence record per check, plus a `manifest.declared` promising all of them first.

Nothing here is an opinion. A finding is a rule that fired on a line, or a module the compiler accepted. What the findings are
worth, and what the bar is, is the juridicator's statute; this repository only makes the facts re-checkable.

## The checks

| check | needs Lean | what it finds |
| --- | --- | --- |
| `style` | no | whitespace, line length, an isolated `by` or `·`, `;` at the end of a line, `$` and `λ`, `sorry`, `native_decide`, `axiom`, debug commands, `maxHeartbeats`, `autoImplicit true`, import order and duplicates, `open Classical`, bare `@[deprecated]`, TODO markers, very long proofs (table in `stylelint.RULES`) |
| `naming` | no | Mathlib's case rules, placeholder and machine-made names, numbered names, a name that says an operation the statement lacks, a name that shares nothing with the statement, a name already in the library, short variable names; `naming.suggest` gives the name the conventions would give |
| `docs` | no | module docstring (title, main results), a docstring on every public definition, docstrings that only repeat the name, backticked names that resolve nowhere |
| `api` | no | `_left` without `_right`, a definition no lemma mentions, a structure without `ext`, statements written `≥`/`>`, `¬ a = b`, `Nat.succ n`, `Type u` |
| `dedupe` | no | the statement is already there (identical up to renaming), is a specialisation of an existing one, is almost one, or generalises existing ones |
| `reuse` | no | how many existing declarations prove an instance of it inline (a `have`/`show`), and none at all |
| `hoist` | no | helpers copied identically into several modules of one proposal |
| `lint` | yes | Batteries' `#lint` (`unusedArguments`, `docBlame`, `simpNF`, `defLemma`, `checkUnivs` ...) |
| `compiler` | yes | the warnings of Mathlib's `linter.style.*`, `linter.flexible`, `linter.unusedTactic` and `linter.unusedVariables` |
| `generalise` | yes | a more general statement the same proof still proves: drop a hypothesis, numeral to variable, type to a type class, `<` to `≤`. The finding carries the module that was compiled |
| `minimise` | yes | tactic steps nothing needs (delta-debugging, 1-minimal), and a theorem one cheap tactic closes |
| `robust` | yes | the module needs a `set_option` of its author, needs `autoImplicit`, or breaks at half the heartbeats |
| `compat` | yes, two | does not compile on the next toolchain (each error classified), uses a deprecated name, elaborates differently there |

## Rules every check follows

- **No answer is not a pass.** A check that needs Lean and was given none is `not_run`. A compiler that timed out, crashed or ran out
  of budget gives `inconclusive`. A `#lint` output that does not agree with its own summary is `inconclusive`. Only a decided answer
  produces `pass`.
- **A patch is a module the compiler accepted.** `generalise` and `minimise` put forward text that was compiled, never a suggestion.
  `patch` travels in a file (`--patches-dir`); the record keeps its hash and size.
- **A `sorry` is not compiling.** The oracle's verdict is False for a module that compiled with a `sorry` warning.
- **Deterministic.** Same input, same findings, same record ids. Findings are sorted; budgets are call counts (never a clock); nothing
  reads time, network or the environment except `loaders.py`.
- **Bounded.** One global budget caps the compiler calls of a review (`--total-calls`), and each theorem has its own
  (`--per-theorem`); running out is reported, not hidden.

## The compile oracle

`--compile-cmd CMD` is run as `CMD <file.lean>`: exit 0 means it compiled (output kept, so warnings are read), exit 1 means an
error, anything else, or a timeout, means no answer. `--forward-cmd` is the same for the toolchain the library will move to.
`lake env lean` on a project that has the library built is the usual command.

**It is not a sandbox.** Lean runs the code of the file it elaborates (`run_cmd`, `elab`, `#eval`, macros), and the file is a
stranger's. Run the reviewer where a hostile module does no harm: a runner with no secrets and no egress. The command is run with a
scrubbed environment, a scratch `HOME`, its own process group (killed on timeout), and bounded output; that is all.

## Limits, said plainly

- Matching is on tokens, not on terms. `dedupe` and `reuse` find what a careful grep would find, everywhere; they do not find a
  duplicate that only unification up to definitional equality would see.
- The `#lint` parser follows Batteries' documented output; the style option names and the type-class ladder follow current Mathlib.
  A toolchain that renames either makes the check `inconclusive` (an unknown option) or find less (a class that does not
  exist does not compile). Rehearse once on the pinned toolchain after a bump: `tests/` run against fakes, never against Lean.
- Nothing here judges whether a result is *worth having*. `reuse` and `dedupe` give evidence for that question; the answer is the
  statute's and, where it asks, a person's.
