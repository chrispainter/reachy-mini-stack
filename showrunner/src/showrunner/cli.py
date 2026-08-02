"""Dry-run a set from a document. The primary development loop."""

import argparse
import sys
from pathlib import Path

from showrunner.claude import RefusalError
from showrunner.ingest import extract_facts
from showrunner.models import Knobs, SetList, StatusDoc
from showrunner.writer import write_setlist


def format_setlist(doc: StatusDoc, setlist: SetList) -> str:
    lines = [f"=== {doc.title} ===", "", f"OPEN: {setlist.opener}", ""]
    for beat in setlist.beats:
        lines.append(f"[{beat.id}] ({beat.source_fact_id}, move: {beat.move_hint})")
        lines.append(f"  premise: {beat.premise}")
        lines.append(f"  angle:   {beat.angle}")
        if beat.act_out:
            lines.append(f"  act-out: {beat.act_out}")
        lines.append(f"  PUNCH:   {beat.punch}")
        for tag in beat.tags:
            lines.append(f"  tag:     {tag}")
        lines.append("")
    lines.append(f"CLOSE: {setlist.closer}")
    if setlist.callbacks:
        lines.extend(["", f"callbacks: {', '.join(setlist.callbacks)}"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a comedy set from a document.")
    parser.add_argument("document", help="path to the source document")
    parser.add_argument("--beats", type=int, default=5, help="number of beats")
    parser.add_argument("--edge", default="pg13", choices=["clean", "pg13", "blue"])
    parser.add_argument("--notes", default="", help="extra direction for the writer")
    args = parser.parse_args(argv)

    path = Path(args.document)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1

    knobs = Knobs(beat_count=args.beats, edge=args.edge, persona_notes=args.notes)
    try:
        doc = extract_facts(path.read_text())
        setlist = write_setlist(doc, knobs)
    except RefusalError as exc:
        print(f"error: Claude declined the request: {exc}", file=sys.stderr)
        return 2
    except (ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(format_setlist(doc, setlist))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
