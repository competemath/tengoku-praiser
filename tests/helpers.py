"""Shared fixtures. No clock, no files outside temp dirs, no network."""

from vendor.juridicator_evidence import make_evidence
from praiser.track_record import GENESIS, entry_hash

HEAD = "a" * 40
OLDER = "b" * 40
REPO = "competemath/tengoku-sandbox"
CASE = {"repo": REPO, "head_sha": HEAD, "class": "content", "author": {"identity": "agent-7", "family": "family-a"}}
NOW = "2026-10-09T00:00:00Z"
PRAISER = {"role": "praiser", "name": "tengoku-praiser", "identity": "tengoku-praiser"}
TOOLING = {"role": "tooling", "name": "ci", "identity": "ci"}
AUTHOR = {"role": "author-system", "name": "agent-7", "identity": "agent-7"}
H = "c" * 64
H2 = "d" * 64


def case(head=HEAD):
    return {"repo": REPO, "head_sha": head, "class": "content"}


def sha(n: int) -> str:
    return f"{n:040x}"


class Chain:
    """Builds a valid ledger (list of entries) the way the juridicator's Ledger does."""

    def __init__(self):
        self.entries = []

    def add(self, kind, body):
        prev = self.entries[-1]["hash"] if self.entries else GENESIS
        seq = len(self.entries)
        self.entries.append({"seq": seq, "kind": kind, "body": body, "prev": prev, "hash": entry_hash(seq, kind, body, prev)})
        return seq

    def provenance(self, head, author="agent-7"):
        ev = make_evidence(case=case(head), producer={"role": "author-system", "name": author, "identity": author},
                           kind="attested.provenance", claim="declared", outcome="pass", verifiability="attested", created=NOW)
        return self.add("evidence", ev)

    def verdict(self, head, decision="ACCEPT"):
        return self.add("verdict", {"case": {"repo": REPO, "head_sha": head, "class": "content"}, "decision": decision})

    def label(self, head, label, by="alice"):
        return self.add("label", {"repo": REPO, "head_sha": head, "label": label, "by": by})

    def accepted(self, n, author="agent-7", label="accept", by="alice", start=1000):
        """n heads, each: provenance, ACCEPT, then (if label) a human label."""
        heads = []
        for i in range(n):
            head = sha(start + len(self.entries) * 7 + i)
            self.provenance(head, author)
            self.verdict(head)
            if label:
                self.label(head, label, by)
            heads.append(head)
        return heads


def tamper(entries, index, **changes):
    """A copy of the ledger with entry `index`'s body changed but its hash left alone (so the chain breaks)."""
    import copy

    out = copy.deepcopy(entries)
    out[index]["body"] = dict(out[index]["body"], **changes)
    return out
