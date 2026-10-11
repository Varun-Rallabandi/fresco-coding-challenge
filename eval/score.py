"""Score the extractor against eval/gold/.

    python -m eval.score
    python -m eval.score ami usi
"""
from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hwsets.boundaries import normalize_set_number  # noqa: E402
from hwsets.extract import extract  # noqa: E402

FIELDS = ["qty", "description", "catalog_number", "mfr", "finish"]


def norm_text(v) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip().upper().replace("”", '"').replace("“", '"')


def same(field: str, gold, pred) -> bool:
    g, p = norm_text(gold), norm_text(pred)
    if field in ("qty", "mfr", "finish"):
        return g == p
    if not g and not p:
        return True
    # Free text: tolerate spacing/punctuation differences from PDF extraction.
    squash = lambda s: re.sub(r"[^A-Z0-9]", "", s)  # noqa: E731
    return squash(g) == squash(p) or SequenceMatcher(None, g, p).ratio() >= 0.9


def align(gold: list[dict], pred: list[dict]) -> list[tuple[dict, dict | None]]:
    """Pair gold components with predicted ones in order, allowing skips."""
    pairs, j = [], 0
    for g in gold:
        best, best_k = 0.0, None
        for k in range(j, min(j + 4, len(pred))):
            score = SequenceMatcher(None, norm_text(g["description"]) + norm_text(g["catalog_number"]),
                                    norm_text(pred[k].get("description")) + norm_text(pred[k].get("catalog_number"))).ratio()
            if score > best:
                best, best_k = score, k
        if best_k is not None and best >= 0.5:
            pairs.append((g, pred[best_k]))
            j = best_k + 1
        else:
            pairs.append((g, None))
    return pairs


def score_file(gold_path: Path) -> dict:
    gold = json.loads(gold_path.read_text())
    result = extract(ROOT / "data" / gold["file"])
    pages = set(gold["pages"])
    pred_sets = [s.model_dump() for s in result.sets if s.location[0].page in pages]
    by_num = {}
    for s in pred_sets:
        by_num.setdefault(normalize_set_number(s["set_number"]), s)

    stats = {"gold_sets": len(gold["sets"]), "found": 0, "pred_sets": len(pred_sets), "exact_sets": 0,
             "fields": {f: [0, 0] for f in FIELDS}, "mfr_fin": [0, 0], "swaps": 0,
             "gold_comps": 0, "matched_comps": 0, "misses": [], "calib": []}
    gold_nums = {normalize_set_number(g["set_number"]) for g in gold["sets"]}
    stats["true_pred"] = sum(1 for n in by_num if n in gold_nums)

    for g in gold["sets"]:
        p = by_num.get(normalize_set_number(g["set_number"]))
        if not p:
            stats["misses"].append(f"set {g['set_number']} not found")
            continue
        stats["found"] += 1
        exact = len(g["components"]) == len(p["components"]) and g.get("not_used", False) == p["not_used"]
        for gc, pc in align(g["components"], p["components"]):
            stats["gold_comps"] += 1
            if pc is None:
                exact = False
                stats["misses"].append(f"set {g['set_number']}: missing '{gc['description']}'")
                for f in FIELDS:
                    stats["fields"][f][1] += 1
                continue
            stats["matched_comps"] += 1
            stats["calib"].append((pc.get("confidence", 1.0), all(same(f, gc.get(f), pc.get(f)) for f in FIELDS)))
            for f in FIELDS:
                ok = same(f, gc.get(f), pc.get(f))
                stats["fields"][f][0] += ok
                stats["fields"][f][1] += 1
                if not ok:
                    exact = False
                    if len(stats["misses"]) < 400:
                        stats["misses"].append(f"set {g['set_number']} '{gc['description']}' {f}: gold={gc.get(f)!r} got={pc.get(f)!r}")
            for f in ("mfr", "finish"):
                if gc.get(f) is not None or pc.get(f) is not None:
                    stats["mfr_fin"][0] += same(f, gc.get(f), pc.get(f))
                    stats["mfr_fin"][1] += 1
            if gc.get("mfr") and norm_text(pc.get("finish")) == norm_text(gc["mfr"]):
                stats["swaps"] += 1
            if gc.get("finish") and norm_text(pc.get("mfr")) == norm_text(gc["finish"]):
                stats["swaps"] += 1
        stats["exact_sets"] += exact
    return stats


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:5.1f}%" if b else "   n/a"


