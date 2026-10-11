"""Manufacturer and finish codes, plus codes learned from each book's legend."""
from __future__ import annotations

import re

# Manufacturer abbreviations commonly used in Division 08 hardware schedules.
MANUFACTURERS: dict[str, str] = {
    "IVE": "Ives", "IV": "Ives", "IVES": "Ives",
    "SCH": "Schlage", "SC": "Schlage", "SCHLAGE": "Schlage", "SCE": "Schlage Electronics",
    "LCN": "LCN",
    "VON": "Von Duprin", "VD": "Von Duprin",
    "PEM": "Pemko", "PE": "Pemko", "PEMKO": "Pemko",
    "NOR": "Norton", "NO": "Norton", "NORTON": "Norton",
    "HAG": "Hager", "HA": "Hager", "HAGER": "Hager",
    "MK": "McKinney", "MCK": "McKinney", "MCKINNEY": "McKinney",
    "ROC": "Rockwood", "RO": "Rockwood", "ROCKWOOD": "Rockwood",
    "ZER": "Zero International", "ZE": "Zero International", "ZERO": "Zero International",
    "GLY": "Glynn-Johnson", "GJ": "Glynn-Johnson", "GL": "Glynn-Johnson",
    "SAR": "Sargent", "SA": "Sargent", "SARGENT": "Sargent",
    "CR": "Corbin Russwin", "COR": "Corbin Russwin",
    "BES": "Best", "BE": "Best", "BEST": "Best",
    "YAL": "Yale", "YA": "Yale", "YALE": "Yale",
    "STA": "Stanley", "ST": "Stanley",
    "TRI": "Trimco", "TR": "Trimco", "TRIMCO": "Trimco",
    "BB": "Bommer", "BOM": "Bommer",
    "RIX": "Rixson", "RF": "Rixson", "RIXSON": "Rixson",
    "FAL": "Falcon", "FA": "Falcon", "FALCON": "Falcon",
    "DOR": "Dormakaba", "DM": "Dormakaba", "DORMA": "Dormakaba",
    "ACC": "Accurate", "AC": "Accurate",
    "AR": "Adams Rite", "ADA": "Adams Rite",
    "HES": "HES", "SU": "Securitron", "SEC": "Securitron",
    "DET": "Detex", "DE": "Detex",
    "NGP": "National Guard Products", "NAT": "National Guard Products",
    "PRE": "Precision", "PR": "Precision",
    "ABH": "ABH", "BBW": "BBW", "DCI": "Door Controls Intl",
    "CAL": "Cal-Royal", "MAR": "Marks", "ALA": "Alarm Lock", "AL": "Alarm Lock",
    "KN": "Knape & Vogt", "HI": "Hiawatha", "BRI": "Brixwell", "LSDA": "LSDA",
    "GLO": "Global", "STE": "Steelcraft", "CUR": "Curries",
    "AA": "Assa Abloy", "ASS": "Assa Abloy", "ALL": "Allegion",
    "MEL": "Medeco", "MED": "Medeco", "SIM": "Simplex", "KAB": "Kaba",
    "SCHL": "Schlage", "VOND": "Von Duprin", "HAGR": "Hager",
}

# Finishes: BHMA numeric codes, US equivalents, and common descriptive finishes.
_BHMA = {str(n) for n in range(600, 750)}
FINISHES: set[str] = _BHMA | {
    "US3", "US4", "US9", "US10", "US10A", "US10B", "US10BE", "US14", "US15", "US15A",
    "US19", "US20", "US26", "US26D", "US28", "US32", "US32D", "US3/605",
    "BSP", "AL", "ALUM", "DKB", "DKBRZ", "SP28", "SPCH", "PC", "STL", "PRIME", "PRM",
    "GRY", "BLK", "BK", "AMB", "CLR", "MILL", "EN", "PE", "SN", "SB", "WHT", "DB",
    "313AN", "335", "313", "689A", "628A", "626AM", "630AM", "BLKAN", "DURA", "ANCLR",
    "PAINT", "PTD", "PNT", "SS", "NA", "N/A", "BRZ", "AB", "ZC",
}

_BHMA_RE = re.compile(r"^(6\d\d|7[0-4]\d)[A-Z]{0,3}$")
_US_RE = re.compile(r"^(US|C)?\d{1,2}[A-Z]{0,2}$")  # US26D, C26D, 26D, US10B


def norm(tok: str) -> str:
    return tok.strip().strip(".,;:()").upper()


