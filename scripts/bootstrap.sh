#!/usr/bin/env bash
set -euo pipefail

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

if [[ "${1:-}" == "--core" ]]; then
  python -m pip install --no-cache-dir -r requirements-core.txt pytest
  echo "Core environment ready. Install the embedding stack later with: pip install --no-cache-dir sentence-transformers==5.1.0"
else
  python -m pip install --no-cache-dir -r requirements-dev.txt
  echo "Full development environment ready."
fi
