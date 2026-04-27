#!/bin/bash
#SBATCH --job-name=broadcast
#SBATCH --partition=partnsf
#SBATCH --qos=qosnsf
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem=128G
#SBATCH --time=04:00:00
#SBATCH --output=slurm_logs/%A_%a.out
#SBATCH --error=slurm_logs/%A_%a.err
# --------------------------------------------------------------------------
# Quantum broadcasting protocol — CUNY HPC (Arrow cluster)
#
# Usage:
#   # Single run
#   sbatch hpc/slurm_broadcast.sh
#
#   # Sweep over 50 noise values (one per task)
#   sbatch --array=0-49 hpc/slurm_broadcast.sh
#
#   # Sweep with concurrency limit
#   sbatch --array=0-49%10 hpc/slurm_broadcast.sh
# --------------------------------------------------------------------------

set -euo pipefail

SCRATCH_DIR=/scratch/prest-hc-13/Broadcasting
GLOBAL_DIR=/global/u/prest-hc-13/Broadcasting

# Create log directory if needed
mkdir -p "${SCRATCH_DIR}/slurm_logs"

# Sync latest code from global storage to scratch (excludes venv and caches)
rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
      --exclude='results' \
      "${GLOBAL_DIR}/" "${SCRATCH_DIR}/"

# Load modules
module purge
module load Compilers/Python/3.12.13

# Move to project directory on scratch
cd "${SCRATCH_DIR}"

# Activate virtual environment if present
if [ -f "${SCRATCH_DIR}/.venv/bin/activate" ]; then
    source "${SCRATCH_DIR}/.venv/bin/activate"
fi

echo "Python:        $(which python)"

echo "=========================================="
echo "Job ID:        ${SLURM_JOB_ID}"
echo "Array Task ID: ${SLURM_ARRAY_TASK_ID:-N/A}"
echo "Node:          $(hostname)"
echo "Working dir:   $(pwd)"
echo "Python:        $(which python)"
echo "=========================================="

# --- Configure experiment parameters here ---
MODE="${MODE:-exact}"
M="${M:-1}"
N="${N:-2}"
P_STEPS="${P_STEPS:-50}"
USE_QEC="${USE_QEC:-}"

QEC_FLAG=""
if [ -n "${USE_QEC}" ]; then
    QEC_FLAG="--use-qec"
fi

python -m hpc.run_experiment \
    --mode "${MODE}" \
    --M "${M}" \
    --N "${N}" \
    --p-steps "${P_STEPS}" \
    ${QEC_FLAG} \
    --output-dir results

# Archive results back to persistent global storage
rsync -a "${SCRATCH_DIR}/results/" "${GLOBAL_DIR}/results/"

echo "Done."
