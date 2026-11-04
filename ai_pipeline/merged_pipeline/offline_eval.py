"""
offline_eval.py - GPU-free evaluation, override auditing, and rule replay.

Everything here runs on the CSVs the pipeline already writes. No model, no GPU.
Requires pandas (available in the cluster `cdcf_new` env; locally: pip install pandas).

Subcommands
-----------
score           Accuracy, per-class P/R/F1, confusion matrix, priority table, combo stats.
                Reproduces the Analysis 1500 Sample notebook numbers.
override-audit  For a run that recorded pre_override_category (Current / LLM Test /
                Merged), count per rule/reason how often it FIXED vs BROKE a row.
replay          Re-apply policy_rules.py to a saved run's MODEL answers, e.g. the Old
                Prompt CSV -> simulates "old prompt + merged rules" at zero GPU cost.
compare         Row-level diff of two runs: which rows became right / became wrong.

Examples (run from the 'Merged Pipeline' folder)
--------
python offline_eval.py score   --results "results/chunks/old_run/*.csv"  --labels combined_1500_labels.csv
python offline_eval.py override-audit --results results/chunks/updated_run_1500_20260928.csv --labels combined_1500_labels.csv
python offline_eval.py replay  --results "results/chunks/old_run/*.csv"  --labels combined_1500_labels.csv --out-dir replay_old
python offline_eval.py compare --a old.csv --b merged.csv --labels combined_1500_labels.csv

Notes
-----
* Results are joined to labels on results[--result-id-col] (default orig_id) ==
  labels[--label-id-col] (default id), exactly like the notebook.
* Duplicate orig_ids are resolved like the notebook: sort by `confidence` descending
  (string sort, so "low" sorts before "high") and keep the first row.
* Categories are lower-cased and collapsed with the notebook's canonical_map
  (concentrate vaporizers -> accessories, closed systems -> closed system,
  heated tobacco products -> heated tobacco product).
"""
import argparse
import glob
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy_rules  # noqa: E402

CANONICAL_MAP = {
    "concentrate vaporizers": "accessories",
    "concentrate vaporizer": "accessories",
    "closed systems": "closed system",
    "heated tobacco products": "heated tobacco product",
}

# Your priority order: disposables > e-liquids > combination systems > closed refills.
PRIORITY_CATEGORIES = ["disposable system", "e-liquid", "closed refills"]

TEXT_COLS = ["product_name", "site_category", "site_tag", "description",
             "eliquid_contents"]


