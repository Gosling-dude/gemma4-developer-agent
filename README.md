# Gemma 4 Developer Agent: competition submission

An autonomous software-engineering agent for **Google – The Gemma 4 Developer Agent Competition**
(Kaggle, 2026). The agent runs on `gemma-4-31b-it-qat-w4a16-ct`, fixes Python issues inside the official
sandbox, and is graded SWE-bench style: the patch has to make hidden tests pass.

> New to this? Start with [docs/getting_started.md](docs/getting_started.md).

**Status (2026-09-28):** V1 is packaged and validated (`submission/submission.zip`). All local checks pass.
**No resolution rate has been measured with a real Gemma 4 model yet**: this machine has no GPU and no model
endpoint or Kaggle credentials were available. See [Results](#results) for exactly what was and wasn't measured.

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
scripts/validate.sh                 # unit/integration tests + strict submission validation + ADK compile
scripts/package_submission.sh       # -> submission/submission.zip
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
| Budgets | `eval_config.yaml` | 4.5 min, 40 calls, 60 turns, 120 s per command (fits 12 h worst case) |
| Sampling | `configs/sampling.yaml` | temperature 0.3, thinking budget 1024, max output 6144 |
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
| **V1** | root | Production: operational prompt + 3 skills + budget tuning |
| V1-nograph | `variants/v1_nograph/` | Ablation: V1 without the 3 graph tools |
| V2 | `variants/v2/` | V1 + code_analyzer and patch_reviewer AgentTools |

Variants are overlays: the packager copies the root sources, overlays `variants/<name>/`, and ships only the
files reachable from that `agent.yaml`.

## Results
See [docs/experiments.md](docs/experiments.md) for the full log. Labels: VERIFIED / EXPERIMENTAL / INFERRED / TODO.

| What | Result | Label |
|---|---|---|
| Grading sanity: empty patch / test-only patch / reference patch through the tools, on 12 execution-verified `rich` cases | 0/12, 0/12, **12/12** (as expected) | VERIFIED |
| Test suite (validator, packager, tools, skills, ADK end-to-end with a scripted model) | 48/48 pass | VERIFIED |
| All 4 variants package, validate and compile with google-adk 1.36.1 | valid | VERIFIED |
| Localization recall@1 of `nav.py find` vs naive grep (same terms) | **0.50 vs 0.08** | EXPERIMENTAL (n=12) |
| Localization recall@3: nav alone vs + graph callee-following + similarity search | 7/12 → **9/12** | EXPERIMENTAL (n=12, approximate graph) |
| Resolution rate of V0 / V1 / V2 with Gemma 4 | **not measured** (no model endpoint available) | TODO |
| Kaggle leaderboard score | **none** (nothing submitted) | TODO |

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
- **No model-in-the-loop measurement yet.** Every design choice that depends on Gemma's behaviour
  (prompt, thinking budget, sub-agents, graph-tool value) is INFERRED until a Gemma 4 endpoint is used.
- The local harness is a documented re-implementation, not the official one (differences are listed in architecture.md §3).
- Local cases come from one public repo (`rich`); the hidden set uses private repos.
- The graph and embedding benchmark uses an AST approximation with lexical-proxy embeddings unless official data is supplied.
- The 12 h / sequential-execution assumption is unconfirmed. If tasks run in parallel, 4.5 min is too conservative.
- No LoRA adapter (see `experiments/lora/README.md`).

## Future work (ordered by expected value)
1. Run V0 vs V1 on the 129 official public tasks with the real model. Measure resolution, time per task and truncations.
2. Tune `max_time_minutes` / `thinking_budget` from measured decode speed on 4× L4.
3. V1-nograph and V2 ablations. Keep a component only if it beats run-to-run noise.
4. Mine failure categories and turn the top ones into prompt or skill changes.
5. Collect successful trajectories, then LoRA per `experiments/lora/README.md`.

## Acknowledgements
Competition documentation © Google/Kaggle (Apache-2.0 dataset). Public repos that mirror the official
docs and starter kit were read for research (listed in docs/competition_notes.md). No code was copied.
