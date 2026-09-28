# Running real Gemma 4 evaluations on Kaggle

**Status: path built and tested locally up to the GPU step; not yet executed on Kaggle** (needs your Kaggle
account; 4× L4 sessions currently queue for hours).

## Can a Kaggle notebook run the agent with the real model? Yes (VERIFIED from the host's notebook)
The organizers' *Getting Started* notebook does exactly this.

| Item | Value |
|---|---|
| Accelerator | `machineShape: NvidiaL4` = **4× NVIDIA L4** (24 GB each), TP=4 |
| Internet | **off** |
| Inputs | competition `gemma-4-developer-agent`; dataset `metric/gemma-4-developer-agent-wheelhouse`; model `google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2` |
| Packages | 41 wheels from the wheelhouse (`vllm 0.19.1` patched, `swegemma 0.2.7`, `adk-submission 0.2.11`, `adk-eval-core 0.1.0`, `google-adk 1.36.1`, ...) installed with `--no-deps` |
| Server | `adk_submission.VllmServer`: `max_model_len=32768`, `tool_call_parser=gemma4`, `reasoning_parser=gemma4`, `gpu_memory_utilization=0.90`, LoRA enabled |
| Evaluator | `swegemma.evaluate.Evaluator` with `sandbox='subprocess'` (no Docker in notebooks) |
| VRAM | model ≈ 16–18 GB INT4 across 4 GPUs; the rest is KV cache (HARNESS_README) |
| GPU quota | Kaggle weekly GPU quota applies; the official notebook's own run took 944 s |

## What we generate
`python -m g4agent.kaggle_kernel --variants v0 root --n-tasks 3` writes `build/kaggle_real_eval/`:
- `g4-real-eval.ipynb`: the host's recipe, plus
  1. **gold control**: each candidate task is graded with its reference patch first (the agent never sees it);
     only tasks whose gold patch passes in this environment count. This matters because the public subprocess
     sandbox fails some FastAPI/requests gold patches (discussion 743973).
  2. each variant (V0, V1.1) on the same sound tasks, sharing one vLLM server;
  3. `/kaggle/working/g4_results/`: `*_task_results.jsonl` (start/end, resolved, exit code, tool calls,
     LLM calls, duration, patch files, error), `summary.json`, `tool_calls_digest.json`, official traces, and
     `g4_results_bundle.zip`.
- `kernel-metadata.json`: exactly the host notebook's sources and machine shape; private kernel.

Tested locally (the notebook's real cells, under the official harness, with a scripted endpoint in place of the vLLM
cell): gold control 6/6, both variants run, and all result files are written. **Not tested:** the wheel-install and vLLM
cells, which are copied from the host notebook.

## Steps (you run these; credentials stay on your machine)
1. Accept the competition rules on the website (needed for the data and model).
2. Create a Kaggle API token and put it at `~/.kaggle/kaggle.json` (chmod 600), or export
   `KAGGLE_USERNAME` / `KAGGLE_KEY` in your shell. **Never commit it** (`.gitignore` covers `kaggle.json` and `.env`).
3. Build and push:
   ```bash
   .venv/bin/python -m g4agent.kaggle_kernel --variants v0 root --n-tasks 3
   sed -i '' "s/{KAGGLE_USERNAME}/$KAGGLE_USERNAME/" build/kaggle_real_eval/kernel-metadata.json
   .venv/bin/kaggle kernels push -p build/kaggle_real_eval
   .venv/bin/kaggle kernels status $KAGGLE_USERNAME/g4-real-eval
   ```
4. When it completes:
   ```bash
   .venv/bin/kaggle kernels output $KAGGLE_USERNAME/g4-real-eval -p evaluations/results/R001-kaggle-v0-v1-smoke
   ```
   Then record it in `docs/real_baseline.md` (template there).

## What can be tested where
| Where | What |
|---|---|
| This laptop (no GPU) | Official validation/compile of every variant; official Evaluator gold/empty controls; the full official pipeline with a scripted model (skills, tools, patch, grading); localization benchmark; unit tests |
| Kaggle 4× L4 notebook | **Real Gemma 4 runs** (smoke, V0 vs V1, ablations), decode speed, per-task durations, the cap-hit fraction |
| Any GPU host with ≥ ~40 GB VRAM total (e.g. 1× A100 80G, 2× L40S) | the same via `scripts/run_real_eval.sh` against your own vLLM server (`G4_API_BASE`, `G4_MODEL`) |
| Kaggle submission (1/day) | The true hidden-test score |

## Alternative: your own vLLM server
```bash
export G4_API_BASE=http://<host>:8000/v1 G4_MODEL=gemma-4-31b-it-qat-w4a16-ct   # + G4_API_KEY if needed
scripts/check_model_endpoint.sh                       # reachability, model name, tool-call smoke, tok/s
scripts/run_real_eval.sh --exp-id R002-v1-smoke --n 3
scripts/run_real_eval.sh --exp-id R003-v0-smoke --n 3 --variant v0
```
Serve the model like the host does (vLLM 0.19.1 from the wheelhouse, `--tool-call-parser gemma4
--reasoning-parser gemma4 --enable-auto-tool-choice --max-model-len 32768`). Otherwise tool calls won't parse.
