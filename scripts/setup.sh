#!/usr/bin/env bash
# Create the project virtualenv and install the tooling (google-adk pinned to the harness version).
# Usage: scripts/setup.sh [--rich-env]   (--rich-env also builds the test env for Textualize/rich cases)
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  for c in python3.12 python3.13 python3.11 python3; do
    if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then PY="$c"; break; fi
  done
fi
[[ -n "$PY" ]] || { echo "ERROR: need Python >= 3.11" >&2; exit 1; }

if [[ ! -x .venv/bin/python ]]; then
  echo "creating .venv with $PY"
  "$PY" -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/pip install -q -e .
echo "tooling installed: $(.venv/bin/python -c 'import google.adk, sys; print("google-adk", google.adk.__version__, "python", sys.version.split()[0])')"

if [[ "${1:-}" == "--rich-env" ]]; then
  E=evaluations/.cache/envs/Textualize__rich
  [[ -x $E/bin/python ]] || "$PY" -m venv "$E"
  "$E/bin/pip" install -q pygments markdown-it-py pytest attrs typing_extensions
  echo "rich test env ready at $E"
fi
