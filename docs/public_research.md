# Public research inputs

## Snapshot 2 (2026-09-29), after V1.1 scored 0.06
Same anonymous API (`research/kaggle/`): leaderboard `leaderboard_public_2026-09-29.json` (922 teams),
71 public notebooks (16 new ones fetched), 59 discussion topics (22 new or updated ones dumped).
Labels as below: **HOST**, **3P** (third party, not reproduced by us), **VERIFIED** (checked here in
official source code or our own logs), **INFERRED**.

### What the board says about 0.06
| Fact | Label |
|---|---|
| The 11 displayed scores (0.00 0.01 0.03 0.05 0.06 0.08 0.10 0.12 0.13 0.15 0.17) are exactly ⌊100·k/58⌋/100 for k = 0…10; no other task count 30–130 reproduces the set under truncation, and none does under rounding. Meta Kaggle confirms 2-decimal truncation and a 50% public split. | VERIFIED arithmetic (also 3P notebook *LB: 58 Tasks, Bronze Is a 124-Team Tie*) |
| **V1.1 = 0.06 = 4 of 58 public tasks.** 0.12 = 7, 0.15 = 9, top 0.17 = 10 tasks. | VERIFIED arithmetic |
| Distribution: 0.17 ×1, 0.15 ×4, 0.13 ×16, 0.12 ×80, 0.10 ×139, 0.08 ×178, **0.06 ×156**, 0.05 ×127, 0.03 ×38, 0.01 ×55, 0.00 ×128 | VERIFIED (snapshot) |
| One submission's binomial s.d. near p ≈ 0.1 is ≈ 2.3 tasks. 4 vs 7 tasks is ≈ 1.3 s.d.: V1.1 may be a genuinely weaker agent or a low draw of a 0.10-level agent. One score can't tell which. | INFERRED (standard binomial) |
| Repeat runs of the same agent on 106 dev tasks resolved 31/28/33 (base) and 30/30/35 (skill): run-to-run s.d. ≈ 2.4 tasks per 106. | 3P (GraphLoc end-to-end) |
| CV (dev set) vs LB correlate weakly: CV 0.18→LB 0.05, 0.19→0.06, 0.23→0.12, 0.24→0.10 | 3P (744319) |

### Real-Gemma failure data (the most useful new source)
*GraphLoc end-to-end* (zzgtylors) ran the official harness + real Gemma 4 on 106 sound dev tasks, 3 runs × 2
agents (sample prompt ± a BM25+PageRank localization skill), 25 min / 40 calls, thinking on, 12 concurrent runs.

| Where the patch edits (base agent, 318 runs) | runs | resolved |
|---|---:|---:|
| a gold function | 143 | 82 (57%) |
| a gold file, other function | 20 | 5 |
| a wrong file | 88 | 4 (5%) |
| no patch (47 time budget, 14 error, 3 tool budget, 2 stopped) | 67 | 1 |

- A gold function edited but the target tests still fail: 43/143. That's the "right place, wrong fix" class.
- The localization skill put a gold function in its top 5 for 51% of tasks, yet overall resolution moved only 92 → 95 of 318 (noise).
  **Better candidate lists alone did not move resolution**; the agent edited a listed candidate only 38% of the time.
- Only 13–17% of runs ran tests; resolved-if-ran-tests 28–48% vs 27–29% without (confounded).

