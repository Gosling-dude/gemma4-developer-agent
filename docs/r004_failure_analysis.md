# R004 failure analysis: why v13_channel and root made zero tool calls

R004 (`evaluations/results/R004-v13-matrix/`, Kaggle 4×L4, real gemma-4-31b-it-qat-w4a16-ct, one vLLM server,
variants run sequentially in the order v1_2 → v13_channel → root, 12 gold-sound rich tasks each):

| Variant | Tasks | Resolved | Mean tool calls |
|---|---:|---:|---:|
| v1_2 | 12 | 4 | 18.4 |
| v13_channel | 12 | 0 | 0.0 |
| root (V1.3) | 12 | 0 | 0.0 |

## 1. KNOWN FACT (from the artifacts)
| # | Fact | Source |
|---|---|---|
| F1 | **V1.2 itself stopped producing model output mid-run.** Its tasks 1–6 made 16/16/43/27/48/71 tool calls; tasks 7–12 (rich_3063 … rich_3454, from 17:17:10Z) made **0 tool calls and 0 LLM calls**, each ending at exactly the 5.5-min cap | `g4_results/v1_2_task_results.jsonl` (`llm_calls`, `start`, `end`) |
| F2 | From that moment, **all 30 remaining tasks** (6 V1.2 + 12 v13_channel + 12 root, 17:17 → 20:02, 2 h 45 min) show the same signature | the three `*_task_results.jsonl` |
| F3 | Every zero-call trace has exactly two steps (system prompt, user task message) and `total_prompt_tokens = 0`: the first model request never returned a response. The V1.3 system prompt *is* in the root traces, so the agent was built and the prompt loaded | `g4_results/*/traces/trace_*.json` |
| F4 | No connection error, retry, or exception is logged for those tasks; only `agent timed out` | kernel log `g4-r004-v13-matrix.log` |
| F5 | At the end, the vLLM process was **still alive** but did not terminate within 10 s and had to be killed | kernel log lines 491–496 (`Inference server did not terminate within 10.0s; killing...`) |
| F6 | The last task with model output (V1.2 rich_3061) hit the time cap in the middle of an identical-call loop (the same `cat > /tmp/repro.py` heredoc 4×), with a model request in flight at cancellation; prompts were ~13k tokens | `v1_2/traces/trace_rich_3061.json` |
| F7 | The packaged V1.2 vs V1.3 files differ only in `agent.yaml` **comments**, `prompts/system.md` (+625 chars), `skills/code-edit/{SKILL.md,scripts/edit.py}` and `skills/debugging/scripts/diagnose.py`. `configs/sampling.yaml`, `eval_config.yaml`, tool list, skill list are byte-identical | `cmp` of `agents/{v1_2,v13_channel,root}/` |
| F8 | The first model request built by the official harness is identical for V1.2 and V1.3 in model, sampling params (`max_completion_tokens 6144, T 0.3, top_p 0.95, enable_thinking false`), the 13 registered tools (9 harness + 4 skill tools) and message structure; only the system text differs | E009 request logs (`evaluations/results/E009-…/{v1_2,root}/model_requests.jsonl`) |
| F9 | Skill scripts only run when the model calls `run_skill_script`; nothing in `edit.py`/`diagnose.py` executes before the first model response | ADK SkillToolset; F3 |
| F10 | `VllmServer` writes vLLM output to a temp **log file** (not a pipe) and the notebook never copied it into the outputs, and never probed the server between tasks | `adk_submission/server.py:272-276`; `src/g4agent/kaggle_kernel.py` (R004 version) |

## 2. HYPOTHESES vs EVIDENCE
| | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| A | Request never reached vLLM | **cannot distinguish from B/H with R004 artifacts** | no vLLM log (F10); no client error (F4) |
| B | Gemma returned but ADK never exposed it | not distinguishable; same for V1.2 tasks 7–12 | F1, F3 |
| C | V1.3 agent config caused an invalid/blocked request | **rejected** | F1 (V1.2 shows the identical failure first), F7, F8; an invalid request would return HTTP 400 at once, not hang 5.5 min (F4) |
| D | Tool registration broken in V1.3 | **rejected** | F8: same 13 tools; F1 |
| E | Skill configuration caused an init failure | **rejected** | F3 (agent ran, prompt rendered), F9, F1 |
| F | Context compaction hang | **unlikely**: compaction triggers on accumulated events; zero-call tasks never produced a first event | F3 |
| G | Model returned empty responses repeatedly | **rejected**: empty responses would end the turn (text-only response terminates the session) or count LLM calls; `llm_calls = 0` | F1 |
| H | Server/runner wedged before the first call | **supported**: server process alive but unresponsive to SIGTERM (F5), no responses for 2 h 45 min to any variant (F2), no errors (F4) | F2, F4, F5 |
| I | Sequential matrix contaminated later variants | **yes**: the wedged state from V1.2 task 7 carried over to every later task and variant | F1, F2 |
| J | Something specific to V1.3 | **no evidence** | F7, F8 |

## 3. CONCLUSION
**R004 says nothing about V1.3.** The zero-call condition began inside the V1.2 control at its 7th task
(rich_3063, 17:17:10Z) and then affected every remaining task of every variant. It is an
inference-path failure of the shared vLLM session (H + I), not a V1.3 configuration bug (C, D, E rejected).
The root cause of the wedge itself (vLLM engine hang vs client-side stall) cannot be determined from R004,
because the notebook neither kept the vLLM log nor probed the server directly (F10). The last event before it
was a 5.5-min cap cancelling an in-flight request during an identical-call loop (F6): a candidate trigger,
not a proven one.

