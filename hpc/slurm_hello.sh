#!/bin/bash
#SBATCH --job-name=hello_arrow
#SBATCH --partition=partnsf
#SBATCH --qos=qosnsf
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:01:00
#SBATCH --output=slurm_logs/%j.out
#SBATCH --error=slurm_logs/%j.err
# --------------------------------------------------------------------------
# Hello-world smoke test — CUNY HPC (Arrow cluster)
#
# Validates: module loading, venv activation, Python version, Qiskit import.
#
# Usage:
#   cd /scratch/prest-hc-13/Broadcasting
#   sbatch hpc/slurm_hello.sh
# --------------------------------------------------------------------------

set -euo pipefail

SCRATCH_DIR=/scratch/prest-hc-13/Broadcasting
GLOBAL_DIR=/global/u/prest-hc-13/Broadcasting

mkdir -p "${SCRATCH_DIR}"
mkdir -p "${SCRATCH_DIR}/slurm_logs"

# Sync latest code from global storage to scratch (excludes venv and caches)
rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
      --exclude='results' \
      "${GLOBAL_DIR}/" "${SCRATCH_DIR}/"

cd "${SCRATCH_DIR}"

# Load modules
module purge
module load Compilers/Python/3.12.13

# Activate virtual environment
if [ -f "${SCRATCH_DIR}/.venv/bin/activate" ]; then
    source "${SCRATCH_DIR}/.venv/bin/activate"
else
    echo "ERROR: .venv not found. Run setup first:"
    echo "  bash /global/u/prest-hc-13/Broadcasting/hpc/setup_scratch.sh"
    exit 1
fi

echo "=========================================="
echo "Job ID:   ${SLURM_JOB_ID}"
echo "Node:     $(hostname)"
echo "Python:   $(which python)"
echo "Version:  $(python --version)"
echo "=========================================="

python -c "
import sys
print(f'Python executable: {sys.executable}')
print(f'Python version:    {sys.version}')

import numpy as np
print(f'NumPy version:     {np.__version__}')

import qiskit
print(f'Qiskit version:    {qiskit.__version__}')

print()
print('Hello from Arrow! All imports successful.')
"

echo "Done."
