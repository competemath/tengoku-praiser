"""Provenance: which model, prompts, tools and toolchain made this, as a claim and as a check.

Two records come out of this module, and the difference between them is the point of the whole repository:

  * `provenance_attestation` is the author system's *declaration*. It is `attested`: a party's word, shown to people and
    weighed at zero by the juridicator. Everything that cannot be checked (model name, "careful team", human
    sign-offs, the rubric version) lives only here.
  * `check_provenance` turns the part that CAN be checked into a `mechanical.provenance_consistent` record: it hashes
    the files that are actually stored (prompts, tool manifest, toolchain pin) and compares them with the hashes that
    were declared. A declaration is a mapping {stored path: sha-256}; a hash with no path could never be checked, so it
    is refused. The check does not read files itself: the caller passes `actual`, a dict of path -> bytes, read from the
    checkout of the exact commit (see `loaders.read_files_under`).

A failed check is a `fail` (so, under the default policy, a rejection): declaring one thing and storing another is
not a harmless mistake in a system whose point is that declarations are checkable.
"""

from __future__ import annotations

import re
from typing import Iterable

from vendor.juridicator_evidence import canonical_json

from .agentrun import tool_policy_fact
from .common import cap_command, case_ref, clip, fit_details, hash_map, make, producer_ref, require_hex64, sha256_bytes

GROUPS = (("prompt", "prompts"), ("tool manifest", "tool_manifest"), ("toolchain", "toolchain"))
UNVERIFIABLE = ("model", "model_family", "rubric_version", "human_signoffs")
TOPIC = re.compile(r"^[a-z0-9_]+$")


def combined_digest(prompts: dict[str, str]) -> str:
    """One hash for a set of prompts: the single hash itself when there is one, else a hash over the sorted mapping."""
    if len(prompts) == 1:
        return next(iter(prompts.values()))
    return sha256_bytes(canonical_json(sorted(prompts.items())).encode("utf-8"))


