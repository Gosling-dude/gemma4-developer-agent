# R015 research note: public solutions, the submission error, and why thinking is the lever (2026-10-11)

## Our public baseline (Kaggle API, `competitions submissions`)
| Ref | Date (UTC) | Public | Note |
|---|---|---|---|
| 56662595 | 09-29 | 0.06 | V1.1 (description says so) |
| 56695943 | 09-30 | 0.08 | V1.2 |
| 56869925 | 10-06 | 0.00 | file unknown; predates every R014 zip |
| 56900045 | 10-07 04:23 | **0.08** | showed "A system error…" for ~20 h, then completed; submitted 7 min after the R014 zip was created (very likely R014 `8a132847…`) |
| 56925859 | 10-08 00:19 | **0.08** | same error, then completed; likely the R014 resubmission |
| 56967270 | 10-08 18:46 | 0.06 | file unknown |

Kaggle stores no downloadable file, so the files behind these refs are inferred from timing and not proven.
Whatever was submitted, every one of our bundles has landed at 0.06–0.08.

**Local does not predict public.** Our 24-task screen gives R014 13/24 (54 %); its likely public score is 0.08
(about 5 of ~58 tasks, 8 %). V1.2 (about 41 % local) also scored 0.08. The 24 tasks come from the public practice repos
(rich, fastapi, requests); the scored set is about 120 tasks from other repositories.

## Submission error diagnosis
The R014 archive is valid:
- ZIP integrity passes; 27 regular files with `agent.yaml` at the root; no `.venv`, `__MACOSX`, symlinks or nested zips.
- It is byte-identical to the agent deployed in `g4-r014-v13-editfirst` and to a clean rebuild from `1ab7c6e`.
- Official `validate_directory` and `compile_submission` both pass.

The two "system error" submissions later completed (0.08, 0.08) with no resubmission of a changed file. The error was
Kaggle-side processing, which matches the staff note quoted in the public notebook below: queues of 20+ h, and one
pending submission per team since 8 Oct. No packaging change was needed.

## Public solutions examined (source pulled with `kaggle kernels pull`)
| Notebook | Reported public | Verified by others? | Architecture / config |
|---|---|---|---|
| verracodeguacas, *Budget-Fit Single Agent* | 0.18 | **Yes.** dmitriigluzdov reports the byte-identical archive scored 0.18 in their own submission (*Measure Before You Tune*) | one agent, 6 harness tools (graph tools registered but not used), **thinking on** (`include_thoughts: true`), T 0.2, 8192 max out; `eval_config` 8 min / 28 calls / 240 s / 80 turns; edit-by-call-12 prompt |
| honghanhhh, *Gemma 4 Baseline \| LB 0.24* | 0.24 (title) | no | Budget-Fit config unchanged; graph tools unregistered; "contract-first" prompt (copy exact strings, edit by call 12, one check, submit once an edit exists) |
| hitarthjain0, *What Took LB 0.12 → 0.24* | survey | partially: quotes a third-party ablation | collects Ayush Thakur's controlled 129-task ablation (discussion 746250) and staff thread 747519 |
| hitarthjain0, *Patch Berserker*; matterhorn3838, *SuperAgent* | 0.2x claims | no | same Budget-Fit config (thinking on, 8 / 28 / 240 / 80) |
| lucifer19, *Black Cat* | 0 | – | 5 min / 100 calls / 250 turns |
| romanrozen, *LB TOP 1* | 0.12 (09-23) | dmitriigluzdov: the identical zip scored 0.10 on 10-03 | analyzer + coder, graph tools |

Leaderboard (10-11): top 0.24; a large cluster at 0.20 (≥ 15 teams), which is consistent with Budget-Fit-derived bundles.

**Ablation (Ayush Thakur, discussion 746250, as quoted; 129 local tasks, single runs, faster GPUs; third-party, not
reproduced by us):**
- reference (thinking on, include_thoughts true): 48 / 129
- **thinking disabled: 23 / 129**
- summaries off (`include_thoughts: false` on a T 1.0 base): 35 vs 51
- tool budget 50 → 25 calls: −14
- analyzer sub-agent: +1
- temperature, top-p and thinking budget: within 0–3

**Mechanism, verified in the official source** (adk-submission `resolvers/generation.py`, `apply_thinking_config_to_model`):
- `include_thoughts: false` → `chat_template_kwargs.enable_thinking = False`
- `include_thoughts: true`, or `thinking_budget > 0` → `True`
- no `thinking_config` → the harness default injects `thinking_budget: 4096` → thinking **on**
- `thinking_budget` is not forwarded as a token limit

V1.1 through R014 all set `include_thoughts: false` (`configs/sampling.yaml`, comment dated V1.1). Thinking was turned off
because of a scorer bug in which thinking mode dropped thoughts between tool calls (host reply in discussion 744354; a vLLM
patch was deployed 09-29) and because of a fear of slow turns. It was never re-measured; our `variants/v1_think` ablation was
never run.

## What transfers and what does not
- **Thinking on (adopted for R015).** It needs no new tools, code or callbacks, and it is the one setting shared by every
  ≥ 0.18 bundle. It has the largest controlled effect in the ablation (about 2×). It is fully compatible with our harness:
  it is the harness default that we overrode.
- **Single agent, no graph tools.** The ablation measured the analyzer at +1, which is noise. Our localizer brought R012
  crashes, now fixed, but no public gain (R012-R014 all about 0.08 with thinking off). This is a separate, later hypothesis.
- **Budget 8 min / 28 calls.** It shifts the tool-call cap down by a factor of three (the ablation shows 50 → 25 calls cost
  14 tasks, so the cap is not innocuous) and raises the time cap. It interacts with the 12 h total. Not changed in R015, so
  that thinking stays the only variable. If R015's per-task duration rises with thinking on, this is the next lever.
- **Contract-first prompt / submit once an edit exists.** Not measured by anyone; prompt-only (R010 and R014 show our
  prompt rules are weakly followed). Deferred.

## Decision
R015 = R014 + `include_thoughts: true` in both sampling configs. That is one variable, verified as the setting that
separates our 0.06-0.08 bundles from every ≥ 0.18 public bundle and backed by the only controlled ablation available.
Expected risk: thinking makes each turn slower, so more 5.5-min caps and a higher mean duration. Both are measured.
