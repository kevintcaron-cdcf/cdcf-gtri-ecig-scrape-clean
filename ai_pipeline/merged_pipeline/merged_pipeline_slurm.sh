#!/bin/bash
#SBATCH --job-name=merged_pipeline
#SBATCH --mail-user=Nathan.Grodzinsky@gtri.gatech.edu
#SBATCH --mail-type=END,FAIL
#SBATCH --partition=all
#SBATCH --gres=gpu:1
#SBATCH --constraint=NVIDIAA100-SXM4-80GB
#SBATCH --mem=80G
#SBATCH --cpus-per-task=16
#SBATCH --time=06:00:00
#SBATCH --array=0-37
#SBATCH --output=logs/merged_pipeline_%A_%a.out
#SBATCH --error=logs/merged_pipeline_%A_%a.err

# ---------------------------------------------------------------------------
# MERGED pipeline (Old prompt base + policy_rules.py + CBD guard).
# Copy the whole "Merged Pipeline" folder to $WORKDIR/merged_pipeline/ so that
# merged_pipeline.py, merged_prompts.py and policy_rules.py sit side by side.
#
# Quick hard-case run instead of the full export:  INPUT_CSV=$WORKDIR/inputs/hard_cases.csv
# and set --array=0-0 / TOTAL_CHUNKS=1 (built with build_hard_case_subset.py).
# ---------------------------------------------------------------------------

source /opt/apps/Module/jupyterhub/2023.07/etc/profile.d/conda.sh
conda activate cdcf_new
export LD_LIBRARY_PATH=$CONDA_PREFIX/lib:$LD_LIBRARY_PATH
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

WORKDIR=/home/projects/cdcf_ecig_analysis/
PIPELINE_DIR=$WORKDIR/merged_pipeline
MODEL_DIR=$WORKDIR/Qwen3-VL-30B-A3B-Instruct
INPUT_CSV=$WORKDIR/inputs/ecig_product_full.csv
IMAGE_DIR=$WORKDIR/updated_image_collages
RESULTS_DIR=$WORKDIR/results/chunks

CHUNK_ID=$SLURM_ARRAY_TASK_ID
TOTAL_CHUNKS=${SLURM_ARRAY_TASK_COUNT:-38}
RUN_TIMESTAMP=$(scontrol show job "$SLURM_ARRAY_JOB_ID" | sed -n 's/.*SubmitTime=\([0-9T:-]*\).*/\1/p' | head -n 1 | tr -d 'T:-')
RUN_DIR="$RESULTS_DIR/merged_pipeline_run_$RUN_TIMESTAMP"

mkdir -p "$WORKDIR/logs" "$RUN_DIR"

# Move any GPU stats files out of the workspace when this task exits (success or failure).
trap 'bash "$PIPELINE_DIR/sweep_gpu_stats.sh" "$WORKDIR/gpu stats"' EXIT
cd "$WORKDIR"

echo "=========================================="
echo "Array Job ID: $SLURM_ARRAY_JOB_ID"
echo "Task ID: $CHUNK_ID (of $TOTAL_CHUNKS)"
echo "Pipeline: $PIPELINE_DIR/merged_pipeline.py"
echo "Run directory: $RUN_DIR"
echo "Started: $(date)"
echo "=========================================="

# Fail fast if the export job has not written the input yet.
if [ ! -s "$INPUT_CSV" ]; then
    echo "ERROR: input CSV missing or empty: $INPUT_CSV (run export_input_csv_slurm.sh first)"; exit 1
fi

# Guard against the earlier mix-up where the SLURM script ran a different file.
for f in merged_pipeline.py merged_prompts.py policy_rules.py; do
    if [ ! -f "$PIPELINE_DIR/$f" ]; then
        echo "ERROR: $PIPELINE_DIR/$f not found"; exit 1
    fi
done

python -u "$PIPELINE_DIR/merged_pipeline.py" \
    --model_dir  $MODEL_DIR \
    --input      $INPUT_CSV \
    --image_dir  $IMAGE_DIR \
    --output     "$RUN_DIR/pipeline_chunk_${CHUNK_ID}.csv" \
    --cbd_max_tokens 400 \
    --cls_max_tokens 300 \
    --checkpoint_interval 25 \
    --cbd_error_policy classify \
    --chunk_id $CHUNK_ID \
    --total_chunks $TOTAL_CHUNKS \
    --debug_token_accounting

EXIT_CODE=$?
echo "=========================================="
echo "Task $CHUNK_ID completed: exit code $EXIT_CODE"
echo "Finished: $(date)"
echo "Results: $RUN_DIR/pipeline_chunk_${CHUNK_ID}.csv"
echo "=========================================="
exit $EXIT_CODE
