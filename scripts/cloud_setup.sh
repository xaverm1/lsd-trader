#!/usr/bin/env bash
# One-shot setup for a fresh (cloud) checkout: install, fetch the private data repo, check.
# Usage: bash scripts/cloud_setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
.venv/bin/pip install -q -e ".[dev]"

if [ ! -d data/histdata ]; then
  git clone -q https://github.com/xaverm1/lsd-trader-data.git data \
    || { echo "Could not clone xaverm1/lsd-trader-data (private). Grant access or download from HistData."; exit 1; }
fi
ls data/histdata | grep -c XAUUSD | xargs echo "XAUUSD year files:"
.venv/bin/pytest -q
