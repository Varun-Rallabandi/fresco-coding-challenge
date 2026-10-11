"""Helpers to build fake pages for tests."""
from hwsets.layout import Line, Word

# Column x positions for a typical "QTY | DESCRIPTION | CATALOG | FINISH | MFR" schedule.
COLS = {"qty": 80, "desc": 140, "cat": 270, "fin": 470, "mfr": 510}


def line(page: int, index: int, cells: list[tuple[str, str]], top: float | None = None) -> Line:
    """cells: list of (column-name or x position, text)."""
    top = 100 + 14 * index if top is None else top
    words = []
    for col, text in cells:
        x = COLS.get(col, col) if isinstance(col, str) else col
        for k, tok in enumerate(text.split()):
            words.append(Word(tok, x + 18 * k, x + 18 * k + 15, top, top + 9))
    return Line(page, index, words)


def row(page, index, qty, desc, cat, fin, mfr):
    cells = []
    if qty is not None:
        cells.append(("qty", str(qty)))
    cells += [("desc", desc), ("cat", cat)]
    if fin:
        cells.append(("fin", fin))
    if mfr:
        cells.append(("mfr", mfr))
    return line(page, index, cells)