def main(names: list[str]) -> None:
    files = sorted((ROOT / "eval" / "gold").glob("*.json"))
    if names:
        files = [f for f in files if f.stem in names]
    print(f"{'book':<12} {'sets':>5} {'recall':>7} {'precis':>7} {'exact':>7} {'comps':>6} {'matched':>8} "
          + " ".join(f"{f[:7]:>8}" for f in FIELDS) + f" {'mfr/fin':>8} {'swaps':>5}")
    details = {}
    details_stats = {}
    for f in files:
        s = score_file(f)
        details[f.stem] = s["misses"]
        details_stats[f.stem] = s
        print(f"{f.stem:<12} {s['gold_sets']:>5} {pct(s['found'], s['gold_sets']):>7} {pct(s['true_pred'], s['pred_sets']):>7} "
              f"{pct(s['exact_sets'], s['gold_sets']):>7} {s['gold_comps']:>6} {pct(s['matched_comps'], s['gold_comps']):>8} "
              + " ".join(f"{pct(*s['fields'][k]):>8}" for k in FIELDS)
              + f" {pct(*s['mfr_fin']):>8} {s['swaps']:>5}")
    print("-" * 120)
    print_total("TOTAL", merge(list(details_stats.values())))
    for split in ("dev", "heldout"):
        sub = [details_stats[k] for k in details_stats if (k.startswith("heldout_")) == (split == "heldout")]
        if sub:
            print_total(split.upper(), merge(sub))
    out = ROOT / "eval" / "last_run_misses.json"
    out.write_text(json.dumps(details, indent=2))
    print(f"\nDetails of every miss: {out.relative_to(ROOT)}")
    print("DEV = books used while building the rules; HELDOUT = books never looked at while tuning.")
    calib = [c for st in details_stats.values() for c in st["calib"]]
    print("\nConfidence calibration (is a low score a real warning sign?):")
    for lo, hi in ((0.9, 1.01), (0.8, 0.9), (0.0, 0.8)):
        bucket = [ok for conf, ok in calib if lo <= conf < hi]
        if bucket:
            print(f"  confidence {lo:.1f}-{min(hi, 1.0):.1f}: {len(bucket):4d} components, "
                  f"{100 * sum(bucket) / len(bucket):5.1f}% fully correct")


def merge(stats: list[dict]) -> dict:
    t = {"gold_sets": 0, "found": 0, "pred_sets": 0, "true_pred": 0, "exact_sets": 0,
         "gold_comps": 0, "matched_comps": 0, "mfr_fin": [0, 0], "swaps": 0,
         "fields": {f: [0, 0] for f in FIELDS}}
    for s in stats:
        for k in ("gold_sets", "found", "pred_sets", "true_pred", "exact_sets", "gold_comps", "matched_comps", "swaps"):
            t[k] += s[k]
        for k in FIELDS:
            t["fields"][k][0] += s["fields"][k][0]
            t["fields"][k][1] += s["fields"][k][1]
        t["mfr_fin"][0] += s["mfr_fin"][0]
        t["mfr_fin"][1] += s["mfr_fin"][1]
    return t


def print_total(name: str, t: dict) -> None:
    print(f"{name:<12} {t['gold_sets']:>5} {pct(t['found'], t['gold_sets']):>7} {pct(t['true_pred'], t['pred_sets']):>7} "
          f"{pct(t['exact_sets'], t['gold_sets']):>7} {t['gold_comps']:>6} {pct(t['matched_comps'], t['gold_comps']):>8} "
          + " ".join(f"{pct(*t['fields'][k]):>8}" for k in FIELDS)
          + f" {pct(*t['mfr_fin']):>8} {t['swaps']:>5}")


if __name__ == "__main__":
    main(sys.argv[1:])
