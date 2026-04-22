#!/bin/bash
# --------------------------------------------------------------------------
# fetch_results.sh — run on your LOCAL machine
#
# Pulls results from Arrow /global storage to your local project folder.
# Uses chizen as a jump host (standard CUNY HPC access).
#
# Usage:
#   bash hpc/fetch_results.sh
#
# Run from the root of your local Broadcasting/ project directory.
# --------------------------------------------------------------------------

set -euo pipefail

USERID=prest-hc-13
JUMP_HOST=chizen.csi.cuny.edu
ARROW_HOST=arrow
REMOTE_DIR=/global/u/${USERID}/Broadcasting/results
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/results"

echo "=========================================="
echo "Fetching results from Arrow → local"
echo "Remote: ${REMOTE_DIR}/"
echo "Local:  ${LOCAL_DIR}/"
echo "=========================================="

mkdir -p "${LOCAL_DIR}"

rsync -avz --progress \
    -e "ssh -J ${USERID}@${JUMP_HOST}" \
    "${USERID}@${ARROW_HOST}:${REMOTE_DIR}/" \
    "${LOCAL_DIR}/"

echo ""
echo "=========================================="
echo "Done. Files in local results/:"
ls -lh "${LOCAL_DIR}/"
echo "=========================================="
