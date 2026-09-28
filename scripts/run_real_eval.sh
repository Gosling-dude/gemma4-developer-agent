#!/usr/bin/env bash
# REAL evaluation: the official swegemma Evaluator runs a packaged variant against a live model endpoint.
# It never fabricates results: it aborts if the endpoint check fails, and results are written only by the harness.
#
#   export G4_API_BASE=http://<vllm-host>:8000/v1 G4_MODEL=gemma-4-31b-it-qat-w4a16-ct
#   scripts/run_real_eval.sh --exp-id R001-v1-smoke [--variant v0] [--data DIR] [--ids rich_4077 ...] [--n 3]
#
# --data defaults to evaluations/.cache/official_local (our 12 rich cases, official layout, no graphs).
# With the official data (after accepting the rules): --data data  (tasks.jsonl, snapshots/, graphs/, ...).
# Without a local GPU endpoint, use the Kaggle path instead: docs/kaggle_runtime.md.
set -euo pipefail
cd "$(dirname "$0")/.."
EXP="" VARIANT="" DATA=evaluations/.cache/official_local N=3 IDS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --exp-id) EXP=$2; shift 2;;
    --variant) VARIANT=$2; shift 2;;
    --data) DATA=$2; shift 2;;
    --n) N=$2; shift 2;;
    --ids) shift; while [[ $# -gt 0 && $1 != --* ]]; do IDS+=("$1"); shift; done;;
    *) echo "unknown arg $1" >&2; exit 2;;
  esac
done
[[ -n $EXP ]] || { echo "ERROR: --exp-id required" >&2; exit 2; }
OUT=evaluations/results/$EXP
[[ ! -e $OUT ]] || { echo "ERROR: $OUT exists (experiment ids are immutable)" >&2; exit 2; }
OFF=evaluations/.cache/official_venv/bin/python
[[ -x $OFF ]] || { echo "ERROR: run scripts/setup_official_harness.sh first" >&2; exit 2; }
[[ -f $DATA/tasks.jsonl ]] || { echo "ERROR: $DATA/tasks.jsonl missing" >&2; exit 2; }

echo "== 1/3 endpoint check"
scripts/check_model_endpoint.sh || { echo "ABORT: endpoint check failed; nothing was evaluated" >&2; exit 3; }

echo "== 2/3 packaging ${VARIANT:-root (V1.1)}"
mkdir -p "$OUT"
.venv/bin/python -m g4agent.packager ${VARIANT:+--variant "$VARIANT"} --out "$OUT/submission.zip" --keep-build "$OUT/submission" >/dev/null
if [[ ${#IDS[@]} -eq 0 ]]; then
  IDS=($(.venv/bin/python -c "import json,sys; print(' '.join(json.loads(l)['instance_id'] for l in list(open('$DATA/tasks.jsonl'))[:$N]))"))
fi
cat > "$OUT/config.json" <<JSON
{"exp_id": "$EXP", "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "variant": "${VARIANT:-root}",
 "model": "$G4_MODEL", "api_base_host": "$(echo "$G4_API_BASE" | sed -E 's#^[a-z]+://##; s#/.*##')",
 "noncompetition_model": $([[ "$G4_MODEL" == *gemma-4-31b-it-qat-w4a16-ct* ]] && echo false || echo true),
 "data": "$DATA", "tasks": "$(echo "${IDS[@]}")", "git_rev": "$(git rev-parse --short HEAD)$(git diff --quiet || echo +dirty)",
 "harness": "official swegemma (subprocess sandbox)", "label": "REAL MODEL RUN"}
JSON

echo "== 3/3 official evaluator on: ${IDS[*]}"
$OFF scripts/official_pipeline_test.py --submission "$OUT/submission" --data "$DATA" --ids "${IDS[@]}" --out "$OUT"
echo "results: $OUT/summary.json  $OUT/task_results.jsonl  (traces: $OUT/official/traces)"
