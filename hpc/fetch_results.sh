#!/usr/bin/env bash
# Run locally. Fetch completed archives without replacing existing local evidence.
set -euo pipefail

USERID="${BROADCAST_SSH_USER:-prest-hc-13}"
JUMP_HOST="${BROADCAST_JUMP_HOST:-chizen.csi.cuny.edu}"
ARROW_HOST="${BROADCAST_CLUSTER_HOST:-arrow}"
REMOTE_DIR="${BROADCAST_REMOTE_RESULTS:-/global/u/${USERID}/Broadcasting/results/records}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="${BROADCAST_LOCAL_RESULTS:-${PROJECT_DIR}/results/records}"

mkdir -p "${LOCAL_DIR}"
rsync -avz --ignore-existing --protect-args \
    -e "ssh -J ${USERID}@${JUMP_HOST}" \
    "${USERID}@${ARROW_HOST}:${REMOTE_DIR}/" "${LOCAL_DIR}/"
echo "Fetched results to ${LOCAL_DIR}; existing local files were preserved."

# Source snapshots stay outside the measured-result store.
REMOTE_EXPERIMENTS="${BROADCAST_REMOTE_EXPERIMENTS:-/global/u/${USERID}/Broadcasting/experiments/submissions}"
LOCAL_EXPERIMENTS="${BROADCAST_LOCAL_EXPERIMENTS:-${PROJECT_DIR}/experiments/submissions}"
mkdir -p "${LOCAL_EXPERIMENTS}"
rsync -avz --ignore-existing --protect-args \
    -e "ssh -J ${USERID}@${JUMP_HOST}" \
    "${USERID}@${ARROW_HOST}:${REMOTE_EXPERIMENTS}/" "${LOCAL_EXPERIMENTS}/"
echo "Fetched submission snapshots to ${LOCAL_EXPERIMENTS}."
