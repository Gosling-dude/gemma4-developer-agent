# R021 Stage 1 (max_tool_calls 28 → 36): go/no-go, 2026-10-17

**Decision: NO-GO. No GPU work was done and no Kaggle kernel was pushed.** The only addition to the repository is this
record and its analysis script, on branch `experiment/r021-stage1-decision` (from `origin/experiment/r019-tool-loop-guard`).

Stage 1 fails three of the five conditions it was to be judged on: the protocol and environment cannot be
reproduced from this machine, quota and authorization cannot be confirmed, and the trace evidence that is available
does not support a credible gain in resolved tasks. A fourth (runtime) is at risk in the worst case. Section 6 lists
what would reopen the decision.

## 1. What could and could not be verified

| item | status | evidence |
|---|---|---|
| `docs/r021_failure_analysis.md` | **not found** | absent from every local worktree, every local and remote branch (fetched `origin` 2026-10-17), the whole home directory and every Claude Code transcript on this machine |
| R020 reports, traces, baseline (Arm A) results | **not found** | same search; `docs/r019.md` §7 (2026-10-14, the last committed record) ends "there is no R020"; GitHub's event log shows no R020/R021 branch ever pushed |
| Stage 1 protocol, thresholds, 39-task list, 12 refused-edit tasks | **not verifiable** | they exist only in the missing report |
| Candidate archive and hash | **not verifiable** | no R021 archive on this machine |
| Baseline archives | partly | R017 `~/Downloads/submission-r017.zip` = `51a6ef89…` ✓; R019 `03cb3f91…` zip is not on this machine (sources on `origin/experiment/r019-tool-loop-guard`) |
| Wheelhouse `metric/gemma-4-developer-agent-wheelhouse` | ✓ unchanged | public listing: 41 files, all created 2026-10-12 19:51; adk-submission 0.2.13, swegemma 0.2.11, google-adk 1.36.1, vllm 0.19.1 (the R018/R019 stack) |
| Docker image | ✓ pinned (R017/R019 metadata) | `gcr.io/kaggle-private-byod/python@sha256:37c64f7dd9c5…d461`, `NvidiaL4`, model `google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2` |
| Test-dependency dataset | **not verifiable** | R017/R019 kernels use only the wheelhouse, competition and model sources; this dataset is an R020/R021 addition |
| Repo state | ✓ preserved | R012–R019 branches and result directories untouched (R018/R019 fetched as `origin/...`); this record and `scripts/r021_cap36_check.py` are the only additions, on their own branch from R019's head |

R018 and R019 were pushed by collaborator `sumitxfermi` from another machine on 2026-10-14, so the R020/R021 work
presumably lives on that machine and was never pushed.

## 2. Quota and authorization