_NAME_WORDS = {v.split()[0].upper().rstrip(",") for v in MANUFACTURERS.values()} | {"SARGENT", "ROCKWOOD", "CORBIN", "RUSSWIN", "DORMAKABA", "GLYNN"}


def is_mfr(tok: str) -> bool:
    """A manufacturer code ("IVE") or a spelled-out maker name ("Sargent")."""
    t = norm(tok)
    return t in MANUFACTURERS or (len(t) > 3 and t in _NAME_WORDS)


def is_finish(tok: str) -> bool:
    t = norm(tok)
    if t in FINISHES or _BHMA_RE.match(t) or (_US_RE.match(t) and not t.isdigit()):
        return True
    # Combo finishes like "626/US26D" or "US26D x 630".
    parts = re.split(r"[/x×]", t)
    return len(parts) > 1 and all(p in FINISHES or _BHMA_RE.match(p) or p.startswith("US") for p in parts if p)


def is_ambiguous(tok: str) -> bool:
    """True when a token could legitimately be read as either kind of code."""
    return is_mfr(tok) and is_finish(tok)


def mfr_name(code: str) -> str | None:
    return MANUFACTURERS.get(norm(code))


# Words that show up in finish names inside a legend ("626 - Satin Chromium").
_FINISH_WORDS = re.compile(
    r"satin|chrom|stainless|brass|bronze|alumin|black|painted|anodiz|prime|nickel|"
    r"polished|oxidiz|enamel|powder|coat|gray|grey|white|brown|dull|bright|clear", re.I)
_LEGEND_RE = re.compile(r"^(?:\d+\.\s*)?([A-Z0-9][A-Z0-9\-/]{0,5})\s*(?:[-–=:]\s*|\s{2,}|\s)(.{3,60})$")
_KNOWN_NAMES = {v.upper() for v in MANUFACTURERS.values()}
_BARE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9\-/]{0,5}$")
# Words that look like codes in running text but never are.
_STOP = {"BY", "OR", "AND", "THE", "TO", "OF", "IN", "ON", "FOR", "WITH", "SEE", "ALL", "NFPA", "ASTM",
         "ANSI", "BHMA", "UL", "ADA", "SIDE", "BASE", "MODEL", "TYPE", "NOTE", "NOTES", "USA", "PART",
         "STRIKE", "SWING", "SECTION", "ITEM", "SET", "EA", "QTY", "AS", "IF", "AT", "BE", "IS", "NO.", "A.", "B."}


class Vocabulary:
    """Base code lists plus codes from the book's own legend (e.g. "PE - Pemko")."""

    def __init__(self) -> None:
        self.learned_mfr: dict[str, str] = {}
        self.learned_finish: dict[str, str] = {}

    def learn_from_lines(self, texts: list[str]) -> None:
        """Find legend blocks (3+ code/name pairs close together)."""
        texts = [t.strip() for t in texts]
        pairs: list[tuple[int, str, str]] = []
        for i, t in enumerate(texts):
            m = _LEGEND_RE.match(t)
            if m and m.group(1) == m.group(1).upper():
                pairs.append((i, m.group(1), m.group(2).strip()))
            elif _BARE_CODE.match(t) and i + 1 < len(texts) and 2 < len(texts[i + 1]) <= 60:
                pairs.append((i, t, texts[i + 1]))
        pairs = [(i, c.upper(), n) for i, c, n in pairs if c.upper() not in _STOP and not n.endswith(".")
                 and len(n.split()) <= 8]
        idx = [i for i, _, _ in pairs]
        for k, (i, code, name) in enumerate(pairs):
            near = sum(1 for j in idx if j != i and abs(j - i) <= 4)
            if near < 2:
                continue  # an isolated "code name" line is usually prose, not a legend
            up = name.upper()
            if not re.search(r"\d", code) and any(n in up for n in _KNOWN_NAMES if len(n) > 3):
                self.learned_mfr.setdefault(code, name)
            elif _FINISH_WORDS.search(name) and len(code) <= 5:
                self.learned_finish.setdefault(code, name)

    def is_mfr(self, tok: str) -> bool:
        t = norm(tok)
        return t in self.learned_mfr or is_mfr(t)

    def is_finish(self, tok: str) -> bool:
        t = norm(tok)
        return t in self.learned_finish or is_finish(t)

    def mfr_name(self, code: str) -> str | None:
        t = norm(code)
        return self.learned_mfr.get(t) or MANUFACTURERS.get(t)
