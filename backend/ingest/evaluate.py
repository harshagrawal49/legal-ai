"""Measure the property filter against hand labels.

    1. uv run python -m ingest --dry-run --source sc --years 2024 --sample-csv decisions.csv
    2. open decisions.csv and fill the last column with y (property / land dispute) or n, for a random sample
       of rows; aim for ~150 accepted and ~150 rejected (ingest_plan.md §10)
    3. uv run python -m ingest.evaluate decisions.csv

Reports precision and recall with 95% Wilson intervals, and the breakdown by deciding stage, so you can
see which stage makes the mistakes. Rows without a y/n label are ignored.
"""

import csv
import sys
from collections import Counter

from eval.run_all import wilson

LABEL = "label (property? y/n)"


def evaluate(path: str) -> str:
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8")) if (r.get(LABEL) or "").strip().lower() in ("y", "n")]
    if not rows:
        return "No labelled rows (fill the last column with y or n)."
    tp = sum(r["decision"].startswith("accept") and r[LABEL].strip().lower() == "y" for r in rows)
    fp = sum(r["decision"].startswith("accept") and r[LABEL].strip().lower() == "n" for r in rows)
    fn = sum(not r["decision"].startswith("accept") and r[LABEL].strip().lower() == "y" for r in rows)
    tn = len(rows) - tp - fp - fn
    p_lo, p_hi = wilson(tp, tp + fp)
    r_lo, r_hi = wilson(tp, tp + fn)
    out = [
        f"Labelled rows: {len(rows)} (TP {tp} · FP {fp} · FN {fn} · TN {tn})",
        f"Precision: {tp / max(tp + fp, 1):.1%} (95% CI {p_lo:.1%}–{p_hi:.1%})",
        f"Recall:    {tp / max(tp + fn, 1):.1%} (95% CI {r_lo:.1%}–{r_hi:.1%})",
        "Note: recall here is over the labelled rows; label rejected rows at random to estimate real recall.",
        "\nMistakes by stage:",
    ]
    errors = Counter((r["stage"], "FP" if r["decision"].startswith("accept") else "FN") for r in rows
                     if r["decision"].startswith("accept") != (r[LABEL].strip().lower() == "y"))
    out += [f"  {stage:10} {kind}: {n}" for (stage, kind), n in errors.most_common()] or ["  none"]
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    print(evaluate(sys.argv[1]))
