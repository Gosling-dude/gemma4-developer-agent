# Real Gemma 4 baseline

## Status: TODO (blocked). No real Gemma 4 run has been executed.
**No real-model numbers exist, and none are reported anywhere in this project.**

### R001-v1-smoke, attempt 1 (2026-09-29): blocked before any task ran
Raw record: `evaluations/attempts/R001-v1-smoke_attempt1_2026-09-29.json`. Tasks executed: **0**. Model calls: **0**.

| Check | Result |
|---|---|
| V1.1 package (`scripts/validate.sh`) | PASSED: 64 tests, strict + ADK + **official** validate/compile; zip sha256 `24b3fab0…` (unchanged since ce40a96) |
| Kaggle API credentials | **absent** (`~/.kaggle/kaggle.json` missing; `KAGGLE_USERNAME`/`KAGGLE_KEY`/`KAGGLE_API_TOKEN` unset) |
| Kaggle web session via browser | **unavailable** (Claude-in-Chrome extension not connected) |
| Own endpoint (`G4_API_BASE`) | unset |
| Local GPU | none (Apple M5, 16 GB unified memory) |

Fallbacks considered and rejected: local inference (the W4A16 31B weights, about 17–18 GB, don't fit in 16 GB, and
there's no vLLM with the `gemma4` tool parser); a hosted Gemma API (not the competition checkpoint or serving stack,
and it needs a third-party key, so at best EXPERIMENTAL). Neither was run.

**Blocker:** one credential only you can provide: a Kaggle API token for an account that has accepted the
competition rules. Nothing else is missing.

### How to unblock (one command)
```bash
# credentials stay local: ~/.kaggle/kaggle.json (chmod 600) or export KAGGLE_USERNAME=... KAGGLE_KEY=...
scripts/run_kaggle_eval.sh --exp-id R001-v1-smoke
```
The script checks credentials and competition access, then builds a private 4× L4 notebook embedding the unchanged V1.1
zip. That notebook uses the host's recipe, the official `swegemma` Evaluator, and a gold control that picks 3 sound
`Textualize/rich` tasks. The script pushes the notebook, waits for it, downloads the raw outputs to
`evaluations/results/R001-v1-smoke/`, and writes `report.md`/`report.json` (`python -m g4agent.real_report`).
It never retries after an error; each failure has its own exit code (see the script header).

## What is ready (VERIFIED)
- `scripts/run_kaggle_eval.sh`: preflight → build → push → wait → download → report. The preflight's failure path was
  tested here (no credentials → exit 2, no results dir created). **The push and GPU steps were not tested.**
- Notebook records per task: id, repo, start/end, duration, resolved, harness status, error, tool calls, LLM calls,
  total tokens, full patch, and the official trace path. `record()` was checked against the official `TaskResult`.
- `g4agent.real_report`: per task: runtime, tokens (total, plus prompt/output from traces), tool calls, files
  inspected, files edited, tests run, patch status, PASS/FAIL, failure category (cap_hit / agent_or_infra_error /
  no_patch / only_test_or_config_edits / wrong_fix). Unit-tested on a synthetic Kaggle-shaped directory.
- `scripts/check_model_endpoint.sh` + `scripts/run_real_eval.sh`: the same with your own vLLM server.
- The official pipeline end to end with a **scripted** model (E005/E006). This proves the plumbing only.

## R001 protocol (unchanged)
- Tasks: 3 official `Textualize/rich` tasks whose gold patch passes in the session (gold control), excluding
  rich_3472 and rich_3486 (reported unsolvable on py3.13).
- Agent: V1.1 exactly as committed (git tag `v1.1-baseline`), no optimization.
- Labels: VERIFIED if the notebook completes with the official harness and the competition model; EXPERIMENTAL if any
  component is non-official; TODO if blocked. Never reported as a competition score.

## Results table (fill only from real runs)
| Exp | Date | Variant | Model | Tasks (sound) | Resolved | Mean s/task | Mean tool calls | Cap hits | Label |
|---|---|---|---|---|---|---|---|---|---|
| R001-v1-smoke | 2026-09-29 (attempt 1) | V1.1 | gemma-4-31b-it-qat-w4a16-ct | 0 run | – | – | – | – | TODO (blocked: no Kaggle credentials) |
| R00x | – | V0 | gemma-4-31b-it-qat-w4a16-ct | – | – | – | – | – | TODO |
