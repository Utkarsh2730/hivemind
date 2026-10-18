#!/usr/bin/env bash
# Run Hivemind directly on macOS without Docker, using embedded FalkorDB (falkordblite).
# First run needs internet to install Python packages; after that it runs fully offline.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
echo "Hivemind: http://localhost:${PORT:-8000}"
exec .venv/bin/python server.py