# ---------------------------------------------------------------------------
# Loading / normalisation
# ---------------------------------------------------------------------------
def canon(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "nan"
    v = str(value).strip().lower()
    return CANONICAL_MAP.get(v, v)


def read_results(pattern):
    """Read one CSV, a glob of chunk CSVs, or a comma-separated list of either."""
    paths = []
    for part in str(pattern).split(","):
        part = part.strip()
        matched = sorted(glob.glob(part))
        paths.extend(matched if matched else ([part] if Path(part).exists() else []))
    if not paths:
        raise SystemExit(f"No results files matched: {pattern}")
    frames = [pd.read_csv(p, low_memory=False) for p in paths]
    df = pd.concat(frames, ignore_index=True)
    print(f"Loaded {len(df)} result rows from {len(paths)} file(s)")
    return df


def dedup_like_notebook(df, id_col):
    df = df.copy()
    df[id_col] = df[id_col].astype(str).str.strip()
    n_dup = int(df[id_col].duplicated().sum())
    if "confidence" in df.columns:
        df = df.sort_values("confidence", ascending=False, kind="stable")
    df = df.drop_duplicates(subset=id_col, keep="first").reset_index(drop=True)
    if n_dup:
        print(f"Dropped {n_dup} duplicate {id_col} rows (notebook-style dedup)")
    return df


def attach_labels(df, labels_path, args):
    labels = pd.read_csv(labels_path)
    labels[args.label_id_col] = labels[args.label_id_col].astype(str).str.strip()
    keep = [args.label_id_col, args.label_col]
    if args.combo_label_col in labels.columns:
        keep.append(args.combo_label_col)
    df = dedup_like_notebook(df, args.result_id_col)
    merged = df.merge(labels[keep], left_on=args.result_id_col,
                      right_on=args.label_id_col, how="left",
                      suffixes=("", "_label"))
    missing = int(merged[args.label_col].isna().sum())
    if missing:
        print(f"WARNING: {missing} result rows have no manual label (excluded)")
    merged = merged[merged[args.label_col].notna()].copy()
    merged["true_final"] = merged[args.label_col].map(canon)
    return merged


def to_bool(series):
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y"})


# ---------------------------------------------------------------------------
# Metrics (pure pandas, so sklearn is optional)
# ---------------------------------------------------------------------------
def classification_table(true, pred):
    labels = sorted(set(true) | set(pred))
    rows = []
    for lab in labels:
        tp = int(((true == lab) & (pred == lab)).sum())
        fp = int(((true != lab) & (pred == lab)).sum())
        fn = int(((true == lab) & (pred != lab)).sum())
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        rows.append({"category": lab, "precision": round(prec, 3), "recall": round(rec, 3),
                     "f1": round(f1, 3), "support": int((true == lab).sum()),
                     "missed (FN)": fn, "wrongly_predicted (FP)": fp})
    return pd.DataFrame(rows).set_index("category")


def report(eval_df, pred_col, title, out_dir=None, tag="run"):
    true, pred = eval_df["true_final"], eval_df[pred_col]
    match = true == pred
    print("\n" + "=" * 78)
    print(f"{title}")
    print("=" * 78)
    print(f"Rows evaluated: {len(eval_df)} | Correct: {int(match.sum())} | "
          f"Errors: {int((~match).sum())} | Accuracy: {match.mean():.3%}")
    table = classification_table(true, pred)
    print("\nPriority categories (disposables > e-liquid > combo > closed refills):")
    print(table.loc[[c for c in PRIORITY_CATEGORIES if c in table.index]].to_string())
    print("\nAll categories:")
    print(table.to_string())
    confusions = (eval_df.loc[~match, ["true_final", pred_col]].value_counts()
                  .reset_index(name="count"))
    confusions.columns = ["true", "pred", "count"]
    print("\nTop confusion pairs:")
    print(confusions.head(20).to_string(index=False))
    combo_summary(eval_df, pred_col)
    if out_dir:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        table.to_csv(out / f"{tag}_classification_table.csv")
        pd.crosstab(true, pred).to_csv(out / f"{tag}_confusion_matrix.csv")
        cols = [c for c in ["orig_id", "product_name", "site_name", "true_final", pred_col,
                            "pre_override_category", "policy_rule_id", "rationale",
                            "cbd_rationale", "combination_device"] if c in eval_df.columns]
        eval_df.loc[~match, cols].to_csv(out / f"{tag}_errors.csv", index=False)
        print(f"\nWrote {tag}_classification_table.csv, {tag}_confusion_matrix.csv, "
              f"{tag}_errors.csv to {out}")
    return match


def combo_summary(eval_df, pred_col, combo_col="combination_device"):
    if combo_col not in eval_df.columns:
        return
    flag = to_bool(eval_df[combo_col])
    on_disp = flag & (eval_df[pred_col] == "disposable system")
    print(f"\nCombination devices flagged: {int(flag.sum())} "
          f"(on final Disposable rows: {int(on_disp.sum())}, "
          f"on non-Disposable rows: {int((flag & ~on_disp).sum())})")
    if "combo_device_flag" in eval_df.columns:
        truth = to_bool(eval_df["combo_device_flag"])
        tp = int((flag & truth).sum())
        fp = int((flag & ~truth).sum())
        fn = int((~flag & truth).sum())
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        print(f"Combo vs combo_device_flag: TP={tp} FP={fp} FN={fn} | "
              f"precision={prec:.3f} recall={rec:.3f}")


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------
def cmd_score(args):
    df = attach_labels(read_results(args.results), args.labels, args)
    df["pred_final"] = df[args.pred_col].map(canon)
    report(df, "pred_final", f"SCORE: {args.results}", args.out_dir, args.tag)
    if "pre_override_category" in df.columns and df["pre_override_category"].notna().any():
        df["pre_final"] = df["pre_override_category"].fillna(df[args.pred_col]).map(canon)
        report(df, "pre_final", "SCORE of the MODEL's own answers (pre_override_category)",
               args.out_dir, args.tag + "_pre_override")


def cmd_override_audit(args):
    df = attach_labels(read_results(args.results), args.labels, args)
    if "pre_override_category" not in df.columns:
        raise SystemExit("This run has no pre_override_category column (Old Prompt runs "
                         "have no override layer). Use `replay` instead.")
    df["pre_final"] = df["pre_override_category"].fillna(df[args.pred_col]).map(canon)
    df["post_final"] = df[args.pred_col].map(canon)
    changed = df[df["pre_final"] != df["post_final"]].copy()
    reason_col = next((c for c in ("policy_rule_id", "policy_override_reason")
                       if c in changed.columns and changed[c].notna().any()), None)
    if reason_col is None:
        changed["reason"] = "(no reason recorded)"
        reason_col = "reason"
    changed["outcome"] = "neutral (wrong -> wrong)"
    changed.loc[changed["post_final"] == changed["true_final"], "outcome"] = "FIXED"
    changed.loc[changed["pre_final"] == changed["true_final"], "outcome"] = "BROKE"
    print(f"\nOverrides that changed the category: {len(changed)} of {len(df)} rows")
    if len(changed):
        summary = changed.groupby([reason_col, "outcome"]).size().unstack(fill_value=0)
        for col in ("FIXED", "BROKE", "neutral (wrong -> wrong)"):
            if col not in summary.columns:
                summary[col] = 0
        summary["net"] = summary["FIXED"] - summary["BROKE"]
        with pd.option_context("display.max_colwidth", 90, "display.width", 250):
            print(summary.sort_values("net").to_string())
        broke = changed[changed["outcome"] == "BROKE"]
        if len(broke):
            print("\nRows the override layer BROKE (priority categories first):")
            broke = broke.assign(_p=~broke["true_final"].isin(PRIORITY_CATEGORIES))
            for _, r in broke.sort_values("_p").iterrows():
                print(f"  true={r['true_final']:<18} model={r['pre_final']:<18} -> "
                      f"{r['post_final']:<16} | {str(r.get('product_name', ''))[:55]}")
    report(df, "pre_final", "MODEL answers before overrides", None)
    report(df, "post_final", "FINAL answers after overrides", None)
    if args.out_dir:
        Path(args.out_dir).mkdir(parents=True, exist_ok=True)
        changed.to_csv(Path(args.out_dir) / f"{args.tag}_override_audit.csv", index=False)


def _row_dict(r):
    return {c: r.get(c, "") for c in TEXT_COLS}


def cmd_replay(args):
    """Re-apply policy_rules to the MODEL answers stored in a saved run."""
    df = attach_labels(read_results(args.results), args.labels, args)
    # Model answer = pre_override_category when the run recorded one, else categories.
    if "pre_override_category" in df.columns and df["pre_override_category"].notna().any():
        base = df["pre_override_category"].fillna(df[args.pred_col])
        print("Replaying from pre_override_category (the model's own answers)")
    else:
        base = df[args.pred_col]
        print(f"Replaying from '{args.pred_col}' (run has no override layer)")
    missing_text = [c for c in ("product_name", "description") if c not in df.columns]
    if missing_text:
        raise SystemExit(f"Results CSV lacks text columns {missing_text}; replay needs them.")

    new_cats, rule_ids, reasons, combos, guard = [], [], [], [], []
    is_cbd_col = df["is_cbd"] if "is_cbd" in df.columns else pd.Series(False, index=df.index)
    for idx, r in df.iterrows():
        row = _row_dict(r)
        model_cat = base.loc[idx]
        was_cbd = canon(model_cat) == "cbd" or str(is_cbd_col.loc[idx]).lower() == "true"
        if was_cbd:
            # We cannot re-run the classifier offline, so a guard hit is only COUNTED.
            fires = policy_rules.cbd_guard_should_override(row)
            guard.append(fires)
            new_cats.append("CBD")
            rule_ids.append("CBD_GUARD_WOULD_RECLASSIFY" if fires else None)
            reasons.append(None)
            combos.append(False)
            continue
        guard.append(False)
        result = {
            "categories": model_cat,
            "rationale": r.get("rationale", ""),
            "combination_device": str(r.get("combination_device", "")).lower() == "true",
        }
        result = policy_rules.apply_category_policy(result, row)
        new_cats.append(result["categories"])
        rule_ids.append(result["policy_rule_id"] or result.get("combo_rule_applied"))
        reasons.append(result["policy_override_reason"])
        combos.append(result["combination_device"])

    df["model_final"] = base.map(canon)
    df["replay_category"] = new_cats
    df["replay_final"] = df["replay_category"].map(canon)
    df["replay_rule_id"] = rule_ids
    df["replay_reason"] = reasons
    df["replay_combination_device"] = combos
    df["cbd_guard_would_fire"] = guard

    report(df, "model_final", "BEFORE replay (model answers)", args.out_dir, args.tag + "_before")
    combo_before = df.get("combination_device")
    df_after = df.copy()
    df_after["combination_device"] = df["replay_combination_device"]
    report(df_after, "replay_final", "AFTER replay (model answers + policy_rules.py)",
           args.out_dir, args.tag + "_after")

    changed = df[df["model_final"] != df["replay_final"]].copy()
    changed["outcome"] = "neutral (wrong -> wrong)"
    changed.loc[changed["replay_final"] == changed["true_final"], "outcome"] = "FIXED"
    changed.loc[changed["model_final"] == changed["true_final"], "outcome"] = "BROKE"
    print(f"\nRules changed {len(changed)} rows")
    if len(changed):
        print(changed.groupby(["replay_rule_id", "outcome"]).size()
              .unstack(fill_value=0).to_string())
        broke = changed[changed["outcome"] == "BROKE"]
        for _, r in broke.iterrows():
            print(f"  BROKE {r['replay_rule_id']}: true={r['true_final']} "
                  f"model={r['model_final']} -> {r['replay_final']} | "
                  f"{str(r.get('product_name', ''))[:60]}")
    g = df[df["cbd_guard_would_fire"]]
    if len(g):
        right = int((g["true_final"] != "cbd").sum())
        print(f"\nCBD guard would send {len(g)} CBD rows to the classifier: {right} are "
              f"truly NOT CBD (fixable), {len(g) - right} ARE CBD (would need the classifier "
              f"to return CBD -> risk)")
        for _, r in g.iterrows():
            print(f"  true={r['true_final']:<18} | {str(r.get('product_name', ''))[:60]}")
    if combo_before is not None:
        added = int((~to_bool(combo_before) & df["replay_combination_device"]).sum())
        cleared = int((to_bool(combo_before) & ~df["replay_combination_device"]).sum())
        print(f"\nCombo flag: +{added} set from text / pod-battery rules, "
              f"-{cleared} cleared on non-Disposable rows")
    if args.out_dir:
        Path(args.out_dir).mkdir(parents=True, exist_ok=True)
        df.to_csv(Path(args.out_dir) / f"{args.tag}_replayed.csv", index=False)
        print(f"Wrote {args.tag}_replayed.csv (feed it to `score --pred-col replay_category`)")


def cmd_compare(args):
    a = attach_labels(read_results(args.a), args.labels, args)
    b = attach_labels(read_results(args.b), args.labels, args)
    key = args.result_id_col
    a = a[[key, "product_name", "true_final", args.pred_col]].rename(
        columns={args.pred_col: "pred_a"})
    b = b[[key, args.pred_col]].rename(columns={args.pred_col: "pred_b"})
    m = a.merge(b, on=key, how="inner")
    m["pred_a"] = m["pred_a"].map(canon)
    m["pred_b"] = m["pred_b"].map(canon)
    ok_a, ok_b = m["pred_a"] == m["true_final"], m["pred_b"] == m["true_final"]
    print(f"\nRows in both runs: {len(m)} | A correct: {int(ok_a.sum())} | "
          f"B correct: {int(ok_b.sum())}")
    for title, mask in (("BECAME RIGHT in B", ~ok_a & ok_b),
                        ("BECAME WRONG in B", ok_a & ~ok_b)):
        sub = m[mask].assign(_p=~m["true_final"].isin(PRIORITY_CATEGORIES)).sort_values("_p")
        print(f"\n{title}: {len(sub)}")
        for _, r in sub.iterrows():
            print(f"  true={r['true_final']:<18} A={r['pred_a']:<18} B={r['pred_b']:<18} | "
                  f"{str(r['product_name'])[:55]}")
    if args.out_dir:
        Path(args.out_dir).mkdir(parents=True, exist_ok=True)
        m[ok_a != ok_b].to_csv(Path(args.out_dir) / f"{args.tag}_compare.csv", index=False)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, results=True):
        if results:
            sp.add_argument("--results", required=True,
                            help="Results CSV, glob of chunk CSVs, or comma-separated list")
        sp.add_argument("--labels", required=True, help="combined_1500_labels.csv")
        sp.add_argument("--label-col", default="UPDATED_PRODUCT_CATEGORY")
        sp.add_argument("--combo-label-col", default="combo_device_flag")
        sp.add_argument("--label-id-col", default="id")
        sp.add_argument("--result-id-col", default="orig_id")
        sp.add_argument("--pred-col", default="categories")
        sp.add_argument("--out-dir", default=None, help="Write CSV artifacts here")
        sp.add_argument("--tag", default="run", help="Prefix for written files")

    common(sub.add_parser("score", help="Accuracy / P-R-F1 / confusion / combo stats"))
    common(sub.add_parser("override-audit", help="Per-rule FIXED vs BROKE for a run"))
    common(sub.add_parser("replay", help="Re-apply policy_rules.py to saved model answers"))
    cp = sub.add_parser("compare", help="Row-level diff of two runs")
    cp.add_argument("--a", required=True)
    cp.add_argument("--b", required=True)
    common(cp, results=False)

    args = p.parse_args()
    {"score": cmd_score, "override-audit": cmd_override_audit,
     "replay": cmd_replay, "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    main()
