"""Turn digital PDF pages into a "scanned" PDF: pictures only, no text layer.

Used to prove the OCR path: run the extractor on both versions and compare.

    python scripts/make_scanned_sample.py data/book.pdf 397,398 samples/scanned.pdf
"""
import sys

import pymupdf

src, pages, dst = sys.argv[1], [int(p) for p in sys.argv[2].split(",")], sys.argv[3]
doc = pymupdf.open(src)
out = pymupdf.open()
for p in pages:
    page = doc[p - 1]
    pix = page.get_pixmap(dpi=200)  # a typical office-scanner resolution
    new = out.new_page(width=page.rect.width, height=page.rect.height)
    new.insert_image(new.rect, pixmap=pix)
out.save(dst)
print(f"wrote {dst}: {len(pages)} image-only pages")