### Harness mechanics found by others, checked here
| Finding | Evidence | Our check |
|---|---|---|
| **Tool results reach the model JSON-encoded twice** (swegemma tools return a JSON string, ADK wraps it in `{"result": …}`, LiteLLM serializes again). The model copies escapes into `edit_file`'s `old_string`: 62/299 `edit_file` calls failed with "old_string not found", 39 of them (18 tasks) provably from escaping; docstrings (`"""`) are the most common trigger. | 3P 744272 | **VERIFIED** in our E006 request log: `edit_file`/`submit_patch` results arrive as `{"result": "{\"status\"…\\\\n…"}` (2 levels), `run_skill_script` results as `{"stdout": "…\\n…"}` (1 level). Official matcher vs escaped copies: **0/300** on quote/backslash/non-ASCII blocks (our M001) |
| Any non-timeout exception in the agent loop discards the patch, even a submitted one; a context overflow is such an exception. | 3P (Black Cat lab) | **VERIFIED** in `swegemma/harness/agent_runner.py`: the outer `except Exception` skips both `submitted_patch` and the working-tree fallback |
| `max_output_tokens` reserves context | – | **Refuted**: vLLM 0.19.1 `get_max_tokens` clamps to `max_model_len - input_length`; only input > 32,768 errors. Lowering it buys nothing |
| Official embeddings are near-collapsed: random pairs cos 0.78–0.90, 7–19% ≥ 0.99; gold file in top 10 for 35/129 tasks vs 67 for grep | 3P 744040, independently reproduced in the thread | Not reproduced (no competition data here). `search_similar_code` advice removed from the V1.2 prompt |
| Graphs have only `calls` edges, no `async def` nodes (0/57 in fastapi, 0/100 in httpx's async client) | 3P 742911, 744040; host confirmed async missing | Unchanged: graph tools stay secondary |
| LoRA: with any adapter the vLLM KV cache drops to ≈ 7,600 tokens and ~20k-token prompts never start | 3P 744331 (measured on 4× L4) | Reinforces: no adapter |
| Repeating the same tool call until the budget runs out is the most common Gemma failure | 3P 743964, Black Cat (13/19 runs had a ≥ 5× loop at T 0.2) | V1.2 skills flag identical calls when nothing changed |
| Callback registry is empty in adk-submission 0.2.11; no way to force tool calls or stop loops in code | 3P 743964 (unanswered) | Consistent with our reading of the schema |
| 12 h overrun still errors the whole submission ("Not yet" fixed); parallel LLM calls not supported | HOST 743964 | Budget stays worst-case safe |
| Only ADK 1.x (wheelhouse) is supported; anything allowing arbitrary code execution is blocked | HOST 743800 | No change |
| Test tasks were reviewed for solvability (unlike the training tasks) | HOST 743817 | – |
| Training a LoRA on Gemma-4-31b's own trajectories is allowed; other models' outputs: undecided | HOST 743964 | LoRA still not pursued (above) |

### Budget evidence from public runs (all 3P)
| Run | Per-task limits | Result |
|---|---|---|
| romanrozen, Pathfinder v2 (coder + analyzer, thinking off) | none (scorer default) | 0.12 |
| Pathfinder v1, same agent | 4 min hard cap | 0.08 |
| Walkthrough v2 | none | 0.10 |
| Walkthrough v3 | 12 min cap | **error: exceeded 12 h** |
| Direct fork of romanrozen | none | 0.08, 14.5 h scoring wall time (incl. ≈ 2 h validation) |
| Black Cat lab (official harness, 2 agents per server): anchor 5 min/40 calls/120 s vs challenger 8 min/100 calls/300 s | – | 3/19 vs 3/19; mean 28 calls in 158 s vs 74 calls in 258 s, i.e. **3.5–5.6 s per tool call** |

Inference for us: at 3.5–5.6 s per call, V1.1's 60-call cap binds after roughly 3.5–5.6 min, about the same
point as its 5.0 min time cap. Raising the time cap alone would therefore change little (V1.2 raises both).

### New notebooks (2026-09-29)
| Notebook | Useful for us | Used? |
|---|---|---|
| LB: 58 Tasks, Bronze Is a 124-Team Tie (dariushafshar) | task-count arithmetic, noise model, "second final pick should be a *different* agent" | yes (above) |
| GraphLoc end-to-end + failure analysis (zzgtylors) | real-Gemma failure taxonomy and run-to-run variance | yes (above) |
| Task Map & 12-Hour Budget (officialabhinavsingh) | dev-set patch sizes: median 18 changed lines fastapi, 9 rich, 4 requests; issue length ≠ patch size (ρ = 0.07) | context only |
| Task anatomy + survival kit (osama133) | onboarding; SWE-agent/Agentless framing | no new evidence |
| Eval errors (bharat0) | sample submission resolves 5/10 fastapi dev tasks | dev set is much easier than the hidden set |
| GTUA graph-tool utility audits, Localization Repaired, Graph Coverage Audit, Repaired Graphs Regen | graph/embedding quality problems | consistent with 744040 |
| Can Gemma 4 Fix an Unseen Repo? (31B QLoRA study) | LoRA | not usable (KV-cache issue) |

### Public ideas considered for V1.2
| Idea | Problem it addresses | Evidence | Rule-compatible | Overlap with V1.1 | Decision |
|---|---|---|---|---|---|
| Escape-tolerant editing | edit_file "old_string not found" from double escaping | 3P counts + VERIFIED mechanism + our M001 | yes (skill script) | none | **V1.2** (`code-edit` skill) |
| Read code through a single-escaped path | same | VERIFIED (E006 log) | yes | `nav.py show` existed | **V1.2** (`nav.py read`, prompt) |
| Stop repetition loops | loops are the top failure | 3P (Black Cat, 743964) | callbacks unavailable; skill-level only | prompt rule | **V1.2** (skill-side notice) |
| No/looser per-task caps | tight caps cost tasks | 3P (Pathfinder A/B, Black Cat timings) | yes, if the 12 h worst case holds | 5.0 min / 60 calls | **V1.2**: 5.5 min / 80 calls / 100 turns (worst case 11.2 h) |
| Stop using `search_similar_code` | embeddings collapsed, one call can flood context | 3P ×3 | yes | prompt recommended it | **V1.2** (prompt) |
| Coder + read-only analyzer | context isolation | every public score ≥ 0.10 uses it, but always confounded with no-cap budgets | yes | `variants/v2` | **not default**; packaged as the V1.2 analyzer variant for a separate measurement |
| Repeat `{problem_description}` in the instruction | issue lost after compaction | 3P (Walkthrough v2, with other changes) | yes | no | TODO (V1.3 candidate; compaction settings on the scorer unknown) |
| BM25/PPR localization skill | localization | 3P: +3/318 runs (noise) | yes | `nav.py find` already does IDF ranking | no |
| LoRA | model skill | KV cache collapse with any adapter (3P) | yes | – | no |

---

## Snapshot 1 (2026-09-28)

Collected anonymously from Kaggle's public web API (`research/kaggle/`: official pages, discussion threads,
leaderboard snapshot, and notebook sources flattened to markdown). Nothing was copied into the agent. Scores are
the notebooks' reported `bestPublicScore` or scores stated by their authors, on the **58-task public LB**.
Labels: **HOST** = stated by a competition host (verified source); **3P** = third-party report (not verified by us).

