"""Stage 4: figure out what each column of a hardware schedule *is*.

Spec writers line their schedules up in columns. We find those columns from where
words start on the page (x position), then decide each column's job by weighing
evidence from every row in the book at once:

    * dictionary hits   - "IVE", "SCH", "LCN" are manufacturers; "626", "US26D" are finishes
    * value shape       - short all-letter codes lean manufacturer; codes with digits lean finish
    * header label      - a "MFR" / "FINISH" heading above the column
    * position          - when there are two code columns, manufacturer is usually the last one

A single ambiguous value such as "PE" (Pemko or Painted Enamel) never decides
anything by itself. It takes the identity of the column it sits in.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .codes import Vocabulary
from .layout import Line

QTY_RE = re.compile(r"^(\d{1,3}(?:\.\d+)?|\(\d{1,3}\)|__+|--+|AS)$", re.I)
UNITS = {"EA", "EA.", "EACH", "PR", "PR.", "PAIR", "SET", "SETS", "LF", "LOT", "REQ", "REQ."}

HEADER_LABELS = {
    "qty": {"QTY", "QTY.", "QUANTITY", "QT", "NO.", "COUNT"},
    "description": {"DESCRIPTION", "ITEM", "TYPE", "PRODUCT", "HARDWARE"},
    "catalog": {"CATALOG", "CAT.", "MODEL", "PRODUCT/MODEL", "NUMBER", "PART"},
    "finish": {"FINISH", "FIN", "FIN.", "FINISHES"},
    "mfr": {"MFR", "MFR.", "MFG", "MFG.", "MANF", "MANF.", "MANUFACTURER", "MANUF", "MANUF.", "MAKE", "MFGR"},
    "notes": {"NOTES", "REMARKS", "COMMENTS"},
}


def label_of(word: str) -> str | None:
    w = word.upper().strip(":")
    for kind, words in HEADER_LABELS.items():
        if w in words:
            return kind
    return None


def is_table_header(line: Line) -> bool:
    kinds = {label_of(w.text) for w in line.words} - {None}
    return len(kinds) >= 3


@dataclass
class Column:
    x: float
    kind: str = "text"
    confidence: float = 1.0
    votes: dict[str, float] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)
    coverage: float = 0.0  # share of rows that have a value in this column


@dataclass
class ColumnMap:
    qty_x: float | None
    columns: list[Column]

    def index_of(self, x0: float, tol: float = 4.0) -> int:
        idx = -1
        for i, c in enumerate(self.columns):
            if c.x <= x0 + tol:
                idx = i
        return idx

    def kind_at(self, x0: float) -> str:
        i = self.index_of(x0)
        return self.columns[i].kind if i >= 0 else "prefix"

    def first_x(self, kind: str) -> float | None:
        for c in self.columns:
            if c.kind == kind:
                return c.x
        return None

    def report(self) -> list[dict]:
        return [
            {"x": round(c.x), "kind": c.kind, "confidence": round(c.confidence, 2),
             "votes": {k: round(v, 1) for k, v in c.votes.items()}, "examples": c.examples[:6]}
            for c in self.columns
        ]


def _peaks(xs: list[float], n_rows: int, min_share: float = 0.25, bin_w: float = 3.0) -> list[float]:
    """Column starts are x positions where many rows begin a word."""
    hist = Counter(round(x / bin_w) for x in xs)
    need = max(2, int(min_share * n_rows))
    starts = sorted(b * bin_w for b, n in hist.items() if n >= need)
    merged: list[float] = []
    for x in starts:
        if merged and x - merged[-1] <= 8:
            continue
        merged.append(x)
    return merged


def guess_qty_x(lines: list[Line]) -> float | None:
    xs = [round(l.words[0].x0 / 3) * 3 for l in lines if QTY_RE.match(l.words[0].text)]
    if not xs:
        return None
    x, n = Counter(xs).most_common(1)[0]
    return x if n >= 2 else None


def build_column_map(row_lines: list[Line], header_lines: list[Line], vocab: Vocabulary) -> ColumnMap:
    """Find column positions and vote on each column's type."""
    qty_x = guess_qty_x(row_lines)
    xs = [w.x0 for l in row_lines for w in l.words[1:]]
    peaks = _peaks(xs, len(row_lines))
    if qty_x is not None:
        peaks = [qty_x] + [p for p in peaks if p > qty_x + 6]
    cmap = ColumnMap(qty_x, [Column(x) for x in peaks])
    if not cmap.columns:
        return cmap

    # Collect each row's cell text per column.
    cells: list[list[str]] = [[] for _ in cmap.columns]
    for l in row_lines:
        per: dict[int, list[str]] = {}
        for w in l.words:
            i = cmap.index_of(w.x0)
            if i >= 0:
                per.setdefault(i, []).append(w.text)
        for i, toks in per.items():
            cells[i].append(" ".join(toks))

    # Header labels: assign each label word to the column under it.
    labels: dict[int, Counter] = {}
    for h in header_lines:
        for w in h.words:
            kind = label_of(w.text)
            if kind:
                # Labels are often centred over their column, so use the word's midpoint
                # but never let it land left of the column it overlaps.
                i = max(cmap.index_of(w.x0), cmap.index_of((w.x0 + w.x1) / 2 - 10))
                if i >= 0:
                    labels.setdefault(i, Counter())[kind] += 1

    n = len(row_lines)
    stats = []
    for i, col in enumerate(cmap.columns):
        vals = cells[i]
        col.examples = [v for v, _ in Counter(vals).most_common(8)]
        coverage = len(vals) / max(n, 1)
        col.coverage = coverage
        toks = [v.split() for v in vals]
        short = sum(1 for t in toks if len(t) <= 2) / max(len(vals), 1)
        first = [t[0] for t in toks if t]
        stats.append({
            "coverage": coverage,
            "short": short,
            "qty": sum(1 for t in first if QTY_RE.match(t)) / max(len(first), 1),
            "unit": sum(1 for t in first if t.upper() in UNITS) / max(len(first), 1),
            "digits": sum(1 for v in vals if re.search(r"\d", v)) / max(len(vals), 1),
            "mfr_dict": sum(1 for t in first if vocab.is_mfr(t)) / max(len(first), 1),
            "fin_dict": sum(1 for t in first if vocab.is_finish(t)) / max(len(first), 1),
            "alpha_code": sum(1 for t in first if re.fullmatch(r"[A-Z][A-Z\-/]{1,4}", t)) / max(len(first), 1),
            "label": labels.get(i, Counter()),
        })

    # 1) qty and unit columns.
    for i, (col, s) in enumerate(zip(cmap.columns, stats)):
        if i == 0 and qty_x is not None and col.x == qty_x and s["qty"] >= 0.5:
            col.kind = "qty"
        elif s["unit"] >= 0.6 and s["short"] >= 0.9:
            col.kind = "unit"

    # 2) code columns (manufacturer / finish): short values, toward the right.
    text_cols = [i for i, c in enumerate(cmap.columns) if c.kind == "text"]
    # text_cols[0] is the description, which always comes first, so it never competes.
    candidates = [i for i in text_cols[1:]
                  if stats[i]["short"] >= 0.75 and stats[i]["coverage"] >= 0.2]
    last = max(candidates) if candidates else None
    scored = []
    for i in candidates:
        s = stats[i]
        mfr = 3 * s["mfr_dict"] + 1.0 * s["alpha_code"] + 3 * s["label"].get("mfr", 0) / max(sum(s["label"].values()), 1)
        fin = 3 * s["fin_dict"] + 1.0 * s["digits"] + 3 * s["label"].get("finish", 0) / max(sum(s["label"].values()), 1)
        if i == last and len(candidates) > 1:
            mfr += 0.5
        cmap.columns[i].votes = {"mfr": mfr, "finish": fin}
        scored.append((abs(mfr - fin), i, mfr, fin))
    taken: set[str] = set()
    for margin, i, mfr, fin in sorted(scored, reverse=True):
        if max(mfr, fin) < 0.8:
            continue  # not enough evidence that this is a code column at all
        kind = "mfr" if mfr >= fin else "finish"
        s = stats[i]
        # Shape alone ("has digits", "is short") is weak; a code column also needs real
        # proof: values found in the dictionary or a header label saying what it is.
        proof = s["mfr_dict"] if kind == "mfr" else s["fin_dict"]
        if proof < 0.25 and not s["label"].get(kind):
            continue
        if kind in taken:
            continue  # a weaker look-alike stays plain text; it is never forced into the other role
        taken.add(kind)
        col = cmap.columns[i]
        col.kind = kind
        # Confidence = how far ahead the winning type is. A lead of 3 votes is near
        # certain (0.98); a near-tie (lead 0.3) is a coin flip worth a human look (0.63).
        col.confidence = 1 - 0.5 * math.exp(-abs(mfr - fin))

    # 3) description / catalog / notes among the remaining text columns.
    code_xs = [c.x for c in cmap.columns if c.kind in ("mfr", "finish")]
    first_code = min(code_xs) if code_xs else float("inf")
    seen_desc = seen_cat = False
    for col, s in zip(cmap.columns, stats):
        if col.kind != "text":
            continue
        lab = s["label"].most_common(1)[0][0] if s["label"] else None
        if col.x > first_code:
            col.kind = "notes"
        elif lab in ("description", "catalog", "notes"):
            col.kind = lab
        elif not seen_desc and s["digits"] < 0.5:
            col.kind = "description"
        elif not seen_cat and s["digits"] >= 0.4:
            col.kind = "catalog"
        else:
            col.kind = "catalog" if seen_cat else "description"
        seen_desc |= col.kind == "description"
        seen_cat |= col.kind == "catalog"
    return cmap
