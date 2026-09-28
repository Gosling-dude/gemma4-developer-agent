#!/usr/bin/env bash
# Build the final submission archive: gemma4-developer-agent/submission/submission.zip
#   scripts/package_submission.sh               V1 (root agent.yaml)
#   scripts/package_submission.sh --variant v2  package a variant instead
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[[ -x $PY ]] || { echo "ERROR: run scripts/setup.sh first" >&2; exit 1; }

OUT=submission/submission.zip
echo "== cleaning stale artifacts"
rm -rf submission/build "$OUT"
find . -name "__pycache__" -type d -not -path "./.venv/*" -not -path "./evaluations/.cache/*" -prune -exec rm -rf {} +
find . -name ".DS_Store" -not -path "./.venv/*" -delete

echo "== packaging"
$PY -m g4agent.packager "$@" --compile --out "$OUT" --keep-build submission/build

echo "== independent re-check of the archive"
$PY -m g4agent.validator "$OUT" --compile | tail -3
unzip -l "$OUT" | awk 'NR>3 && $4 != "" {print "  " $4}' | grep -q '^  agent.yaml$' \
  || { echo "ERROR: agent.yaml not at archive root" >&2; exit 1; }
echo "SUBMISSION READY: $(cd submission && pwd)/submission.zip ($(du -h "$OUT" | cut -f1))"
