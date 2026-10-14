# R017 (budget-fit) trace analysis: root variant, 24 tasks

Source: `evaluations/results/R017-budget-fit/g4_results/` (root_task_results.jsonl, root/traces, gold_control.jsonl). All facts below come from `extract.py` / `facts2.py` (run with `python3 -I`); the classifications are judgements made from the agent patch, the gold patch, and the grader's test tail.

**Call indexing:** call numbers are *budget-counted* calls. Calls that do not count are `submit_patch`, `get_status`, `list_skills`, `load_skill`, edit/write calls rejected for missing parameters, and calls rejected with BudgetExceeded. These rules reproduce `tool_calls` in the results file exactly for all 24 tasks.

## Per-task table

| task | resolved | calls | dur (s) | cap 28 | timeout 8m | first / last src edit | test/python after final edit (outcome) | submit (count) / after verification | scratch files in final patch | malformed edit/write calls / budget-rejected |
|---|---|---|---|---|---|---|---|---|---|---|
| fastapi_14873 | ❌ | 28 | 231.8 | yes | no | none | — | submit_patch ×1 / no | `` repro.py `` | 0 / 1 |
| fastapi_15589 | ❌ | 28 | 400.4 | yes | no | none | — | submit_patch ×1 / no | `` repro.py ``, `` repro_model.py `` | 0 / 1 |
| rich_3052 | ❌ | 28 | 396.5 | yes | no | 3 / 24 | #25 `python3 test_case_insensitive_preserves.py` exit=0 | submit_patch ×3 / yes | `` test_case_insensitive_preserves.py` `` | 0 / 0 |
| rich_3061 | ❌ | 26 | 198.4 | no | no | 25 / 25 | #26 `pytest tests/test_text.py -k test_tabs_to_spaces` exit=0 | submit_patch ×1 / yes | — | 0 / 0 |
| rich_3063 | ❌ | 27 | 371.3 | no | no | none | — | submit_patch ×1 / no | `` repro.py ``, `` repro_escape.py `` | 9 / 0 |
| rich_3105 | ❌ | 28 | 298.8 | yes | no | none | — | submit_patch ×1 / no | — | 0 / 0 |
| rich_3180 | ❌ | 24 | 483.6 | no | yes | none | — | none | `` repro.py ``, `` repro_disappear.py ``, `` repro_disappear_v2.py `` | 0 / 0 |
| rich_3468 | ❌ | 26 | 331.4 | no | no | 16 / 23 | #25 `python3 test_broken_pipe.py \| head -n 1` exit=0; #26 `python3 -c "from rich.console import Console; c = Console(); [c.print(` exit=0 | submit_patch ×1 / yes | — | 0 / 0 |
| rich_3470 | ❌ | 28 | 197.6 | yes | no | none | — | submit_patch ×1 / no | `` repro.py `` | 0 / 2 |
| rich_3471 | ❌ | 21 | 365.0 | no | no | 19 / 19 | #20 `python3 repro.py` exit=0 | submit_patch ×2 / yes | — | 0 / 0 |
| rich_3480 | ❌ | 20 | 723.0 | no | yes | 16 / 16 | — | none | `` reproduce_issue.py `` | 6 / 0 |
| fastapi_11194 | ✅ | 26 | 261.0 | no | no | 26 / 26 | — | submit_patch ×1 / no | `` reproduce_issue.py `` | 1 / 0 |
| fastapi_13537 | ✅ | 10 | 166.1 | no | no | 8 / 8 | #9 `pytest tests/test_repro_form_empty_string.py` exit=0 | submit_patch ×1 / yes | — | 0 / 0 |
| fastapi_14458 | ✅ | 20 | 230.3 | no | no | 12 / 14 | #15 `python3 repro.py` exit=0; #16 `python3 repro_gen.py` exit=0 | submit_patch ×2 / yes | — | 0 / 0 |
| fastapi_14786 | ✅ | 4 | 44.1 | no | no | 2 / 2 | #3 `cat > verify_fix.py <<'EOF' from fastapi.security.utils import get_aut` exit=0 | submit_patch ×1 / yes | — | 0 / 0 |
| fastapi_5077 | ✅ | 28 | 257.8 | yes | no | 15 / 23 | #25 `python3 tests/test_repro.py` exit=0 | submit_patch ×1 / yes | — | 0 / 0 |
| requests_6644 | ✅ | 28 | 261.7 | yes | no | 14 / 14 | #15 `python3 repro.py` exit=1; #22 `python3 repro.py` exit=1; #23 `python3 -c "from urllib.parse import urlsplit; print(f'Path: {urlsplit` exit=0; #26 `python3 debug_path.py` exit=0 | submit_patch ×1 / yes | `` debug_path.py ``, `` repro.py `` | 3 / 1 |
| rich_2725 | ✅ | 17 | 192.2 | no | no | 6 / 6 | #8 `python3 reproduce_issue.py` exit=1; #14 `python3 reproduce_issue.py` exit=1; #16 `python3 reproduce_issue.py` exit=0 | submit_patch ×2 / yes | — | 0 / 0 |
| rich_2943 | ✅ | 23 | 136.6 | no | no | 20 / 20 | #21 `python3 repro.py` exit=0; #22 `pytest tests/test_style.py` exit=0 | submit_patch ×2 / yes | — | 0 / 0 |
| rich_3006 | ✅ | 17 | 84.4 | no | no | 13 / 13 | #14 `python3 reproduce_issue.py` exit=0 | submit_patch ×2 / yes | — | 0 / 0 |
| rich_3043 | ✅ | 28 | 483.5 | yes | yes | 4 / 4 | #8 `pytest tests/test_console.py -k "test_export_html"` exit=1; #22 `pytest tests/test_console.py -k "test_export_html"` exit=1 | none | — | 0 / 0 |
| rich_3067 | ✅ | 17 | 136.9 | no | no | 12 / 12 | #13 `python3 repro.py` exit=0 | submit_patch ×1 / yes | — | 2 / 0 |
| rich_3278 | ✅ | 12 | 483.3 | no | yes | 11 / 11 | #12 `python3 repro.py` exit=0 | none | `` repro.py `` | 0 / 0 |
| rich_3454 | ✅ | 12 | 131.9 | no | no | 5 / 5 | #9 `pytest tests/test_highlighter.py` exit=1; #11 `pytest tests/test_highlighter.py` exit=0 | submit_patch ×1 / yes | — | 3 / 0 |

