# Hardware Set Extractor

Pulls door hardware sets out of Division 08 specbooks and returns them as JSON/CSV, with the page and box each set came from.

Live demo: https://fresco-hwsets.streamlit.app (opens on a sample book, or upload your own PDF)

Demo video: _Loom link here_

## Setup

Python 3.11+.

```bash
make setup    # creates .venv and installs requirements
make data     # downloads the challenge specbooks into data/
```

Tesseract is only needed for scanned PDFs (`brew install tesseract`).

## Run

Review UI (shows each set drawn on the page next to an editable table):

```bash
make ui       # http://localhost:8501
```

Command line:

```bash
.venv/bin/python -m hwsets.cli extract path/to/book.pdf    # writes outputs/<book>.json and .csv
.venv/bin/python -m hwsets.cli batch data -o outputs       # every book in data/
```

API (upload a PDF, poll for the result):

```bash
make api      # http://localhost:8000/docs
curl -F "file=@book.pdf" localhost:8000/jobs
curl localhost:8000/jobs/<id>/result
```

Tests and scoring:

```bash
make test     # unit tests, no PDFs needed
make eval     # scores against the hand-checked answers in eval/gold/
```

## How it works

1. Find the hardware pages (some manuals are 4,000 pages).
2. Read every word with its x/y position, using OCR if the page is scanned.
3. Split the text into sets at each header (`SET #1`, `Hardware Group No. 02`, `Heading #4`, etc.). Roselle uses a table with a SET column instead, so that format has its own parser.
4. Work out what each column is. Every row in the schedule votes, so a code like `PE` gets its meaning from the column it's in (Pemko in the manufacturer column, painted enamel in the finish column). Abbreviation lists printed in the book are picked up too.
5. Parse the rows into components. Missing quantities stay null.
6. Check every value against the words printed inside that set's box, and drop anything that isn't there.

Each component gets a confidence score, and low scores are flagged for review in the UI.

I kept it rule-based. I wasn't sure an LLM was allowed for this, and the schedules are laid out in columns, so position gets you most of the way.

## Results

On 16 books I labeled by hand (77 sets): every set found, 98.7% of components correct, manufacturer vs finish 99.9% correct. Six of those books were held back while building. The first run on them scored 96% set recall; the misses and fixes are in `eval/heldout_first_run.md`.

## Known issues

- One page in JC Ryan is shifted relative to the rest of the book, so some values land in the wrong column. Those rows get flagged.
- StarHardware writes its schedule as sentences, so every set there is flagged for review.
- Struck-through text is still extracted.
- Woodridge has no hardware sets in its specbook (they're on the drawings), so it returns nothing.
