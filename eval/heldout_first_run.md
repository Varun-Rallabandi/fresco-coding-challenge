# First run on held-out books

Before changing any rules for these six books (Lyons, Oswego, Door Co, Shubie, Morris, National):

| sets | set recall | set precision | sets fully exact | components matched | mfr/finish | swaps |
|-----:|-----------:|--------------:|-----------------:|-------------------:|-----------:|------:|
| 25 | 96.0% | 100.0% | 76.0% | 98.7% | 100.0% | 0 |

Misses and what I changed:
- Door Co 720CRZ: header at the bottom of one page, rows on the next.
- Morris: door handing (RH / LH / LHR) was getting merged into the catalog number.
- Morris, Oswego: "Properties: ..." and "NOTE" lines without a colon were merged into a component.
