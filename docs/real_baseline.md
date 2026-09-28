# Real Gemma 4 baseline

## Status: TODO (blocked). No real Gemma 4 run has been executed.
There is no GPU on this machine, no model endpoint configured (`G4_API_BASE`/`G4_MODEL` unset), and no Kaggle
credentials (`~/.kaggle/kaggle.json` absent). **No real-model numbers exist, and none are reported anywhere in
this project.**

## What is ready (VERIFIED)
- `scripts/check_model_endpoint.sh`: refuses non-competition models; tool-calling smoke; prints tok/s.
  Its failure paths were tested (no config → exit 2, unreachable → 3, wrong model → 4); `run_real_eval.sh` aborts
  before evaluating anything if the check fails.
- `scripts/run_real_eval.sh`: official `swegemma` Evaluator on a packaged variant against a live endpoint;
  writes `config.json`, `task_results.jsonl`, `summary.json` and official traces to an immutable results dir.
- Kaggle path (`docs/kaggle_runtime.md`): the host's recipe plus a gold control, V0 and V1.1 in one session.
- The same official pipeline was exercised end to end with a **scripted** model (E005): compile → skills
  in the sandbox → edit → tests → review → submit → Phase-2 grading = resolved. That proves the plumbing only.

## Planned first real experiment (R001)
- Tasks: 3 official `Textualize/rich` tasks whose gold patch passes in the session (gold control), excluding
  rich_3472 and rich_3486 (reported unsolvable on py3.13).
- Variants: V0 (`variants/v0`) and V1.1 (root), same tasks, same server.
- Record per task: id, repo, start/end, model, prompt version (git rev), tools used, files inspected, commands,
  patch status, test status, failure reason, tool/LLM calls, duration. These come from `*_task_results.jsonl`
  + `python -m g4agent.traces <dir>`.

## Results table (fill only from real runs)
| Exp | Date | Variant | Model | Tasks (sound) | Resolved | Mean s/task | Mean tool calls | Cap hits | Label |
|---|---|---|---|---|---|---|---|---|---|
| R001 | – | V0 | gemma-4-31b-it-qat-w4a16-ct | – | – | – | – | – | TODO |
| R001 | – | V1.1 | gemma-4-31b-it-qat-w4a16-ct | – | – | – | – | – | TODO |