Notes: `requests_6644` was resolved by editing `src/requests/models.py`, while gold edits `src/requests/adapters.py`. That is a different location, but it still passed. `rich_3043` and `rich_3278` hit the 8-minute timeout and were still resolved, because their edit had landed earlier. The only finish tool used is `submit_patch`. Per the system prompt, the working tree is graded whether or not it is called.

## Unresolved tasks: shortfall classification

### rich_3052 (calls 28, 396.5 s, first src edit: 3)
**(b) wrong contract.** Issue: *"it would accept 'paul' or 'Paul' as valid responses"* and never says what is returned. Gold's `process_response` returns the canonical choice; hidden test `test_prompt_str_case_insensitive` expects `'foo'` for input `FoO` and got `'FoO'`. The agent's own test asserted the opposite (`test_case_insensitive_preserves_case`), so re-running its repro would not catch this. It also left a scratch file named with a backtick (`test_case_insensitive_preserves.py\``) that `rm` could not delete because of shell quoting, and it submitted three times.

### rich_3061 (calls 26, 198.4 s, first src edit: 25)
**(a) partial (with a (b) hidden-API part).** Issue: *"extending the style(s) on the tab to cover the new space characters"*. The agent added the tab's style as a separate span on the padding spaces. Gold extends the existing spans (new `Span.extend`/`Text.extend_style`), fixes the tab-stop arithmetic (`cell_len`, `% tab_size`), and changes the `tab_size` default to None. 12 hidden tests failed (10 `test_tabs_to_spaces_spans` exact-span cases, `test_extend_style` AttributeError, `test_panel::test_render_size`). First edit came at call 25 of 28, with only the existing `-k test_tabs_to_spaces` check (passed) after it. Re-running a repro would not have caught it.

### rich_3468 (calls 26, 331.4 s, first src edit: 16)
**(b) wrong contract.** Issue only says *"Handle BrokenPipe exceptions"*. The agent wraps the write in try/except and sets a `_broken_pipe` flag, so the error is swallowed and the process exits 0. Gold adds `on_broken_pipe()`, which dup2's stdout to devnull and `raise SystemExit(1)`. Hidden `test_brokenpipeerror` fails (`assert 1...`, i.e. exit code). **The agent's post-edit repro (calls 25 and 26) still printed `Exception ignored ... BrokenPipeError: [Errno 32] Broken pipe` on stderr**, and the agent submitted anyway. That output was a visible sign that handling was incomplete.

