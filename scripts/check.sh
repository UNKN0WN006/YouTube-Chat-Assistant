#!/usr/bin/env bash
set -euo pipefail

python -m compileall -q app run.py
python -m pytest -q
node --check static/app.js
node --check extension/content.js
node --check extension/background.js

echo "All local checks passed."
