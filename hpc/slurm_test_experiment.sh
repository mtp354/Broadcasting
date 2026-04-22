#!/bin/bash
#SBATCH --job-name=broadcast_test
#SBATCH --partition=partnsf
#SBATCH --qos=qosnsf
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --output=slurm_logs/%j.out
#SBATCH --error=slurm_logs/%j.err
# --------------------------------------------------------------------------
# Minimal experiment test — CUNY HPC (Arrow cluster)
#
# Runs the smallest possible exact-mode experiment:
#   M=1 sender, N=2 receivers, 5 noise points, no QEC
#
# This exercises the full pipeline (state prep → noise → fidelity → save)
# with negligible compute cost.
#
# Usage:
#   cd /scratch/prest-hc-13/Broadcasting
#   sbatch hpc/slurm_test_experiment.sh
# --------------------------------------------------------------------------

set -euo pipefail

SCRATCH_DIR=/scratch/prest-hc-13/Broadcasting
GLOBAL_DIR=/global/u/prest-hc-13/Broadcasting

mkdir -p "${SCRATCH_DIR}"
mkdir -p "${SCRATCH_DIR}/slurm_logs"
mkdir -p "${SCRATCH_DIR}/results"

# Sync latest code from global storage to scratch (excludes venv and caches)
rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
      --exclude='results' \
      "${GLOBAL_DIR}/" "${SCRATCH_DIR}/"

cd "${SCRATCH_DIR}"

# Load modules
module purge
module load Compilers/Python/3.12.13

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "ERROR: .venv not found. Run the hello-world test first."
    exit 1
fi

echo "=========================================="
echo "Job ID:      ${SLURM_JOB_ID}"
echo "Node:        $(hostname)"
echo "Working dir: $(pwd)"
echo "Python:      $(which python3)"
echo "=========================================="

echo ""
echo "--- Running minimal exact experiment ---"
echo "    M=1, N=2, p_steps=5, no QEC"
echo ""

python3 -m hpc.run_experiment \
    --mode exact \
    --M 1 \
    --N 2 \
    --p-steps 5 \
    --seed 42 \
    --output-dir results

echo ""
echo "--- Verifying output ---"
LATEST=$(ls -t results/*.json 2>/dev/null | head -1)
if [ -n "${LATEST}" ]; then
    echo "Result file: ${LATEST}"
    echo "File size:   $(wc -c < "${LATEST}") bytes"
    echo "First 5 lines:"
    head -5 "${LATEST}"
    echo ""
    echo "SUCCESS: Experiment pipeline completed."
else
    echo "ERROR: No result JSON found in results/"
    exit 1
fi

# Archive results back to persistent global storage
rsync -a "${SCRATCH_DIR}/results/" "${GLOBAL_DIR}/results/"

echo "Done."
