# V1.3 hypotheses (2026-09-30)

Baseline: **V1.2 = 0.08 REAL KAGGLE PUBLIC SCORE (5/58)**. V1.1 = 0.06 (4/58).
Labels: **VERIFIED** = measured here or read in official source, reproducible with the command given.
**3P-DATA** = third-party real-Gemma data (public Kaggle notebook outputs) that *we* re-analysed with our own
code (the classification is ours and reproducible; the runs are not ours). **EXPERIMENTAL** = measured, but
on a proxy that may not transfer. **INFERRED** = reasoning. **TODO** = not run.

## 0. What V1.1 → V1.2 changed, and what 0.06 → 0.08 says
Diff `v1.1-baseline..v1.2-baseline` (VERIFIED, `git diff --stat`): `code-edit` skill (escape-tolerant,
syntax-checked edits), `nav.py read`, repeat notices in all skills, prompt (read via show/read, code-edit after
"old_string not found", five-line brief, failure classes, no `search_similar_code`), budget 5.0/60/80 →
5.5/80/100. Nothing else (model, sampling, tools, single agent unchanged).

0.06 → 0.08 is **+1 task of 58**. A single submission has s.d. ≈ 2.2 tasks, so this is **not evidence**
that V1.2 is better; it is also not evidence it is worse. Kaggle gives no per-task data, so no failure in
*our* hidden-set runs is known. Everything below comes from (a) real Gemma 4 trajectories on the public dev
set produced by others with the official harness, re-analysed by our scripts, and (b) mechanisms verified
in official source code. None of it is our agent's hidden-set behaviour.

## 1. The data we used (new this session)
| Source | What | Label |
|---|---|---|
| GraphLoc end-to-end runs 1–3 (public notebook outputs, downloaded anonymously) | **636 real trajectories**: 106 official dev tasks × 2 agents × 3 runs; official swegemma harness; gemma-4-31b-it-qat-w4a16-ct on 4×L4; full ATIF traces, patches, grader results | 3P-DATA |
| GraphLoc-129 labels | base commit, gold files, gold symbols for all 129 dev tasks | 3P-DATA |
| "Shape of Doubt" sampling screen | 16 real trajectories, **thinking off**, 5 min / 45 calls (closest to our regime) | 3P-DATA |
| "Direct Code Verifier" | 32 real trajectories, 4.5 min caps, thinking on (small budget, not enforced) | 3P-DATA |
| Problem statements for 111 dev tasks | from the task message in those traces | 3P-DATA |

Their agents are not ours: GraphLoc ran thinking on, 25 min / 40 calls, 12 agents per vLLM server, so its
per-call **times do not transfer**. Call counts, edit outcomes, loops and where patches land are model
behaviour and are used as such. Script: `python -m g4agent.trace_taxonomy` (F001).

