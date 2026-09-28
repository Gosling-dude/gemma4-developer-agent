# 🐈‍⬛ Black Cat SWE Agent | Pack Instinct
source: https://www.kaggle.com/code/lucifer19/black-cat-swe-agent-pack-instinct  votes=62 bestPublicScore=0.1 gpu=None runtime_s=19

# Hello Kaggle Community! 👋
# 🐈‍⬛ Black Cat SWE Agent | Pack Instinct
### The consensus challenger: what the leaderboard proves, plus what our lab measured

**Objective.** Beat our **0.10 public anchor**. This version combines two sources of evidence: what our own private lab measured over 209 agent runs with the official harness, and what the best public notebooks have in common on the leaderboard.

**The story so far**

| Version | What we tried | Public score | Lesson |
|---|---|---|---|
| First Strike | One agent, default budget | 0.06 | A working baseline |
| Compact Challenger | One agent, 4 min · 24 calls | 0.08 | A budget guard helps, and grep-first search is cheap |
| **Analyzer Challenger** (current anchor) | Coder + read-only analyzer, 5 min · 40 calls | **0.10** | A separate analyzer context pays off |
| Lab-Tuned Challenger (private) | One lean agent, temperature 1.0, 100 calls | 0.06 | It looked equal in the lab and lost about three tasks on the leaderboard |
| **Pack Instinct** (this version) | The anchor's design with the settings of the 0.12 notebooks, plus lab-proven prompt hygiene | *pending* | |

The Lab-Tuned experiment is the reason for this version's design. It changed the architecture *and* the sampling temperature at once, both against what the leaderboard favours, and it paid for it. This time we keep everything the leaderboard supports and change only what the evidence points to.

```python
from pathlib import Path
import hashlib, json, platform, re, zipfile
import yaml

WORKING = Path('/kaggle/working') if platform.system() == 'Linux' and Path('/kaggle/working').exists() else Path.cwd()
WORKING.mkdir(parents=True, exist_ok=True)
print(r"""
 /\_/\\
( o.o )  BLACK CAT // PACK INSTINCT
 > ^ <   keep what the leaderboard proves; fix what the traces show
         Chief Whisker Officer: "The pack hunts better than the lone cat."
""")
print(f'Python {platform.python_version()} | output: {WORKING}')
```
```
[output] 
 /\_/\\
( o.o )  BLACK CAT // PACK INSTINCT
 > ^ <   keep what the leaderboard proves; fix what the traces show
         Chief Whisker Officer: "The pack hunts better than the lone cat."

Python 3.12.13 | output: /kaggle/working

```

## 🔬 What our lab measured

We built a private lab from the hosts' [Getting Started notebook](https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent): the official `swegemma` Evaluator, vLLM on the same 4x L4 machine and Docker image, and the scoring compaction settings. It runs several agent bundles **side by side on the same 19 public tasks at the same time** and keeps every trace. Over three runs and ten variants, the traces showed five failure modes:

1. **Repetition loops.** Without thinking, Gemma often sends the *same* tool call 10 to 80 times. `git grep` with no match exits with code 1 and returns an error with an empty message, which is a common trigger.
2. **The 40-call budget runs out in about 100 seconds.** One model call takes 1.5–2 s, so our anchor rarely used its 5 minutes. Its analyzer used 60% of the calls.
3. **Malformed edit calls.** Edits containing regular expressions or backslashes came back as "mandatory input parameters are not present" and were resent dozens of times.
4. **Context overflow discards the patch.** Reading a whole test file of box-drawing characters added about 18k tokens in one step. Any harness exception other than a timeout drops the patch, even one that was already submitted.
5. **The 120 s command limit also caps the hidden-test run** (`verification.py`). A requests test file took 73 s in the lab, so a slower file could fail a correct patch.

We also learned the lab's limit. In 209 runs, the outcome depended on the *task*, not the variant: three tasks passed in 32 of 33 runs and sixteen never did. So the lab is good at finding failure modes and at checking runtime, but it cannot rank variants that differ by one or two tasks. The leaderboard does that.

## 🏆 What the best public notebooks share

