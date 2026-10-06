# Hardware Set Extractor

Pulls every **door hardware set** out of a Division 08 construction specbook and
returns it as structured data, with the page and box where each set lives.

> Built for the Fresco coding challenge. It runs on every provided project
> folder: 1,138 hardware sets and 10,100+ components across 20 distinct
> specbooks (the 21st, Woodridge, correctly yields none). On hand-checked answer keys it
> finds **100% of sets** and gets **98.7% of components** right, and on the
> manufacturer-vs-finish problem it is **99.9% accurate with zero swaps**.

---

## The idea in one paragraph

Read the page like an estimator would. First find the few hardware pages inside
a manual that can run to 4,000 pages. Then read every word *with its position*, so
the columns of the schedule become visible. Then decide what each column **is**
(quantity, description, catalog number, finish, manufacturer) by letting every
row in the schedule **vote**, which settles ambiguous codes like `PE` (Pemko or
Painted Enamel) from context instead of guessing them one at a time. Finally,
**check every value against the words actually printed on the page**, so
nothing invented can reach the output. AI is an optional backup for the few
sets the rules flag as uncertain. It is not the engine.

```mermaid
flowchart LR
    A[PDF, up to 4,000 pages] --> B[1 Locate<br/>find hardware pages]
    B --> C[2 Read<br/>words + x/y positions<br/>OCR if scanned]
    C --> D[3 Split<br/>set headers or SET column]
    D --> E[4 Vote<br/>what is each column?]
    E --> F[5 Parse rows<br/>qty, desc, catalog,<br/>mfr, finish, notes]
    F --> G[6 Verify<br/>every value printed<br/>on the page?]
    G --> H{confident?}
    H -- yes --> J[JSON / CSV<br/>with page + box]
    H -- no, and --ai --> I[Multimodal AI<br/>re-reads that region] --> G
```

## Results

Scored with `make eval` against hand-checked answer keys (`eval/gold/`). The
labels were made from page images, independently of this code.

| split | books | sets | set recall | set precision | components matched | mfr/finish accuracy | mfr↔finish swaps | sets 100% exact |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Dev** (used while building) | 10 | 52 | 100% | 100% | 98.7% | 99.8% | 0 | 96.2% |
| **Held-out** (never tuned on) | 6 | 25 | 100% | 100% | 98.7% | 100% | 0 | 88.0% |
| **All** | 16 | 77 | **100%** | **100%** | **98.7%** | **99.9%** | **0** | 93.5% |

**Honesty note on the held-out books.** The first blind run on them scored 96%
set recall and 76% exact sets. It is recorded in
[`eval/heldout_first_run.md`](eval/heldout_first_run.md). The misses taught
three *general* rules (longer set suffixes like `720CRZ`, door-handing codes,
`NOTE` lines), and those rules are what the table above reflects.

**Confidence scores are calibrated.** Components scored ≥ 0.9 are 99.4% fully
correct. Components below 0.8 are wrong two times out of three. So "needs
review" really means needs review.

**Scanned pages.** The same pages turned into images (no text layer) and read
with OCR give 98.4% field-for-field agreement with the digital originals
(`scripts/make_scanned_sample.py`).

## How each caveat in the brief is handled

| Caveat | What the code does | Where |
|---|---|---|
| **Mfr vs finish codes** (`PE`, `NO`) | Columns are typed by a vote over every row: dictionary hits, value shape, header label, and position. A single ambiguous value inherits its column's type and never decides alone. Codes from the book's own legend ("PE - Pemko") are learned first. | `columns.py`, `codes.py` |
| **Set boundaries** | Header patterns for every style in the corpus (`SET #1`, `Set: 1.0`, `Heading #4`, `HW 25A`, `Hardware Group No. 02`, `PART 34 - HARDWARE GROUP NO. 401C`, `Group/Set #B1`), plus a separate table mode where a SET column carries the numbers. | `boundaries.py`, `table_mode.py` |
| **NOT USED sets** | Extracted with `not_used: true` and no components. | `boundaries.py` |
| **Multi-page sets** | A set stays open across page breaks (a repeated header on the next page is recognised), and its location is a list of `{page, bbox}` spans. | `extract.py` |
| **Different column layouts** | Columns are found per schedule from where words start (x positions), not hard-coded. | `columns.py` |
| **Missing quantities** | `null`, never guessed. "As Req", `__` and `--` also become `null`. | `extract.py` |