## 2. Hypotheses, ranked by (measured size of the failure class × strength of the mechanism) ÷ cost
| # | Hypothesis | Evidence | Label | V1.3 action |
|---|---|---|---|---|
| H1 | **Patches never land.** The largest failure class is "no library source edit at all" | GraphLoc F001: *timeout with no source edit* = **179/449 failures (40%)**, the largest primary category; plus tool loop 35 and edit_file failure 14 as primary. 245/636 runs never landed an edit and **2/245 resolved**. In 152/179 of those timeouts the agent had already opened a gold file (median call 2–3), then kept reading (10.5 reads + 6.4 searches per run, 0.2 edits). Thinking-off screen: only 7/16 runs landed an edit | 3P-DATA | Edit deadline (call 12) + new edit channel (H2) |
| H2 | **edit_file is unreliable for Gemma 4 in this harness** — two independent mechanisms | 1,689 real `edit_file` calls: **49% fail**: 375 "old_string not found", 375 "mandatory parameter old_string missing", 81 other. Not-found: **81% when the arguments contain a backslash** (copied escapes) vs 5% without. Argument loss: 320/375 have `new_string` closed with a backtick, which swallows `old_string` (the model emits `new_string` before `old_string` in 267/274 successful calls). Thinking-off screen: **130/143 edit_file calls failed**. Same traces: `run_command` with long code (198 heredocs, 228 `python -c`): **0 corrupted**; short-args `run_skill_script`: **0/251 corrupted** | 3P-DATA (rates); VERIFIED (our reanalysis) | **Two-step edit channel**: code in a `run_command` heredoc → `code-edit lines PATH START END @/tmp/new.txt` (short args; no old text copied) |
| H3 | Earlier first edits resolve more often | resolve rate by call of first edit: 1–5: 53%, 6–10: **65%**, 11–15: 48%, 16–20: 33%, 21–30: 31%, 31+: 29%, never: 0.8% | 3P-DATA, **confounded** with task difficulty | Deadline rule "first edit by call 12" (prompt only) |
| H4 | Redundant reads / repeated calls waste the budget | failed runs 11.5 reads and 3.2 same-output repeats per run vs 6.9 and 2.0 in resolved runs; one trace re-read `rich/logging.py` 6× in a row | 3P-DATA, confounded | Prompt: "what new information will this call give?"; no re-read of unchanged lines. Skills already print a repeat notice (V1.2) |
| H5 | `search_similar_code` is useless and dangerous | 173 real calls: **148 empty (86%)**; phrase queries 0/71 non-empty; symbol queries 25/102 non-empty, 12 containing a gold node, and all 5 responses > 20k chars. 3P 744577: responses > 100k chars end the task with ContextWindowExceeded | 3P-DATA | Keep discouraged (V1.2). **Keep registered**: the harness message always advertises it, and ADK raises `ValueError` on an unregistered tool, which discards the patch (VERIFIED `google/adk/flows/llm_flows/functions.py:_get_tool`, no on_tool_error plugin in swegemma) |
| H6 | Graph tools improve localization | 111 official dev tasks, repaired graphs: A nav 0.477/0.622/0.721 (@1/3/5); B always-expand 0.477/0.631/0.721; C conditional 0.477/0.622/0.703; D graph-first **0.360**/0.622/0.712. GraphLoc: 28 graph calls in 636 runs | EXPERIMENTAL (no model) | **None.** Policy A (normal search) is the simplest and as good. Prompt keeps get_code_neighbors only for delegation |
| H7 | Localization is the bottleneck | wrong file 16 + repository localization 16 + wrong symbol 16 = **48/449 (11%)** of failures; gold file opened by call 2–4 in most runs. nav.py @1 0.48 vs grep 0.30 on 111 official tasks | 3P-DATA + EXPERIMENTAL | No change to nav.py. Noise filters: env/URL ±0.02, PR-template filter ±0.01 (noise); the env filter was dropping exception names in traceback lines; fixed in the benchmark extractor (+1 task) |
| H8 | Right place, wrong patch | right location/wrong patch 62 + incomplete 35 + regression 34 = **131/449 (29%)** | 3P-DATA | Not addressed by a code change (no verified mechanism). V1.2's brief/repair loop stays |
| H9 | Dynamic stopping wastes budget after the fix | only **0.28** calls on average after the first `submit_patch`; 17% of runs make any | 3P-DATA | None needed; the waste is *before* the first edit (H1) |
| H10 | Context overflow discards patches | 26/636 runs (4%) ended with ContextWindowExceeded (patch discarded, VERIFIED mechanism) | 3P-DATA | Nothing new beyond H5 and small skill outputs |
| H11 | Sub-agents (analyzer/reviewer/debugger) pay for their turns | every public ≥ 0.10 agent uses coder+analyzer, always confounded with no caps/thinking on | 3P, confounded | TODO: `v12_analyzer`/`v12_reviewer`/`v12_both` packaged; needs a GPU run |
| H12 | Thinking on beats thinking off | top public 0.15 uses thinking on and no caps; host patched thought-dropping on 09-29 (744354). Thinking-on calls took 15–21 s in 4.5-min runs vs 5.5 s thinking off | 3P, confounded | Not changed: at 15–21 s/call a 5.5-min cap allows ~16–22 calls; resolved GraphLoc runs needed a median 18 |

Not assigned from data (no deterministic signal): *issue misunderstanding*, *dependency misunderstanding*,
*correct diagnosis vs wrong diagnosis at the right location*. Reported as merged "right location, wrong patch".

## 3. Choice for V1.3 (one main mechanism)
V1.3 = V1.2 + **H2 edit channel** (skill + prompt) + H1/H4 prompt rules. H1 is the largest measured class;
H2 is its mechanism with the strongest evidence (two measured failure modes, a measured robust alternative).
Everything else (localization, graph policy, search_similar_code, stopping) is measured and left unchanged.
Budget unchanged (5.5 min / 80 / 100; worst case 11.2 h).
