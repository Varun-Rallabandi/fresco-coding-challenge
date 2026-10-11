"""Schedules laid out as a table with a SET column (e.g. Roselle)."""
from __future__ import annotations

import re

from .codes import Vocabulary
from .layout import Line
from .schema import Component, HardwareSet, Span

SET_ID = re.compile(r"^\d{1,3}(?:\.\d{1,2})?[A-Z]?$")
LABELS = [
    ("set", re.compile(r"^(HW\s*)?(SET|GROUP|HEADING)$", re.I)),
    ("qty", re.compile(r"^QTY\.?$|^QUANTITY$", re.I)),
    ("finish", re.compile(r"^FIN(ISH)?\.?$", re.I)),
    ("notes", re.compile(r"^(NOTES?|REMARKS)$", re.I)),
    ("mfr", re.compile(r"^(MFR|MFG|MANUFACTURER|MANF)\.?$", re.I)),
    ("catalog", re.compile(r"^(CATALOG|PRODUCT|MODEL)$", re.I)),
    ("description", re.compile(r"^(DESCRIPTION|TYPE|ITEM|HARDWARE)$", re.I)),
]


def _label(tok: str) -> str | None:
    for kind, rx in LABELS:
        if rx.match(tok):
            return kind
    return None


def find_header(lines: list[Line]) -> tuple[int, list[tuple[float, str]]] | None:
    """Locate a heading row whose first column is SET; return its column starts."""
    for i, l in enumerate(lines):
        cols: list[tuple[float, str]] = []
        for w in l.words:
            # Headings sometimes run together ("QTY.FINISH"); split them in proportion.
            parts = [p for p in re.split(r"(?<=\.)(?=[A-Z])", w.text) if p]
            width = (w.x1 - w.x0) / max(len(w.text), 1)
            offset = 0
            for p in parts:
                kind = _label(p.strip("."))
                if kind:
                    cols.append((w.x0 + offset * width, kind))
                offset += len(p)
        kinds = [k for _, k in cols]
        if kinds and kinds[0] == "set" and len(set(kinds)) >= 4:
            # "MANUFACTURER - PRODUCT" is one combined column.
            merged: list[tuple[float, str]] = []
            for x, k in cols:
                if merged and merged[-1][1] == "mfr" and k == "catalog" and x - merged[-1][0] < 80:
                    merged[-1] = (merged[-1][0], "mfr_product")
                elif merged and merged[-1][1] == k:
                    continue  # "HARDWARE TYPE" -> one description column
                else:
                    merged.append((x, k))
            return i, merged
    return None


def _kind_at(cols: list[tuple[float, str]], x: float) -> str:
    kind = cols[0][1]
    for cx, k in cols:
        if cx <= x + 4:
            kind = k
    return kind


def parse_table(pages: dict[int, list[Line]], vocab: Vocabulary) -> list[HardwareSet] | None:
    """pages: raw lines per page. The heading row repeats on each page; we read below it."""
    body: list[Line] = []
    cols = None
    for p in sorted(pages):
        found = find_header(pages[p])
        if found:
            start, cols_p = found
            cols = cols or cols_p
            body += pages[p][start + 1:]
        elif cols:
            body += pages[p]
    if not cols:
        return None
    sets: list[dict] = []
    for l in body:
        if re.search(r"END OF (SECTION|SCHEDULE)", l.text, re.I):
            break
        if l.top > 0.9 * l.page_height:
            continue  # page footer (project name, page number)
        cells: dict[str, list[str]] = {}
        for w in l.words:
            cells.setdefault(_kind_at(cols, w.x0), []).append(w.text)
        set_cell = cells.pop("set", [])
        if set_cell and SET_ID.match(set_cell[0]):
            sets.append({"number": set_cell[0], "desc": set_cell[1:], "lines": [l], "rows": []})
        elif not sets:
            continue
        else:
            sets[-1]["desc"] += set_cell
            sets[-1]["lines"].append(l)
        cur = sets[-1]
        if not cells:
            continue
        if "qty" in cells:  # a quantity (or "--") marks a new line item
            cur["rows"].append({"cells": {k: list(v) for k, v in cells.items()}, "lines": [l]})
        elif cur["rows"]:  # wrapped text: continue the item above
            row = cur["rows"][-1]
            row["lines"].append(l)
            for k, v in cells.items():
                row["cells"].setdefault(k, []).extend(v)
    if not sets:
        return None
    return [_to_set(s, vocab) for s in sets]


def _to_set(s: dict, vocab: Vocabulary) -> HardwareSet:
    comps = []
    for r in s["rows"]:
        c = r["cells"]
        qty_tok = (c.get("qty") or [""])[0]
        mfr, catalog = None, " ".join(c.get("catalog", [])) or None
        if "mfr_product" in c:
            text = " ".join(c["mfr_product"])
            if " - " in text:
                mfr, catalog = (p.strip() for p in text.split(" - ", 1))
            else:
                catalog = text
        elif "mfr" in c:
            mfr = " ".join(c["mfr"])
        finish_cell = c.get("finish", [])
        finish = finish_cell[0] if finish_cell and finish_cell[0] not in ("--", "-") else None
        notes = " ".join(finish_cell[1:] + c.get("notes", [])) or None
        ls = r["lines"]
        comps.append(Component(
            qty=int(qty_tok) if qty_tok.isdigit() else None,
            description=" ".join(c.get("description", [])) or None,
            catalog_number=catalog,
            mfr=mfr,
            mfr_name=vocab.mfr_name(mfr.split()[0]) if mfr else None,
            finish=finish,
            notes=notes,
            confidence=0.9 if qty_tok.isdigit() else 0.8,
            page=ls[0].page,
            bbox=(min(l.x0 for l in ls), min(l.top for l in ls), max(l.x1 for l in ls), max(l.bottom for l in ls)),
        ))
    by_page: dict[int, list[Line]] = {}
    for l in s["lines"]:
        by_page.setdefault(l.page, []).append(l)
    location = [Span(page=p, bbox=(min(l.x0 for l in ls), min(l.top for l in ls), max(l.x1 for l in ls),
                                   max(l.bottom for l in ls)), lines=(min(l.index for l in ls), max(l.index for l in ls)))
                for p, ls in sorted(by_page.items())]
    return HardwareSet(
        set_number=s["number"],
        description=" ".join(s["desc"]) or None,
        location=location,
        components=comps,
        confidence=min((c.confidence for c in comps), default=0.8),
    )
