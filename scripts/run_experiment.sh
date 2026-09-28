#!/usr/bin/env bash
# Run a recorded experiment. All arguments are passed to `python -m g4agent.experiment`.
#
# Pipeline self-test (no model):
#   scripts/run_experiment.sh --exp-id E000-oracle --agent oracle
# Agent run against an OpenAI-compatible Gemma 4 endpoint:
#   export G4_API_BASE=http://host:8000/v1 G4_MODEL=gemma-4-31b-it-qat-w4a16-ct G4_API_KEY=...
#   scripts/run_experiment.sh --exp-id E010-v0 --variant v0
#   scripts/run_experiment.sh --exp-id E011-v1
# With the official competition data:
#   scripts/run_experiment.sh --exp-id E020-v1 --tasks data/tasks.jsonl --data-dir data
# Compare runs:
#   .venv/bin/python -m g4agent.analysis evaluations/results/E010-v0 evaluations/results/E011-v1
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m g4agent.experiment "$@"
