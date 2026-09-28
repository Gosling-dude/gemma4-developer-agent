# V1_BASELINE record

**Frozen at git tag `v1-baseline` (commit 48309a2, 2026-09-28).** Reproduce exactly with
`git checkout v1-baseline && scripts/package_submission.sh`. For ablations on current tooling, use
`variants/v1_baseline/` (the same agent.yaml, prompt, sampling and eval_config; current skill scripts, see Known issues).

| Item | V1_BASELINE | V1.1 (current root) |
|---|---|---|
| Model | `gemma-4-31b-it-qat-w4a16-ct` (all agents) | same |
| Agents | 1 root `LlmAgent` `swe_coder`, no sub-agents | same |
| Prompt | `prompts/system.md` @48309a2: 8-step workflow, term-selection rules, callee-following | + "one or two sentences before each call" (thinking off); + anti-repetition rule |
| Tools | all 9 harness tools | same |
| Skills | repo-navigation (`nav.py`), test-discovery (`tests.py`), debugging (`diagnose.py`, `review.py`) | same skills; workspace-resolution fix; review also flags whitespace-only/broad edits |
| Sampling | T 0.3, top_p 0.95, top_k 64, max_output 6144, `thinking_budget: 1024, include_thoughts: true` | same except **`include_thoughts: false`** |
| What the harness actually sends | `enable_thinking: true`, `max_completion_tokens: 6144`; the budget is **not** sent (VERIFIED, E005 request log) | `enable_thinking: false` |
| eval_config | 4.5 min, 40 calls, 60 turns, **timeout_seconds 120** | **5.0 min**, 60 calls, 80 turns, **300 s** |
| Graph tools | available; prompt: follow callees when the named API delegates | same |
| Expected behaviour | locate with nav.py → show → repro in /tmp → minimal edit → targeted tests → review → submit, in 12–20 calls | same, with visible short reasoning instead of hidden thinking |

## Known issues in V1_BASELINE (found this session, all fixed in V1.1)
1. **`timeout_seconds: 120` also caps the hidden-test pytest run in grading** (VERIFIED in `swegemma/harness/verification.py`).
   A correct patch on a slow test file could be graded as failed.
2. **Skills see an empty directory in the official subprocess sandbox** (Kaggle notebooks): `/workspace` doesn't exist there
   and ADK chdirs into a temp dir. VERIFIED with the official Evaluator (E005 before/after). The Docker scorer has
   `/workspace`, so real scoring was likely unaffected, but every Kaggle dev evaluation would have been.
3. `thinking_budget: 1024` was believed to cap thinking; it doesn't (VERIFIED). Thinking was uncapped up to 6144 tokens per turn.

## Scores
V1_BASELINE: **no real-model score exists.** Pipeline-only results (oracle/scripted) are in docs/experiments.md.
