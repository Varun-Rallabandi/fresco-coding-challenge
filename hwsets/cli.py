"""Command line entry point.

    python -m hwsets.cli extract path/to/book.pdf -o outputs/book.json
    python -m hwsets.cli batch data/ -o outputs/
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

from .cache import Cache
from .extract import extract
from .locate import find_hardware_pages


def write_outputs(result, out_json: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(result.model_dump_json(indent=2))
    with out_json.with_suffix(".csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["set_number", "set_description", "not_used", "page", "qty", "description",
                    "catalog_number", "mfr", "finish", "notes", "confidence"])
        for s in result.sets:
            if not s.components:
                w.writerow([s.set_number, s.description, s.not_used, s.location[0].page] + [""] * 7)
            for c in s.components:
                w.writerow([s.set_number, s.description, s.not_used, c.page, c.qty, c.description,
                            c.catalog_number, c.mfr, c.finish, c.notes, c.confidence])


def cmd_extract(args) -> None:
    pages = [int(p) for p in args.pages.split(",")] if args.pages else None
    t = time.time()
    result = extract(args.pdf, pages=pages, cache=None if args.no_cache else Cache())
    out = Path(args.output or f"outputs/{Path(args.pdf).stem}.json")
    write_outputs(result, out)
    n = sum(len(s.components) for s in result.sets)
    print(f"{len(result.sets)} sets, {n} components from {len(result.hardware_pages)} pages "
          f"in {time.time() - t:.1f}s -> {out}")


def cmd_batch(args) -> None:
    root, out_dir = Path(args.folder), Path(args.output)
    cache = Cache()
    index = []
    for pdf in sorted(root.rglob("*.pdf")):
        if not find_hardware_pages(str(pdf)):
            continue
        rel = pdf.relative_to(root)
        out = out_dir / rel.parent.name / f"{pdf.stem}.json"
        try:
            t = time.time()
            r = extract(pdf, cache=cache)
            write_outputs(r, out)
            n = sum(len(s.components) for s in r.sets)
            low = r.stats["low_confidence_sets"]
            index.append({"pdf": str(rel), "output": str(out.relative_to(out_dir)), "sets": len(r.sets),
                          "components": n, "low_confidence_sets": low})
            print(f"{len(r.sets):4d} sets {n:5d} comps {low:3d} low-conf {time.time() - t:6.1f}s  {rel}")
        except Exception as e:  # keep going; one bad book shouldn't stop the batch
            print(f"FAILED {rel}: {e}", file=sys.stderr)
    (out_dir / "index.json").write_text(json.dumps(index, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(prog="hwsets", description="Extract hardware sets from specbooks")
    sub = ap.add_subparsers(required=True)
    e = sub.add_parser("extract", help="extract one PDF")
    e.add_argument("pdf")
    e.add_argument("-o", "--output")
    e.add_argument("--pages", help="comma-separated 1-based pages (skip auto-detection)")
    e.add_argument("--no-cache", action="store_true", help="ignore cached results")
    e.set_defaults(fn=cmd_extract)
    b = sub.add_parser("batch", help="extract every PDF under a folder")
    b.add_argument("folder")
    b.add_argument("-o", "--output", default="outputs")
    b.set_defaults(fn=cmd_batch)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
