#!/usr/bin/env bash
# Install the OFFICIAL harness libraries (swegemma, adk-submission, adk-eval-core) into an isolated venv.
# Source: the organizers' public Kaggle dataset metric/gemma-4-developer-agent-wheelhouse (no credentials needed).
# Only the three small harness wheels are fetched (HTTP range reads), not the 867 MB archive.
set -euo pipefail
cd "$(dirname "$0")/.."
URL="https://www.kaggle.com/api/v1/datasets/download/metric/gemma-4-developer-agent-wheelhouse"
W=evaluations/.cache/wheelhouse
V=evaluations/.cache/official_venv
.venv/bin/python -m g4agent.remote_zip "$URL" "$W" "adk_eval_core*" "adk_submission*" "swegemma*"
PY=$(command -v python3.12 || command -v python3.13 || true)
[[ -n "$PY" ]] || { echo "ERROR: need python3.12+" >&2; exit 1; }
[[ -x $V/bin/python ]] || "$PY" -m venv "$V"
$V/bin/pip install -q --upgrade pip
$V/bin/pip install -q "$W"/*.whl "google-adk==1.36.1"
shasum -a 256 "$W"/*.whl
$V/bin/pip list 2>/dev/null | grep -iE "swegemma|adk-submission|adk-eval-core|google-adk"
