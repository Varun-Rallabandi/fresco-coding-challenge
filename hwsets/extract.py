"""Main pipeline: find pages -> read lines -> split sets -> columns -> rows."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
import pymupdf

from .boundaries import END_RE, NOT_USED_RE, clean_description, match_header
from .cache import Cache
from .codes import Vocabulary, is_ambiguous
from .columns import QTY_RE, UNITS, ColumnMap, build_column_map, is_table_header
from .layout import Line, read_page_lines, strip_boilerplate
from .locate import find_hardware_pages
from .table_mode import parse_table
from .schema import Component, Extraction, HardwareSet, Span
from .verify import verify_set

LOW_CONFIDENCE = 0.8  # sets below this are flagged for review

DOORS_RE = re.compile(r"^(doors?\s*:|for use on|opening\s*:|item\s*#)", re.I)
FILLER_RE = re.compile(r"^(?:PART\s+\d+\s*[-–]\s*)?(provide each|each (opening )?to (have|receive)|each to have)", re.I)
FILLER_ANYWHERE = re.compile(r"provide\s+\S+\s+door\(?s?\)?\s+with|with the following", re.I)
NOTE_RE = re.compile(r"^\s*(notes?\b:?|(operation(al description)?|properties)\s*:)", re.I)
# Door handing (which way the door swings) is a property of the opening, not the part number.
HANDING = {"RH", "LH", "RHR", "LHR", "RHRA", "LHRA", "RHRB", "LHRB"}
PLACEHOLDER = {"---", "--", "—", "-", "N/A", "NA", "TBD-", ""}
HARDWARE_WORDS = re.compile(
    r"hinge|closer|lock|latch|stop|exit|panic|silencer|pull|push|kick|plate|threshold|sweep|"
    r"gasket|seal|core|cylinder|strike|bolt|holder|astragal|pivot|operator|bumper|coordinator|"
    r"trim|harness|power|switch|viewer|drip|lever|deadbolt|weatherstrip|hardware|door|guide|"
    r"reader|supply|cabinet|kit|key|rail|track|actuator|button|alarm|magnet|mullion", re.I)


@dataclass
class RawSet:
    number: str
    header: Line
    rest: str
    run: int = 0  # which contiguous block of pages (one schedule) this set came from
    lines: list[Line] = field(default_factory=list)


def split_sets(lines: list[Line]) -> list[RawSet]:
    """Walk the lines in reading order and cut them into sets at each header."""
    sets: list[RawSet] = []
    cur: RawSet | None = None
    prev_page = None
    run = 0
    for l in lines:
        if prev_page is not None and l.page - prev_page > 1:
            cur = None  # a gap in pages means a different schedule
            run += 1
        prev_page = l.page
        if END_RE.match(l.text):
            cur = None
            continue
        hit = match_header(l.text)
        if hit and cur is not None and hit[0] == cur.number and not cur.lines:
            continue  # the same header printed twice in a row
        if hit and cur is not None and hit[0] == cur.number and l.page != cur.header.page:
            continue  # header repeated at the top of a continuation page: same set
        if hit:
            cur = RawSet(hit[0], l, hit[1], run)
            sets.append(cur)
        elif cur is not None:
            cur.lines.append(l)
    return sets


def _qty_value(tok: str) -> int | None:
    t = tok.strip("()")
    try:
        return int(float(t))
    except ValueError:
        return None


class RowParser:
    """Turns the lines of one set into components using the book's column map."""

    def __init__(self, cmap: ColumnMap, vocab: Vocabulary):
        self.cmap = cmap
        self.vocab = vocab
        self.desc_x = cmap.first_x("description") or (cmap.columns[0].x if cmap.columns else 0)

    def is_row_start(self, l: Line) -> bool:
        w0 = l.words[0]
        if not any(re.search(r"[A-Za-z]{2}", w.text) for w in l.words[1:]):
            return False  # a run of bare numbers is a door list, not a component
        if FILLER_ANYWHERE.search(l.text):
            return False  # "Provide each SGL door(s) with the following:"
        if len(l.words) > 1 and re.fullmatch(r"\d{2,4}[A-Z]?(-\d+)?", l.words[1].text) \
                and re.fullmatch(r"\d{2,4}[A-Z]?(-\d+)?", l.words[0].text):
            return False  # "326 327 330 ..." door numbers
        if self.cmap.qty_x is not None and abs(w0.x0 - self.cmap.qty_x) <= 8 and QTY_RE.match(w0.text):
            return True
        if w0.text.upper() in UNITS and self.cmap.kind_at(w0.x0) in ("unit", "qty"):
            return True
        kinds = {self.cmap.kind_at(w.x0) for w in l.words}
        cat = [w.text.upper() for w in l.words if self.cmap.kind_at(w.x0) == "catalog"]
        if "description" in kinds and cat and cat[0] in ("BY", "PROVIDED", "FURNISHED"):
            return True  # "SEALS | BY DOOR MANUFACTURER": a by-others item is its own row
        codes = [w for w in l.words if self.cmap.kind_at(w.x0) in ("mfr", "finish")
                 and (self.vocab.is_mfr(w.text) or self.vocab.is_finish(w.text))]
        return bool(codes) and "description" in kinds

    def is_strong_row(self, l: Line) -> bool:
        """A quantity plus a unit or a recognised mfr/finish code: unmistakably a component."""
        if not (self.is_row_start(l) and QTY_RE.match(l.words[0].text)):
            return False
        has_code = any(self.cmap.kind_at(w.x0) in ("mfr", "finish")
                       and (self.vocab.is_mfr(w.text) or self.vocab.is_finish(w.text)) for w in l.words)
        has_unit = len(l.words) > 1 and l.words[1].text.upper() in UNITS  # "1 Ea. Privacy Latch"
        return has_code or has_unit

    def new_component(self, l: Line) -> dict:
        row = {"qty": None, "unit": [], "description": [], "catalog": [], "mfr": [], "finish": [],
               "notes": [], "lines": [l]}
        words = list(l.words)
        w0 = words[0]
        if QTY_RE.match(w0.text) and self.cmap.kind_at(w0.x0) in ("qty", "prefix", "unit"):
            row["qty"] = _qty_value(w0.text)
            if row["qty"] is None and w0.text.upper() == "AS":
                row["notes"].append("as required")
                if len(words) > 1 and words[1].text.upper().startswith("REQ"):
                    words = words[1:]
            words = words[1:]
        self.add_words(row, words)
        return row

    def add_words(self, row: dict, words) -> None:
        for w in words:
            kind = self.cmap.kind_at(w.x0)
            if kind in ("qty", "prefix", "text"):
                kind = "description"
            if w.text.upper() in HANDING and kind in ("catalog", "notes"):
                row["notes"].append(w.text)
                continue
            if kind == "unit":
                if w.text.upper().strip(".") not in ("EA", "EACH"):
                    row["notes"].append(w.text)
                continue
            row[kind].append(w.text)

    def parse(self, raw: RawSet) -> HardwareSet:
        rows: list[dict] = []
        preamble: list[str] = []
        set_notes: list[str] = []
        not_used = bool(NOT_USED_RE.search(raw.rest))
        after_table_header = False
        for l in raw.lines:
            if is_table_header(l):
                after_table_header = True
                continue
            if NOTE_RE.match(l.text) or (set_notes and not self.is_strong_row(l)):
                set_notes.append(l.text)  # once the notes start, prose stays prose
                continue
            if self.is_row_start(l) or (after_table_header and not rows
                                        and self.cmap.kind_at(l.words[0].x0) in ("description", "unit", "catalog")
                                        and not NOTE_RE.match(l.text)):
                # first line under a header row is a component even without a qty
                rows.append(self.new_component(l))
            elif not rows:
                if NOT_USED_RE.search(l.text):
                    not_used = True
                preamble.append(l.text)
            elif l.words[0].x0 < self.desc_x - 12:
                set_notes.append(l.text)  # full-width text after the rows
            else:
                rows[-1]["lines"].append(l)
                self.add_words(rows[-1], l.words)

        description = clean_description(raw.rest)
        doors = None
        for p in preamble:
            if DOORS_RE.match(p) or doors is not None:
                if not FILLER_RE.match(p):
                    doors = (doors + " " if doors else "") + p
            elif (description is None and not NOT_USED_RE.search(p) and len(p) < 120
                  and len(re.findall(r"[A-Za-z]{2,}", p)) >= 2 and not FILLER_RE.match(p)):
                description = p
        if doors:
            doors = re.sub(r"^(doors?\s*:|for use on door\s*#?\(?s?\)?:?)\s*", "", doors, flags=re.I).strip() or None
        if description and NOT_USED_RE.fullmatch(description.strip(" -–()")):
            description = None

        components = [self.to_component(r) for r in rows]
        lines = [raw.header] + raw.lines
        hs = HardwareSet(
            set_number=raw.number,
            description=description,
            doors=doors,
            not_used=not_used and not components,
            location=spans(lines),
            components=components,
            notes=" ".join(set_notes) or None,
        )
        if components:
            hs.confidence = round(min(c.confidence for c in components), 2)
        if not components and not hs.not_used:
            hs.warnings.append("no components found")
        return hs

    def _code(self, parts: list[str]) -> str | None:
        """Join a manufacturer/finish cell. Letter-spaced text ("N GP") is re-joined."""
        val = join_wrapped(parts) or ""
        if val.upper() in PLACEHOLDER or re.fullmatch(r"[-–—_\s]+", val):
            return None  # "---" means "nothing here", not a code
        squeezed = "".join(parts)
        # only re-join tiny pieces that make a known code
        if len(parts) > 1 and all(len(p) <= 2 for p in parts) and (
                self.vocab.is_mfr(squeezed) or self.vocab.is_finish(squeezed)):
            return squeezed
        return val

    def to_component(self, r: dict) -> Component:
        conf = 1.0
        if not any(c.kind in ("mfr", "finish") for c in self.cmap.columns):
            conf *= 0.6  # layout not understood well enough to place mfr/finish: send for review
        mfr = self._code(r["mfr"])
        fin = self._code(r["finish"])
        for kind, val in (("mfr", mfr), ("finish", fin)):
            if val:
                col = next(c for c in self.cmap.columns if c.kind == kind)
                conf *= col.confidence if is_ambiguous(val) else max(col.confidence, 0.9)
        if r["qty"] is None:
            conf *= 0.9
        if not r["catalog"]:
            conf *= 0.9
        # missing mfr when the column is almost always filled -> probably shifted columns
        cat = " ".join(r["catalog"]).upper()
        by_others = bool(re.search(r"(^|\(|\s)(BY|PROVIDED|FURNISHED|PER|COORDINATE)\b", cat))
        mfr_col = next((c for c in self.cmap.columns if c.kind == "mfr"), None)
        if mfr_col and mfr_col.coverage >= 0.8 and not mfr and not by_others:
            conf *= 0.7
        if r["catalog"] and all(self.vocab.is_mfr(w) for w in r["catalog"]):
            conf *= 0.6  # the "catalog number" is a maker's name: columns are shifted
        desc = " ".join(r["description"])
        if re.search(r"\b(by|with|of|and|to|for)$", desc, re.I):
            conf *= 0.7  # a description ending mid-phrase: text was split across columns
        x0 = min(l.x0 for l in r["lines"]); x1 = max(l.x1 for l in r["lines"])
        top = min(l.top for l in r["lines"]); bottom = max(l.bottom for l in r["lines"])
        return Component(
            qty=r["qty"],
            description=join_wrapped(r["description"]),
            catalog_number=join_wrapped(r["catalog"]),
            mfr=mfr,
            mfr_name=self.vocab.mfr_name(mfr) if mfr else None,
            finish=fin,
            notes=" ".join(r["notes"]) or None,
            confidence=round(conf, 2),
            page=r["lines"][0].page,
            bbox=(round(x0, 1), round(top, 1), round(x1, 1), round(bottom, 1)),
        )


