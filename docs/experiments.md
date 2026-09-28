# Experiment log

Labels: **VERIFIED** = measured here, reproducible with the command given. **EXPERIMENTAL** = measured, but on a
small or proxy setup that may not transfer. **INFERRED** = reasoning without measurement. **TODO** = not run yet.

Every experiment writes an immutable directory (`evaluations/results/<id>/` or
`evaluations/analysis/localization_<id>.json`) recording its configuration, git revision and outputs.

## Environment for all runs below (2026-09-28)
Apple M5, 16 GB, macOS 26.6, no GPU/Docker. Python 3.12.14, google-adk 1.36.1. Local harness (`src/g4agent/harness`).
Cases: `evaluations/cases/tasks.jsonl`, **12 execution-verified cases from Textualize/rich merged PRs** (2024–2026):
each case's tests fail without the reference fix and pass with it (the same F2P/P2P check as the official
curation). Built with `python -m g4agent.cases --repo Textualize/rich --max-cases 12 --scan 400`. The builder
scanned 30+ PRs and rejected most for having no linked issue text, a reference fix that fails, or tests that pass without the fix.

## A. Pipeline and grading correctness (VERIFIED)

| ID | What | Result | Command |
|---|---|---|---|
| E000-noop | Empty patch on every case (grader must not give false positives) | **0 / 12 resolved** | `scripts/run_experiment.sh --exp-id E000-noop --agent noop` |
| E001-oracle | Reference patch applied *through the harness tools*, then `submit_patch` → extraction → Phase-2 verification | **12 / 12 resolved** | `scripts/run_experiment.sh --exp-id E001-oracle --agent oracle` |
| E002-testsonly | Test-only patch (the `test_patch` submitted as the fix; the anti-tampering reset must discard it) | **0 / 12 resolved** | `scripts/run_experiment.sh --exp-id E002-testsonly --agent tests_only` |
| T001 | Unit and integration tests: validator rules, packager determinism, 9 tools' contracts, skill scripts, **full ADK run of the packaged V1 YAML with a scripted model** (SkillToolset → run_skill_script → sandbox executor → nudge → submit → patch) | **48 / 48 pass** | `scripts/validate.sh` |
| P001 | Packaging V1, V0, V1-nograph, V2 with strict validation + ADK compile | all **VALID** | `scripts/package_submission.sh [--variant X]` |

## B. Localization benchmark (EXPERIMENTAL: n = 12, one repository, no LLM)

Question: given the issue text, is a file edited by the reference fix in the top-k of a strategy's ranking?
Search terms are extracted **deterministically** from the issue, as a stand-in for the terms the model would pick.
The graph is our AST approximation and "similar" uses lexical-proxy embeddings; official graph data wasn't
available (see architecture.md §3). Command: `python -m g4agent.localization [--filters none|env,urls]`.

| ID | Change | term filters | grep@1 | grep@3 | nav_find@1 | nav_find@3 | nav_callees@3 | similar@3 |
|---|---|---|---|---|---|---|---|---|
| L001 | baseline nav.py (raw idf × log hits + flat def boost) | none | 0.17 | 0.25 | 0.17 | 0.42 | – | 0.50 |
| L003 | nav.py v2: def boost ÷ #defining files, capped per-term score, term-order weight, no double counting | none | 0.17 | 0.25 | 0.25 | 0.42 | – | 0.50 |
| L004 | + drop env-dump / URL / doc-link terms | env,urls | 0.08 | 0.42 | **0.50** | **0.58** | – | 0.67 |
| L005 | + graph strategy: follow `calls` 1–2 hops from the issue's named symbols | env,urls | 0.08 | 0.42 | 0.50 | 0.58 | **0.67** | 0.67 |
| L006 | + nav.py: dotted module term → module file boost | env,urls | 0.08 | 0.42 | 0.50 | 0.58 | 0.67 | 0.67 |

(L002 was an intermediate run with two changes at once; it's superseded by the L003/L004 ablation and kept only for the record.)

Findings:
1. **Term quality is the biggest lever.** With nav.py fixed, removing environment-report and URL terms doubled
   top-1 (0.25 → 0.50). Issue templates (e.g. `python -m rich.diagnose` output) inject misleading identifiers.
   → Prompt and SKILL.md now tell the agent which terms to use and which to ignore.
2. **nav.py beats naive grep at top-1** with the same clean terms: 0.50 vs 0.08 (6 vs 1 of 12). Its scoring
   change alone (L001 → L003) was a modest gain (0.17 → 0.25 @1).
3. **Graph reasoning helps in a specific, predictable way.** Following *outgoing calls* of the API the issue names
   recovered a case where the bug sits one call deeper (`Text.from_ansi` → `rich/ansi.py`). The union of
   nav_callees and similar reaches **9/12 @3 (vs 7/12 for nav_find alone)**. Undirected graph expansion around
   the top files (nav_graph) was not reliably helpful. → The prompt now recommends
   `get_code_neighbors` on the named API when it delegates, not blanket graph use.
4. Remaining misses need semantic understanding (e.g. an emoji width bug → `cells.py`) or following a failing test's traceback
   (`diagnose.py`). That's the model's job; the skills keep it cheap.

Caveats: 12 cases from one repository; a proxy extractor rather than the model; an approximate graph. Treat these as direction, not magnitude.

## C. Agent runs with Gemma 4 (TODO: blocked on a model endpoint)

Nothing in this section has been run. No resolution rate for V0/V1/V2 exists yet. The runs are fully scripted:
```bash
export G4_API_BASE=http://<vllm-host>:8000/v1 G4_MODEL=gemma-4-31b-it-qat-w4a16-ct   # + G4_API_KEY if needed
scripts/run_experiment.sh --exp-id E010-v0 --variant v0
scripts/run_experiment.sh --exp-id E011-v1
scripts/run_experiment.sh --exp-id E012-v1nograph --variant v1_nograph
scripts/run_experiment.sh --exp-id E013-v2 --variant v2
.venv/bin/python -m g4agent.analysis evaluations/results/E01*
```
Planned order and decision rules:
| ID | Hypothesis | Keep the change if |
|---|---|---|
| E010 vs E011 | V1 (skills + operational prompt) beats V0 | V1 resolves more **and** has fewer `no_attempt`/`timeout_budget` failures |
| E011 × 3 seeds | Measure run-to-run noise | (needed before any other comparison is meaningful) |
| E012 | Graph tools earn their calls | V1 ≥ V1-nograph by more than the noise |
| E013 | Sub-agents pay for their extra turns within 4.5 min | V2 > V1 by more than the noise, and mean time stays below the budget |
| E014 | `thinking_budget` 1024 vs 2048 vs 512 | best resolution at equal time |
| E015 | `max_time_minutes` sensitivity (3 / 4.5 / 6) | measured on the real server to confirm the 12 h projection |

Official data (129 tasks) replaces the local cases as soon as Kaggle credentials are available:
`--tasks data/tasks.jsonl --data-dir data` (also switches the graph tools to the official graphs and embeddings).

## D. Leaderboard submissions
None made. **No leaderboard score exists for this project.** (Submitting needs your Kaggle account; see docs/submission.md.)
