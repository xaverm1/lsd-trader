#!/usr/bin/env bash
# One-shot setup for a fresh (cloud) checkout: install, fetch the private data repo, check.
# Usage: bash scripts/cloud_setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY=""
for c in python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 12))'; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || { echo "Need Python >= 3.12"; exit 1; }
"$PY" -m venv .venv
.venv/bin/pip install -q -e ".[dev]"

if [ ! -d data/histdata ]; then
  git clone -q https://github.com/xaverm1/lsd-trader-data.git data \
    || { echo "Could not clone xaverm1/lsd-trader-data (private). Grant access or download from HistData."; exit 1; }
fi
ls data/histdata | grep -c XAUUSD | xargs echo "XAUUSD year files:"
.venv/bin/pytest -q
