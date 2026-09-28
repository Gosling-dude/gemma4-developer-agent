# Getting started (from zero)

This is a beginner's walkthrough of the competition and of this project. Nothing is assumed.

## 1. What is this competition?
Google and Kaggle want an **AI coding agent** that runs on modest hardware and fixes real bugs.
You don't submit code that fixes bugs. You submit a **configuration** that tells an AI model *how to behave
as a software engineer*. Kaggle then runs your agent on about 120 hidden bug reports from private Python
repositories. Each fix is checked with hidden tests. Your score is the fraction of bugs fixed.

- The model is fixed: **Gemma 4, variant `gemma-4-31b-it-qat-w4a16-ct`** (31B parameters, quantized to
  4-bit weights). You can't swap in a different model. You can optionally add a small fine-tuned "LoRA" layer on top of it.
- Deadline: final submission by **2 Dec 2026** (entry and team merge by 25 Nov).

## 2. Key concepts
- **Agent:** a loop in which the model looks at the situation, picks a *tool* (run a command, read a file,
  edit a file...), sees the result, and repeats until it's done. Our agent is a disciplined engineer:
  find the code, reproduce the bug, make a small edit, test it, review it, submit.
- **Gemma:** Google's family of open-weight models. Gemma 4 31B is the one we must use.
- **ADK (Agent Development Kit):** Google's Python framework for agents. The competition uses ADK
  (version 1.36.1) to turn your YAML files into a running agent.
- **agent.yaml:** the root of your submission. It names the model, the system prompt (`instruction`), the tools,
  the skills and the sampling settings. `!include path` pulls another file in, so prompts can live in `.md` files.
- **Harness:** Kaggle's program that runs everything. For each task it copies the repo into a sandbox at
  `/workspace`, starts your agent with the bug report, gives it 9 tools, stops it when budgets run out,
  and collects `git diff` as your patch.
- **SWE-style evaluation (as in SWE-bench):** your patch is applied to a *fresh* copy of the repo, the hidden tests
  are added, and pytest runs. All required tests must pass, or the task scores 0. No partial credit.
- **Tools** (provided by the harness): `run_command`, `read_file`, `edit_file`, `write_file`, `get_status`,
  `submit_patch`, and three code-graph tools, `get_code_neighbors`, `search_similar_code` and `get_code_subgraph`,
  which query a pre-built call graph of the repository.
- **Skills:** folders with a `SKILL.md` manual plus helper Python scripts the agent can run with
  `run_skill_script`. Ours bundle several searches or test runs into a single call.
- **LoRA:** a small add-on weight file that fine-tunes the model's behaviour. Optional here. We haven't
  trained one yet (see `experiments/lora/README.md`).
- **Budgets:** the whole run gets **12 hours**, so each task gets only a few minutes. We set 4.5 min per task in
  `eval_config.yaml`. This constraint shaped the whole design: a fast, focused agent beats a slow, thorough one.

## 3. Project tour
| Path | What it is |
|---|---|
| `agent.yaml`, `eval_config.yaml`, `configs/`, `prompts/system.md`, `skills/` | **The submission (V1)** |
| `variants/` | Alternative versions (V0 baseline, V2 with sub-agents, a no-graph ablation) for experiments |
| `sub_agents/`, `prompts/*analyzer*.md` ... | Specialist agents used by V2 |
| `src/g4agent/` | Local tooling: validator, packager, a local copy of the harness, experiment runner |
| `tests/` | Unit and integration tests for all of the above |
| `evaluations/` | Test cases, experiment results, analyses |
| `docs/` | Notes on the competition, architecture, experiments and submission |
| `submission/submission.zip` | The file you upload |

## 4. Run it
```bash
cd gemma4-developer-agent
scripts/setup.sh                       # creates .venv, installs google-adk 1.36.1 and tooling
scripts/validate.sh                    # runs 50+ tests and validates the submission
scripts/package_submission.sh          # builds submission/submission.zip
```

## 5. Run an experiment
Without a model (checks the pipeline itself):
```bash
scripts/setup.sh --rich-env            # Python env for the local 'rich' test cases
scripts/run_experiment.sh --exp-id E000-oracle --agent oracle   # should resolve 100%
.venv/bin/python -m g4agent.localization                         # how well our search finds the right file
```
With a model: you need an OpenAI-compatible endpoint serving Gemma 4. The best option is the competition model on
vLLM with a GPU (Kaggle notebooks, a cloud VM). Then:
```bash
export G4_API_BASE=http://<server>:8000/v1 G4_MODEL=gemma-4-31b-it-qat-w4a16-ct
scripts/run_experiment.sh --exp-id E010-v0 --variant v0
scripts/run_experiment.sh --exp-id E011-v1
.venv/bin/python -m g4agent.analysis evaluations/results/E010-v0 evaluations/results/E011-v1
```
With the official data (after accepting the rules and setting up Kaggle credentials):
```bash
.venv/bin/kaggle competitions download -c gemma-4-developer-agent -f tasks.jsonl -p data
scripts/run_experiment.sh --exp-id E020 --tasks data/tasks.jsonl --data-dir data
```

## 6. Submit
Upload `submission/submission.zip` on the competition's "Submit Predictions" page. See `docs/submission.md`.

## 7. Assumptions to know about
- The 12 h budget may be shared sequentially across tasks. We *assume the worst case*. If Kaggle runs
  tasks in parallel, more time per task would be affordable.
- The official harness source isn't public. Our local harness follows its documentation closely but isn't
  identical (see `docs/architecture.md` §3).
- No real model has been run from this machine yet, so there is **no measured resolution rate**. See `docs/experiments.md`.
