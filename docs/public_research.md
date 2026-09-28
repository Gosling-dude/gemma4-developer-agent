# Public research inputs (snapshot 2026-09-28)

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