## Leaderboard context (public LB, 2026-09-28)
738 teams. Top **0.15** (1 team), then 0.13 (12 teams), 0.12 (61), 0.10 (96), 0.08 (141). One task ≈ 0.017, so
0.12 ≈ 7/58 resolved and 0.15 ≈ 9/58. The public LB is 58 tasks: inferred from the rounding pattern
(discussion 743506, 3P), consistent with "about 120 tasks split evenly" (data page, HOST).

## Notebooks

| Notebook (author) | Public score | Idea / architecture | Evidence offered | Useful component | Compatible with ours? |
|---|---|---|---|---|---|
| Getting Started (ryanholbrook, **HOST**) | – | Official runtime: install wheelhouse → `VllmServer` (TP4, 32k, gemma4 parsers) → `Evaluator` (subprocess sandbox) → zip | Runs 2 tasks on 4× L4; 944 s total | **Exact recipe for real Gemma runs on Kaggle**: used verbatim in `src/g4agent/kaggle_kernel.py` | Yes (basis of our real-eval path) |
| GEMMA: EDA, Baseline (romanrozen) | **0.12** | Coder + read-only analyzer AgentTool; grep-first prompt; T 0.2, 8192 tokens, **thinking off**; **no eval_config** (no per-task limit) | LB | Thinking off; analyzer isolates context | Yes; sub-agent = our V2 |
| Pathfinder (mizeroluckygall) | **0.12** | Same design as above | **Its v1 with a hard 4-min limit scored 0.08** (3P, via Black Cat notebook) | Evidence that tight per-task caps cost tasks | Raised our cap 4.5 → 5.0 (see budget_model.md) |
| Black Cat SWE Agent (lucifer19) | 0.10 | Coder + analyzer, 5 min / 40 calls, T 0.2; "lab" of 209 official-harness runs | Version table: single 4 min/24 calls 0.08 → +analyzer 5 min/40 calls 0.10; T 1.0 variant 0.06 | **Thinking-off Gemma repeats the same tool call 10–80×**; `git grep` exit 1 with empty message triggers loops | Anti-repetition rule added to V1.1 prompt; V2 ablation |
| Walkthrough & First Submission (zhukovoleksiy) | 0.10 | Coder + analyzer, thinking off | A version with **12 min/task exceeded the 12 h limit** (3P) | Hard evidence for the budget risk | Budget model |
| [0.10] Submission (nihilisticneuralnet) | 0.10 | Coder + localizer + verifier sub-agents, T 0.15, 4.5 min | LB | Multi-agent with small sub-agent budgets | V2-style; untested by us |
| Gemma Super Basic (twangygarlic449) | 0.08 | Minimal single agent | LB | Lower bound for "minimal" | ≈ our V0 |
| Complete EDA & ADK Starter (nursrijan) | 0.05 (3P) | Starter kit, thinking on, 16k tokens | LB (as reported) | – | – |
| Localization Bench (woldywei) | – | Official 129 tasks, **official graphs/embeddings**: TF-IDF vs embedding vs PPR vs hybrid | File recall@1/5: **TF-IDF 0.21/0.50**, embedding 0.05/0.21, PPR 0.08/0.26, hybrid 0.14/0.42 | Lexical retrieval dominates; official embeddings weak for issue text | Supports our lexical `nav.py`; **downgrades** our "similar" finding (ours used proxy embeddings) |
| GraphLoc (zzgtylors) | – | Real Gemma 4 on 4× L4 choosing functions from BM25 / graph-hop pools | Function H@1 0.238 after **stripping URLs** from issues | URL/noise stripping helps, same as our L004 finding | Consistent with our term-selection rules |
| 119 of 129 sound (busyaprime) | – | Rebuilt grader | 119/129 public tasks sound; achievable range 2/129 … 125/129 | Some public tasks are unsolvable (py3.13 env) | We exclude rich_3472/rich_3486 in Kaggle smoke runs |
| Dual-Space Spectral Graph (avikdas567) | – | Graph-spectral + embedding fusion, multi-agent | Math and design; **no LB score or measured result** | – | Not adopted (no evidence) |
| DevAgent Graph Reasoning (nursrijan) | – | Graph-navigator sub-agent + diff architect | Claims "prune search space by 85%" without a measurement shown | – | Not adopted (no evidence) |

