# Gemma 4 Developer Agent: competition submission

An autonomous software-engineering agent for **Google – The Gemma 4 Developer Agent Competition**
(Kaggle, 2026). The agent runs on `gemma-4-31b-it-qat-w4a16-ct`, fixes Python issues inside the official
sandbox, and is graded SWE-bench style: the patch has to make hidden tests pass.

> New to this? Start with [docs/getting_started.md](docs/getting_started.md).

**Status (2026-09-28, session 2):** current version **V1.1** (`submission/submission.zip`). It passes the
**official** harness's validation and compilation (swegemma 0.2.7 / adk-submission 0.2.11 from the organizers'
wheelhouse) and runs end to end in the official Evaluator with a scripted model. **It has never been run with the real
Gemma 4 model, and nothing has been submitted to Kaggle**: this machine has no GPU and no credentials. A ready
real-evaluation path exists (Kaggle 4× L4 notebook or your own vLLM server). See [docs/real_baseline.md](docs/real_baseline.md).

Session-2 fixes found by checking against the official harness: skill scripts saw an empty directory in the
official subprocess sandbox; `timeout_seconds: 120` would also have capped the grading test run; V2's sub-agent
skill paths were rejected by the official compiler; and `thinking_budget` is never enforced, so thinking is now off.
Details: [docs/v1_baseline.md](docs/v1_baseline.md).

