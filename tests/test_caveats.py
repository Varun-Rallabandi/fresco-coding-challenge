"""One test per caveat called out in the challenge brief."""
from hwsets.boundaries import match_header, normalize_set_number
from hwsets.codes import Vocabulary, is_ambiguous
from hwsets.columns import build_column_map
from hwsets.extract import RowParser, split_sets
from tests.helpers import line, row


def schedule(rows_spec, page=1, header="Hardware Group No. 01"):
    lines = [line(page, 0, [(72, header)])]
    lines += [row(page, i + 1, *r) for i, r in enumerate(rows_spec)]
    return lines


TYPICAL = [
    (3, "HINGE", "5BB1 4.5 X 4.5", "652", "IVE"),
    (1, "LOCKSET", "L9010 17A", "626", "SCH"),
    (1, "CLOSER", "4040XP", "689", "LCN"),
    (1, "THRESHOLD", "171A", "AL", "PE"),      # PE sits in the manufacturer column -> Pemko
    (1, "GASKETING", "S88BL", "BK", "PE"),
    (3, "SILENCER", "SR64", "GRY", "IVE"),
]


def parse(lines):
    vocab = Vocabulary()
    sets = split_sets(lines)
    body = [l for s in sets for l in s.lines]
    cmap = build_column_map(body, [], vocab)
    return [RowParser(cmap, vocab).parse(s) for s in sets], cmap


def test_pe_in_manufacturer_column_is_a_manufacturer():
    assert is_ambiguous("PE")  # the dictionaries alone can't decide
    (hs,), cmap = parse(schedule(TYPICAL))
    kinds = {c.kind for c in cmap.columns}
    assert {"mfr", "finish"} <= kinds
    threshold = hs.components[3]
    assert threshold.mfr == "PE" and threshold.mfr_name == "Pemko"
    assert threshold.finish == "AL"


def test_pe_in_finish_column_is_a_finish():
    # Same codes, but now PE appears in a column that is mostly finishes.
    spec = [(q, d, c, "PE" if i in (2, 4) else f, m) for i, (q, d, c, f, m) in enumerate(TYPICAL)]
    spec = [(q, d, c, f, "SCH" if m == "PE" else m) for q, d, c, f, m in spec]
    (hs,), _ = parse(schedule(spec))
    assert hs.components[2].finish == "PE"
    assert hs.components[2].mfr == "LCN"


def test_missing_quantity_is_null_not_guessed():
    spec = list(TYPICAL)
    spec[0] = (None, "HINGE", "5BB1 4.5 X 4.5", "652", "IVE")
    (hs,), _ = parse(schedule(spec))
    assert hs.components[0].qty is None
    assert hs.components[0].confidence < 1.0


def test_not_used_set_is_still_extracted():
    lines = schedule(TYPICAL)
    lines.append(line(1, 20, [(72, "Hardware Group No. 02 - NOT USED")]))
    sets, _ = parse(lines)
    assert [s.set_number for s in sets] == ["01", "02"]
    assert sets[1].not_used and sets[1].components == []


def test_set_spanning_two_pages_keeps_both_locations():
    lines = schedule(TYPICAL[:3], page=7)
    lines += [row(8, i, *r) for i, r in enumerate(TYPICAL[3:])]
    (hs,), _ = parse(lines)
    assert len(hs.components) == 6
    assert [s.page for s in hs.location] == [7, 8]


def test_header_variants():
    cases = {
        "Hardware Group No. 02": "02",
        "SET #1 — ENTRANCE DOORS": "1",
        "Set: 1.0": "1.0",
        "Heading #4": "4",
        "HW SET 3A": "3A",
        "HW 25A": "25A",
        "PART 34 - HARDWARE GROUP NO.  401C": "401C",
        "Hardware Group/Set #B1 and #B2 – Bedroom": "B1",
        "Heading Number 12": "12",
    }
    for text, num in cases.items():
        hit = match_header(text)
        assert hit and hit[0] == num, text


def test_component_lines_are_not_headers():
    assert match_header("1 Hardware Set LP200A 6' PE") is None
    assert match_header("3 EA HINGE 5BB1 4.5 X 4.5 652 IVE") is None


def test_set_number_normalization():
    assert normalize_set_number("02") == "2"
    assert normalize_set_number("1.0") == "1"
    assert normalize_set_number("#3A") == "3A"


def test_legend_teaches_book_specific_codes():
    v = Vocabulary()
    v.learn_from_lines(["1. GS - ASSA ABLOY Glass Solutions", "2. PE - Pemko",
                        "3. RU - Corbin Russwin", "4. RO - Rockwood"])
    assert v.mfr_name("RU") == "Corbin Russwin"
    assert v.is_mfr("GS")


def test_verifier_removes_values_not_printed_on_the_page():
    """Anti-hallucination: a value the page doesn't contain is dropped, whoever produced it."""
    from hwsets.verify import verify_set
    lines = schedule(TYPICAL)
    (hs,), _ = parse(lines)
    hs.components[0].mfr = "HAGER"           # invented: not printed anywhere in this set
    hs.components[1].catalog_number = "L9010 17A"  # real: printed on the page
    verify_set(hs, {1: lines})
    assert hs.components[0].mfr is None
    assert hs.components[1].catalog_number == "L9010 17A"
    assert any("ungrounded" in w for w in hs.warnings)


def test_verifier_does_not_borrow_values_from_another_set():
    from hwsets.verify import verify_set
    lines = schedule(TYPICAL[:3])
    lines.append(line(1, 10, [(72, "Hardware Group No. 02")]))
    lines += [row(1, 11 + i, *r) for i, r in enumerate(TYPICAL[3:])]
    sets, _ = parse(lines)
    sets[0].components[0].finish = "BK"      # only printed in set 02, not in set 01
    verify_set(sets[0], {1: lines})
    assert sets[0].components[0].finish is None
