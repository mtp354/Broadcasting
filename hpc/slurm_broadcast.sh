#!/bin/bash
#SBATCH --job-name=broadcast
#SBATCH --partition=partnsf
#SBATCH --qos=qosnsf
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
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

# Create log directory if needed
mkdir -p slurm_logs

# Load modules
module purge
module load python

# Move to submission directory (project root)
cd "${SLURM_SUBMIT_DIR}"

# Activate virtual environment if present
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

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

echo "Done."
