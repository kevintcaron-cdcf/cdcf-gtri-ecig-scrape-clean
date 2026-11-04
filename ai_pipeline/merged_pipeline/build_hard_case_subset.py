"""
build_hard_case_subset.py - build a small input CSV for a quick GPU sanity run.

Takes every row that ANY of the given runs got wrong (the "hard cases"), plus a random
sample of rows every run got right in the priority categories (a regression guard for
disposables / e-liquids / closed refills / combo devices), and writes them as a pipeline
INPUT CSV (same columns as the full input), so you can run:

    python merged_pipeline.py --input hard_cases.csv ...

Example (from the 'Merged Pipeline' folder, on the cluster):
    python build_hard_case_subset.py \
        --input  ../inputs/combined_1500_labeled.csv \
        --labels ../inputs/combined_1500_labels.csv \
        --runs "results/chunks/old_run/*.csv" results/chunks/updated_run_1500_20260928.csv \
        --out  inputs/hard_cases.csv --control-per-category 40
"""
import argparse
import sys

import pandas as pd

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from offline_eval import attach_labels, canon, read_results  # noqa: E402

CONTROL_CATEGORIES = ["disposable system", "e-liquid", "closed refills", "closed system",
                      "open system", "accessories"]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help="Full pipeline input CSV (1500 rows)")
    p.add_argument("--labels", required=True)
    p.add_argument("--runs", nargs="+", required=True,
                   help="One or more result CSVs/globs (e.g. old, current, llm-test)")
    p.add_argument("--out", required=True)
    p.add_argument("--control-per-category", type=int, default=40)
    p.add_argument("--seed", type=int, default=13)
    p.add_argument("--input-id-col", default="orig_id",
                   help="ID column in --input that matches results' orig_id")
    p.add_argument("--label-col", default="UPDATED_PRODUCT_CATEGORY")
    p.add_argument("--combo-label-col", default="combo_device_flag")
    p.add_argument("--label-id-col", default="id")
    p.add_argument("--result-id-col", default="orig_id")
    p.add_argument("--pred-col", default="categories")
    args = p.parse_args()

    wrong_ids, right_sets, truth = set(), [], {}
    for run in args.runs:
        df = attach_labels(read_results(run), args.labels, args)
        df["pred_final"] = df[args.pred_col].map(canon)
        ok = df["pred_final"] == df["true_final"]
        wrong_ids |= set(df.loc[~ok, args.result_id_col])
        right_sets.append(set(df.loc[ok, args.result_id_col]))
        truth.update(dict(zip(df[args.result_id_col], df["true_final"])))
        # Combo rows are always worth re-checking.
        if "combination_device" in df.columns:
            flag = df["combination_device"].astype(str).str.lower() == "true"
            wrong_ids |= set(df.loc[flag, args.result_id_col])
    always_right = set.intersection(*right_sets) - wrong_ids if right_sets else set()

    control = []
    for cat in CONTROL_CATEGORIES:
        pool = sorted(i for i in always_right if truth.get(i) == cat)
        k = min(args.control_per_category, len(pool))
        control += list(pd.Series(pool).sample(n=k, random_state=args.seed)) if k else []

    full = pd.read_csv(args.input, low_memory=False)
    if args.input_id_col not in full.columns:
        raise SystemExit(f"--input has no '{args.input_id_col}' column. Columns: "
                         f"{list(full.columns)[:20]} ... pass --input-id-col")
    full["_id"] = full[args.input_id_col].astype(str).str.strip()
    wanted = wrong_ids | set(control)
    subset = full[full["_id"].isin(wanted)].drop(columns="_id")
    subset.to_csv(args.out, index=False)
    print(f"Hard cases (wrong in >=1 run, or combo-flagged): {len(wrong_ids)}")
    print(f"Always-right controls sampled: {len(control)} "
          f"({args.control_per_category}/category max from {CONTROL_CATEGORIES})")
    print(f"Wrote {len(subset)} input rows to {args.out}")


if __name__ == "__main__":
    main()
