#!/usr/bin/env bash
# Install the tested environment or check an existing one. No experiments run.
set -euo pipefail

case "${1:-}" in
    "") INSTALL=1 ;;
    --check) INSTALL=0 ;;
    --help|-h)
        echo "Usage: bash scripts/setup.sh [--check]"
        echo "BROADCAST_PYTHON selects Python (default python3.12)."
        echo "BROADCAST_VENV selects the environment (default .venv in this checkout)."
        exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
    echo "Expected at most one argument. See --help." >&2
    exit 2
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${BROADCAST_VENV:-${PROJECT_DIR}/.venv}"
PYTHON_BIN="${BROADCAST_PYTHON:-python3.12}"
cd "${PROJECT_DIR}"

if [ "${INSTALL}" = 1 ]; then
    if [ ! -x "${VENV_DIR}/bin/python" ]; then
        "${PYTHON_BIN}" -c 'import sys; sys.exit("Python 3.12 is required for the tested environment.") if sys.version_info[:2] != (3, 12) else None'
        "${PYTHON_BIN}" -m venv "${VENV_DIR}"
    fi
    "${VENV_DIR}/bin/python" -c 'import sys; sys.exit("Use a Python 3.12 environment with requirements-tested.txt.") if sys.version_info[:2] != (3, 12) else None'
    "${VENV_DIR}/bin/python" -m pip install -r requirements-tested.txt
elif [ ! -x "${VENV_DIR}/bin/python" ]; then
    echo "Environment missing: ${VENV_DIR}. Run bash scripts/setup.sh first." >&2
    exit 1
fi

"${VENV_DIR}/bin/python" -m pip --no-cache-dir check
"${VENV_DIR}/bin/python" -m pytest -q -m "not slow"
echo "Setup verified. Activate this environment:"
printf '  source %q\n' "${VENV_DIR}/bin/activate"
echo "Next: python scripts/hardware_campaign.py plan configs/hardware_repeats.json"
