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
SUBMISSION_DIR="${SCRATCH_DIR}/submissions/${SUBMISSION_ID}"
CODE_DIR="${SUBMISSION_DIR}/source"
RESULT_DIR="${SUBMISSION_DIR}/results"
ARCHIVE_DIR="${GLOBAL_DIR}/results/submissions/${SUBMISSION_ID}"
mkdir -p "${SUBMISSION_DIR}" "${RESULT_DIR}" "${SCRATCH_DIR}/slurm_logs"

# Each submission gets its own source tree. A later submission cannot replace
# code being imported by running array tasks. Publish the snapshot only once
# the copy is complete, and make it read-only before any task uses it.
(
    flock -x 200
    if [ ! -d "${CODE_DIR}" ]; then
        STAGING_DIR="$(mktemp -d "${SUBMISSION_DIR}/.source.XXXXXX")"
        trap 'rm -rf "${STAGING_DIR}"' EXIT
        rsync -a --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
              --exclude='*.pyc' --exclude='results' --exclude='slurm_logs' \
              --exclude='submissions' --exclude='campaigns' "${GLOBAL_DIR}/" "${STAGING_DIR}/"
        REVISION="$(git -C "${GLOBAL_DIR}" rev-parse HEAD 2>/dev/null || true)"
        printf '{"submission_id":"%s","code_revision":"%s"}\n' \
               "${SUBMISSION_ID}" "${REVISION}" > "${STAGING_DIR}/source_snapshot.json"
        chmod -R a-w "${STAGING_DIR}"
        mv "${STAGING_DIR}" "${CODE_DIR}"
        trap - EXIT
    fi
    mkdir -p "${ARCHIVE_DIR}"
    if [ ! -d "${ARCHIVE_DIR}/source" ]; then
        rsync -a "${CODE_DIR}/" "${ARCHIVE_DIR}/.source/"
        mv "${ARCHIVE_DIR}/.source" "${ARCHIVE_DIR}/source"
    fi
) 200>"${SUBMISSION_DIR}/.snapshot.lock"

module purge
module load "${BROADCAST_PYTHON_MODULE:-Compilers/Python/3.12.13}"
cd "${CODE_DIR}"
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
python -m hpc.run_experiment "${ARGS[@]}"

# Preserve submission identity in persistent storage as well as in each JSON.
rsync -a --ignore-existing --include='run_*.json' --exclude='*' "${RESULT_DIR}/" "${ARCHIVE_DIR}/"
echo "Done: ${SUBMISSION_ID}"