def provenance_attestation(
    case: dict,
    producer: dict,
    *,
    model: str,
    model_family: str,
    prompt_sha256: dict,
    tool_manifest: dict,
    toolchain: dict,
    rubric_version: str,
    human_signoffs: Iterable[str],
    created: str,
    tool_policy: object = None,
    jail_spec_sha256: str | None = None,
) -> dict:
    """The author system's declaration (`attested.provenance`, outcome pass, verifiability attested).

    `prompt_sha256`, `tool_manifest` and `toolchain` are each {stored path: sha-256}: the files, in the repository
    at this commit, whose hashes are being declared. `check_provenance` is what makes them mean something.

    Optionally (both default to nothing, and then the record is exactly what it always was) the declaration also names the agent's
    confinement: `tool_policy` (the tool policy the agent ran under, a mapping or warden's `ToolPolicy`; its name, tool set and
    hash are recorded) and `jail_spec_sha256` (the digest of the jail specification). They are declared facts like the rest;
    `agentrun.agent_contained(..., declared=agentrun.declared_digests(record))` is what checks the audit reports against them.
    """
    prompts = hash_map(prompt_sha256, "prompt_sha256")
    if not prompts:
        raise ValueError("an attestation with no prompt declares nothing worth checking")
    tools = hash_map(tool_manifest, "tool_manifest")
    chain = hash_map(toolchain, "toolchain")
    for name, value in (("model", model), ("model_family", model_family), ("rubric_version", rubric_version)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if isinstance(human_signoffs, (str, bytes)):
        raise ValueError("human_signoffs must be a list of identities, not one string")
    signoffs = sorted({str(s) for s in human_signoffs})
    details = {
        "model": clip(model, 120),
        "model_family": clip(model_family, 60),
        "prompts": prompts,
        "tool_manifest": tools,
        "toolchain": chain,
        "rubric_version": clip(rubric_version, 60),
        "human_signoffs": [clip(s, 80) for s in signoffs[:20]],
        "not_checkable": list(UNVERIFIABLE),
    }
    if tool_policy is not None:
        details["tool_policy"] = tool_policy_fact(tool_policy)
    if jail_spec_sha256 is not None:
        details["jail_spec_sha256"] = require_hex64(jail_spec_sha256, "jail_spec_sha256")
    return make(
        case=case_ref(case),
        producer=producer_ref(producer),
        kind="attested.provenance",
        claim=clip(f"Declared, not verified: made by {model} (family {model_family}) with {len(prompts)} prompt file(s), "
                   f"{len(tools)} tool manifest(s), {len(chain)} toolchain pin(s)."),
        outcome="pass",
        verifiability="attested",
        created=created,
        ai={"used": True, "role": "proposer", "model": clip(model, 120), "family": clip(model_family, 60),
            "prompt_sha256": combined_digest(prompts)},
        details=fit_details(details),
    )


def attested_claim(case: dict, producer: dict, topic: str, text: str, created: str) -> dict:
    """A statement that cannot be checked ("careful team", "reviewed by a senior person"). Recorded as
    `attested.<topic>`, shown on the trust card under "noted, not weighed", and worth exactly nothing to the judge."""
    if not isinstance(topic, str) or not TOPIC.match(topic):
        raise ValueError("topic must be lowercase letters, digits and underscores")
    return make(
        case=case_ref(case), producer=producer_ref(producer), kind=f"attested.{topic}",
        claim=clip(text), outcome="pass", verifiability="attested", created=created,
        details={"weighed": False},
    )


def _declared_details(declared: dict, case: dict) -> dict:
    if not isinstance(declared, dict):
        raise ValueError("declared must be an attestation record or its details")
    if declared.get("kind") is not None:
        if declared.get("kind") != "attested.provenance":
            raise ValueError("declared is not an attested.provenance record")
        if declared.get("case", {}).get("head_sha") != case_ref(case)["head_sha"]:
            raise ValueError("the declaration is about another commit")
        details = declared.get("details")
    else:
        details = declared
    if not isinstance(details, dict):
        raise ValueError("declared has no details")
    return {key: hash_map(details.get(key, {}), key) for _, key in GROUPS}


def check_provenance(declared: dict, actual: dict, case: dict, producer: dict, created: str, *, command: str | None = None) -> dict:
    """`mechanical.provenance_consistent`: recompute the hash of every stored file that was declared and compare.

    pass         every declared hash equals the hash of the stored file at that path, and something was declared
                 in each of the three groups (prompts, tool manifest, toolchain);
    fail         at least one declared hash does not match, or names a file that is not stored. The claim names exactly
                 which declarations did not match;
    inconclusive everything declared matches, but a whole group was left empty, so there was nothing to check there.
    """
    decl = _declared_details(declared, case)
    if not isinstance(actual, dict) or not all(isinstance(v, (bytes, bytearray)) for v in actual.values()):
        raise ValueError("actual must map stored paths to bytes")
    rows, mismatches = [], []
    for label, key in GROUPS:
        for path, want in sorted(decl[key].items()):
            data = actual.get(path)
            got = sha256_bytes(bytes(data)) if data is not None else None
            row = {"what": label, "path": clip(path, 120), "declared": want, "actual": got}
            rows.append(row)
            if got != want:
                row["why"] = "not stored" if got is None else "hash differs"
                mismatches.append(row)
    empty = [label for label, key in GROUPS if not decl[key]]
    if mismatches:
        outcome = "fail"
        named = "; ".join(f"{m['what']} {m['path']} ({m['why']})" for m in mismatches[:4])
        more = f" (+{len(mismatches) - 4} more)" if len(mismatches) > 4 else ""
        claim = clip(f"Provenance does not match the stored files: {named}{more}")
    elif empty:
        outcome = "inconclusive"
        claim = clip("What was declared matches the stored files, but nothing was declared for: " + ", ".join(empty))
    else:
        outcome = "pass"
        claim = clip(f"All {len(rows)} declared hashes (prompts, tool manifest, toolchain) match the stored files.")
    paths = " ".join(r["path"] for r in rows)
    how = command or (
        "python3 -m praiser check-provenance --declared attested_provenance.json --root <checkout of this commit> "
        f"--case case.json --producer producer.json --created <time>   # or by hand: sha256sum -- {paths}"
    )
    details = {
        "n_checked": len(rows),
        "n_mismatched": len(mismatches),
        "mismatches": mismatches[:20],
        "empty_groups": empty,
        "matched_paths": [r["path"] for r in rows if r not in mismatches][:30],
        "not_checked": list(UNVERIFIABLE),
    }
    return make(
        case=case_ref(case), producer=producer_ref(producer), kind="mechanical.provenance_consistent",
        claim=claim, outcome=outcome, verifiability="mechanical", created=created,
        reproduce={"command": cap_command(how)},
        details=fit_details(details, ("matched_paths", "mismatches")),
    )
