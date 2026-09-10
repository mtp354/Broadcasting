#!/usr/bin/env bash
# Run locally. Fetch validated archives and append verified HPC progress.
set -euo pipefail

USERID="${BROADCAST_SSH_USER:-prest-hc-13}"
JUMP_HOST="${BROADCAST_JUMP_HOST:-chizen.csi.cuny.edu}"
ARROW_HOST="${BROADCAST_CLUSTER_HOST:-arrow}"
REMOTE_DIR="${BROADCAST_REMOTE_RESULTS:-/global/u/${USERID}/Broadcasting/results}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="${BROADCAST_LOCAL_RESULTS:-${PROJECT_DIR}/results}"

FETCH_STAGE="$(mktemp -d "${TMPDIR:-/tmp}/broadcast-fetch.XXXXXX")"
trap 'rm -rf "${FETCH_STAGE}"' EXIT
rsync -avz --protect-args --include='*.json' --exclude='*' \
    -e "ssh -J ${USERID}@${JUMP_HOST}" \
    "${USERID}@${ARROW_HOST}:${REMOTE_DIR}/" "${FETCH_STAGE}/"
PYTHON_BIN="${BROADCAST_PYTHON:-${PROJECT_DIR}/.venv/bin/python}"
if [ ! -x "${PYTHON_BIN}" ]; then PYTHON_BIN=python3; fi
"${PYTHON_BIN}" "${PROJECT_DIR}/hpc/archive.py" merge-dir "${FETCH_STAGE}" "${LOCAL_DIR}"
echo "Fetched validated results to ${LOCAL_DIR}; existing task measurements were preserved."