### rich_3471 (calls 21, 365.0 s, first src edit: 19)
**(c) wrong root cause/approach.** Issue: *"Fixed exception in append_tokens / Fixes #3014"* (no repro given). The agent guessed non-str content and added a `TypeError`. Gold applies `strip_control_codes(content)` so span offsets match the stripped text. Hidden `test_append_tokens` hits `IndexError` in `divide`. The agent's repro tested its own hypothesis (`(None, None)` tokens), so re-running it would show 'fixed'.

### rich_3480 (calls 20, 723.0 s, first src edit: 16)
**(e) out of budget mid-fix, which leaves it (a) partial.** Issue: *"fix infinite loop in append"*. The agent's repro hung, and the 240 s command timeout (call 10) used half the 8-minute budget. It then fixed `append` (`if text is self: text = text.copy()`), but its next 5 `edit_file` calls for `append_text` were malformed (missing `old_string`). The session hit the timeout at 723 s with no test run after the edit. Gold copies `_spans` in both `append` and `append_text`. The grader's test tail is empty, which fits a hang in the unfixed `append_text`. The repro covered only `append`, so re-running it would pass.

### fastapi_14873 (calls 28, 231.8 s, first src edit: none)
**No edit: exploration until the cap.** The issue states the cause and location (*"`APIRouter.on_startup` is set in `APIRouter.__init__` before calling `super().__init__` and is overridden"*). Even so, the agent used 28 calls reading `routing.py`/`applications.py`, 3 of them `read_file` calls with malformed keys (`start_line"`) that returned the file head. The edit at call 29 was rejected with `BudgetExceeded`.

### fastapi_15589 (calls 28, 400.4 s, first src edit: none)
**No edit: exploration and repro loop until the cap.** 4 repro scripts across calls 18–28. A concrete `fastapi/dependencies/utils.py` edit was attempted at call 29 and rejected with `BudgetExceeded`.

### rich_3470 (calls 28, 197.6 s, first src edit: none)
**No edit: exploration and repro iteration until the cap.** 4 rewrites of `repro.py`. Call 29 (grep) and call 30 (`edit_file` on `rich/console.py`) were both rejected with `BudgetExceeded`. The agent then said: *"I'm very confused. I didn't make any edits."*

### rich_3063 (calls 27, 371.3 s, first src edit: none)
**No edit: exploration, then malformed tool calls.** 27 counted calls went to escaping and regex experiments. The 28th call never landed: 9 consecutive `edit_file` calls were rejected because `old_string` was missing (malformed arguments, which do not count against the budget). The agent never switched to the code-edit skill.

### rich_3105 (calls 28, 298.8 s, first src edit: none)
**No edit: underspecified issue plus a search loop.** The issue body is only *"Fix #3104 … See #3104"*. The agent ran `grep/git log 3104` and similar searches more than 20 times, repeating the same commands, until the cap, then submitted an empty patch.

### rich_3180 (calls 24, 483.6 s, first src edit: none)
**No edit: 8-minute timeout.** 24 calls in 483 s (about 20 s per call, with gaps of 70–100 s between some turns). The agent wrote 3 repro scripts and read `_wrap.py`/`cells.py`/`text.py`, but never edited. Gold touches `rich/_wrap.py` and `rich/cells.py`.

## Aggregates

**Outcome:** 13 resolved, 11 unresolved. The 11 unresolved split into 5 wrong fixes and 6 with no source edit.

