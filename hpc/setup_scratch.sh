#!/bin/bash
# --------------------------------------------------------------------------
# One-time setup script — CUNY HPC (Arrow cluster)
#
# Run this ONCE after logging into Arrow to:
#   1. Create the scratch directory structure
#   2. Sync project code from /global to /scratch
#   3. Create a Python 3.12 virtual environment in /scratch
#   4. Install all dependencies
#
# After this, use sbatch to submit jobs. The SLURM scripts will
# automatically rsync the latest code from /global before each run.
#
# Usage (on Arrow login node, NOT via sbatch):
#   bash /global/u/prest-hc-13/Broadcasting/hpc/setup_scratch.sh
# --------------------------------------------------------------------------

set -euo pipefail

GLOBAL_DIR=/global/u/prest-hc-13/Broadcasting
SCRATCH_DIR=/scratch/prest-hc-13/Broadcasting
VENV_DIR=${SCRATCH_DIR}/.venv

echo "=========================================="
echo "CUNY HPC Scratch Setup"
echo "Global:  ${GLOBAL_DIR}"
echo "Scratch: ${SCRATCH_DIR}"
echo "=========================================="

# 1. Create scratch directory structure
echo ""
echo "[1/4] Creating scratch directories..."
mkdir -p "${SCRATCH_DIR}/slurm_logs"
mkdir -p "${SCRATCH_DIR}/results"
echo "      Done."

# 2. Sync code from global to scratch
echo ""
echo "[2/4] Syncing code from global to scratch..."
rsync -av --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
          --exclude='results' --exclude='.git' \
          "${GLOBAL_DIR}/" "${SCRATCH_DIR}/"
echo "      Done."

# 3. Load Python module and create venv
echo ""
echo "[3/4] Loading Python module and creating venv..."
module purge
module load Compilers/Python/3.12.13
echo "      Python: $(which python3) ($(python3 --version))"

if [ -d "${VENV_DIR}" ]; then
    echo "      Venv already exists at ${VENV_DIR} — skipping creation."
    echo "      (Delete ${VENV_DIR} and re-run to recreate from scratch.)"
else
    python3 -m venv "${VENV_DIR}"
    echo "      Venv created at ${VENV_DIR}"
fi

# 4. Install dependencies
echo ""
echo "[4/4] Installing dependencies into venv..."
source "${VENV_DIR}/bin/activate"
python3 -m pip install --upgrade pip
python3 -m pip install -r "${SCRATCH_DIR}/requirements.txt"
echo "      Done."

echo ""
echo "=========================================="
echo "Setup complete!"
echo ""
echo "To run jobs:"
echo "  sbatch ${SCRATCH_DIR}/hpc/slurm_hello.sh"
echo "  sbatch ${SCRATCH_DIR}/hpc/slurm_test_experiment.sh"
echo ""
echo "Results are saved to:"
echo "  ${SCRATCH_DIR}/results/   (scratch, may be purged)"
echo "  ${GLOBAL_DIR}/results/    (global, persistent)"
echo "=========================================="