Files responsible: `src/g4agent/kaggle_kernel.py` (one server for a long sequential matrix, no health check, vLLM
log discarded). Nothing in `agent.yaml`, `prompts/`, `skills/` of V1.3.

Fix applied (commit `2b13940`): before and after every task the notebook sends a direct 8-token request to
vLLM (bypassing ADK/LiteLLM) and records `ok`, latency and whether the process is alive; on a failed probe it
prints the vLLM log tail; the full vLLM log is saved as `g4_results/vllm_server.log`; each task row records
the first model response time. Runs can be pinned to explicit tasks without the gold-control phase.

## 4. Isolated re-runs (separate Kaggle kernels, fresh vLLM server each, same 3 tasks)
Tasks rich_2725, rich_2943, rich_3043; no gold-control phase; direct vLLM probe before/after each task.
Per-task table: `python3 scripts/smoke_summary.py evaluations/results/<EXP>`.

| | R005 V1.3 (archive `9f74b068…`) | R006 V1.2 (archive `b446da1c…`) |
|---|---|---|
| probes (before/after every task) | all ok, 0.08–0.09 s, server alive | all ok, 0.08–0.09 s, server alive |
| first model response | 18.0 / 4.1 / 3.7 s | 17.3 / 3.2 / 3.5 s |
| tool calls | 80 / 24 / 42 | 20 / 51 / 85 |
| first successful edit (call) | 79 (edit_file) / 13 (code-edit lines) / 14 (code-edit lines) | 14 / 46 / 65 (all edit_file) |
| resolved | rich_2725 ✓, rich_2943 ✓, rich_3043 ✗ (wrong fix) | rich_2725 ✓, rich_2943 ✓, rich_3043 ✗ (no patch at the call cap) |
| **V1.3 executes normally?** | **yes** | (control) |

**R005 conclusion:** with a healthy server, V1.3 makes real model calls and tool calls from the first step. This
confirms §3: R004's zeros came from the shared session, not from V1.3.

### What the real V1.3 traces showed about the edit channel (R005)
- **Skill loading works:** `load_skill("repo-navigation")` was the first call in 2 tasks; `code-edit`'s `edit.py` ran
  and returned `EDITED` diffs (4 successful `lines @/tmp/new.txt` edits).
- **Full chain verified on rich_2943** (resolved, 24 calls, 77 s): nav `find` → `show` → repro heredoc (fails as
  the issue describes) → `show __eq__` → heredoc `/tmp/new.txt` → `code-edit lines 664 666 @/tmp/new.txt`
  (EDITED) → repro passes → `tests.py related` → `tests.py run tests/test_style.py` (26 passed) → second
  `lines` edit → repro + tests → `review.py` → `submit_patch` (400 chars) → graded resolved.
- **Defect 1: steps merged.** In all 3 tasks the model sometimes put the step-b text `run_skill_script(...)`
  *inside* the step-a `run_command` (bash syntax error after the heredoc). The heredoc file was still written,
  and the next call made the edit, so this cost calls, not edits.
- **Defect 2: wrong range, resent identically.** rich_2725: `lines 867 867` split a multi-line statement;
  `edit.py` refused ("'(' was never closed"); the model resent the identical call 8× despite the repeat
  notice, then used `edit_file` at call 79 of 80 (resolved on the last calls).
- Fix (commit `48ca961`, archive `2091fc86…`): the prompt now says "two SEPARATE tool calls; the run_command
  contains only the heredoc", "START..END = all lines of the statement(s)", and "if code-edit refuses the same
  edit twice, re-read or use edit_file"; `edit.py` appends a HINT to parse refusals with the best-matching
  nearby line and the full START/END span of the enclosing statement(s). Unit-tested; official pipeline E008
  re-run on the new archive: resolved.

## 5. R007: V1.2 vs fixed V1.3, matched 8 tasks, separate kernels (fresh server each)
Tasks rich_3006, 3052, 3061, 3063, 3067, 3105, 3180, 3278 (the R005/R006 tasks were held out).
V1.2 archive `b446da1c…`; V1.3 archive `2091fc86…` (commit `48ca961`).

| | V1.2 (R007-v12-control) | V1.3 (R007-v13-root) |
|---|---|---|
| probes before/after every task | 16/16 ok (0.08–0.09 s) | 16/16 ok (0.08–0.09 s) |
| tasks with model output | 8/8 (first response 3.6–8.2 s) | 8/8 (first response 3.5–7.7 s) |
| resolved | **1/8** (rich_3006) | **2/8** (rich_3006, rich_3067) |
| tasks with a successful source edit | 3/8 (all edit_file) | 3/8 (2 via code-edit lines, 1 edit_file) |
| time-cap hits | 3 | 3 |

1 vs 2 of 8 is noise; R007 shows V1.3 **executes normally** and does not establish that it is better.

Edit-channel events in V1.3 (R007): 15 heredoc writes, of which **10 still contained the merged
`run_skill_script(...)` text** despite the prompt fix (open defect: costs one call each, the file is still written);
code-edit: 4 EDITED, 8 refused (3 refusals carried the new HINT). 5 of 8 tasks in *both* variants never landed an
edit: the dominant failure is still exploration without an edit, in V1.2 as much as in V1.3.