def join_wrapped(parts: list[str]) -> str | None:
    """Join words; a word ending in "-" was broken across lines, so no space after it."""
    out = ""
    for p in parts:
        out += p if (not out or out.endswith("-") and len(out) > 1 and out[-2].isalnum()) else " " + p
    return out.strip() or None


def spans(lines: list[Line]) -> list[Span]:
    """One box per page the set touches, so multi-page sets keep every piece."""
    by_page: dict[int, list[Line]] = {}
    for l in lines:
        by_page.setdefault(l.page, []).append(l)
    out = []
    for page, ls in sorted(by_page.items()):
        out.append(Span(
            page=page,
            bbox=(round(min(l.x0 for l in ls), 1), round(min(l.top for l in ls), 1),
                  round(max(l.x1 for l in ls), 1), round(max(l.bottom for l in ls), 1)),
            lines=(min(l.index for l in ls), max(l.index for l in ls)),
        ))
    return out


def extract(pdf_path: str | Path, pages: list[int] | None = None,
            cache: Cache | None = None) -> Extraction:
    """Run the pipeline on one PDF. pages: skip page finding and read these (1-based)."""
    t0 = time.time()
    pdf_path = str(pdf_path)
    if cache:
        key = cache.result_key(pdf_path, pages)
        hit = cache.get_result(key)
        if hit:
            out = Extraction.model_validate(hit)
            out.stats["cache"] = "hit"
            return out

    doc = pymupdf.open(pdf_path)
    pages = pages or find_hardware_pages(pdf_path, doc)
    if not pages and len(doc) <= 30 and not any(pg.get_text().strip() for pg in doc):
        pages = list(range(1, len(doc) + 1))  # a short scan has no text to search: read it all with OCR

    vocab = Vocabulary()
    # Legends usually sit just before the schedule, so read a few pages back too.
    legend_pages = range(max(1, (pages[0] if pages else 1) - 6), (pages[-1] if pages else 0) + 1)
    vocab.learn_from_lines([ln for p in legend_pages for ln in doc[p - 1].get_text().splitlines()])

    ocr_pages = []
    raw_lines: dict[int, list[Line]] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for p in pages:
            raw_lines[p], used_ocr = read_page_lines(pdf, p, doc)
            if used_ocr:
                ocr_pages.append(p)
    page_lines = strip_boilerplate(raw_lines)
    all_lines = [l for p in sorted(page_lines) for l in page_lines[p]]

    raw_sets = split_sets(all_lines)
    table_sets = parse_table(raw_lines, vocab)  # SET-column table format (no header lines)
    if table_sets and len(table_sets) >= 2:
        for hs in table_sets:
            verify_set(hs, raw_lines)
        return _finish(pdf_path, doc, pages, [], vocab, ocr_pages, table_sets, t0, cache,
                       cache.result_key(pdf_path, pages) if cache else None, fmt="table")

    # learn columns per schedule (run of pages); small runs use the whole-book map
    def column_map(sets_: list[RawSet]) -> tuple[ColumnMap, int]:
        lines_ = [l for s in sets_ for l in s.lines]
        heads = [l for l in lines_ if is_table_header(l)]
        cands = [l for l in lines_ if not is_table_header(l) and _looks_like_row(l, vocab)]
        return build_column_map(cands, heads, vocab), len(cands)

    book_map, _ = column_map(raw_sets)
    sets: list[HardwareSet] = []
    reports = []
    for run in sorted({r.run for r in raw_sets}):
        members = [r for r in raw_sets if r.run == run]
        cmap, n = column_map(members)
        if n < 8 or not any(c.kind in ("mfr", "finish") for c in cmap.columns):
            cmap = book_map
        parser = RowParser(cmap, vocab)
        parsed = [parser.parse(r) for r in members]
        # skip runs where most sets don't look like door hardware
        good = sum(1 for s in parsed if s.not_used or looks_like_hardware(s))
        if good < 0.5 * len(parsed):
            continue
        report = cmap.report()
        for hs in parsed:
            if ocr_pages and any(sp.page in ocr_pages for sp in hs.location):
                hs.warnings.append("read with OCR (scanned page)")
                for c in hs.components:
                    c.confidence = round(c.confidence * 0.85, 2)
            verify_set(hs, raw_lines)
            hs.confidence = round(min((c.confidence for c in hs.components), default=hs.confidence), 2)
        reports.append({"pages": f"{members[0].header.page}-{(members[-1].lines or [members[-1].header])[-1].page}",
                        "columns": report})
        sets.extend(parsed)

    return _finish(pdf_path, doc, pages, reports, vocab, ocr_pages, sets, t0, cache,
                   key if cache else None, fmt="list")


