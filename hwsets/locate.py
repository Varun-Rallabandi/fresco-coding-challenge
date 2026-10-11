"""Find the hardware schedule pages in a big project manual."""
from __future__ import annotations

import re

import pymupdf

pymupdf.TOOLS.mupdf_display_errors(False)  # some books have broken image refs; harmless noise

from .boundaries import END_RE, match_header
from .codes import is_finish, is_mfr


TABLE_HEADING = re.compile(r"(?s)^\s*SET\s*$.{0,120}?\bQTY\b.{0,40}?FINISH", re.M)


def code_count(text: str) -> int:
    """How many tokens on the page look like manufacturer or finish codes."""
    return sum(1 for t in text.split() if len(t) >= 2 and (is_mfr(t) or is_finish(t)))


def find_hardware_pages(pdf_path: str, doc: pymupdf.Document | None = None) -> list[int]:
    """1-based pages that belong to hardware schedules."""
    doc = doc or pymupdf.open(pdf_path)
    texts = [p.get_text() for p in doc]
    pages: set[int] = set()
    # Table-format schedules have no "SET #1" lines; spot their heading row instead.
    for i, t in enumerate(texts):
        if TABLE_HEADING.search(t) and code_count(t) >= 4:
            pages.add(i + 1)
    i = 0
    while i < len(texts):
        t = texts[i]
        has_header = any(match_header(l) for l in t.splitlines())
        if has_header and code_count(t) >= 4:
            j = i
            while j < len(texts):
                tj = texts[j]
                if j > i and code_count(tj) < 3 and not any(match_header(l) for l in tj.splitlines()):
                    break
                pages.add(j + 1)
                if any(END_RE.match(l) for l in tj.splitlines()):
                    break
                j += 1
            i = j + 1
        else:
            i += 1
    return sorted(pages)