Bonus items:
- **Confidence scores** on every component and set ✅ (calibrated, see above).
- **Feedback UI** for correcting mistakes ✅. Corrections are logged per field.
- **Code resolution from on-page lookup tables**, partly done. Manufacturer and
  finish legends printed in the book ("RU - Corbin Russwin", "626 Satin
  Chromium") are learned per book and used both to classify columns and to fill
  `mfr_name`. Expanding item-level shorthand (a code like "A" standing for a
  whole component) isn't implemented. In this corpus the closest thing is
  Forest Park's option-code list (`NRP`, `LAR`, ...), which would slot into the
  same legend reader.

## Run it

```bash
make setup          # Python 3.11+; creates .venv and installs requirements
make data           # downloads the challenge specbooks into data/
```

**Command line**

```bash
.venv/bin/python -m hwsets.cli extract "data/AMI _Copy_/<file>.pdf"   # -> outputs/<file>.json + .csv
.venv/bin/python -m hwsets.cli batch data -o outputs                  # every book
.venv/bin/python -m hwsets.cli extract book.pdf --ai                  # AI second opinion
```

**Review screen** (`make ui`, then open http://localhost:8501). Pick a book or
upload a PDF. Each set is drawn on the page (blue = set, green/amber/red =
component confidence) next to an editable table. "Save corrections" logs every
changed field. The *column vote* panel shows exactly why each column was called
manufacturer or finish.

**HTTP API with background jobs** (`make api`, docs at http://localhost:8000/docs)

```bash
curl -F "file=@book.pdf" localhost:8000/jobs          # -> {"job_id": "...", "status": "queued"}
curl localhost:8000/jobs/<id>                         # queued | running | done | failed
curl localhost:8000/jobs/<id>/result                  # the hardware sets
```

**Tests and evaluation**

```bash
make test           # 12 unit tests, one per caveat; no PDFs needed (also runs in CI)
make eval           # scoreboard against eval/gold/, plus confidence calibration
```

## Output format

```json
{
  "set_number": "03",
  "description": null,
  "doors": "120 157",
  "not_used": false,
  "location": [{"page": 398, "bbox": [72.0, 316.5, 532.9, 654.4], "lines": [19, 43]}],
  "confidence": 1.0,
  "components": [
    {"qty": 1, "description": "CONT. HINGE", "catalog_number": "112XY", "mfr": "IVE",
     "mfr_name": "Ives", "finish": "628", "notes": null, "confidence": 1.0,
     "source": "rules", "page": 398, "bbox": [80.0, 390.9, 527.3, 400.9]}
  ]
}
```

`bbox` is in PDF points from the top-left of the page: `[x0, top, x1, bottom]`.
Each file also records how every column was classified (with its votes), the
codes learned from the book's legend, and run stats (pages, OCR pages, values
removed by verification, AI re-reads, cache hit or miss).

## Design decisions and tradeoffs

**Rules first, AI as a backup.** Specbook schedules are *laid out* data. The
columns are physically aligned, so position plus a little domain knowledge gets
almost everything right. It is fast (a 4,000-page manual takes ~40 s, most
books take a few seconds), costs nothing per page, gives the same answer every
run, and every decision can be explained. An LLM reading whole pages would be
slower, cost money per page, and could invent plausible-looking part numbers.
The tradeoff is that unusual layouts need a rule. The confidence score routes
exactly those cases to the AI fallback or to a person.

**Verification on everything.** Every value, whether it came from rules or AI,
must be printed inside that set's box. In the full corpus the check looks at
34,000+ values. During development it caught my own code fusing `AN CLR` into
`ANCLR`, a value that isn't on the page. The check is at the **set** level, so a
value can't be borrowed from a different set. It could still be borrowed from
another row of the *same* set. A per-row check is stricter but breaks on
legitimately wrapped text, so I chose set level.

**Judge a schedule as a whole.** Metal-fabrication and elevator specs also
contain lines like "Set 1" or "Group Number: 2". Instead of trusting each header,
a page run is kept only if most of its sets look like door hardware.

**Columns are learned per schedule, not per book.** One project manual can
contain several schedules with different layouts.

## Known limitations (and what I'd do next)

- **One page in JC Ryan is shifted 14 pt** relative to the rest of the book, so
  its catalog numbers land in the wrong column. The rows are flagged
  low-confidence and are exactly what `--ai` is for. *Next:* re-learn columns
  per page when a page's word starts don't line up with the book's.
- **Struck-through text** (deleted in a revision) is still extracted. *Next:*
  detect strike lines from the PDF's drawing layer.
- **StarHardware** writes its schedule as prose ("Hinges (residential light
  duty…)") with codes buried in sentences. All 46 sets are flagged for review.
- **Woodridge** has no hardware sets in its specbook (it says "See Door Hardware
  Schedule", which lives on the drawings). The tool correctly returns zero sets.
- OCR reads a small lightning-bolt icon as letters on 4 of 255 fields.

## How this would scale

The API already separates *accepting* work from *doing* it: uploads go into a
jobs table and a queue, and workers process them. Today the queue is in-process
(`asyncio.Queue`, 2 workers, extraction in a thread). For real volume:
Redis/SQS for the queue, worker processes on separate machines, results in
Postgres plus object storage, and a page-level fan-out (each hardware page is
independent once the column map is learned). The cache is keyed by a SHA-256 of
the PDF bytes, so re-uploads are free at any scale.

## Repository layout

```
hwsets/
  locate.py       1. find hardware pages in a large manual
  layout.py       2. words + positions per page; OCR for scanned pages; header/footer removal
  boundaries.py   3. set header patterns, NOT USED, END OF SECTION
  table_mode.py   3b. table schedules where a SET column holds the numbers
  columns.py      4. find columns and vote on their type (mfr vs finish lives here)
  codes.py        manufacturer / finish vocabularies + legend learning
  extract.py      5. row parsing and the pipeline that ties the stages together
  verify.py       6. anti-hallucination: every value must be printed on the page
  llm_fallback.py optional multimodal second opinion, strict structured output
  cache.py        SQLite cache keyed by file fingerprint (results and AI calls)
  store.py        jobs + corrections tables
  schema.py       Pydantic output models
  cli.py          command line
api/server.py     FastAPI + background job queue
app/streamlit_app.py  review and correction screen
eval/             answer keys, scorer, first blind held-out run
tests/            unit tests per caveat, AI path tested with a fake model
docs/             format survey, learning guide, demo script
```
