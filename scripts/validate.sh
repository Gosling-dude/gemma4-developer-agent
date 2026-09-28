#!/usr/bin/env bash
# Validate the submission. Fails loudly (non-zero exit) on any error.
#   scripts/validate.sh                 build the V1 tree in a temp dir and validate it (+ ADK compile)
#   scripts/validate.sh --variant v2    same for a variant overlay
#   scripts/validate.sh path/to.zip     validate an existing archive
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[[ -x $PY ]] || { echo "ERROR: run scripts/setup.sh first" >&2; exit 1; }

if [[ "${1:-}" == *.zip ]]; then
  echo "== validating archive $1"
  $PY -m g4agent.validator "$1" --compile
  exit $?
fi

VARIANT_ARGS=()
if [[ "${1:-}" == "--variant" ]]; then VARIANT_ARGS=(--variant "$2"); fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo "== unit tests"
$PY -m pytest -q -p no:cacheprovider tests || { echo "VALIDATION FAILED: unit tests" >&2; exit 1; }
echo "== building and validating submission tree"
$PY -m g4agent.packager ${VARIANT_ARGS[@]+"${VARIANT_ARGS[@]}"} --compile --out "$TMP/submission.zip" \
  || { echo "VALIDATION FAILED" >&2; exit 1; }
OFFICIAL=evaluations/.cache/official_venv/bin/python
if [[ -x $OFFICIAL ]]; then
  echo "== official harness check (adk-submission / swegemma from the organizers' wheelhouse)"
  $OFFICIAL scripts/official_check.py "$TMP/submission.zip" || { echo "VALIDATION FAILED: official compiler" >&2; exit 1; }
else
  echo "WARN: official harness venv missing; run scripts/setup_official_harness.sh for the authoritative check" >&2
fi
echo "VALIDATION PASSED"
