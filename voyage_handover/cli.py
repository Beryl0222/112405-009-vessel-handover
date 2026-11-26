"""Command line interface for continuous hand-over processing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .briefing import render_markdown
from .store import HandoverStore


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_text(path: str | Path | None, text: str) -> None:
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _load_or_create_store(path: str | Path | None, case_path: str | Path | None) -> HandoverStore:
    if path and Path(path).exists():
        return HandoverStore.load(path)
    if case_path:
        case = _read_json(case_path)
        return HandoverStore.from_case(case)
    if path:
        return HandoverStore()
    raise SystemExit("either --case or an existing --store is required")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voyage-handover",
        description="Organize multilingual vessel hand-over texts with sentence-level provenance.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build a store and briefing from a case JSON file")
    build.add_argument("case", help="path to case JSON")
    build.add_argument("--store", help="persistent state JSON output path")
    build.add_argument("--brief", help="Markdown briefing output path; defaults to stdout")
    build.add_argument("--json", dest="json_out", help="full structured analysis JSON output path")

    ingest = sub.add_parser("ingest", help="ingest new record JSON files into a persistent store")
    ingest.add_argument("--store", required=True, help="persistent state JSON path")
    ingest.add_argument("records", nargs="+", help="record JSON files, each a record or {'records': [...]}")
    ingest.add_argument("--brief", help="optional Markdown briefing output path")

    show = sub.add_parser("show", help="render Markdown briefing from a store")
    show.add_argument("--store", required=True)
    show.add_argument("--brief", help="output Markdown path; defaults to stdout")

    trace = sub.add_parser("trace", help="trace a sentence ID through all judgements")
    trace.add_argument("--store", required=True)
    trace.add_argument("sentence_id")

    verify = sub.add_parser("verify", help="verify the track hash chain")
    verify.add_argument("--store", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        store = HandoverStore.from_case(_read_json(args.case))
        if args.store:
            store.save(args.store)
        briefing = store.briefing()
        markdown = render_markdown(briefing)
        if args.json_out:
            Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json_out).write_text(
                json.dumps(store.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        _write_text(args.brief, markdown)
        if not args.brief:
            sys.stdout.write("\n")
        return 0

    if args.command == "ingest":
        if Path(args.store).exists():
            store = HandoverStore.load(args.store)
        else:
            first_payload = _read_json(args.records[0])
            if isinstance(first_payload, dict) and "records" in first_payload:
                store = HandoverStore.from_case(first_payload)
            else:
                vessels = first_payload.get("vessels", []) if isinstance(first_payload, dict) else []
                store = HandoverStore(case_id=first_payload.get("case_id") if isinstance(first_payload, dict) else None, vessels=vessels)
        for filename in args.records:
            payload = _read_json(filename)
            if isinstance(payload, dict) and payload.get("vessels") and not store.vessels:
                store.vessels = list(payload["vessels"])
                from .entities import VesselRegistry

                store.analyzer.registry = VesselRegistry(store.vessels)
            records = payload.get("records", []) if isinstance(payload, dict) and "records" in payload else [payload]
            for record in records:
                store.ingest_record(record)
        store.save(args.store)
        if args.brief:
            Path(args.brief).write_text(render_markdown(store.briefing()), encoding="utf-8")
        sys.stdout.write(f"ingested {len(args.records)} file(s); store={args.store}\n")
        return 0

    if args.command == "show":
        store = HandoverStore.load(args.store)
        _write_text(args.brief, render_markdown(store.briefing()))
        if not args.brief:
            sys.stdout.write("\n")
        return 0

    if args.command == "trace":
        store = HandoverStore.load(args.store)
        sys.stdout.write(json.dumps(store.trace(args.sentence_id), ensure_ascii=False, indent=2) + "\n")
        return 0

    if args.command == "verify":
        store = HandoverStore.load(args.store)
        ok = store.verify_track_chain()
        sys.stdout.write(("OK" if ok else "FAILED") + f": {len(store.track_chain)} track records\n")
        return 0 if ok else 2

    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
