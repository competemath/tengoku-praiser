"""Commit before the attempt: the statement could not have been adjusted to fit the proof afterwards.

A statement is committed to (hash of its normalized text plus a nonce) in a commit that must be a strict ancestor of the
commit carrying the proof. If the hash matches and the ancestry holds, the statement was fixed before the proof existed.
Whether one commit is an ancestor of another is a fact about git, so the caller supplies `is_ancestor` (for example from
`git merge-base --is-ancestor`); this module does no IO.

Normalization is deliberately strict: whitespace is collapsed (runs of spaces, tabs and newlines become one space, ends
trimmed) and NOTHING else is touched. Case, unicode, binder names and comments all count. A statement edited in any way
other than whitespace is a different statement, and the check says so.
"""

from __future__ import annotations

import re

from vendor.juridicator_evidence import SHA40

from .common import cap_command, case_ref, clip, make, producer_ref, sha256_bytes

DOMAIN = "tengoku-prereg/1"
COMMITMENT = re.compile(r"^sha256:[0-9a-f]{64}$")


def normalize(statement_text: str) -> str:
    return " ".join(statement_text.split())


def commit_statement(statement_text: str, nonce: str) -> str:
    """`sha256:<hex>` over a domain tag, the nonce and the normalized statement. The nonce stops anyone from checking a
    guessed statement against a published commitment before the statement is revealed."""
    if not isinstance(statement_text, str) or not normalize(statement_text):
        raise ValueError("statement_text must be non-empty")
    if not isinstance(nonce, str) or not nonce:
        raise ValueError("nonce must be a non-empty string")
    return "sha256:" + sha256_bytes(f"{DOMAIN}\n{nonce}\n{normalize(statement_text)}".encode("utf-8"))


def check_preregistration(
    commitment: str,
    statement_text: str,
    nonce: str,
    case: dict,
    producer: dict,
    created: str,
    committed_before_sha: str,
    head_sha: str,
    is_ancestor: bool | None,
) -> dict:
    """`mechanical.statement_preregistered`. Pass only if (1) the statement and nonce reproduce the commitment, (2) the
    commit that recorded the commitment is a strict ancestor of `head_sha`, and (3) `head_sha` is the case's commit.
    `is_ancestor` None means git could not answer: inconclusive."""
    case_r = case_ref(case)
    for name, sha in (("committed_before_sha", committed_before_sha), ("head_sha", head_sha)):
        if not isinstance(sha, str) or not SHA40.match(sha):
            raise ValueError(f"{name} must be a 40-hex commit")
    if is_ancestor is not True and is_ancestor is not False and is_ancestor is not None:
        raise ValueError("is_ancestor must be True, False or None")
    problems = []
    if not isinstance(commitment, str) or not COMMITMENT.match(commitment) or commitment != commit_statement(statement_text, nonce):
        problems.append("the statement and nonce do not reproduce the commitment")
    if head_sha != case_r["head_sha"]:
        problems.append("the commit carrying the proof is not this case's commit")
    if committed_before_sha == head_sha:
        problems.append("the commitment was recorded in the same commit as the proof, not before it")
    elif is_ancestor is False:
        problems.append("the commitment's commit is not an ancestor of the proof's commit")
    if problems:
        outcome, claim = "fail", clip("Statement not shown to be fixed before the proof: " + "; ".join(problems) + ".")
    elif is_ancestor is None:
        outcome, claim = "inconclusive", "The commitment matches, but git could not say whether it came before the proof."
    else:
        outcome, claim = "pass", "The statement matches a commitment recorded in an earlier commit than the proof."
    how = (f"python3 -m praiser check-prereg --commitment {commitment} --statement statement.txt --nonce <nonce> "
           f"--committed-in {committed_before_sha} --head {head_sha} --is-ancestor <yes|no|unknown>   # ancestry from: "
           f"git merge-base --is-ancestor {committed_before_sha} {head_sha}")
    return make(
        case=case_r, producer=producer_ref(producer), kind="mechanical.statement_preregistered", claim=claim,
        outcome=outcome, verifiability="mechanical", created=created, reproduce={"command": cap_command(how)},
        details={"commitment": clip(commitment, 80), "committed_before_sha": committed_before_sha, "head_sha": head_sha,
                 "is_ancestor": is_ancestor, "problems": problems},
    )
