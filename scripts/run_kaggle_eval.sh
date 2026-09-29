#!/usr/bin/env bash
# REAL Gemma 4 evaluation on Kaggle (4x L4, official recipe, official swegemma Evaluator), end to end:
# preflight -> build notebook -> push (private) -> wait -> download raw outputs -> per-task report.
#
#   scripts/run_kaggle_eval.sh --exp-id R001-v1-smoke                         # V1.1, 3 gold-sound rich tasks
#   scripts/run_kaggle_eval.sh --exp-id R002-v0-smoke --variants v0 --n-tasks 3
#
# Credentials stay on your machine and are never printed or written to the repo. Any ONE of:
#   ~/.kaggle/kaggle.json (chmod 600)  |  KAGGLE_USERNAME + KAGGLE_KEY  |  KAGGLE_USERNAME + KAGGLE_API_TOKEN
# You must have accepted the competition rules on the website (the notebook needs its data and model).
#
# Exit codes: 2 bad args / not configured, 3 Kaggle auth or competition access failed, 4 push failed,
#             5 kernel ended in error/cancel (outputs still downloaded), 6 timed out waiting.
# No step is retried after an error: fix the cause, then rerun with a NEW --exp-id if results were written.
set -uo pipefail
cd "$(dirname "$0")/.."
EXP="" VARIANTS=(root) NTASKS=3 WAIT_H=6 POLL_S=120
while [[ $# -gt 0 ]]; do
  case "$1" in
    --exp-id) EXP=$2; shift 2;;
    --variants) shift; VARIANTS=(); while [[ $# -gt 0 && $1 != --* ]]; do VARIANTS+=("$1"); shift; done;;
    --n-tasks) NTASKS=$2; shift 2;;
    --wait-hours) WAIT_H=$2; shift 2;;
    *) echo "unknown arg $1" >&2; exit 2;;
  esac
done
[[ -n $EXP ]] || { echo "ERROR: --exp-id required" >&2; exit 2; }
OUT=evaluations/results/$EXP
[[ ! -e $OUT ]] || { echo "ERROR: $OUT exists (experiment ids are immutable)" >&2; exit 2; }
KAGGLE=.venv/bin/kaggle
[[ -x $KAGGLE ]] || { echo "ERROR: $KAGGLE missing; run scripts/setup.sh" >&2; exit 2; }

echo "== 1/6 preflight: credentials (presence only)"
USER_NAME="${KAGGLE_USERNAME:-}"
if [[ -z $USER_NAME && -f ~/.kaggle/kaggle.json ]]; then
  USER_NAME=$(.venv/bin/python -c "import json,os;print(json.load(open(os.path.expanduser('~/.kaggle/kaggle.json'))).get('username',''))")
fi
if [[ -z $USER_NAME ]] || { [[ ! -f ~/.kaggle/kaggle.json ]] && [[ -z ${KAGGLE_KEY:-} ]] && [[ -z ${KAGGLE_API_TOKEN:-} ]]; }; then
  echo "NOT CONFIGURED: no Kaggle credentials found (see header of this script / docs/kaggle_runtime.md)" >&2; exit 2
fi
echo "kaggle user: $USER_NAME"

echo "== 2/6 preflight: API auth + competition access"
if ! ACCESS=$($KAGGLE competitions files -c gemma-4-developer-agent 2>&1); then
  echo "$ACCESS" | head -5 >&2
  echo "FAIL: Kaggle API refused (bad credentials, or competition rules not accepted)" >&2; exit 3
fi
echo "$ACCESS" | head -3

echo "== 3/6 build notebook (${VARIANTS[*]}, $NTASKS tasks)"
SLUG="g4-$(echo "$EXP" | tr 'A-Z_.' 'a-z--')"
BUILD=build/kaggle_$EXP
.venv/bin/python -m g4agent.kaggle_kernel --variants "${VARIANTS[@]}" --n-tasks "$NTASKS" --slug "$SLUG" --out "$BUILD" \
  | grep -E "sha256|VALID|kernel written" || { echo "FAIL: notebook build" >&2; exit 2; }
.venv/bin/python - "$BUILD/kernel-metadata.json" "$USER_NAME" <<'EOF'
import json, sys
p, user = sys.argv[1], sys.argv[2]
m = json.load(open(p)); m["id"] = m["id"].replace("{KAGGLE_USERNAME}", user); json.dump(m, open(p, "w"), indent=2)
EOF

echo "== 4/6 push $USER_NAME/$SLUG (private, 4x L4, internet off)"
$KAGGLE kernels push -p "$BUILD" || { echo "FAIL: kernels push" >&2; exit 4; }
mkdir -p "$OUT"
cat > "$OUT/config.json" <<JSON
{"exp_id": "$EXP", "pushed_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "kernel": "$USER_NAME/$SLUG",
 "variants": "${VARIANTS[*]}", "n_tasks": $NTASKS, "model": "gemma-4-31b-it-qat-w4a16-ct",
 "git_rev": "$(git rev-parse --short HEAD)$(git diff --quiet || echo +dirty)",
 "harness": "official swegemma Evaluator, subprocess sandbox, Kaggle NvidiaL4 x4 (host Getting Started recipe)",
 "label": "REAL MODEL RUN"}
JSON

echo "== 5/6 wait (poll every ${POLL_S}s, up to ${WAIT_H}h)"
DEADLINE=$(( $(date +%s) + WAIT_H * 3600 )) STATE=""
while (( $(date +%s) < DEADLINE )); do
  S=$($KAGGLE kernels status "$USER_NAME/$SLUG" 2>&1 | tr 'A-Z' 'a-z')
  echo "$(date -u +%H:%M:%S) $S"
  case "$S" in *complete*) STATE=complete; break;; *error*|*cancel*) STATE=failed; break;; esac
  sleep "$POLL_S"
done

echo "== 6/6 download outputs -> $OUT"
$KAGGLE kernels output "$USER_NAME/$SLUG" -p "$OUT" || echo "WARN: output download failed" >&2
[[ -n $STATE ]] || { echo "TIMEOUT: kernel still running; later: $KAGGLE kernels output $USER_NAME/$SLUG -p $OUT" >&2; exit 6; }
.venv/bin/python -m g4agent.real_report "$OUT" || true
[[ $STATE == complete ]] || { echo "KERNEL FAILED: see the log in $OUT" >&2; exit 5; }
echo "done: $OUT/report.md (raw: $OUT/g4_results/)"
