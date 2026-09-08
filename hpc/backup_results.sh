#!/bin/bash
# Copy completed immutable result records and their submission source snapshots
# from scratch to persistent storage. Legacy top-level results remain supported.
set -euo pipefail
SCRATCH_DIR="${BROADCAST_SCRATCH_DIR:-/scratch/prest-hc-13/Broadcasting}"
GLOBAL_DIR="${BROADCAST_GLOBAL_DIR:-/global/u/prest-hc-13/Broadcasting}"
mkdir -p "${GLOBAL_DIR}/results"
if [ -d "${SCRATCH_DIR}/results" ]; then
    rsync -a --include='run_*.json' --exclude='*' "${SCRATCH_DIR}/results/" "${GLOBAL_DIR}/results/"
fi
shopt -s nullglob
for SUBMISSION_DIR in "${SCRATCH_DIR}"/submissions/*; do
    [ -d "${SUBMISSION_DIR}/results" ] || continue
    ARCHIVE_DIR="${GLOBAL_DIR}/results/submissions/$(basename "${SUBMISSION_DIR}")"
    mkdir -p "${ARCHIVE_DIR}"
    rsync -a --include='run_*.json' --exclude='*' "${SUBMISSION_DIR}/results/" "${ARCHIVE_DIR}/"
    if [ -d "${SUBMISSION_DIR}/source" ] && [ ! -d "${ARCHIVE_DIR}/source" ]; then
        rsync -a "${SUBMISSION_DIR}/source/" "${ARCHIVE_DIR}/source/"
    fi
done
echo "Archived completed runs to ${GLOBAL_DIR}/results/"
