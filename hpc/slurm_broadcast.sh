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

SCRATCH_DIR="${BROADCAST_SCRATCH_DIR:-/scratch/prest-hc-13/Broadcasting}"
GLOBAL_DIR="${BROADCAST_GLOBAL_DIR:-/global/u/prest-hc-13/Broadcasting}"
SUBMISSION_ID="${SLURM_ARRAY_JOB_ID:-${SLURM_JOB_ID:-manual_$(date +%s)_$$}}"
RESULT_DIR="${GLOBAL_DIR}/results"
mkdir -p "${RESULT_DIR}" "${SCRATCH_DIR}/slurm_logs"

module purge
module load "${BROADCAST_PYTHON_MODULE:-Compilers/Python/3.12.13}"
if [ -f "${SCRATCH_DIR}/.venv/bin/activate" ]; then
    source "${SCRATCH_DIR}/.venv/bin/activate"
else
    echo "Missing ${SCRATCH_DIR}/.venv; run hpc/setup_scratch.sh first." >&2
    exit 1
fi
export PYTHONDONTWRITEBYTECODE=1

# Bash arrays preserve each argument, including multi-sender lists. P_LIST is
# space-delimited because commas delimit sbatch --export assignments.
ARGS=(--mode "${MODE:-exact}" --M "${M:-1}" --N "${N:-2}"
      --n-samples "${N_SAMPLES:-1000}" --output-dir "${RESULT_DIR}"
      --experiment-id "${SUBMISSION_ID}"
      --linear-feedforward "${LINEAR_FEEDFORWARD:-1}")
if [ -n "${P_LIST:-}" ]; then
    read -r -a PROBABILITIES <<< "${P_LIST}"
    ARGS+=(--p-values "${PROBABILITIES[@]}")
else
    ARGS+=(--p-min "${P_MIN:-0.0}" --p-max "${P_MAX:-1.0}" --p-steps "${P_STEPS:-50}")
fi
if [ "${USE_QEC:-0}" = "1" ]; then ARGS+=(--use-qec); fi
if [ -n "${ALPHA:-}" ]; then ARGS+=(--alpha "${ALPHA}"); fi
if [ -n "${THETAS:-}" ]; then
    read -r -a PHASES <<< "${THETAS}"
    ARGS+=(--thetas "${PHASES[@]}")
fi
if [ -n "${OUTCOMES:-}" ] && [ "${OUTCOMES}" != "random" ]; then
    read -r -a BRANCHES <<< "${OUTCOMES}"
    ARGS+=(--outcomes "${BRANCHES[@]}")
else
    ARGS+=(--random-outcomes)
fi
if [ -n "${SEED:-}" ]; then ARGS+=(--seed "${SEED}"); fi
# One persistent JSON owns the frozen source/configuration and every task result.
# Source files exist only in this task's temporary runtime directory.
SNAPSHOT_ARGS=(prepare --source-dir "${GLOBAL_DIR}" --results-dir "${RESULT_DIR}"
               --submission-id "${SUBMISSION_ID}")
if [ -z "${SLURM_ARRAY_TASK_ID:-}" ]; then SNAPSHOT_ARGS+=(--single); fi
JOB_JSON="$(python "${GLOBAL_DIR}/hpc/archive.py" "${SNAPSHOT_ARGS[@]}" -- "${ARGS[@]}")"
CODE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/broadcast-runtime.XXXXXX")"
trap 'rm -rf "${CODE_DIR}"' EXIT
python "${GLOBAL_DIR}/hpc/archive.py" extract "${JOB_JSON}" "${CODE_DIR}"
cd "${CODE_DIR}"
python -m hpc.run_experiment "${ARGS[@]}" --execution-file "${JOB_JSON}"
echo "Saved self-contained job: ${JOB_JSON}"