## Official links
[Overview](https://www.kaggle.com/competitions/gemma-4-developer-agent/overview) ·
[Data](https://www.kaggle.com/competitions/gemma-4-developer-agent/data) ·
[Rules](https://www.kaggle.com/competitions/gemma-4-developer-agent/rules) ·
[Code](https://www.kaggle.com/competitions/gemma-4-developer-agent/code) ·
[Models](https://www.kaggle.com/competitions/gemma-4-developer-agent/models) ·
[Leaderboard](https://www.kaggle.com/competitions/gemma-4-developer-agent/leaderboard) ·
[Discussion](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion) ·
[Paper track](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper)

## Quick start
```bash
scripts/setup.sh                    # .venv with google-adk==1.36.1 (the harness version) + tooling
scripts/setup_official_harness.sh   # official swegemma/adk-submission wheels into an isolated venv (no login)
scripts/validate.sh                 # tests + strict validation + ADK compile + OFFICIAL compile
scripts/package_submission.sh       # -> submission/submission.zip
# real Gemma 4 (needs a GPU endpoint; see docs/kaggle_runtime.md):
scripts/check_model_endpoint.sh && scripts/run_real_eval.sh --exp-id R001-v1-smoke --n 3
```

## The competition in five lines
- Input: an issue text plus a repository snapshot at `/workspace` (offline sandbox, 4 GiB RAM, 2 vCPU).
- Output: a git diff. It's applied to a fresh copy, hidden tests are added, and the task counts only if all required tests pass.
- Only `gemma-4-31b-it-qat-w4a16-ct`, served by vLLM (32k context) on 4× L4. Optional LoRA adapters.
- Submission = declarative ADK YAML (`agent.yaml`, prompts, skills, sub-agents, adapters). No Python entry point.
- **12 hours for about 120 tasks**, setup included. This budget drives most of the design.

Full research notes, with a provenance label on every claim: [docs/competition_notes.md](docs/competition_notes.md).

## Architecture (V1)
One disciplined coder agent, all 9 harness tools, and 3 skills whose Python scripts compress several steps
into one tool call:

```
issue ─► UNDERSTAND ─► LOCATE ─────────► READ ──────► REPRODUCE ─► HYPOTHESIS ─► EDIT ─► VERIFY ─► REVIEW ─► SUBMIT
         (prompt)      nav.py find       nav.py show   /tmp repro   one sentence   edit_file tests.py   review.py  submit_patch
                       (+graph tools     read_file     diagnose.py                          related/run
                        when the cause                                   ▲                        │
                        spans functions)                                 └── repair loop ◄────────┘ (≤3 rounds/hypothesis)
```

| Component | File | What it does |
|---|---|---|
| Root agent | `agent.yaml` | model, 9 tools, 3 skills, sampling |
| System prompt | `prompts/system.md` | step-by-step workflow with call budgets, hard rules (no test edits, /tmp scratch, edit early), repair and budget discipline |
| Budgets | `eval_config.yaml` | 5.0 min, 60 calls, 80 turns, 300 s per command (also caps grading); 10.9 h worst case for 125 tasks ([budget model](docs/budget_model.md)) |
| Sampling | `configs/sampling.yaml` | temperature 0.3, top_p 0.95, top_k 64, max output 6144, **thinking off** (the harness never enforces a thinking budget) |
| repo-navigation | `skills/repo-navigation/` | `find` ranks files for issue terms (IDF + definition boost, related tests); `show` prints numbered source of a symbol; `outline`, `usages`, `layout` |
| test-discovery | `skills/test-discovery/` | `related` maps a file or symbol to tests and test functions; `run` gives a condensed pytest report and refuses full-suite runs |
| debugging | `skills/debugging/` | `diagnose` shows the innermost *repository* frames of a traceback; `review` shows the exact diff and flags stray files, protected-file edits, debug prints, syntax errors, empty diffs |

Details and design rationale: [docs/architecture.md](docs/architecture.md).

### Tool strategy
- Skills first, because they cost 1 call for what would otherwise take 3–6 raw calls.
- `read_file` only for narrow ranges that `show` can't reach, since its output is capped at 150 lines.
- Graph tools **only when the cause spans functions**: `get_code_neighbors` for callers or callees of a
  symbol about to change, `search_similar_code` (symbol names, not sentences) for twin implementations such as
  sync/async. Each graph call costs budget, so they have to replace at least two greps or reads.
- `get_status` and `submit_patch` are free. `get_status` is checked about 10 calls in.

### Testing strategy
Reproduce in `/tmp` → targeted related tests → repair → rerun → broader related tests. Full-suite runs
are forbidden (they can use up the whole task budget). Test files are never edited (the grader resets them).

### Sub-agents
`sub_agents/` has four specialists (code_analyzer, patch_reviewer, test_analyzer, debugger), each with a
structured-output prompt. They are **off in V1**: each delegation is a separate model loop, and time per task
is the binding constraint. `variants/v2` enables code_analyzer and patch_reviewer to measure the trade-off.

## Versions
| Version | Location | Description |
|---|---|---|
| V0 | `variants/v0/` | Baseline: 9 tools, 5-line generic prompt, no skills |
| V1_BASELINE | git tag `v1-baseline`; `variants/v1_baseline/` | First version (thinking on, 4.5 min, 120 s timeout); see docs/v1_baseline.md |
| **V1.1** | root | Current: V1 + thinking off, 5.0-min cap, 300 s timeout, anti-repetition rule, sandbox-safe skills |
| Ablations | `variants/v1_nograph`, `v1_noskills`, `v1_oldloc`, `v1_think` | One variable each (docs/experiments.md §C) |
| V2 | `variants/v2/` | V1.1 + code_analyzer and patch_reviewer AgentTools |

## Results
The canonical score table is in [docs/experiments.md](docs/experiments.md). Summary:
- **Real Gemma 4 resolution rate: not measured (TODO).** **Kaggle leaderboard: nothing submitted.**
- Grading controls, local grader and **official** grader on 12 verified `rich` cases: empty 0/12, reference 12/12 (VERIFIED).
- Official harness + scripted model: V1.1 skills run inside the sandbox; patch resolved (pipeline test, VERIFIED).
- Localization benchmark (n=12, no LLM): `nav.py` recall@1 0.50 vs grep 0.08; reproduced exactly (EXPERIMENTAL; the
  similarity-search part is downgraded, see §B).
- Public context: top public LB score is 0.15 (≈ 9/58); the best public notebooks score 0.10–0.12 ([docs/public_research.md](docs/public_research.md)).

## Reproducing
```bash
scripts/setup.sh --rich-env
.venv/bin/python -m g4agent.cases --repo Textualize/rich --max-cases 12     # rebuild local cases (network + gh)
scripts/run_experiment.sh --exp-id <new-id> --agent oracle                   # pipeline self-test
.venv/bin/python -m g4agent.localization                                      # localization benchmark
# with a Gemma 4 endpoint:
export G4_API_BASE=... G4_MODEL=gemma-4-31b-it-qat-w4a16-ct
scripts/run_experiment.sh --exp-id <new-id> --variant v0
```
Experiment ids are immutable: a results directory is never overwritten.

## Validation and packaging
`scripts/validate.sh` and `scripts/package_submission.sh` fail loudly on any rule violation. For the full list of
checks, see [docs/submission.md](docs/submission.md). Validator highlights beyond the obvious ones:
- **`{placeholder}` detection.** ADK raises `KeyError` on unknown state keys in instructions, so a stray brace
  in a prompt would crash every task.
- **Skill naming.** ADK requires the kebab-case `name` to equal the directory name.
- **12-hour projection** from `eval_config.yaml`.

## Known limitations
- **No real-Gemma measurement yet.** V1.1's config choices (thinking off, 5-min cap, single agent) rest on
  verified harness mechanics plus third-party leaderboard evidence, not on our own runs.
- The local runs use the official harness in its **subprocess** sandbox on macOS/py3.12; the scorer uses Docker/py3.13.
  Our own re-implementation (`src/g4agent/harness`) remains for fast unit tests.
- Local cases come from one public repo (`rich`); the hidden set uses private repos.
- The graph and embedding benchmark uses an AST approximation with lexical-proxy embeddings unless official data is supplied.
- Sequential execution is confirmed by the host. The 5.0-min cap trades some tasks for safety against the 12 h failure mode; re-tune it from a real run's durations (docs/budget_model.md §5).
- No LoRA adapter: currently not justified, because adapters are wiped by the scorer's patched vLLM (see `experiments/lora/README.md`).

## Future work (ordered by expected value)
1. **R001 real smoke test** on Kaggle 4× L4: V0 vs V1.1 on 3 gold-verified rich tasks (`python -m g4agent.kaggle_kernel`).
   Measure decode speed, durations, cap hits, loops.
2. V1.1 × 3 seeds on ≥ 20 public tasks to measure noise, then the one-variable ablations (docs/experiments.md §C).
3. Re-tune `max_time_minutes` from measured durations (docs/budget_model.md §5).
4. Cluster real failures (`python -m g4agent.traces`, `g4agent.analysis`) and fix the responsible component.
5. First Kaggle submission of the best measured variant (1/day), then LoRA only if the conditions in experiments/lora hold.

## Acknowledgements
Competition documentation © Google/Kaggle (Apache-2.0 dataset). Public repos that mirror the official
docs and starter kit were read for research (listed in docs/competition_notes.md). No code was copied.
