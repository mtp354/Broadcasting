#!/bin/bash
# Optional backup of standalone scratch results. SLURM job JSONs are already
# written atomically to persistent GLOBAL_DIR/results by the submission script.
set -euo pipefail
SCRATCH_DIR="${BROADCAST_SCRATCH_DIR:-/scratch/prest-hc-13/Broadcasting}"
GLOBAL_DIR="${BROADCAST_GLOBAL_DIR:-/global/u/prest-hc-13/Broadcasting}"
mkdir -p "${GLOBAL_DIR}/results"
if [ -d "${SCRATCH_DIR}/results" ]; then
    rsync -a --ignore-existing --include='*.json' --exclude='*' "${SCRATCH_DIR}/results/" "${GLOBAL_DIR}/results/"
fi
echo "Archived self-contained JSON records to ${GLOBAL_DIR}/results/"
