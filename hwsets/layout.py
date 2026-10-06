"""Stage 2: turn a PDF page into words and lines, each with its position.

Everything downstream works on these Line objects, so every extracted value
can be traced back to an exact box on the page.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pdfplumber


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass
class Line:
    page: int  # 1-based
    index: int  # position of the line on its page
    words: list[Word] = field(default_factory=list)
    page_height: float = 792.0

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.top, self.x1, self.bottom)


def words_to_lines(words: list[Word], page_no: int, page_height: float = 792.0) -> list[Line]:
    """Group words that share a row into lines, left to right.

    Table cells are often vertically centred, so a quantity can sit a few points
    lower than its description. Words join the current line when they start
    within ~70% of a text height of the line's first word.
    """
    words = sorted((w for w in words if w.text.strip()), key=lambda w: (w.top, w.x0))
    rows: list[list[Word]] = []
    for w in words:
        anchor = rows[-1][0] if rows else None
        tol = 0.7 * (anchor.bottom - anchor.top) if anchor else 0
        if anchor and w.top - anchor.top <= max(tol, 2.5):
            rows[-1].append(w)
        else:
            rows.append([w])
    return [Line(page_no, i, _rejoin(sorted(r, key=lambda w: w.x0)), page_height) for i, r in enumerate(rows)]


def _rejoin(words: list[Word]) -> list[Word]:
    """Glue a lone capital back onto its word: revised text often extracts as "L ock", "B y"."""
    out: list[Word] = []
    for w in words:
        prev = out[-1] if out else None
        if (prev and len(prev.text) == 1 and prev.text.isupper() and w.text[:1].islower()
                and w.x0 - prev.x1 < 4.5):
            out[-1] = Word(prev.text + w.text, prev.x0, w.x1, min(prev.top, w.top), max(prev.bottom, w.bottom))
        else:
            out.append(w)
    return out


def read_page_lines(pdf: pdfplumber.PDF, page_no: int, mu_doc=None) -> tuple[list[Line], bool]:
    """Words with positions for one page. Returns (lines, used_ocr).

    Digital PDFs carry a text layer, so we read it directly. A scanned page has
    no text layer, just a picture; then we run OCR (optical character
    recognition: turning an image of text into words with boxes) and feed those
    words through exactly the same pipeline.
    """
    page = pdf.pages[page_no - 1]
    raw = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
    words = [Word(_clean(w["text"]), w["x0"], w["x1"], w["top"], w["bottom"]) for w in raw]
    words = [w for w in words if w.text]
    used_ocr = False
    if len(words) < 10 and mu_doc is not None:
        ocr_words = ocr_page(mu_doc, page_no)
        if len(ocr_words) > len(words):
            words, used_ocr = ocr_words, True
    return words_to_lines(words, page_no, float(page.height)), used_ocr


def ocr_available() -> bool:
    import shutil
    return shutil.which("tesseract") is not None


def ocr_page(mu_doc, page_no: int, dpi: int = 300) -> list[Word]:
    """OCR a page with Tesseract (through PyMuPDF). Coordinates come back in PDF points."""
    if not ocr_available():
        return []
    page = mu_doc[page_no - 1]
    if not page.get_images():
        return []
    tp = page.get_textpage_ocr(language="eng", dpi=dpi, full=True)
    out = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words", textpage=tp):
        t = _clean(text)
        # Icons and specks get "read" as stray symbols ("=", "~", "|"); a real word
        # always has at least one letter or digit.
        if t and re.search(r"[A-Za-z0-9]", t):
            out.append(Word(t, x0, x1, y0, y1))
    return out


_DIGITS = re.compile(r"\d+")
_PRIVATE_USE = re.compile("[\ue000-\uf8ff]")  # icon-font glyphs (checkboxes, bullets)


def _clean(text: str) -> str:
    return _PRIVATE_USE.sub("", text).strip()


def _shape(line: Line) -> str:
    return _DIGITS.sub("#", line.text.upper())


def strip_boilerplate(pages: dict[int, list[Line]]) -> dict[int, list[Line]]:
    """Drop running headers/footers: text that repeats at the same height on many pages.

    Digits are masked so "Page 4 of 49" and "Page 5 of 49" count as the same line.
    Only the top and bottom margins are considered, so a hinge row that happens to
    sit at the same height on every page is never mistaken for a header.
    """
    from .boundaries import match_header  # set headers are content, never boilerplate

    def in_margin(l: Line) -> bool:
        if match_header(l.text):
            return False
        return l.top < 0.13 * l.page_height or l.bottom > 0.88 * l.page_height

    if len(pages) < 3:
        return pages
    seen: Counter[tuple[str, int]] = Counter()
    for lines in pages.values():
        for key in {(_shape(l), round(l.top / 6)) for l in lines if in_margin(l)}:
            seen[key] += 1
    limit = max(3, int(0.4 * len(pages)))
    repeated = {k for k, n in seen.items() if n >= limit}
    out = {}
    for p, lines in pages.items():
        kept = [l for l in lines if not (in_margin(l) and (_shape(l), round(l.top / 6)) in repeated)]
        out[p] = kept  # original line indexes are kept so locations match the raw page
    return out
