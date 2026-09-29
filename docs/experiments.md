# Experiment log

## Canonical score table (the ONLY place scores are summarized)
No row below is a Gemma 4 result or a Kaggle score. The "Model" column says exactly what produced the patch.

| Version | Model / patch source | Harness | Tasks | Resolved | Score | Runtime | Status |
|---|---|---|---:|---:|---:|---|---|
| (grading control) | empty patch | local re-impl (E000) | 12 | 0 | 0.00 | – | VERIFIED |
| (grading control) | empty patch | **official swegemma 0.2.7** (E004) | 12 | 0 | 0.00 | ~2 s/task | VERIFIED |
| (grading control) | test-only patch | local re-impl (E002) | 12 | 0 | 0.00 | – | VERIFIED |
| (grading control) | reference patch via tools (oracle) | local re-impl (E001) | 12 | 12 | 1.00 | – | VERIFIED |
| (grading control) | reference patch | **official swegemma 0.2.7** (E003) | 12 | 12 | 1.00 | 1.8–4.0 s/task | VERIFIED |
| V1 (pre-fix skills) | scripted fake model | official, subprocess sandbox | 1 | 1* | – | 4.4 s | VERIFIED pipeline test; *resolved only because the scripted edit was correct: the skills saw an empty dir (bug) |
| V1.1 | scripted fake model | official, subprocess sandbox (E005/E006) | 1 | 1 | – | 3.9 s | VERIFIED pipeline test (no model quality measured) |
| V0 | **real Gemma 4** | official | – | – | – | – | TODO (blocked: no GPU/endpoint/credentials) |
| V1.1 | **real Gemma 4** | official, Kaggle 4× L4 (R001-v1-smoke) | 0 run | – | – | – | TODO (blocked 2026-09-29: no Kaggle credentials; see §C) |
| any | **Kaggle leaderboard** | – | – | – | – | – | **none: nothing submitted** |

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

## A2. Checks against the OFFICIAL harness (VERIFIED, added in session 2)
Official libraries: `swegemma 0.2.7`, `adk-submission 0.2.11`, `adk-eval-core 0.1.0` from the organizers' public
wheelhouse dataset (`scripts/setup_official_harness.sh`). Subprocess sandbox, macOS, Python 3.12.

| ID | What | Result |
|---|---|---|
| O001 | Official `validate_directory` + `compile_submission` on every variant | V1, V0, V1-nograph pass; **V2 FAILED** (`PathTraversalError`: sub-agent `skills: ../skills/...`; official skill paths are root-relative and reject `..`). Fixed; now all 8 variants pass |
| E003 | Official Evaluator grading of reference patches on the 12 local cases | **12/12 resolved**, the same as our grader |
| E004 | Official Evaluator grading of empty patches | **0/12** |
| E005 | V1 skills in the official subprocess sandbox (scripted model) | **Bug found**: nav/tests/review saw an empty directory (`/workspace` absent, ADK chdir to temp). Fixed (`$PWD` fallback) and re-run: skills return real results; patch resolved |
| E006 | Final V1.1 zip, same scripted run | resolved; request log: `enable_thinking: false`, `max_completion_tokens 6144`, 13 tools |
| O002 | What the harness sends for thinking | only `enable_thinking` on/off; `thinking_budget` is never sent (V1's "1024-token budget" was not real) |
| O003 | Grading timeout | `timeout_seconds` caps the hidden-test pytest run → V1's 120 s was a latent failure mode; V1.1 uses 300 |
| T002 | Test suite | **63 tests pass** (`scripts/validate.sh`, which also runs the official check) |

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

**Reproduction check (L007, session 2):** rerunning the benchmark with current code gives per-task results
identical to L006 (`evaluations/analysis/localization_L007_repro.json`), so the numbers reproduce.
**Downgrade:** the "similar" strategy used *our lexical-proxy* embeddings. A third-party benchmark on the **official**
129 tasks with the **official** embeddings found them weak for issue-text localization (file recall@5: embeddings 0.21,
graph PPR 0.26, vs TF-IDF 0.50; see docs/public_research.md). The "+similarity search" part of finding 3 therefore
probably doesn't transfer. The callee-following part uses `calls` edges, which the official graphs do contain,
though without async functions. It remains EXPERIMENTAL.

## C. Real Gemma 4 runs (TODO: blocked on credentials)
Nothing here has been run.

| ID | Date | What | Outcome | Label |
|---|---|---|---|---|
| R001-v1-smoke (attempt 1) | 2026-09-29 | V1.1 (unchanged, tag `v1.1-baseline`), 3 gold-sound official rich tasks, Kaggle 4× L4 | **Not executed.** Preflight: package VALID (official compile OK); no Kaggle API credentials, browser session unavailable, no GPU/endpoint. 0 tasks, 0 model calls. Record: `evaluations/attempts/R001-v1-smoke_attempt1_2026-09-29.json` | TODO |

The id `R001-v1-smoke` was deliberately **not** used for a results directory, so the real run can use it:
`scripts/run_kaggle_eval.sh --exp-id R001-v1-smoke`. The paths are built and tested up to the GPU (docs/kaggle_runtime.md, docs/real_baseline.md):
- Kaggle (4× L4, official recipe): `python -m g4agent.kaggle_kernel --variants v0 root --n-tasks 3` → push → `kernels output`.
- Own vLLM server: `scripts/check_model_endpoint.sh`, then `scripts/run_real_eval.sh --exp-id R00x ... [--variant X]`.

### Controlled ablation plan (one variable per variant; same tasks, same server session)
| ID | Variant | Single change vs V1.1 (root) | Question |
|---|---|---|---|
| A | root | – (V1.1) | reference |
| B | `v1_nograph` | graph tools removed; prompt uses nav.py show/usages instead | do graph tools earn their calls? |
| C | `v1_noskills` | no skills; same workflow with plain run_command | do the helper scripts help? |
| D | `v1_oldloc` | LOCATE section reverted to the pre-benchmark prompt | does the evidence-driven localization prompt help? |
| E | A vs B | graph-guided (callee-following) localization vs none | – |
| F | `v1_baseline` | V1 configuration (thinking on, 4.5 min, 120 s timeout) | did the V1.1 changes help as a whole? |
| G | `v2` | + code_analyzer and patch_reviewer AgentTools | do sub-agents pay for their extra turns? |
| H | `v1_think` | thinking on (everything else V1.1) | thinking vs visible short reasoning at a 5-min cap |
Run order: (1) R001 smoke, V0 vs A on 3 sound tasks; (2) A × 3 seeds on ≥ 20 tasks to measure noise; (3) B, C, D, G, H on the same tasks.
A sub-agent (G) is kept only if it beats A by more than the noise **and** its mean duration stays under the cap.
Command: `python -m g4agent.kaggle_kernel --variants root v1_nograph v1_noskills v1_oldloc v1_think v2 --n-tasks 20`.

## D. Leaderboard submissions
None made. **No leaderboard score exists for this project.** (Submitting needs your Kaggle account; see docs/submission.md.)
