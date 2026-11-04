#!/bin/bash
#SBATCH --job-name=export_ecig_product
#SBATCH --mail-user=Nathan.Grodzinsky@gtri.gatech.edu
#SBATCH --mail-type=END,FAIL
#SBATCH --partition=all
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=logs/export_ecig_product_%j.out
#SBATCH --error=logs/export_ecig_product_%j.err

# ---------------------------------------------------------------------------
# Export ecig_product from Azure SQL to $WORKDIR/inputs/ecig_product_full.csv.
# CPU only. Submit this first, then the GPU array job with a dependency:
#   EXPORT_ID=$(sbatch --parsable export_input_csv_slurm.sh)
#   sbatch --dependency=afterok:$EXPORT_ID merged_pipeline_slurm.sh
#
# DB credentials are read from DB_ENV_FILE (outside the repo, chmod 600), e.g.
#   DB_SERVER=cdcfdomestictobacco.database.windows.net
#   DB_NAME=OnlineTobaccoScrape
#   DB_USER=...
#   DB_PASSWORD='...'
# ---------------------------------------------------------------------------

source /opt/apps/Module/jupyterhub/2023.07/etc/profile.d/conda.sh
conda activate cdcf_new

WORKDIR=/home/projects/cdcf_ecig_analysis
PIPELINE_DIR=$WORKDIR/merged_pipeline
DB_ENV_FILE=${DB_ENV_FILE:-$WORKDIR/.db_env}
OUTPUT_CSV=$WORKDIR/inputs/ecig_product_full.csv

mkdir -p "$WORKDIR/logs" "$WORKDIR/inputs"
cd "$WORKDIR"

if [ ! -f "$DB_ENV_FILE" ]; then
    echo "ERROR: DB env file not found: $DB_ENV_FILE"; exit 1
fi

set -a
source "$DB_ENV_FILE"
set +a

echo "=========================================="
echo "Export job: $SLURM_JOB_ID"
echo "Output: $OUTPUT_CSV"
echo "Started: $(date)"
echo "=========================================="

python -u "$PIPELINE_DIR/export_input_csv.py" --output "$OUTPUT_CSV"
EXIT_CODE=$?

echo "=========================================="
echo "Export finished: exit code $EXIT_CODE at $(date)"
echo "=========================================="
exit $EXIT_CODE
