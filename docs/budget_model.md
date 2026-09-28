# Budget model

Labels: VERIFIED (host statement or official source code), MEASURED-LOCAL (measured here, different hardware),
3P (third-party report), ESTIMATE (planning number, not measured).

## 1. Global vs per-task budget

| Quantity | Value | Label / source |
|---|---|---|
| Global limit | **12 h**, covering agent phase + sandbox setup; **excluding** Phase-2 validation | VERIFIED: Evaluation page |
| Execution order | **sequential**, one task at a time | VERIFIED: host, discussion 743063 |
| Exceeding 12 h | **whole submission errors** (a fix to score unfinished tasks as 0 is "planned") | VERIFIED: host, 743063 |
| Per-task limit | whatever `eval_config.yaml` sets; a missing key means **no limit** | VERIFIED: host, 743063 |
| Enforcement | `asyncio.timeout(max_time_minutes*60)` around the whole agent loop, so in-flight model calls are cut too; the working tree is still graded | VERIFIED: `swegemma/harness/agent_runner.py` |
| Per-command timeout | `min(timeout_seconds, remaining time)`; **also caps the hidden-test pytest run in grading** | VERIFIED: `swegemma/tools/execution.py`, `harness/verification.py` |
| Skill scripts | same executor timeout, debited from the task budget | VERIFIED: `adk_eval_core/sandbox/base.py` |
| Hidden test tasks | about 120 (public LB = 58 of them) | VERIFIED data page; 58 is 3P inference |

## 2. Overheads

| Component | Value | Label |
|---|---|---|
| vLLM server start (31B W4A16, TP4) | ≤ 20 min timeout; the official notebook's full run (install + start + 2 tasks) took 944 s | VERIFIED timeout; ESTIMATE ~5–10 min |
| Whole run with no patches | ≈ 10 min (server start + all task setups) | VERIFIED: host, 743663 |
| Per-task setup (snapshot, editable install, baseline commit) | ≈ seconds (from the above: < 5 s/task) | ESTIMATE |
| Local official-Evaluator task incl. setup + verification (no model) | 1.8–4.0 s per rich task | MEASURED-LOCAL (E003) |
| Model retries | ModelRetryPlugin, ≤ 5 retries, backoff ≤ 60 s, **inside** the task timeout | VERIFIED (HARNESS_README; enforced by the asyncio timeout) |
| Cleanup / patch extraction | `git add -N . && git diff`, container reset: seconds | ESTIMATE |

## 3. Worst-case plan (what `eval_config.yaml` must guarantee)

Worst case = every task hits the cap:

    T_max = S_server + N_max x (c + s_task + e_task)
          = 15 min + 125 x (c + 0.1 min)

| cap c | T_max (N=125) | Fits 12 h (720 min) with >= 45 min margin? |
|---|---|---|
| 4.5 min (V1) | 600 min = 10.0 h | yes (2 h spare) |
| **5.0 min (V1.1)** | **652 min = 10.9 h** | **yes (68 min spare)** |
| 5.5 min | 715 min = 11.9 h | no (5 min spare) |
| 6.0 min | 777 min = 13.0 h | **no, would fail** |
| none (defaults) | unbounded | relies on the agent stopping early; public 0.12 runs did finish (≈ 14.5 h wall incl. ≈ 2 h validation, 3P) |

## 4. Evidence on the trade-off (3P)
- Pathfinder: 4-min cap scored 0.08; no cap scored 0.12.
- Walkthrough: a 12-min cap exceeded 12 h and failed.
- Black Cat: 4 min/24 calls 0.08; 5 min/40 calls (+ analyzer) 0.10.
Tight caps cost tasks, loose caps risk losing the whole submission. V1.1 uses the **largest worst-case-safe cap
(5.0 min)**.

## 5. What a real run must measure (then re-tune)
From `task_results.jsonl` of a real Kaggle run (duration_s, tool_calls, error = "Agent exceeded session timeout"):
1. the fraction of tasks hitting the cap, f;
2. the mean duration of tasks that stop by themselves, m;
3. expected total E[T] = S + N·(f·c + (1−f)·m + s).
Raise c only if the **worst case** still fits, or once the host's "unfinished = 0" fix is confirmed live. After that,
the expected total becomes the relevant constraint.

## 6. Thinking and per-turn time
`thinking_budget` is **not enforced** by the harness: only `enable_thinking` on/off is sent (VERIFIED,
`adk_submission/resolvers/generation.py` and the request logged in E005). With thinking on, a turn can emit up
to `max_output_tokens` (6144) tokens. At tens of tokens per second (ESTIMATE, unmeasured for 31B W4A16 on 4× L4),
that is minutes per turn, which doesn't fit a 5-minute task. V1.1 therefore turns thinking off; `variants/v1_think`
keeps the V1 behaviour for the ablation. **Decode speed is the first number to measure** (`scripts/check_model_endpoint.sh` prints tok/s).