**Wrong-fix categories (5):**
| category | count | tasks |
|---|---|---|
| (a) partial | 1 | rich_3061 |
| (b) wrong contract | 2 | rich_3052 (return canonical choice), rich_3468 (exit code 1 / silence stderr) |
| (c) wrong location/approach | 1 | rich_3471 (guessed non-str input; real cause was control codes) |
| (d) regression | 0 | (rich_3061 also fails `test_panel::test_render_size`, but only because it lacks gold's `tab_size` default change, not because its edit broke something) |
| (e) out of budget mid-fix | 1 | rich_3480 (fixed `append`, not `append_text`; 240 s repro hang + 5 malformed edits → 723 s timeout) |

In 3 of the 5 wrong fixes (rich_3052, rich_3468, rich_3471) the deciding contract is **not in the issue text**: the issues are PR titles or "Fixes #NNNN" with no stated return value, exit code or root cause. The gold tests encode it.

**No-edit failures (6):**
| mechanism | tasks | calls used before stop |
|---|---|---|
| 28-call cap reached during exploration; a concrete edit was attempted at the cap and rejected with `BudgetExceeded` | fastapi_14873, fastapi_15589, rich_3470 | 28, 28, 28 |
| one call left, then 9 malformed `edit_file` calls (missing `old_string`) | rich_3063 | 27 (+9 rejected) |
| search loop on an underspecified issue ("Fix #3104") | rich_3105 | 28 |
| 8-minute timeout (slow turns) | rich_3180 | 24 |

So 4 of 6 no-edit tasks ended with an edit fully composed but never applied.

**Edit deadline (prompt: "By your 12th tool call you must have edited a source file"):**
- First source edit by call 12: resolved **8/13**; unresolved **1/11** (rich_3052 only); no-edit tasks 0/6.
- Median first-edit call: resolved 12 (range 2–26); unresolved-with-edit 16 (3, 16, 16, 19, 25).

**Budget hits:** 8 tasks used all 28 calls (3 resolved: rich_3043, fastapi_5077, requests_6644; 5 unresolved: rich_3052, fastapi_14873, rich_3105, fastapi_15589, rich_3470). 4 tasks hit the 8-minute limit (2 resolved: rich_3043, rich_3278; 2 unresolved: rich_3180, rich_3480).

**Scratch files:** 3 of the 13 resolved tasks shipped scratch files (rich_3278 `repro.py`; fastapi_11194 `reproduce_issue.py`; requests_6644 `repro.py`, `debug_path.py`). Grading ignored them. Among unresolved tasks, 7/11 had scratch files in the patch, but none of the failures is caused by them.

**Would re-running the agent's own repro after the final edit have caught the wrong fix?** Plausibly **1 of 5**: rich_3468, where the post-edit repro *did* still print `BrokenPipeError` and the agent submitted anyway. Not for rich_3052 (its own test asserted the opposite contract), rich_3061 (only a span-structure check would show it), rich_3471 (no repro in the issue; the agent's repro tested a wrong hypothesis), or rich_3480 (its repro covered only `append`, which was fixed). 4 of the 5 wrong fixes did run a test or repro after the final edit, and it passed or exited 0.

**Submit behaviour:** 20/24 called `submit_patch` (27 calls in total; rich_3052 called it 3 times and rich_2725, rich_2943, rich_3006, fastapi_14458, rich_3471 twice each). The 4 that never submitted (rich_3043, rich_3278, rich_3180, rich_3480) all ran out of time.

**Tool usage (all 24 traces, including non-counted calls):**
| tool | calls | error notes |
|---|---|---|
| run_command | 282 | 45 non-zero exit (CommandError), 1 TimeoutExceeded (240 s), 2 BudgetExceeded |
| read_file | 170 | 8 with malformed keys like `start_line\"` (silently returned the file head) |
| edit_file | 54 | **21 missing-`old_string` (malformed args)**, 3 BudgetExceeded, 1 FileEditError; 29 ok |
| write_file | 48 | 3 missing-param |
| submit_patch | 27 | — |
| get_status | 2 | — |
| load_skill | 2 | — |
| list_skills | 1 | — |
| run_skill_script (code-edit) | 1 | ok (rich_3468) |

15 of the 21 malformed `edit_file` calls came from two failed tasks (rich_3063: 9, rich_3480: 6).

## Most consequential failure mechanism

**The agent commits to a source edit too late, so the 28-call / 8-minute budget runs out before an edit lands or before there is room to iterate.** This is the proximate cause for 7 of 11 failures: all 6 no-edit tasks plus rich_3480. It also starved rich_3061 (first edit at call 25). Evidence:
- 0/6 no-edit tasks and 1/11 failures edited by call 12, versus 8/13 resolved tasks.
- 4 no-edit tasks had the edit composed at the very end. In 3 it was rejected with `BudgetExceeded` (fastapi_14873, fastapi_15589, rich_3470). In 1 it was blocked by malformed `edit_file` arguments (rich_3063).
- fastapi_14873's issue text named the exact bug location, yet 28 calls went to reading.
- Malformed `edit_file` calls (missing `old_string`, 21 in total) amplify the late commitment. They hit when there is no budget left to fall back to the code-edit skill, which was used only once.

Wrong-contract fixes (rich_3052, rich_3468) are second. In both, the contract lives in the hidden tests rather than the issue text, so verifying against the issue's repro would have rescued at most 1 (rich_3468).
