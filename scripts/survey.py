"""Quick look at each specbook: hardware pages and set headers.

    python scripts/survey.py data/
"""
import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hwsets.locate import SET_HEADER_RE, find_hardware_pages  # noqa: E402

root = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
for pdf in sorted(root.rglob("*.pdf")):
    try:
        doc = pymupdf.open(pdf)
    except Exception as e:  # corrupt or partial download
        print(f"!! {pdf}: {e}")
        continue
    pages = find_hardware_pages(str(pdf))
    no_text = sum(1 for p in pages if len(doc[p - 1].get_text().strip()) < 50)
    heads = []
    for p in pages[:40]:
        for m in SET_HEADER_RE.finditer(doc[p - 1].get_text()):
            heads.append(m.group(0).strip())
    print(f"\n## {pdf.relative_to(root)}  ({len(doc)} pages, {len(pages)} hardware, {no_text} without text)")
    if pages:
        print(f"   pages {pages[0]}-{pages[-1]}; headers: {sorted(set(heads))[:8]}")
