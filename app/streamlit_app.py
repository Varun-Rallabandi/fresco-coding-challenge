"""Review screen: see each extracted set on the page, fix mistakes, save corrections.

    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pymupdf
import streamlit as st
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hwsets.cache import Cache  # noqa: E402
from hwsets.extract import LOW_CONFIDENCE, extract  # noqa: E402
from hwsets.store import Store  # noqa: E402

FIELDS = ["qty", "description", "catalog_number", "mfr", "finish", "notes"]
LOW = LOW_CONFIDENCE

st.set_page_config(page_title="Hardware Set Extractor", layout="wide")


@st.cache_resource
def services():
    return Cache(), Store()


cache, store = services()


@st.cache_data(show_spinner=False)
def local_books() -> list[str]:
    """Books known to contain hardware sets (from `hwsets.cli batch`'s index), present in data/."""
    index = ROOT / "outputs" / "index.json"
    data = ROOT / "data"
    if index.exists():
        return [b["pdf"] for b in json.loads(index.read_text()) if (data / b["pdf"]).exists()]
    return sorted(str(p.relative_to(data)) for p in data.rglob("*.pdf")) if data.exists() else []


@st.cache_data(show_spinner="Reading the specbook...")
def run(pdf_path: str) -> dict:
    return extract(pdf_path, cache=cache).model_dump()


def page_image(pdf_path: str, page: int, boxes: list[tuple], zoom: float = 1.6) -> Image.Image:
    """Render a page and draw boxes: (bbox, colour, width)."""
    pix = pymupdf.open(pdf_path)[page - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    for (x0, top, x1, bottom), colour, width in boxes:
        draw.rectangle([x0 * zoom - 3, top * zoom - 2, x1 * zoom + 3, bottom * zoom + 2], outline=colour, width=width)
    return img


def colour(conf: float) -> str:
    return "#16a34a" if conf >= 0.9 else "#d97706" if conf >= LOW else "#dc2626"


# ---------------------------------------------------------------- sidebar: pick a book
st.sidebar.title("Hardware Set Extractor")
source = st.sidebar.radio("Specbook", ["Upload a PDF", "Sample from data/"], index=1 if local_books() else 0)
pdf_path = None
if source == "Upload a PDF":
    up = st.sidebar.file_uploader("Division 08 specbook (PDF)", type="pdf")
    if up:
        tmp = Path(tempfile.gettempdir()) / f"hwsets-{up.file_id}.pdf"
        tmp.write_bytes(up.getvalue())
        pdf_path = str(tmp)
else:
    books = local_books()
    if books:
        pdf_path = str(ROOT / "data" / st.sidebar.selectbox("Book", books))
    else:
        st.sidebar.info("No PDFs in data/. Upload one instead.")

if not pdf_path:
    st.title("Hardware Set Extractor")
    st.write("Pick a specbook on the left. The extractor finds the Division 08 hardware schedule, "
             "pulls out every hardware set, and shows you where each one is on the page.")
    st.stop()

result = run(pdf_path)
sets = result["sets"]
stats = result["stats"]

# ---------------------------------------------------------------- summary
st.title(result["source_file"])
m = st.columns(6)
m[0].metric("Pages in PDF", stats.get("pages_in_pdf"))
m[1].metric("Hardware pages", stats.get("hardware_pages"))
m[2].metric("Sets", stats.get("sets"))
m[3].metric("Components", stats.get("components"))
m[4].metric("Needs review", stats.get("low_confidence_sets"))
m[5].metric("Seconds", stats.get("seconds"))
if stats.get("ocr_pages"):
    st.info(f"Scanned pages read with OCR: {stats['ocr_pages']}")

with st.expander("How the columns were classified (manufacturer vs finish vote)"):
    st.caption("Each column's job is decided by votes from every row in the schedule: dictionary hits, "
               "value shape, header label, and position. An ambiguous code like 'PE' takes the identity of its column.")
    for run_ in result["columns"]:
        st.write(f"Pages {run_['pages']}")
        st.dataframe(pd.DataFrame([{**{k: c[k] for k in ("x", "kind", "confidence")},
                                    "mfr votes": c["votes"].get("mfr"), "finish votes": c["votes"].get("finish"),
                                    "examples": ", ".join(c["examples"][:5])} for c in run_["columns"]]),
                     hide_index=True, use_container_width=True)
    learned = result.get("learned_codes", {})
    if any(learned.values()):
        st.write("Codes learned from this book's own legend:", learned)

if not sets:
    st.warning("No hardware sets found in this PDF.")
    st.stop()

# ---------------------------------------------------------------- set picker
only_low = st.sidebar.checkbox("Only sets that need review", value=False)
choices = [s for s in sets if not only_low or s["confidence"] < LOW]
if not choices:
    st.success("Nothing below the confidence threshold.")
    st.stop()


def label(s: dict) -> str:
    flag = "🔴" if s["confidence"] < LOW else "🟢"
    extra = " (NOT USED)" if s["not_used"] else ""
    return f"{flag} Set {s['set_number']}{extra} · p.{s['location'][0]['page']} · {len(s['components'])} items"


idx = st.sidebar.selectbox("Set", range(len(choices)), format_func=lambda i: label(choices[i]))
hs = choices[idx]

left, right = st.columns([1.1, 1])
with left:
    for span in hs["location"]:
        boxes = [(span["bbox"], "#2563eb", 3)]
        boxes += [(c["bbox"], colour(c["confidence"]), 2) for c in hs["components"] if c["page"] == span["page"] and c["bbox"]]
        st.image(page_image(pdf_path, span["page"], boxes), caption=f"Page {span['page']}, lines {span['lines'][0]}-{span['lines'][1]}",
                 use_container_width=True)

with right:
    st.subheader(f"Set {hs['set_number']}" + (f" — {hs['description']}" if hs["description"] else ""))
    if hs.get("doors"):
        st.caption(f"Doors: {hs['doors']}")
    st.caption(f"Set confidence {hs['confidence']:.2f}. Green ≥ 0.90, amber ≥ {LOW}, red below: check these.")
    for w in hs["warnings"]:
        st.warning(w)

    df = pd.DataFrame([{f: c[f] for f in FIELDS} | {"confidence": c["confidence"]}
                       for c in hs["components"]])
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, hide_index=True,
                            disabled=["confidence"], key=f"ed-{result['source_file']}-{hs['set_number']}")

    if st.button("Save corrections", type="primary"):
        n = 0
        for i in range(max(len(df), len(edited))):
            for f in FIELDS:
                old = df[f].iloc[i] if i < len(df) else None
                new = edited[f].iloc[i] if i < len(edited) else None
                old = None if pd.isna(old) else old
                new = None if pd.isna(new) else new
                if old != new:
                    store.add_correction(result["source_file"], hs["set_number"], i, f, old, new)
                    n += 1
        st.success(f"Saved {n} change(s). They're logged for review and for growing the answer key.")

    if hs.get("notes"):
        with st.expander("Set notes"):
            st.write(hs["notes"])

st.sidebar.download_button("Download JSON", json.dumps(result, indent=2), file_name=f"{Path(pdf_path).stem}.json")
summary = store.correction_summary()
if summary:
    st.sidebar.caption("Fields corrected most often: " + ", ".join(f"{r['field']} ({r['n']})" for r in summary))