| Notebook | Score | Design | Sampling | Per-task budget |
|---|---|---|---|---|
| [GEMMA: EDA, Baseline for a start](https://www.kaggle.com/code/romanrozen/gemma-eda-baseline-for-a-start-lb-top-1) (romanrozen) | **0.12** | Coder + analyzer | T 0.2 · top-k 40 · 8,192 tokens · thinking off | No `eval_config.yaml`: scorer defaults of 100 calls, 300 s commands, 60 min |
| [Pathfinder](https://www.kaggle.com/code/mizeroluckygall/pathfinder-gemma-4-agent-eda-baseline) (mizeroluckygall) | **0.12** | Coder + analyzer | T 0.2 · top-k 40 · 8,192 tokens · thinking off | Defaults. **Its v1 with a hard 4-minute limit scored 0.08** |
| [Walkthrough & First Submission](https://www.kaggle.com/code/zhukovoleksiy/gemma-4-walkthrough-first-submission) (zhukovoleksiy) | 0.10 | Coder + analyzer | T 0.2 · top-k 40 · thinking off | Defaults. A later version **with up to 12 minutes per task exceeded the 12-hour limit** and moved to 4 minutes |
| [0.10 submission](https://www.kaggle.com/code/nihilisticneuralnet/0-10-gemma-4-developer-agent-submission) (nihilisticneuralnet) | 0.10 | One lean agent | T 0.15 | 4.5 min · 40 calls |

Three lessons stand out. Coder + analyzer at T 0.2 is behind every score above 0.10. Short hard time limits cost score (Pathfinder v1 → v2). A long per-task time limit can still blow the 12-hour budget (zhukovoleksiy), while the notebooks that ran on the scorer's defaults (100 tool calls, 300 s commands) stayed inside it.

## ⚙️ Pack Instinct: the consensus challenger

| Area | 0.10 anchor | Challenger | Evidence |
|---|---|---|---|
| Architecture | Coder + read-only analyzer | **Unchanged** | Every public score above 0.10; our lean experiment lost about three tasks |
| Sampling | T 0.2 · top-k 40 · 4,096 tokens | T 0.2 · top-k 40 · **8,192 tokens** | Both 0.12 notebooks |
| Tool calls | 40 | **100** (the scorer's default) | 40 calls ran out after about 100 s; both 0.12 notebooks use 100 |
| Command / verification timeout | 120 s | **300 s** (the scorer's default) | `timeout_seconds` also caps the hidden-test run |
| Time per task | 5 min | **8 min safety cap** | 100 calls usually end sooner. The cap only stops pathological tasks, such as repeated 300 s commands, so 120 tasks stay inside 12 hours |
| Turns | 100 | 150 | Stops a model that keeps talking without tools |
| Search | `git grep` | `git grep` with an explicit `NO MATCHES` marker, plus "never repeat a call" | Repetition loops were the most common failure |
| Reading | Narrow ranges suggested | `start_line`/`end_line` mandatory, at most about 80 lines; tests are listed first | Whole-file reads caused overflow crashes, and the analyzer has no compaction of its own |
| Malformed calls, git history, reproduction | No rules | Do not resend malformed calls; never search `git log` for the fix; reproduction at most two calls, with no multi-statement `python3 -c` | Each one was a measured loop in the traces |
| Issue reading | Skip PR templates | Also: exact names from the issue, small fixes, `docs_src/` counts as code | Pathfinder's data-driven rules |

## 🧪 Smoke test in the lab

The challenger ran next to the anchor on the same 19 tasks, with the official harness. The aim is to check for crashes and runtime, not to rank the two (see the lab's limit above).

| Variant | Resolved | With a patch | Repeat loops (≥5×) | Crashes | Mean tool calls | Mean seconds | Max seconds |
|---|---|---|---|---|---|---|---|
| 0.10 anchor (5 min · 40 calls · 120 s) | **3/19** | 11 | 9 | 1 | 28 | 158 | 604 |
| Pack Instinct (8 min · 100 calls · 300 s) | **3/19** | 12 | 13 | 0 | 74 | 258 | 708 |

What the smoke test shows:
- **Crashes:** the challenger had 0, the anchor 1. The anchor's crash was a context overflow that discarded its patch.
- **Patches:** the challenger produced 12 against the anchor's 11. Both resolved the same three tasks, as the lab's limit predicts.
- **Runtime:** at the challenger's lab average of 258 s per task, including setup and verification, 120 hidden tasks would take about **8.6 hours**. Patch verification does not count toward the 12-hour limit. The lab also runs two agents at once on one GPU server, so the scorer's one-at-a-time runs should be faster.
- **Repeat loops remain common at T 0.2** (13 of 19 runs). The anti-repetition rules reduce them only at higher temperatures, which the leaderboard punished. With 100 calls, a loop costs time but still ends at the call cap.

```python
CHALLENGER = {'agent.yaml': 'name: black_cat_coder\nmodel: gemma-4-31b-it-qat-w4a16-ct\ndescription: Fixes one repository issue with a small, verified source patch.\ninstruction: !include prompts/system.md\ntools:\n  - run_command\n  - read_file\n  - edit_file\n  - write_file\n  - get_status\n  - submit_patch\n  - get_code_neighbors\n  - search_similar_code\n  - get_code_subgraph\n  - agent_tool:\n      config_path: sub_agents/code_analyzer.yaml\n      skip_summarization: true\ngenerate_content_config: !include configs/sampling.yaml\n', 'sub_agents/code_analyzer.yaml': 'name: code_analyzer\nmodel: gemma-4-31b-it-qat-w4a16-ct\ndescription: Read-only code navigator. It already knows the issue; returns the exact fix location, root cause, fix plan and closest tests.\ninstruction: !include ../prompts/analyzer.md\ntools:\n  - run_command\n  - read_file\n  - get_code_neighbors\n  - get_code_subgraph\ngenerate_content_config:\n  temperature: 0.1\n  top_p: 0.95\n  top_k: 40\n  max_output_tokens: 2048\n  thinking_config:\n    include_thoughts: false\n', 'configs/sampling.yaml': 'temperature: 0.2\ntop_p: 0.95\ntop_k: 40\nmax_output_tokens: 8192\nthinking_config:\n  include_thoughts: false\n', 'prompts/system.md': 'You are Black Cat, an autonomous software engineer fixing one issue in the Python repository at /workspace. Nobody will answer questions. Work with your tools until a fix is in place, then call `submit_patch()`.\n\n## How you are graded\n- Hidden tests run against your source changes in a fresh checkout; the task passes only if pytest exits 0. A careful best-effort fix beats an empty patch.\n- The hidden tests call the exact names, parameters, defaults, exception types and messages the issue describes. Use exactly the names and spelling the issue gives, and implement the requested behaviour completely, including the edge cases it mentions.\n- If time or tool calls run out, the working tree is graded as it is. Never revert a plausible fix.\n- Test files, `pytest.ini`, `conftest.py`, `pyproject.toml`, `setup.cfg` and `tox.ini` are reset before grading, so editing them never helps. Fix the source code.\n\n## Sandbox facts\n- Offline, dependencies already installed. Never install packages.\n- Available: git, grep, find, sed, awk, python3. NOT available: `rg` (ripgrep) and `tree`.\n- Search so that a miss is explicit: `(git grep -n "text" -- \'*.py\' || echo "NO MATCHES") | head -20`\n- `run_command` output is cut to its FIRST 5,000 characters. Always pass `start_line` and `end_line` to `read_file`, at most about 80 lines; never read a whole file. Test files can be huge: list them first with `grep -n "def test_" tests/test_x.py | head -30`, then read one test.\n- `read_file`, `write_file` and `edit_file` only work inside /workspace. Create scratch files in /tmp with `run_command`, never inside /workspace.\n- Git history stops at the base commit, so the fix is not in `git log`. Never search the history for it.\n- The context window is small (32k tokens) and older tool outputs get summarized. After each important finding, write one line of plain text: file:line, what it means, next step.\n- `get_status()` and `submit_patch()` are free.\n\n## Never repeat yourself\n- Never send the same tool call twice; an unchanged command returns the same output and wastes the budget.\n- Empty output, `NO MATCHES`, or exit code 1 with an empty message from `grep`/`git grep` means the text does not exist. Do not retry it: search a shorter substring, a related name from the issue, or list files with `git ls-files \'*.py\' | grep -i keyword | head -20`.\n- If a tool reports missing mandatory parameters, your call was malformed, usually by quotes, backslashes or regex characters. Do not resend it: make a smaller edit whose strings avoid those characters at their edges.\n\n## Workflow\n1. Understand. State the expected and the actual behaviour in one or two sentences. Many issues are pasted pull-request descriptions: ignore checklists and template text; the title, code snippets, error text and API names are the specification.\n2. Localize. Call `code_analyzer` once. Its request should be one short sentence with the key identifiers from the issue; it already has the full issue text and answers with LOCATION, ROOT CAUSE, FIX PLAN and TESTS. Skip it only when the issue names the exact file and function to change. Confirm its answer by reading those lines. If it is unsure or wrong, search yourself with the command above.\n3. Reproduce, if it takes at most two tool calls. Write the script with a heredoc and run it in the same command:\n   `cat > /tmp/repro.py << \'EOF\'` ... `EOF` then `python3 /tmp/repro.py 2>&1 | tail -n 20`. Never use `python3 -c` for more than one statement. If the script fails for a reason unrelated to the bug, drop it and go to the fix.\n4. Fix. Before each edit, state in one or two sentences what you will change and why. Use `edit_file` with an `old_string` copied exactly from the file, including indentation and without line-number prefixes; keep it short but unique. Fix the root cause and keep public signatures backward compatible. Most real fixes change one file and about a dozen lines; several small coordinated edits are fine, one huge edit can be cut off. Code under `docs_src/` counts as source when the issue is about it.\n5. Verify in one command, saving output to /tmp and reading its end, because test verdicts are printed last:\n   `python3 -m py_compile path/to/changed.py && python3 -m pytest tests/test_x.py -q -x -p no:anyio -o timeout=0 > /tmp/t1.log 2>&1; tail -n 25 /tmp/t1.log`\n   Never run bare `pytest` or a whole test suite. Existing failures unrelated to your change (missing fixtures, network, imports) are not your problem; do not touch test code. If your reproduction still fails, revise the same source change.\n6. Submit. Run `git status --short` and `git diff | head -150`. Remove anything unintended from /workspace. Call `submit_patch()` as your last tool call, then reply with one line on what changed and what you verified.\n\n## Tool rules\n- Never call `search_similar_code`: each result carries the full source of whole classes (often over 100,000 characters), which overflows your context and loses the task.\n- `get_code_neighbors` and `get_code_subgraph` only know synchronous "calls" edges and no async functions. Never pass `edge_type`. If a graph tool errors, stop using it and use `git grep`.\n\n## Pace\n- The tool-call budget is shared with `code_analyzer`. Call `get_status()` after about 10 tool calls and again before verifying.\n- Aim to have your first edit in place by the halfway point. When about a quarter of the time or tool calls remains, stop exploring: finish the edit, compile, check the diff and submit.\n', 'prompts/analyzer.md': 'You are `code_analyzer`, a read-only code navigator for the Python repository at /workspace. You never modify files. The coder sends you a short request; the full issue is at the end of these instructions. Find exactly where the issue must be fixed, then answer.\n\n## Tools\n- `run_command` for read-only commands only. Search so that a miss is explicit: `(git grep -n "text" -- \'*.py\' || echo "NO MATCHES") | head -20`. Also `sed -n \'START,ENDp\' FILE`, `ls`, `git ls-files \'*.py\' | grep -i keyword | head -20`. `rg` and `tree` are not installed. Output is cut to its first 5,000 characters.\n- `read_file` always with `start_line` and `end_line`, at most about 80 lines. Never read a whole file; your context is small and is never compacted.\n- `get_code_neighbors` and `get_code_subgraph` only know synchronous "calls" edges and no async functions. Never pass `edge_type`. If a graph tool errors, stop using it.\n- Never send the same call twice. `NO MATCHES` or empty output means the text does not exist: search a different name instead of retrying. Git history stops at the base commit, so never search `git log` for the fix.\n\n## Method (at most 6 tool calls)\n1. Extract identifiers from the issue: function and class names, error messages, option and parameter names, file paths, and any new names the issue asks for. Ignore pull-request template text such as checklists.\n2. Search for the most specific identifier first. Follow the code to the line where the behaviour diverges from what the issue expects. For a feature request, find where the closest existing feature is implemented and where the new behaviour must plug in.\n3. Find the existing test file that covers that code.\n4. Confirm by reading the code. Never guess line numbers.\n\n## Answer (at most 200 words, nothing else)\nLOCATION: path:start-end (function or class)\nROOT CAUSE: one or two sentences\nFIX PLAN: the concrete change, using the exact names the issue uses and covering the edge cases it names\nRELATED: other places needing the same change, or none\nTESTS: existing test file(s) for this code\nCONFIDENCE: high | medium | low\n\n## The issue\n{problem_description?}\n', 'eval_config.yaml': 'evaluation:\n  timeout_seconds: 300\n  max_tool_calls: 100\n  max_time_minutes: 8\n  max_turns: 150\n'}
ANCHOR = {'agent.yaml': 'name: black_cat_coder\nmodel: gemma-4-31b-it-qat-w4a16-ct\ndescription: Fixes one repository issue with a small, verified source patch.\ninstruction: !include prompts/system.md\ntools:\n  - run_command\n  - read_file\n  - edit_file\n  - write_file\n  - get_status\n  - submit_patch\n  - get_code_neighbors\n  - search_similar_code\n  - get_code_subgraph\n  - agent_tool:\n      config_path: sub_agents/code_analyzer.yaml\n      skip_summarization: true\ngenerate_content_config: !include configs/sampling.yaml\n', 'sub_agents/code_analyzer.yaml': 'name: code_analyzer\nmodel: gemma-4-31b-it-qat-w4a16-ct\ndescription: Read-only code navigator. It already knows the issue; returns the exact fix location, root cause, fix plan and closest tests.\ninstruction: !include ../prompts/analyzer.md\ntools:\n  - run_command\n  - read_file\n  - get_code_neighbors\n  - get_code_subgraph\ngenerate_content_config:\n  temperature: 0.1\n  top_p: 0.95\n  top_k: 40\n  max_output_tokens: 2048\n  thinking_config:\n    include_thoughts: false\n', 'configs/sampling.yaml': 'temperature: 0.2\ntop_p: 0.95\ntop_k: 40\nmax_output_tokens: 4096\nthinking_config:\n  include_thoughts: false\n', 'prompts/system.md': 'You are Black Cat, an autonomous software engineer fixing one issue in the Python repository at /workspace. Nobody will answer questions. Work with your tools until a fix is in place, then call `submit_patch()`.\n\n## How you are graded\n- Hidden tests run against your source changes in a fresh checkout; the task passes only if pytest exits 0. A careful best-effort fix beats an empty patch.\n- If time or tool calls run out, the working tree is graded as it is. Never revert a plausible fix.\n- Test files, `pytest.ini`, `conftest.py`, `pyproject.toml`, `setup.cfg` and `tox.ini` are reset before grading, so editing them never helps. Fix the source code.\n\n## Sandbox facts\n- Offline, dependencies already installed. Never install packages.\n- Available: git, grep, find, sed, awk, python3. NOT available: `rg` (ripgrep) and `tree`. Search with `git grep -n`.\n- `run_command` output is cut to its FIRST 5,000 characters. `read_file` returns at most 150 lines or 10,000 characters, so request narrow line ranges.\n- `read_file`, `write_file` and `edit_file` only work inside /workspace. Create scratch files in /tmp with `run_command`, never inside /workspace.\n- The context window is small (32k tokens). Every long output brings you closer to a crash that discards your work, so keep outputs short.\n- `get_status()` and `submit_patch()` are free.\n\n## Workflow\n1. Understand. State the expected and the actual behaviour in one or two sentences. Some issues are pull-request descriptions: skip checklists and template text, keep the substance. Note exact names, messages and values.\n2. Localize. Call `code_analyzer` once. Its request should be one short sentence with the key identifiers from the issue; it already has the full issue text and answers with LOCATION, ROOT CAUSE, FIX PLAN and TESTS. Skip it only when the issue names the exact file and function to change. Confirm its answer by reading those lines (at most about 60 lines per `read_file`). If it is unsure or wrong, search yourself: `git grep -n "identifier" -- \'*.py\' | head -20`.\n3. Reproduce when it is cheap. Write the script with a heredoc and run it in the same command:\n   `cat > /tmp/repro.py << \'EOF\'` ... `EOF` then `python3 /tmp/repro.py 2>&1 | tail -n 20`.\n4. Fix. Before each edit, state in one or two sentences what you will change and why. Use `edit_file` with an `old_string` copied exactly from the file, including indentation and without line-number prefixes; keep it short but unique. Fix the root cause, handle every edge case the issue names, and keep public signatures backward compatible. Several small coordinated edits are fine; one huge edit can be cut off. Code under `docs_src/` counts as source when the issue is about it. Create a new file only when the requested feature needs one.\n5. Verify in one command, saving long output to /tmp and reading its end, because test verdicts are printed last:\n   `python3 -m py_compile path/to/changed.py && python3 -m pytest tests/test_x.py -q -x -p no:anyio -o timeout=0 > /tmp/t1.log 2>&1; tail -n 25 /tmp/t1.log`\n   Find the closest tests with `git grep -l "name" -- \'tests/*.py\' | head`. Never run bare `pytest` or a whole test suite. Existing failures unrelated to your change (missing fixtures, network, imports) are not your problem; do not touch test code. If your reproduction still fails, revise the same source change once.\n6. Submit. Run `git status --short` and `git diff | head -150`. Remove anything unintended from /workspace. Call `submit_patch()` as your last tool call, then reply with one line on what changed and what you verified.\n\n## Tool rules\n- Never call `search_similar_code`: each result carries the full source of whole classes (often over 100,000 characters), which overflows your context and loses the task.\n- `get_code_neighbors` and `get_code_subgraph` only know synchronous "calls" edges and no async functions. Never pass `edge_type`. If a graph tool errors, stop using it and use `git grep`.\n- If the same call fails twice, change method; for example read lines with `sed -n \'START,ENDp\' FILE` instead of `read_file`.\n- Keep every output short: `head`, `tail`, `grep -n`, `pytest -q`. Never print whole large files.\n\n## Pace\n- The budget is shared with `code_analyzer`. Call `get_status()` after about 8 tool calls and again before verifying.\n- Aim to have your first edit in place by the halfway point. When about a quarter of the time or tool calls remains, stop exploring: finish the edit, compile, check the diff and submit.\n', 'prompts/analyzer.md': 'You are `code_analyzer`, a read-only code navigator for the Python repository at /workspace. You never modify files. The coder sends you a short request; the full issue is at the end of these instructions. Find exactly where the issue must be fixed, then answer.\n\n## Tools\n- `run_command` for read-only commands only: `git grep -n "text" -- \'*.py\' | head -20`, `grep -rn`, `sed -n \'START,ENDp\' FILE`, `ls`, `git log --oneline -5 -- FILE`. `rg` and `tree` are not installed. Output is cut to its first 5,000 characters, so always pipe searches through `head`.\n- `read_file` with tight line ranges (at most about 80 lines). It only accepts paths inside /workspace.\n- `get_code_neighbors` and `get_code_subgraph` only know synchronous "calls" edges and no async functions. Never pass `edge_type`. If a graph tool errors, stop using it.\n\n## Method (at most 6 tool calls)\n1. Extract identifiers from the issue: function and class names, error messages, option and parameter names, file paths. Ignore pull-request template text such as checklists.\n2. Search for the most specific identifier first. Follow the code to the line where the behaviour diverges from what the issue expects. For a feature request, find where the closest existing feature is implemented and where the new behaviour must plug in.\n3. Find the existing test file that covers that code.\n4. Confirm by reading the code. Never guess line numbers.\n\n## Answer (at most 200 words, nothing else)\nLOCATION: path:start-end (function or class)\nROOT CAUSE: one or two sentences\nFIX PLAN: the concrete change, including edge cases named in the issue\nRELATED: other places needing the same change, or none\nTESTS: existing test file(s) for this code\nCONFIDENCE: high | medium | low\n\n## The issue\n{problem_description?}\n', 'eval_config.yaml': 'evaluation:\n  timeout_seconds: 120\n  max_tool_calls: 40\n  max_time_minutes: 5\n  max_turns: 100\n'}
FALLBACK = {'agent.yaml': 'name: black_cat_fallback\nmodel: gemma-4-31b-it-qat-w4a16-ct\ninstruction: !include prompts/system.md\ntools: [run_command, read_file, edit_file, get_status, submit_patch]\ngenerate_content_config:\n  temperature: 0.1\n  max_output_tokens: 4096\n  thinking_config:\n    include_thoughts: false\n', 'prompts/system.md': 'Solve the issue in /workspace. Inspect the relevant source, make a focused change, run a small check, inspect git diff, and call submit_patch(). Do not edit tests or harness files.\n', 'eval_config.yaml': 'evaluation:\n  timeout_seconds: 300\n  max_tool_calls: 40\n  max_time_minutes: 4\n  max_turns: 40\n'}
ANCHOR_SHA256 = '18b20200ba4a42f99ecaa0c889664ead4b78848835317bc114f4e4095f759916'

```

## 🛡️ Validator and packaging

The offline validator checks:
- paths, file types and YAML parsing,
- that `!include` and `config_path` targets resolve inside the bundle,
- the model alias, registered tools, and read-only sub-agents,
- ADK state placeholders: an unknown `{name}` in an instruction raises `KeyError` at run time,
- that no prompt tells the agent to run `rg`, which is not installed.

Archives are deterministic, and the anchor is checked byte for byte against the archive that scored 0.10. The challenger was also compiled and run by the official harness in the lab.

```python
import posixpath

class IncludeLoader(yaml.SafeLoader):
    pass

IncludeLoader.add_constructor('!include', lambda loader, node: loader.construct_scalar(node))
MODEL = 'gemma-4-31b-it-qat-w4a16-ct'
ALLOWED = {'.yaml', '.yml', '.md', '.txt', '.py', '.json', '.safetensors'}
REGISTERED_TOOLS = {'run_command', 'read_file', 'edit_file', 'write_file', 'get_status',
                    'submit_patch', 'get_code_neighbors', 'search_similar_code', 'get_code_subgraph'}
WRITE_TOOLS = {'edit_file', 'write_file', 'submit_patch'}
ADK_PLACEHOLDER = re.compile(r'(?<![\$\{\\]){+[^{}]*}+')    # same pattern ADK uses for state injection
ALLOWED_STATE = {'problem_description'}

def resolve(name, ref):
    """`!include` paths are relative to the including file."""
    return posixpath.normpath(posixpath.join(posixpath.dirname(name), ref))

def check_instruction(owner, text):
    for match in ADK_PLACEHOLDER.finditer(text):
        var = match.group().strip('{}').strip().removesuffix('?')
        assert not var.isidentifier() or var in ALLOWED_STATE, f'{owner}: unknown state placeholder {match.group()}'
    assert not re.search(r'(^|[`\s(])rg\s+-', text), f'{owner}: tells the agent to run rg, which is not installed'

def check_agent(files, name, root):
    agent = yaml.load(files[name], Loader=IncludeLoader)
    assert agent['model'] == MODEL, (name, agent['model'])
    instruction = agent['instruction']
    instruction = files[resolve(name, instruction)] if resolve(name, instruction) in files else instruction
    check_instruction(name, instruction)
    names = [t for t in agent['tools'] if isinstance(t, str)]
    assert set(names) <= REGISTERED_TOOLS, (name, set(names) - REGISTERED_TOOLS)
    if root:
        assert 'submit_patch' in names, 'root agent must be able to submit'
    else:
        assert not set(names) & WRITE_TOOLS, f'{name}: sub-agent must stay read-only'
    config = agent.get('generate_content_config')
    if isinstance(config, str):
        config = yaml.safe_load(files[resolve(name, config)])
    assert 0 < config['max_output_tokens'] <= 8192, (name, config['max_output_tokens'])
    assert config.get('thinking_config', {}).get('include_thoughts') is False, f'{name}: thinking must stay off'
    subs = [t['agent_tool']['config_path'] for t in agent['tools'] if isinstance(t, dict)]
    for sub in subs:
        assert sub in files, (name, sub)       # config_path is relative to the bundle root
        check_agent(files, sub, root=False)
    return 1 + len(subs)

def package(files, output):
    assert 'agent.yaml' in files and len(files) <= 10000
    for name, content in files.items():
        path = Path(name)
        assert not path.is_absolute() and '..' not in path.parts and path.suffix in ALLOWED
        assert isinstance(content, str) and content.strip()
    for name, content in files.items():
        if name.endswith(('.yaml', '.yml')):
            yaml.load(content, Loader=IncludeLoader)
        for include in re.findall(r'!include\s+([^\s]+)', content):
            assert resolve(name, include) in files, (name, include)
    agents = check_agent(files, 'agent.yaml', root=True)
    budget = yaml.safe_load(files['eval_config.yaml'])['evaluation']
    assert 0 < budget['max_time_minutes'] <= 8 and 0 < budget['max_tool_calls'] <= 100
    assert 0 < budget['max_turns'] <= 150 and 0 < budget['timeout_seconds'] <= 300
    with zipfile.ZipFile(output, 'w') as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, content.encode('utf-8'))
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert sorted(archive.namelist()) == sorted(files)
        assert all(archive.read(name) == files[name].encode('utf-8') for name in files)
    return output, agents

for bad, reason in [('Use {hints} here.', 'placeholder'), ('Run `rg -n foo`.', 'rg')]:
    try:
        check_instruction('self-test', bad)
    except AssertionError:
        pass
    else:
        raise AssertionError(f'validator missed the {reason} case')

primary_path, n_agents = package(CHALLENGER, WORKING / 'submission.zip')
anchor_path, _ = package(ANCHOR, WORKING / 'anchor_submission.zip')
fallback_path, _ = package(FALLBACK, WORKING / 'fallback_submission.zip')
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert sha(anchor_path) == ANCHOR_SHA256, 'anchor archive differs from the one that scored 0.10'

budget = yaml.safe_load(CHALLENGER['eval_config.yaml'])['evaluation']
sampling = yaml.safe_load(CHALLENGER['configs/sampling.yaml'])
manifest = {
    'selected': primary_path.name, 'sha256': sha(primary_path), 'agents': n_agents,
    'budget': budget, 'sampling': sampling,
    'anchor': {'archive': anchor_path.name, 'sha256': ANCHOR_SHA256, 'public_score': 0.10},
    'challenger_score': None,
}
(WORKING / 'experiment_card.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('✅ FINAL PACKAGE CHECK PASSED')
for path in (primary_path, anchor_path, fallback_path):
    print(f'📦 {path.name}: {path.stat().st_size:,} bytes | sha256 {sha(path)[:16]}…')
print(f'Agents: {n_agents} | budget: {budget} | temperature: {sampling["temperature"]}')
```
```
[output] ✅ FINAL PACKAGE CHECK PASSED
📦 submission.zip: 5,278 bytes | sha256 d2575a4ea9c85943…
📦 anchor_submission.zip: 4,690 bytes | sha256 18b20200ba4a42f9…
📦 fallback_submission.zip: 748 bytes | sha256 578ff979c2e2a368…
Agents: 2 | budget: {'timeout_seconds': 300, 'max_tool_calls': 100, 'max_time_minutes': 8, 'max_turns': 150} | temperature: 0.2

```

## 🐈‍⬛ Handoff

| File | Role |
|---|---|
| `submission.zip` | **Pack Instinct**, the consensus challenger |
| `anchor_submission.zip` | The scored 0.10 Analyzer Challenger, verified byte for byte |
| `fallback_submission.zip` | Minimal single-agent bundle for emergencies |
| `experiment_card.json` | Hashes, budget and sampling for this run |

**Promotion rule:** keep the challenger only if its public score beats 0.10; otherwise resubmit `anchor_submission.zip`. The public split has about 60 tasks, so one task is worth roughly 0.02, and a one-task change is within noise.

**What comes next.** Prompt and budget tuning is close to its ceiling for this model. The next large step is likely a LoRA adapter trained on successful trajectories (the harness serves up to eight adapters), or a larger lab task set that includes tasks the agent solves only sometimes.

Thank you to the hosts for the Getting Started notebook, and to romanrozen, mizeroluckygall, zhukovoleksiy and nihilisticneuralnet for publishing their work. If this notebook helps you, please upvote theirs too.