def _finish(pdf_path, doc, pages, reports, vocab, ocr_pages, sets, t0, cache, key, fmt) -> Extraction:
    comps = [c for s in sets for c in s.components]
    out = Extraction(
        source_file=Path(pdf_path).name,
        hardware_pages=pages,
        columns=reports,
        learned_codes={"mfr": vocab.learned_mfr, "finish": vocab.learned_finish},
        stats={
            "format": fmt,
            "seconds": round(time.time() - t0, 2),
            "pages_in_pdf": len(doc),
            "hardware_pages": len(pages),
            "ocr_pages": ocr_pages,
            "sets": len(sets),
            "components": len(comps),
            "low_confidence_sets": sum(1 for s in sets if s.confidence < LOW_CONFIDENCE),
            "ungrounded_values_removed": sum(1 for s in sets for w in s.warnings if w.startswith("removed ungrounded")),
            "cache": "miss" if cache else "off",
        },
        sets=sets,
    )
    if cache:
        cache.put_result(key, out.model_dump())
    return out


def looks_like_hardware(s: HardwareSet) -> bool:
    """False for prose that matched a set header (e.g. "Set 1" in a metals spec)."""
    comps = s.components
    if not comps:
        return False
    short = sum(1 for c in comps if c.description and len(c.description) <= 80)
    named = sum(1 for c in comps if c.description and HARDWARE_WORDS.search(c.description))
    return short >= 0.6 * len(comps) and named >= max(1, 0.4 * len(comps))


def _looks_like_row(l: Line, vocab: Vocabulary) -> bool:
    if len(l.words) < 2:
        return False
    if QTY_RE.match(l.words[0].text) or l.words[0].text.upper() in UNITS:
        return True
    last = l.words[-1].text
    return vocab.is_mfr(last) or vocab.is_finish(last)
