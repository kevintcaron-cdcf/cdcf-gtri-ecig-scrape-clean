#!/bin/bash
# sweep_gpu_stats.sh
# Move dcgm-gpu-stats-*.out files out of the workspace into one folder.
# Searches the job's working directory and the sbatch submit directory.
# Usage: sweep_gpu_stats.sh [destination_dir]

DEST=${1:-/home/projects/cdcf_ecig_analysis/gpu stats}
SEARCH_DIRS=("/home/projects/cdcf_ecig_analysis" "${SLURM_SUBMIT_DIR:-$PWD}")

mkdir -p "$DEST" || exit 1
shopt -s nullglob
moved=0
for dir in "${SEARCH_DIRS[@]}"; do
    for f in "$dir"/dcgm-gpu-stats-*.out; do
        if mv -n "$f" "$DEST/"; then
            moved=$((moved + 1))
        fi
    done
done
echo "sweep_gpu_stats: moved $moved file(s) to $DEST"
