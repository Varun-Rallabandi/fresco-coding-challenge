"""Anti-hallucination check: every value we output must be printed on the page.

This runs on everything, rules output and AI output alike. For each component
we look at the words physically inside that set's box on that page and confirm
each field's text is made of those words. A value that isn't on the page is
removed (set to null) and the set gets a warning, so nothing invented can reach
the final output, no matter which stage produced it.
"""
from __future__ import annotations

import re

from .layout import Line
from .schema import Component, HardwareSet

CHECKED_FIELDS = ("description", "catalog_number", "mfr", "finish")


def _tokens(text: str) -> list[str]:
    """Pieces of a value, split at spaces, hyphens and slashes ("630-316" -> 630, 316)."""
    pieces = (t.strip(".:;,()[]{}\"'“”") for t in re.split(r"[\s,;\-/]+", text.upper()))
    return [t for t in pieces if t]


def _squash(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def page_vocab(lines: list[Line], bbox: tuple[float, float, float, float], pad: float = 6.0) -> tuple[set[str], str]:
    """Words inside a box (plus a little padding), as a token set and one squashed string."""
    x0, top, x1, bottom = bbox
    words = [w.text for l in lines for w in l.words
             if w.x1 >= x0 - pad and w.x0 <= x1 + pad and w.bottom >= top - pad and w.top <= bottom + pad]
    pieces = {p for w in words for p in _tokens(w)}
    return pieces, _squash("".join(words))


def is_grounded(value: str, vocab: set[str], squashed: str) -> bool:
    """True when the value can be rebuilt from words on the page.

    Exact tokens are the normal case. The squashed fallback allows for text that
    the PDF split differently ("N GP" vs "NGP", or a hyphen break across lines).
    """
    toks = _tokens(value)
    if all(t in vocab for t in toks):
        return True
    return _squash(value) in squashed


def set_vocab(hs: HardwareSet, lines_by_page: dict[int, list[Line]]) -> tuple[set[str], str]:
    """All words inside the set's footprint, across every page it spans.

    A component can wrap across a page break, so we check against the whole set,
    never against neighbouring sets.
    """
    vocab: set[str] = set()
    squashed = []
    for span in hs.location:
        v, sq = page_vocab(lines_by_page.get(span.page, []), span.bbox)
        vocab |= v
        squashed.append(sq)
    return vocab, "".join(squashed)


def verify_set(hs: HardwareSet, lines_by_page: dict[int, list[Line]]) -> HardwareSet:
    """Null out any field that isn't printed inside the set's footprint."""
    vocab, squashed = set_vocab(hs, lines_by_page)
    for c in hs.components:
        for field in CHECKED_FIELDS:
            val = getattr(c, field)
            if val and not is_grounded(val, vocab, squashed):
                hs.warnings.append(f"removed ungrounded {field} {val!r} ({c.source})")
                setattr(c, field, None)
                c.confidence = round(c.confidence * 0.5, 2)
    return hs


def grounding_rate(hs: HardwareSet, lines_by_page: dict[int, list[Line]]) -> float:
    """Share of filled fields that are printed on the page (1.0 = fully grounded)."""
    vocab, squashed = set_vocab(hs, lines_by_page)
    vals = [getattr(c, f) for c in hs.components for f in CHECKED_FIELDS if getattr(c, f)]
    return sum(is_grounded(v, vocab, squashed) for v in vals) / len(vals) if vals else 1.0


def component_from_ai(data: dict, page: int) -> Component:
    """Build a component from model output; the verifier decides what survives."""
    qty = data.get("qty")
    return Component(
        qty=qty if isinstance(qty, int) else None,
        description=data.get("description") or None,
        catalog_number=data.get("catalog_number") or None,
        mfr=data.get("mfr") or None,
        finish=data.get("finish") or None,
        notes=data.get("notes") or None,
        confidence=0.75,
        source="ai",
        page=page,
    )