## Discussion facts that changed our design

| Fact | Source | Effect |
|---|---|---|
| Tasks run **sequentially**; scorer reads exactly `timeout_seconds, max_tool_calls, max_time_minutes, max_turns`; missing = **no limit**; hitting 12 h currently **errors the submission** | HOST, 743063 | Budget model; explicit cap kept |
| Patch validation ≈ **2 h** and is excluded from 12 h; a no-patch run takes ≈ 10 min | HOST, 743663 | Setup overhead is small |
| Official sample (with adapters) failed; LoRA adapters are **silently wiped** by the patched vLLM (layers registered twice) | 3P 743213/743508; host "will address" | **LoRA not justified now** |
| Graphs contain only `calls` edges, no module nodes, **no async functions**; embeddings keyed to the same nodes | 3P 742911; HOST confirmed async still missing | Graph tools can't reach async code; prompt keeps lexical search primary |
| Public subprocess sandbox fails some FastAPI/requests gold patches (missing test deps, installed-package shadowing) | 3P 742882/743973; HOST: "may be a problem with the subprocess sandbox" | Kaggle smoke runs use rich tasks + a gold control per task |
| 4× L4 sessions queue 4–9+ h | 3P 743600/743901 | Real runs must be planned; notebook runs V0 and V1 in one session |
| 1 submission/day, 2 final selections | Rules (HOST) | Validate offline first; spend submissions deliberately |
