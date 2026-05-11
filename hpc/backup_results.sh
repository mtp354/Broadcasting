#!/bin/bash
# --------------------------------------------------------------------------
# backup_results.sh — CUNY HPC (Arrow cluster)
#
# Copies results from /scratch to /global for persistent storage.
# Run this on the Arrow login node after jobs complete.
#
# Usage:
#   bash /scratch/prest-hc-13/Broadcasting/hpc/backup_results.sh
# --------------------------------------------------------------------------

set -euo pipefail

SCRATCH_DIR=/scratch/prest-hc-13/Broadcasting
GLOBAL_DIR=/global/u/prest-hc-13/Broadcasting

echo "=========================================="
echo "Backing up results: scratch → global"
echo "From: ${SCRATCH_DIR}/results/"
echo "To:   ${GLOBAL_DIR}/results/"
echo "=========================================="

mkdir -p "${GLOBAL_DIR}/results"

rsync -av --progress \
    "${SCRATCH_DIR}/results/" \
    "${GLOBAL_DIR}/results/"

echo ""
echo "=========================================="
echo "Done. Files in global:"
ls -lh "${GLOBAL_DIR}/results/"
echo "=========================================="
