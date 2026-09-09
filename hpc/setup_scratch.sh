#!/usr/bin/env bash
# Run on the cluster login node; slurm_broadcast.sh snapshots each submission's code.
set -euo pipefail

GLOBAL_DIR="${BROADCAST_GLOBAL_DIR:-/global/u/prest-hc-13/Broadcasting}"
SCRATCH_DIR="${BROADCAST_SCRATCH_DIR:-/scratch/prest-hc-13/Broadcasting}"
mkdir -p "${GLOBAL_DIR}/slurm_logs" "${SCRATCH_DIR}/slurm_logs"

module purge
module load "${BROADCAST_PYTHON_MODULE:-Compilers/Python/3.12.13}"
BROADCAST_PYTHON=python BROADCAST_VENV="${SCRATCH_DIR}/.venv" \
    bash "${GLOBAL_DIR}/scripts/setup.sh"

echo "Cluster environment ready at ${SCRATCH_DIR}/.venv."
echo "See README.md for the small smoke submission and array workflow."
