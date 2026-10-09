"""Command line. Reads and writes JSON files. Exit codes: 0 ok, 2 bad input.

`track-record --verify` additionally exits 12 when the claimed record does not match the ledger (like the juridicator's
`ledger-verify`). Every command that stamps a time takes `--created` explicitly: nothing here reads a clock.
"""

from __future__ import annotations

import argparse
import sys

from . import attest, merit, preregistration, receipts, track_record, trustcard
from .common import sha256_bytes
from .loaders import InputError, read_files_under, read_json, read_ledger, read_records, write_json


def _common(p: argparse.ArgumentParser, *, created: bool = True) -> None:
    p.add_argument("--case", required=True)
    p.add_argument("--producer", required=True)
    if created:
        p.add_argument("--created", required=True)
    p.add_argument("--out")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="praiser")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("attest", help="write an attested.provenance record from a spec file")
    _common(p)
    p.add_argument("--spec", required=True, help="JSON: model, model_family, prompt_sha256, tool_manifest, toolchain, rubric_version, human_signoffs")
    p = sub.add_parser("hash-files", help="print {path: sha-256} for files in a checkout")
    p.add_argument("--root", required=True)
    p.add_argument("paths", nargs="+")
    p = sub.add_parser("check-provenance", help="compare declared hashes with the stored files")
    _common(p)
    p.add_argument("--declared", required=True)
    p.add_argument("--root", required=True)
    p = sub.add_parser("track-record", help="compute, emit or verify a track record from a ledger")
    p.add_argument("--ledger", required=True)
    p.add_argument("--author")
    p.add_argument("--as-of", type=int)
    p.add_argument("--humans", help="JSON list of identities whose labels count")
    p.add_argument("--case")
    p.add_argument("--producer")
    p.add_argument("--created")
    p.add_argument("--verify", help="a claimed track-record record to re-derive from the ledger")
    p.add_argument("--max-lag", type=int)
    p.add_argument("--out")
    p = sub.add_parser("card", help="render a trust card")
    p.add_argument("--verdict", required=True)
    p.add_argument("--evidence", nargs="+", required=True)
    p.add_argument("--out")
    p = sub.add_parser("manifest", help="declare the kinds a producer will report")
    _common(p)
    p.add_argument("--checks", nargs="+", required=True)
    p = sub.add_parser("check-prereg", help="check a statement against its earlier commitment")
    _common(p)
    p.add_argument("--commitment", required=True)
    p.add_argument("--statement", required=True, help="file holding the statement text")
    p.add_argument("--nonce", required=True)
    p.add_argument("--committed-in", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--is-ancestor", required=True, choices=("yes", "no", "unknown"))
    p = sub.add_parser("compare-receipts", help="compare two rebuild receipts")
    _common(p)
    p.add_argument("receipts", nargs=2)
    return ap


def _run(args: argparse.Namespace) -> int:
    if args.cmd == "hash-files":
        files = read_files_under(args.root, args.paths)
        write_json({p: sha256_bytes(files[p]) for p in sorted(files)}, None)
        return 0
    if args.cmd == "card":
        verdict = read_json(args.verdict)
        text = trustcard.render(verdict, read_records(args.evidence))
        if args.out and args.out != "-":
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
        else:
            sys.stdout.write(text)
        return 0
    if args.cmd == "track-record":
        entries = read_ledger(args.ledger)
        humans = read_json(args.humans) if args.humans else None
        if args.verify:
            ok, problems = track_record.verify_against_ledger(read_json(args.verify), entries, humans=humans, max_lag=args.max_lag)
            write_json({"ok": ok, "problems": problems}, args.out)
            return 0 if ok else 12
        if not args.author:
            raise InputError("--author is required")
        if args.case:
            if not args.producer or not args.created:
                raise InputError("--case needs --producer and --created")
            rec = track_record.track_record_evidence(args.author, entries, read_json(args.case), read_json(args.producer),
                                                     args.created, humans=humans, as_of_seq=args.as_of)
            write_json(rec, args.out)
        else:
            write_json(track_record.compute(entries, args.author, humans=humans, as_of_seq=args.as_of), args.out)
        return 0
    case, producer = read_json(args.case), read_json(args.producer)
    if args.cmd == "attest":
        spec = read_json(args.spec)
        if not isinstance(spec, dict):
            raise InputError("spec must be an object")
        rec = attest.provenance_attestation(case, producer, created=args.created, **{
            k: spec.get(k) for k in ("model", "model_family", "prompt_sha256", "tool_manifest", "toolchain", "rubric_version")
        }, human_signoffs=spec.get("human_signoffs", []))
    elif args.cmd == "check-provenance":
        declared = read_json(args.declared)
        d = declared.get("details", declared) if isinstance(declared, dict) else None
        if not isinstance(d, dict):
            raise InputError("declared must be an attestation record or its details")
        paths = [p for key in ("prompts", "tool_manifest", "toolchain") if isinstance(d.get(key), dict) for p in d[key]]
        rec = attest.check_provenance(declared, read_files_under(args.root, paths), case, producer, args.created)
    elif args.cmd == "manifest":
        rec = merit.manifest(case, producer, args.checks, args.created)
    elif args.cmd == "check-prereg":
        try:
            with open(args.statement, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            raise InputError(f"cannot read {args.statement}: {exc}") from exc
        anc = {"yes": True, "no": False, "unknown": None}[args.is_ancestor]
        rec = preregistration.check_preregistration(args.commitment, text, args.nonce, case, producer, args.created,
                                                    args.committed_in, args.head, anc)
    elif args.cmd == "compare-receipts":
        rec = receipts.compare_receipts(read_json(args.receipts[0]), read_json(args.receipts[1]), case, producer, args.created)
    else:  # pragma: no cover - argparse refuses unknown commands
        raise InputError(f"unknown command {args.cmd}")
    write_json(rec, args.out)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except (InputError, ValueError, KeyError, TypeError, OSError) as exc:
        print(f"praiser: bad input: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
