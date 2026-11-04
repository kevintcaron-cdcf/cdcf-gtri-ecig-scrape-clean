#!/bin/bash
#SBATCH --job-name=image_prep
#SBATCH --mail-user=Nathan.Grodzinsky@gtri.gatech.edu
#SBATCH --mail-type=END,FAIL
#SBATCH --partition=all
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --output=logs/image_prep_%j.out
#SBATCH --error=logs/image_prep_%j.err

# ---------------------------------------------------------------------------
# Image preparation chain (CPU only), run before the GPU array job:
#   1. preprocess_images.py      raw images_from_box_updated -> images_resized
#   2. create_image_collages_dynamic.py  build *_collage.jpg beside the sources
#   3. preprocess_collages.py    compress collages into updated_image_collages
#
# Existing outputs are skipped at every step, so the 1,451 collages already in
# updated_image_collages are not rebuilt. Set DRY_RUN=1 to print the commands only.
#
# Usage:
#   EXPORT_ID=$(sbatch --parsable export_input_csv_slurm.sh)
#   IMAGE_ID=$(sbatch --parsable --dependency=afterok:$EXPORT_ID image_prep_slurm.sh)
#   sbatch --dependency=afterok:$IMAGE_ID merged_pipeline_slurm.sh
# ---------------------------------------------------------------------------

source /opt/apps/Module/jupyterhub/2023.07/etc/profile.d/conda.sh
conda activate cdcf_new

WORKDIR=/home/projects/cdcf_ecig_analysis
SCRIPT_DIR=${COLLAGE_SCRIPT_DIR:-$WORKDIR}  # the three collage scripts sit in the main cdcf folder
RAW_DIR=$WORKDIR/images_from_box_updated
RESIZED_DIR=$WORKDIR/images_resized
FINAL_DIR=$WORKDIR/updated_image_collages
INPUT_CSV=$WORKDIR/inputs/ecig_product_full.csv

# Flags confirmed by the tests on the existing outputs.
MAX_SIDE=640            # preprocess_images.py (most common longest side in images_resized)
PREPROCESS_QUALITY=90   # preprocess_images.py default; the original value was not logged
WORKERS=32              # preprocess_images.py and preprocess_collages.py
THUMB_PX=512            # create_image_collages_dynamic.py cell size
COLLAGE_QUALITY=${COLLAGE_QUALITY:-90}   # not byte-identical to the 1451 originals; see test
COMPRESS_MAX_PIXELS=524288   # preprocess_collages.py default (512K budget)
COMPRESS_QUALITY=85     # preprocess_collages.py default

DRY_RUN=${DRY_RUN:-0}
mkdir -p "$WORKDIR/logs"
cd "$WORKDIR" || exit 1

run() {
    echo ">>> $*"
    if [ "$DRY_RUN" = "1" ]; then return 0; fi
    "$@"
}

echo "=========================================="
echo "Image prep job: $SLURM_JOB_ID"
echo "Started: $(date)"
echo "Raw: $RAW_DIR"
echo "Resized: $RESIZED_DIR"
echo "Final collages: $FINAL_DIR"
echo "=========================================="

for path in "$SCRIPT_DIR/preprocess_images.py" \
            "$SCRIPT_DIR/create_image_collages_dynamic.py" \
            "$SCRIPT_DIR/preprocess_collages.py"; do
    if [ ! -f "$path" ]; then
        echo "ERROR: required file not found: $path"; exit 1
    fi
done

# The export job writes INPUT_CSV. On a real run it must exist, but a dry run is
# allowed to pass without it, so you can check the script before the export finishes.
if [ ! -s "$INPUT_CSV" ]; then
    if [ "$DRY_RUN" = "1" ]; then
        echo "WARNING (dry run): $INPUT_CSV not found yet; the export job creates it."
    else
        echo "ERROR: input CSV missing or empty: $INPUT_CSV (run export_input_csv_slurm.sh first)"; exit 1
    fi
fi

echo
echo "--- Step 1/3: resize raw product images ---"
run python -u "$SCRIPT_DIR/preprocess_images.py" \
    --src_dir "$RAW_DIR" \
    --dst_dir "$RESIZED_DIR" \
    --max_side "$MAX_SIDE" \
    --quality "$PREPROCESS_QUALITY" \
    --workers "$WORKERS" || { echo "Step 1 failed"; exit 1; }

echo
echo "--- Step 2/3: build collages (existing ones are skipped) ---"
run python -u "$SCRIPT_DIR/create_image_collages_dynamic.py" \
    --image-dir "$RESIZED_DIR" \
    --input "$INPUT_CSV" \
    --thumb-width "$THUMB_PX" \
    --thumb-height "$THUMB_PX" \
    --jpeg-quality "$COLLAGE_QUALITY" \
    --skip-existing || { echo "Step 2 failed"; exit 1; }

echo
echo "--- Step 3/3: compress collages into the final folder ---"
run python -u "$SCRIPT_DIR/preprocess_collages.py" \
    --src_dir "$RESIZED_DIR" \
    --dst_dir "$FINAL_DIR" \
    --max_pixels "$COMPRESS_MAX_PIXELS" \
    --quality "$COMPRESS_QUALITY" \
    --workers "$WORKERS" || { echo "Step 3 failed"; exit 1; }

echo
echo "=========================================="
echo "Image prep finished: $(date)"
echo "=========================================="
exit 0