- **`sumitxory`: quota unknown.** The legacy API key in `~/.kaggle/kaggle.json` (saved 2026-09-30) is now
  rejected for every authenticated call (`kernels list --mine`: "Authentication required"; `kernels status` on the
  account's own R019 kernel: "Permission 'kernels.get' was denied"). Public calls work, so the API is up and the key
  has been revoked or rotated. It worked on 2026-10-12. As things stand, no kernel can be pushed from this machine either.
- **Teammate account: quota unknown, authorization unconfirmed.** There is no credential for it on this machine and
  no written record of the teammate's consent to use their quota.

Neither the pre-start quota requirement nor the teammate condition can be confirmed, so the run cannot start.

## 3. Would 28 → 36 resolve more issues, or only produce more edits?

Independent check on the 120 task-episodes held locally: R017 stored, R018, the R017 replicate in R018's kernel,
R019, and R019's R017 control, all on the same 24 gold-sound tasks. Computed by `scripts/r021_cap36_check.py` with
`scripts/trace_mechanics.py` counting rules.

**Refused edits are rare, and most of them are on tasks a landed edit does not fix.** 8 of 120 episodes had an edit
refused with `BudgetExceeded` (R017 3, R018 2, R018c 1, R019 **0**, R019c 2), on 5 distinct tasks:

| task | refused-edit episodes | resolved across the 5 runs | what more calls would buy |
|---|---:|---|---|
| rich_3105 | 1 | 0/5 | issue text is only "Fix #3104"; the model cannot find what to fix, so more calls mean more reads |
| rich_3468 | 1 | 0/5 (**wrong fix in 4/5**) | when the edit lands, it is wrong (exit-code contract not in the issue): more edits, no resolution |
| fastapi_14873 | 3 | 1/5 | flip task |
| rich_3470 | 2 | 2/5 | flip task |
| fastapi_15589 | 1 | 3/5 | flip task; the R017 refusal came with only 92 s of session time left |

Using each task's cross-run resolution rate as the chance that letting the refused edit through resolves it, the 7
unresolved refused-edit episodes are worth ≈ **1.6 resolutions over 5 runs, about +0.3 per 24 tasks**. The 12
refused-edit tasks the R021 report names would come to about **+2.7 at most** at the same rate (≈23 % per refused edit). That is an
optimistic figure: those rates come from runs where the model edited earlier with the full session left.

**There is a structural loss channel.** swegemma 0.2.11 attaches `budget_warning` when ≤ 10 calls remain
(`swegemma/tools/base.py:47`, relative to `max_tool_calls`). A 36-call cap moves the warning from call 18 to call 26.
The R019 prompt makes "your next call must be that edit" conditional on that warning. In 8 resolved episodes (1.6
per run) the first edit came straight after the warning (e.g. R019 rich_3480: edit at call 20, resolved at 27 calls,
484 s, already past the 8-min session cap). Delaying those edits by up to 8 calls risks losses on tasks that are
currently resolved. The 8-min session cap is unchanged, so extra calls compete with time on exactly the long tasks.

**Stage 1 cannot separate the expected effect from noise.** The unchanged R017 archive, run three times, disagrees
with itself on 5, 6 and 7 of 24 tasks (W3 L2, W3 L3, W3 L4), and 9/24 tasks flip across the five runs. Three of the five
refused-edit tasks are among those flips; the other two were never solved. Scaled to 39 paired tasks, run-to-run
noise alone gives about 9–10 discordant tasks, a standard deviation of about 3 on the net W−L. The optimistic expected
net (≤ +2.7 before losses) is under one standard deviation. If Arm B is compared with an Arm A from an earlier
kernel rather than a same-kernel control, the comparison carries all of that noise. A Stage 1 pass or fail would
mostly reflect noise, so its information value does not justify ≈8.7 GPU-hours.

"How many of the 12 refused edits now land" cannot be the success signal. With a higher cap, the harness accepts
those calls by construction; what matters is whether the tasks resolve.

## 4. Runtime (projected full run = 120 × mean + 15 min; gate 10.5 h ⇔ mean ≤ 307.5 s)

| behaviour profile | now | 36 cap, central estimate | 36 cap, worst case (cap-hit episodes run to 8 min) |
|---|---:|---:|---:|
| R017 stored | 9.79 h | 10.33 h | **11.67 h** |
| R018 | 8.83 h | 9.43 h | 9.91 h |
| R018c (R017 replicate) | 8.88 h | 9.17 h | 9.77 h |
| R019 | 9.18 h | 9.32 h | 9.81 h |
| R019c (R017 control) | 8.94 h | 9.90 h | **10.93 h** |

Central estimate: each episode that hit the 28 cap gets 8 more calls at its own recent call pace, up to the session cap.
That estimate is optimistic because it ignores the later warning lengthening other tasks. In the worst case 2 of 5
historical profiles exceed 10.5 h, and R017's central estimate is within 0.17 h of the gate.

## 5. The five conditions

| condition | result |
|---|---|
| quota meets the pre-start requirement plus margin | **cannot be confirmed** (sumitxory key rejected; no teammate credential) |
| exact environment and task list reproducible | **no**: protocol, task list, candidate and test-dependency dataset are not on this machine |
| credible chance of additional resolutions, not just more edits | **weak**: ≈ +0.3 per 24 tasks on local evidence, ≤ +2.7 on the report's 12 tasks before losses; 2 of 5 refused-edit tasks are never solved and one is a repeat wrong fix |
| projected runtime within 10.5 h | central yes (9.2–10.3 h); **worst case no** (up to 11.7 h) |
| information value worth the quota | **no**: expected net < 1 SD of paired noise at 39 tasks |

## 6. What would reopen the decision

1. The R020/R021 artifacts made available here, or this check rerun on the machine that has them: the report, the
   39-task list, the candidate and baseline archives with hashes, and the test-dependency dataset version.
2. A working Kaggle credential and a quota read for the account that will run, plus written consent from the
   teammate if theirs is used.
3. Evidence beyond refused-edit counts: e.g. the 12 tasks' resolution rates in runs where the edit did land.
   Without that, a resolution gain cannot be credible. The design also needs a same-kernel control. The harness
   fixes the warning at ≤ 10 calls remaining, so with a 36 cap the prompt's warning-keyed edit rule would have to be
   re-keyed; otherwise the cap change is confounded with a later edit trigger.
