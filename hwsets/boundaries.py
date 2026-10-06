"""Stage 3: find where each hardware set starts and stops."""
from __future__ import annotations

import re

# Optional outline prefix that some spec writers' auto-numbering adds ("PART 34 -", "3.", "A.").
# A bare number is NOT a prefix: "1 Hardware Set LP200A" is a component row (qty 1), not a header.
_PREFIX = r"(?:PART\s+\d+\s*[-–]\s*|\d+(?:\.\d+)*\.\s+|\d+\.\d+\s+|[A-Z]\.\s+)?"
_NUM = r"(?P<num>(?:[A-Z]{1,2}[- ]?)?\d{1,4}(?:\.\d{1,3})?[A-Z]{0,4})\b"

HEADER_RES = [
    # "Hardware Group No. 02", "SET #1", "Set: 1.0", "Heading #4", "HW SET 3A", "Hardware Group/Set #B1"
    re.compile(
        rf"^{_PREFIX}(?:(?:DOOR\s+)?HARDWARE\s+|HDWR?E?\.?\s+|HDW\.?\s+|HW\.?\s+)?"
        rf"(?:SET|GROUP(?:\s*/\s*SET)?|HEADING)\s*(?:NO\.?|NUMBER|#)?\s*[:#.]?\s*#?\s*{_NUM}(?P<rest>.*)$",
        re.I,
    ),
    # "HW 25", "HW-3A", "HS 12"
    re.compile(rf"^{_PREFIX}(?:HW|HS|HDW)\s*[-#.]?\s*{_NUM}(?P<rest>.*)$", re.I),
]

NOT_USED_RE = re.compile(r"\b(NOT\s+USED|N/A|NOT\s+APPLICABLE|DELETED|OMITTED|VOID)\b", re.I)
END_RE = re.compile(r"^\s*END\s+OF\s+(SECTION|SCHEDULE)", re.I)


def match_header(text: str) -> tuple[str, str] | None:
    """Return (set_number, trailing text) when a line opens a hardware set."""
    t = text.strip()
    if len(t) > 140:
        return None
    for rx in HEADER_RES:
        m = rx.match(t)
        if m:
            rest = m.group("rest").strip()
            # Prose such as "Group Number: 2." in an elevator spec ends in a period
            # with nothing useful after it; those are rejected later if no rows follow.
            return m.group("num").upper(), rest
    return None


def clean_description(rest: str) -> str | None:
    """Trim separators from the text that follows a set number on the header line."""
    rest = re.sub(r"^(?:and\s+#?\S+\s*)+", "", rest, flags=re.I)  # "#B1 and #B2 – ..."
    rest = re.sub(r"^[\s\-–—:.,|]+", "", rest).strip()
    return rest or None


def normalize_set_number(num: str) -> str:
    """Canonical form used for comparisons: "02" -> "2", "1.0" -> "1"."""
    n = num.upper().lstrip("#")
    n = re.sub(r"\.0+$", "", n)
    m = re.match(r"^([A-Z]*-?)0*(\d.*)$", n)
    return (m.group(1) + m.group(2)) if m else n
