# Merged Pipeline

Old Prompt base (kept for its disposable and combination-device accuracy), plus the Current Prompt's fixes, which are implemented mostly as **code** rather than prompt text.

| File | What it is |
|---|---|
| `merged_pipeline.py` | GPU pipeline: the Old pipeline plus the CBD guard, the CBD rationale in output, and `policy_rules` |
| `merged_prompts.py` | Old prompts, edited in place. Each edit is tagged `[MERGE E#]`. The Disposable definition and Rule 4 (combo) are unchanged. |
| `policy_rules.py` | Rules R1–R12 plus the CBD guard. Standard library only, so it also runs offline. |
| `offline_eval.py` | No GPU needed: `score`, `override-audit`, `replay`, `compare` |
| `build_hard_case_subset.py` | Builds a small input CSV (all errors plus controls) for a quick GPU check |
| `merged_pipeline_slurm.sh` | Runs `merged_pipeline.py`, and checks that all 3 `.py` files are present |

## Offline workflow (no GPU; needs pandas)
Run these from the `Merged Pipeline` folder.
```bash
# 1. Reproduce the numbers you already have
python offline_eval.py score --results "results/chunks/<old_run>/*.csv"  --labels combined_1500_labels.csv
python offline_eval.py score --results results/chunks/updated_run_1500_20260928.csv --labels combined_1500_labels.csv
# 2. How much did the Current override layer help or hurt? (runs that have pre_override_category)
python offline_eval.py override-audit --results results/chunks/updated_run_1500_20260928.csv --labels combined_1500_labels.csv
# 3. Simulate "old prompt + merged rules"
python offline_eval.py replay --results "results/chunks/<old_run>/*.csv" --labels combined_1500_labels.csv --out-dir replay_old --tag old
# 4. Row-level diff between any two runs
python offline_eval.py compare --a old.csv --b merged.csv --labels combined_1500_labels.csv
```
Joins, dedup and category collapsing all match `Analysis 1500 Sample.ipynb`. When a `combo_device_flag` column exists in the labels, `score` also reports combo precision and recall.

## Rules (policy_rules.py)
- **R1** Closed Refills → Accessories when there's no liquid evidence. Evidence can be prefilled wording, a nicotine strength, a puff count, or "disposable".
- **R2** Closed Refills → Disposable (combo) when the pod has its own battery and a separate device only recharges it.
- **R3** Accessories → Open System for an operational box mod (named as a mod, with W / TC / chipset specs, not concentrate).
- **R4** Open/Closed System → Accessories when the product name is a standalone tank/RTA/RDA/coil/replacement pod.
- **R5** 510 cartridge devices, e-nails and dab tools → Accessories.
- **R6** Accessories → Closed Refills for a pod listing with explicit prefilled wording.
- **R7** Nicotine pouches wrongly called Closed Refills → Nicotine Pouches.
- **R8** Category-name normalisation.
- **R9** Combo flag: cleared on any row that isn't Disposable; set on Disposables whose text uses modular wording.
- **R10** Disposable → Closed Refills only when a prefilled pod/capsule listing explicitly depends on a separately named host or is demonstrably a pod-only package. A self-powered pod remains Disposable.
- **R11** Disposable → Closed System only when a reusable powered host, prefilled consumables, and their replacement lifecycle are all explicit.
- **R12** Disposable → Open System only when a named complete device is explicitly repeatedly refilled by the customer with bottled e-liquid.
- **CBD guard:** a CBD positive with no cannabinoid/strain term but with nicotine context → sent to the classifier.

A **Disposable System answer is not broadly demoted**. Besides hard 510 / e-nail / dab-tool policies, R10–R12 only correct it when multiple independent statements establish a contradictory reusable role. Generic "disposable," puff count, battery, replaceable/detachable/magnetic/snap-in, or refillable wording never fires these rules alone.

Flags: `--disable_policy_rules` and `--disable_cbd_guard` let you A/B test each layer.
