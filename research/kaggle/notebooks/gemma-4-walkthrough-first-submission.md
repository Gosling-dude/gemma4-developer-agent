# Gemma 4 | Walkthrough & First Submission
source: https://www.kaggle.com/code/zhukovoleksiy/gemma-4-walkthrough-first-submission  votes=51 bestPublicScore=0.1 gpu=None runtime_s=98

# <p style="font-family:JetBrains Mono; font-weight:bold; letter-spacing: 2px; color:#005B46; font-size:140%; text-align:left;padding: 0px; border-bottom: 3px solid #003300"> Introduction</p>

This notebook explains what the competition actually runs, looks at the data and the starter kit, fixes three problems in the starter kit, and builds my own agent into a `submission.zip`.

Worth knowing up front:

- The unmodified starter kit (`sample_submission/`) **errored** when I submitted it: *"Your notebook hit an unhandled error while rerunning your code"*.
- Its `eval_config.yaml` caps every task at **1 minute and 10 tool calls**.
- Its two LoRA adapters are **no-ops**: every `lora_B` weight is zero.
- With those fixed and 5 minutes per task, it runs but scores **0.00**, so this notebook builds my own agent (see *Version 2: my own agent*).
- My agent's version 2 scored **0.10**. Version 3 adds memory handling and fixes found in the now-public harness code; its first submission ran past the **12-hour limit**, so it now caps each task at 4 minutes (see *Version 3: memory and robustness*).
- The platform allows **1 submission per day**.
- The official harness is public: the [wheelhouse dataset](https://www.kaggle.com/datasets/metric/gemma-4-developer-agent-wheelhouse), attached to this notebook, and the hosts' [getting-started notebook](https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent).
- Until the hosts re-uploaded the data on 2026-09-25, half of the graph and embedding files were **empty**, even on Kaggle; only the readable commit-named files remain now.
- The code graphs contain **no async functions**, and embedding similarity is a weak signal.

## <p style="font-family:JetBrains Mono; font-weight:bold; letter-spacing: 2px; color:#005B46; font-size:140%; text-align:left;padding: 0px; border-bottom: 3px solid #003300">Useful submit & scoring info</p>

- You submit a zip holding a **declarative Google ADK agent**: YAML configs, Markdown prompts, and optionally LoRA adapters and skills. There is no Python entry point.
- Kaggle's harness compiles it, serves the Gemma 4 model you declare with vLLM on **4x NVIDIA L4** (32k context), and runs the agent on about **120 hidden tasks from private repositories**.
- Each task runs in two phases:
  1. **Agent phase.** The agent works in `/workspace` (the repo at the task's base commit, offline) with 9 tools: `run_command`, `read_file`, `edit_file`, `write_file`, `get_status`, `submit_patch`, `search_similar_code`, `get_code_neighbors`, `get_code_subgraph`. Its patch is the `git diff HEAD` of the working tree.
  2. **Verification phase.** A fresh container applies the patch and the task's hidden tests. The task passes if pytest exits with code 0.
- The score is the share of tasks that pass.
- Limits: **12 hours for all tasks**, including sandbox setup; per-task limits in `eval_config.yaml`; under 3 GiB unpacked; one model for every agent, and only `gemma-4-31b-it-qat-w4a16-ct` is allowed.

The harness libraries (`swegemma`, `adk-submission`, `adk-eval-core`) were published on 2026-09-25 in the [wheelhouse dataset](https://www.kaggle.com/datasets/metric/gemma-4-developer-agent-wheelhouse), and the hosts' [getting-started notebook](https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent) runs the real evaluator on the competition's 4x L4 machine. Tasks run one after another, and a run that passes 12 hours currently errors.

```python
import difflib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


def find_competition_dir() -> Path:
    if override := os.environ.get("G4_COMP_DIR"):
        return Path(override)
    matches = sorted(Path("/kaggle/input").glob("**/tasks.jsonl"))
    if not matches:
        raise FileNotFoundError("Attach the data: Add Input > Competitions > gemma-4-developer-agent")
    return matches[0].parent


COMP = find_competition_dir()
WORKING = Path("/kaggle/working") if Path("/kaggle/working").exists() else Path(os.environ.get("G4_WORKING_DIR", "working"))
WORKING.mkdir(parents=True, exist_ok=True)
print(COMP)
print(sorted(p.name for p in COMP.iterdir()))
```
```
[output] /kaggle/input/competitions/gemma-4-developer-agent
['HARNESS_README.md', 'docker', 'embeddings', 'graphs', 'sample_submission', 'sandbox', 'snapshots', 'tasks.jsonl', 'wheels']

```

## <p style="font-family:JetBrains Mono; font-weight:bold; letter-spacing: 2px; color:#005B46; font-size:140%; text-align:left;padding: 0px; border-bottom: 3px solid #003300">The data at a glance</p>

```python
tasks = pd.read_json(COMP / "tasks.jsonl", lines=True)
print(f"{len(tasks)} tasks, {tasks.base_commit.nunique()} distinct base commits, "
      f"{tasks.hints_text.str.strip().ne('').sum()} with hints")
tasks.repo.value_counts().rename("tasks").to_frame()
```
```
[output] 129 tasks, 127 distinct base commits, 0 with hints

```
```
[output]                  tasks
repo                  
fastapi/fastapi     67
Textualize/rich     48
psf/requests        13
encode/httpx         1
```

```python
def patched_files(patch: str) -> list[str]:
    return re.findall(r"^\+\+\+ b/(\S+)", patch, re.MULTILINE)


pd.DataFrame({
    "problem statement chars": tasks.problem_statement.str.len(),
    "files in reference fix": tasks.patch.map(lambda p: len(patched_files(p))),
    "files in test patch": tasks.test_patch.map(lambda p: len(patched_files(p))),
}).describe().loc[["mean", "50%", "max"]].round(1)
```
```
[output]       problem statement chars  files in reference fix  files in test patch
mean                    803.6                     2.2                  2.2
50%                     418.0                     1.0                  1.0
max                   10095.0                    26.0                 29.0
```

```python
example = tasks.set_index("instance_id").loc["rich_3006"]
print(example.problem_statement[:1500])
print("\nReference fix touches:", patched_files(example.patch))
print("Test patch touches:", patched_files(example.test_patch))
```
```
[output] Fixed issue with custom classes (fixes #2875)

## Type of changes

- [x] Bug fix
- [ ] New feature
- [ ] Documentation / docstrings
- [ ] Tests
- [ ] Other

## Checklist

- [x] I've run the latest [black](https://github.com/psf/black) with default args on new code.
- [x] I've updated CHANGELOG.md and CONTRIBUTORS.md where appropriate.
- [x] I've added tests for new code.
- [x] I accept that @willmcgugan may be pedantic in the code review.

## Description

When `repr`ing classes that have overwritten `__eq__` as parameters, the check with `== Parameters.empty` can be `True`.
Fixes #2875 with the suggested change. Also added the sample code as a test.


Reference fix touches: ['rich/repr.py']
Test patch touches: ['tests/test_repr.py']

```

Things to notice:

- Problem statements can be pull-request descriptions rather than issue reports, checklist and all, like the one above.
- 129 training tasks from 4 public repos. The hidden test set comes from private repos, so the score measures how well the agent generalizes, not how well it knows fastapi.
- `hints_text` is empty for every task.
- `patch` (the reference fix) and `test_patch` (the verification tests) are there for training and local checks. Every patch in `tasks.jsonl` lacks its final newline; add one before applying it with `git apply` or `patch`.
- `snapshots/<instance_id>.tgz` is the repo at the base commit. `graphs/` and `embeddings/` back the three code-intelligence tools (see the graph-tools section).

## <p style="font-family:JetBrains Mono; font-weight:bold; letter-spacing: 2px; color:#005B46; font-size:140%; text-align:left;padding: 0px; border-bottom: 3px solid #003300"> The starter kit, file by file </p>

```python
SAMPLE = COMP / "sample_submission"
for path in sorted(SAMPLE.rglob("*")):
    if path.is_file():
        print(f"{path.stat().st_size:>8,}  {path.relative_to(SAMPLE)}")
```
```
[output]      664  adapters/main_lora/adapter_config.json
 217,672  adapters/main_lora/adapter_model.safetensors
     664  adapters/tool_lora/adapter_config.json
 217,672  adapters/tool_lora/adapter_model.safetensors
     438  agent.yaml
     120  configs/sampling.yaml
     232  eval_config.yaml
     527  prompts/analyzer.md
   3,888  prompts/system.md
     361  sub_agents/code_analyzer.yaml

```

```python
for name in ["agent.yaml", "sub_agents/code_analyzer.yaml", "configs/sampling.yaml", "eval_config.yaml"]:
    print(f"--- {name}\n{(SAMPLE / name).read_text()}")
```
```
[output] --- agent.yaml
name: swe_baseline_agent
model: gemma-4-31b-it-qat-w4a16-ct
adapter: main_lora
instruction: !include prompts/system.md
tools:
  - run_command
  - read_file
  - edit_file
  - write_file
  - get_status
  - submit_patch
  - get_code_neighbors
  - search_similar_code
  - get_code_subgraph
  - agent_tool:
      config_path: sub_agents/code_analyzer.yaml
      skip_summarization: true
generate_content_config: !include configs/sampling.yaml

--- sub_agents/code_analyzer.yaml
name: code_analyzer_agent
description: Analyzes repository source files and symbol graphs to locate root causes.
model: gemma-4-31b-it-qat-w4a16-ct
adapter: tool_lora
instruction: !include ../prompts/analyzer.md
tools:
  - read_file
  - search_similar_code
  - get_code_neighbors
  - get_code_subgraph
generate_content_config: !include ../configs/sampling.yaml

--- configs/sampling.yaml
temperature: 0.2
top_p: 0.95
max_output_tokens: 16384
thinking_config:
  thinking_budget: 4096
  include_thoughts: true

--- eval_config.yaml
# Optional participant evaluation configuration for Stage 1 inference.
# Controls per-task execution budgets and sandbox command timeouts.
evaluation:
  timeout_seconds: 60
  max_tool_calls: 10
  max_time_minutes: 1
  max_turns: 50


```

- `agent.yaml` is the root agent: the model alias (`gemma-4-31b-it-qat-w4a16-ct`, Gemma 4 31B with 4-bit weights), a LoRA adapter, the system prompt (`!include prompts/system.md`), all 9 tools, and a sub-agent exposed as a tool.
- `sub_agents/code_analyzer.yaml` is a read-only analyzer. Wrapping it in `agent_tool` with `skip_summarization: true` keeps its file reads out of the root agent's context window.
- `configs/sampling.yaml` sets temperature 0.2 and thinking with a 4,096-token budget.
- `eval_config.yaml` sets the per-task budget.

## <p style="font-family:JetBrains Mono; font-weight:bold; letter-spacing: 2px; color:#005B46; font-size:140%; text-align:left;padding: 0px; border-bottom: 3px solid #003300">Three fixes before submission </p>

### The LoRA adapters do nothing

A LoRA adapter adds `B @ A` to a weight matrix, so if every value in `B` is zero, the adapter changes nothing. A safetensors file is an 8-byte header length, a JSON header, then raw tensor bytes, so we can check without extra libraries.

```python
def lora_tensors(path: Path) -> dict[str, np.ndarray]:
    raw = path.read_bytes()
    header_len = struct.unpack("<Q", raw[:8])[0]
    header = json.loads(raw[8 : 8 + header_len])
    body = raw[8 + header_len :]
    tensors = {}
    for name, info in header.items():
        if name == "__metadata__":
            continue
        assert info["dtype"] == "BF16", info["dtype"]
        start, end = info["data_offsets"]
        bf16_bits = np.frombuffer(body[start:end], dtype=np.uint16).astype(np.uint32) << 16
        tensors[name] = bf16_bits.view(np.float32).reshape(info["shape"])
    return tensors


for adapter in sorted((SAMPLE / "adapters").iterdir()):
    for name, tensor in lora_tensors(adapter / "adapter_model.safetensors").items():
        print(f"{adapter.name:10s} {name.split('layers.')[1]:34s} shape={str(tensor.shape):12s} all zero: {not tensor.any()}")
```
```
[output] main_lora  0.self_attn.o_proj.lora_A.weight   shape=(4, 8192)    all zero: False
main_lora  0.self_attn.o_proj.lora_B.weight   shape=(5376, 4)    all zero: True
main_lora  0.self_attn.q_proj.lora_A.weight   shape=(4, 5376)    all zero: False
main_lora  0.self_attn.q_proj.lora_B.weight   shape=(8192, 4)    all zero: True
tool_lora  0.self_attn.o_proj.lora_A.weight   shape=(4, 8192)    all zero: False
tool_lora  0.self_attn.o_proj.lora_B.weight   shape=(5376, 4)    all zero: True
tool_lora  0.self_attn.q_proj.lora_A.weight   shape=(4, 5376)    all zero: False
tool_lora  0.self_attn.q_proj.lora_B.weight   shape=(8192, 4)    all zero: True

```

Every `lora_B` is zero, so both adapters are placeholders (rank 4, layer 0 only, byte-identical to each other). Dropping them and their `adapter:` lines leaves the model's behaviour unchanged and removes one thing that can fail at scoring time.

### The 1-minute budget

The sample `eval_config.yaml` gives each task 1 minute and 10 tool calls. The scorer allows 12 hours for all tasks, including sandbox setup.

```python
hidden_tasks, hours = 120, 12
print(f"{hours * 60 / hidden_tasks:.0f} minutes per task if tasks run one at a time")
```
```
[output] 6 minutes per task if tasks run one at a time

```

How many tasks the scorer runs at once is not documented. My first version gave each task 5 minutes (with `timeout_seconds: 300` and `max_tool_calls: 50`) and scored **0.00**, and the whole run finished in about 80 minutes, far inside the 12 hours. The two public notebooks that scored above 0 ship no `eval_config.yaml` at all, so version 2 drops the file and runs on the harness defaults (the README lists 60 minutes per task). The sample's own comment says the file controls "per-task execution budgets and sandbox command timeouts", so `timeout_seconds` is most likely the per-command timeout.

Update: the hosts have since confirmed that tasks run one after another, and my version 3 submission, with up to 12 minutes per task, failed with *Notebook Exceeded Allowed Compute*. The 6 minutes above also has to cover model startup, task setup and the tests, so version 3 now caps each task at 4 minutes and 80 model calls (see *Version 3: memory and robustness*).

### Package files only, with `agent.yaml` at the root

The harness wants exactly one root config (`agent.yaml`, `agent.yml`, `root_agent.yaml` or `root_agent.yml`) at the root of the archive, only `.yaml`, `.yml`, `.md`, `.txt`, `.py`, `.json` and `.safetensors` files, and under 3 GiB unpacked. The zip built at the end of this notebook holds files only, with no directory entries.

Why change all three at once: my unmodified starter-kit submission errored, and the public notebooks that ran without errors at the time shipped no adapters, no `eval_config.yaml`, and files-only zips. Changing all three worked (the next run scored 0.00 without errors), but it does not say which change mattered.

## <p style="font-family:JetBrains Mono; font-weight:bold; letter-spacing: 2px; color:#005B46; font-size:140%; text-align:left;padding: 0px; border-bottom: 3px solid #003300">Graph tools: what they can and cannot do </p>

`get_code_neighbors(node)` and `get_code_subgraph(nodes)` query `graphs/<task>.json`; `search_similar_code(query)` ranks nodes by cosine similarity using `embeddings/<task>.npz`. The harness only offers these tools when both files are over 100 bytes.

The files are named `<repo>_<base_commit>`, the name the harness looks up. Until the 2026-09-25 re-upload the data also shipped task-named copies, half of them empty; the helper below finds a readable file either way.

```python
def readable(kind: str, suffix: str, task: pd.Series) -> Path:
    short = task.instance_id.rsplit("_", 1)[0]
    names = [f"{short}_{task.base_commit}", task.instance_id, *tasks.instance_id[tasks.base_commit == task.base_commit]]
    return next(p for p in (COMP / kind / f"{n}{suffix}" for n in names) if p.is_file() and p.stat().st_size > 100)


empty = {kind: sum(p.stat().st_size == 0 for p in (COMP / kind).iterdir()) for kind in ["graphs", "embeddings"]}
print("empty files in this copy of the data:", empty)
```
```
[output] empty files in this copy of the data: {'graphs': 0, 'embeddings': 0}

```

```python
OWN_DEFINITION = re.compile(r"^\s*(async\s+def|def|class)\s", re.MULTILINE)


def is_async(text: str) -> bool:
    match = OWN_DEFINITION.search(text or "")
    return bool(match) and match.group(1).startswith("async")


task = tasks.set_index("instance_id", drop=False).loc["fastapi_13786"]
graph = json.loads(readable("graphs", ".json", task).read_text())
nodes = {node["id"]: node for node in graph["nodes"]}
print(f"{len(nodes):,} nodes, {len(graph['edges']):,} edges")
print("edge types:", pd.Series([edge["type"] for edge in graph["edges"]]).value_counts().to_dict())
print("async function nodes:", sum(is_async(node["text"]) for node in nodes.values()))
largest = sorted(nodes.values(), key=lambda node: len(node["text"] or ""), reverse=True)[:3]
print("largest node sources (characters):", {node["id"]: len(node["text"]) for node in largest})
for symbol in ["fastapi.routing.get_request_handler", "fastapi.routing.serialize_response"]:
    print(f"{symbol} in graph: {symbol in nodes}")
```
```
[output] 3,698 nodes, 2,456 edges
edge types: {'calls': 2456}
async function nodes: 0
largest node sources (characters): {'tests.test_include_router_defaults_overrides.test_openapi': 356100, 'fastapi.applications.FastAPI': 130349, 'fastapi.routing.APIRouter': 109916}
fastapi.routing.get_request_handler in graph: True
fastapi.routing.serialize_response in graph: False

```

```python
embeddings = np.load(readable("embeddings", ".npz", task))
keys = embeddings.files
vectors = np.stack([embeddings[key] for key in keys]).astype(np.float64)
unit = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def similar(symbol: str, k: int = 5) -> pd.DataFrame:
    query = next(key for key in keys if key == symbol or key.endswith("." + symbol))
    scores = unit @ unit[keys.index(query)]
    top = np.argsort(-scores)[1 : k + 1]
    print("query:", query)
    return pd.DataFrame({"node": [keys[i] for i in top], "cosine": scores[top].round(3)})


rng = np.random.default_rng(0)
i, j = rng.integers(0, len(keys), (2, 20_000))
print(f"median cosine between random pairs of nodes: {np.median((unit[i] * unit[j]).sum(axis=1)):.2f}")
similar("APIKeyHeader")
```
```
[output] median cosine between random pairs of nodes: 0.84
query: fastapi.security.api_key.APIKeyHeader

```
```
[output]                                               node  cosine
0            fastapi.security.api_key.APIKeyCookie   1.000
1   fastapi.security.api_key.APIKeyHeader.__init__   1.000
2  custom_request_and_route.tutorial003.TimedRoute   1.000
3       scripts.notify_translations.create_comment   0.999
4       scripts.notify_translations.update_comment   0.999
```

- The only edge type is `calls`: no import or containment edges, and no module nodes.
- `get_code_neighbors` filters `edge_type` by exact match, and the data only has lowercase `calls`, so the docstring's `CALLS` returns nothing.
- Async functions and methods are missing entirely (first reported on the forum by Jason Wold https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/742911). Much of fastapi's request path is async, so the graph tools cannot reach it, while `grep` and `read_file` can.
- `search_similar_code` takes a symbol name, not a sentence. Offline, the query is matched to an existing node, then ranked by cosine similarity.
- The embeddings are dominated by one direction, so even random pairs of nodes score high, and top matches can be unrelated code. Treat the tool as a weak hint.
- Each `search_similar_code` result includes the node's full source with no length cap, and single nodes run past 100,000 characters (printed above). Here the harness's own function returns about 136,000 characters for the query `FastAPI` and 259,000 for `get_openapi`, more than the model's whole 32,768-token context. That overflow is an uncaught error, so the task's patch is lost.

## <p style="font-family:JetBrains Mono; font-weight:bold; letter-spacing: 2px; color:#005B46; font-size:140%; text-align:left;padding: 0px; border-bottom: 3px solid #003300">Version 2: my own agent</p>

Results so far on the public leaderboard (about 60 tasks):

| Submission | Public score |
| :--- | :--- |
| Starter kit, unmodified | error |
| Starter kit with the three fixes, 5 minutes per task | 0.00 |
| Version 2 of my agent | 0.10 |
| Version 3 of my agent, up to 12 minutes per task | error: *Notebook Exceeded Allowed Compute* (over the 12-hour limit) |
| [Black Cat SWE Agent](https://www.kaggle.com/code/lucifer19/black-cat-swe-agent-second-strike) by lucifer19 | 0.06 |
| [GEMMA: EDA, Baseline for a start](https://www.kaggle.com/code/romanrozen/gemma-eda-baseline-for-a-start-lb-top-1) by romanrozen | 0.12 |

Version 2 changes several things at once, based on what the two scoring notebooks have in common:

| Change | Why |
| :--- | :--- |
| No `eval_config.yaml`, so default budgets | Both scoring notebooks ship none; my 5-minute run scored 0.00 |
| Thoughts not returned (`include_thoughts: false`), output capped at 8,192 tokens | Shared by both scoring notebooks |
| A coder plus a read-only `code_analyzer` sub-agent that answers in a fixed format | The design of the 0.12 notebook, and the answer format follows romanrozen's; unlike that notebook, the coder keeps all nine tools, as in the starter kit |
| New prompts | The usual loop (reproduce, `py_compile`, targeted tests, `git diff` review), plus facts from this notebook: use `git grep` because the sandbox has no `rg` or `tree`, the working tree is graded even without `submit_patch()`, and the graph tools cannot see async code. The rules for pre-existing test failures are adapted from the starter kit's prompt |

Because several things change at once, a score will not say which change mattered.

```python
V2_FILES = {
    "agent.yaml": r"""name: swe_coder
model: gemma-4-31b-it-qat-w4a16-ct
description: Fixes one repository issue with a small, verified source patch.
instruction: !include prompts/system.md
tools:
  - run_command
  - read_file
  - edit_file
  - write_file
  - get_status
  - submit_patch
  - get_code_neighbors
  - search_similar_code
  - get_code_subgraph
  - agent_tool:
      config_path: sub_agents/code_analyzer.yaml
      skip_summarization: true
generate_content_config: !include configs/sampling.yaml
""",
    "sub_agents/code_analyzer.yaml": r"""name: code_analyzer
model: gemma-4-31b-it-qat-w4a16-ct
description: Read-only code navigator. Given an issue, returns where to fix it, the root cause and a fix plan.
instruction: !include ../prompts/analyzer.md
tools:
  - run_command
  - read_file
  - get_code_neighbors
  - get_code_subgraph
  - search_similar_code
generate_content_config: !include ../configs/sampling.yaml
""",
    "configs/sampling.yaml": r"""temperature: 0.2
top_p: 0.95
top_k: 40
max_output_tokens: 8192
seed: 42
thinking_config:
  thinking_budget: 4096
  include_thoughts: false
""",
    "prompts/system.md": r"""You are an autonomous software engineer fixing one issue in the Python repository at /workspace. No one will answer questions. Keep working with your tools until the fix is in place, then call `submit_patch()`.

## How you are graded
- Hidden tests run on your changes in a fresh checkout. Only source changes in the working tree count, and a careful best-effort fix beats no patch.
- If time runs out, the working tree is graded as it is, so never revert a plausible fix.
- Test files used by the hidden tests are reset before grading, so editing tests never helps. Never edit tests, `pytest.ini` or `conftest.py`.

## Environment
- Offline, with dependencies installed. Do not install packages.
- /workspace is a git repository at the base commit.
- Available: git, grep, find, sed, awk, python3. Not available: rg (ripgrep), tree.
- Commands time out after 300 seconds and output is cut at 5,000 characters. `read_file` returns at most 150 lines, so read focused ranges.
- `get_status()` and `submit_patch()` are free.

## Workflow
1. Understand. Work out the expected and the actual behaviour. Some issues are pull-request descriptions: skip checklists and template text, keep the substance. Note exact names, messages and values.
2. Localize. Call `code_analyzer` with the issue text; it replies with LOCATION, ROOT CAUSE and FIX PLAN. Confirm by reading those lines. If it is unsure or wrong, search yourself: `git grep -n "<identifier>" -- '*.py' | head -30`.
3. Reproduce. Write a minimal script to /tmp/repro.py that shows the problem, and run it.
4. Fix. Edit with `edit_file`: copy `old_string` exactly from the file, including indentation, and keep it short but unique. Fix the root cause, handle the edge cases the issue names, and keep public signatures unchanged. Documentation examples under `docs_src/` count as source when the issue concerns them.
5. Verify. After each edit run `python3 -m py_compile <file>` and rerun /tmp/repro.py, then run the targeted tests described below.
6. Submit. Check `git status --short` and `git diff`, remove anything unintended, then call `submit_patch()` as your last tool call and reply with one line on what changed.

## Tests
- Run only the test file or test that exercises your change: `python3 -m pytest tests/test_x.py -q -x -k <name>`, or `python3 -m unittest tests.test_x`. Find test files with `git ls-files | grep test_<name>`.
- Never run bare `pytest`, `pytest .` or `python3 -m unittest discover`. A whole suite can take minutes and use up your time.
- Existing tests may already fail for reasons unrelated to the issue, such as missing fixtures, no network access or import errors. Ignore those failures: do not fix them, stub them or change test code. Judge your fix by the tests that exercise it.

## Code-graph tools
- `get_code_neighbors` and `get_code_subgraph` show synchronous call relationships only: the graph has only "calls" edges and no async functions.
- `search_similar_code` takes a symbol name such as `APIKeyHeader`, not a sentence, and its ranking is imprecise. Confirm every hit by reading the code.
- If a graph tool returns an error, stop using it. For async code and everything else, use `git grep` and `read_file`.

## Pace
- Call `get_status()` every 8 or so tool calls. When a quarter of the time remains, stop exploring and go straight to fix, verify and submit.
- Keep outputs short: `head`, `grep -n`, `pytest -q`.
- If an edit fails twice, reread the exact lines and retry with a smaller snippet. Keep each edit small so the tool call is not cut off.
""",
    "prompts/analyzer.md": r"""You are `code_analyzer`, a read-only code navigator. You never modify files. Given an issue, find exactly where it must be fixed.

## Tools
- `run_command` for read-only commands only: `git grep -n`, `grep -rn`, `sed -n 'START,ENDp' FILE`, `ls`, `git log -p -S "<text>"`. ripgrep (rg) is not installed.
- `read_file` with tight line ranges to confirm what you found.
- `get_code_neighbors` and `get_code_subgraph` for synchronous call relationships. The graph has only "calls" edges and no async functions.
- `search_similar_code` takes a symbol name such as `APIKeyHeader` or `routing.get_request_handler`, not a sentence, and its ranking is imprecise. Confirm every hit by reading the code.
- If a graph tool returns an error, stop using it and search the source instead.

## Method
1. Pull the identifiers out of the issue: function and class names, error messages, file paths, options. Pull-request descriptions may include template text; ignore it.
2. Search for each one, then follow the code until you reach the line where the behaviour diverges from what the issue expects.
3. Confirm by reading the code. Never guess line numbers.

## Answer (at most 250 words, nothing else)
LOCATION: <path>:<start>-<end> (<function or class>)
ROOT CAUSE: <one or two sentences>
FIX PLAN: <the concrete change>
RELATED: <other places needing the same change, or "none">
TESTS: <existing test files that exercise this code>
CONFIDENCE: high | medium | low
""",
}

for name in ["prompts/system.md", "prompts/analyzer.md"]:
    print(f"--- {name}\n{V2_FILES[name]}")
```
```
[output] --- prompts/system.md
You are an autonomous software engineer fixing one issue in the Python repository at /workspace. No one will answer questions. Keep working with your tools until the fix is in place, then call `submit_patch()`.

## How you are graded
- Hidden tests run on your changes in a fresh checkout. Only source changes in the working tree count, and a careful best-effort fix beats no patch.
- If time runs out, the working tree is graded as it is, so never revert a plausible fix.
- Test files used by the hidden tests are reset before grading, so editing tests never helps. Never edit tests, `pytest.ini` or `conftest.py`.

## Environment
- Offline, with dependencies installed. Do not install packages.
- /workspace is a git repository at the base commit.
- Available: git, grep, find, sed, awk, python3. Not available: rg (ripgrep), tree.
- Commands time out after 300 seconds and output is cut at 5,000 characters. `read_file` returns at most 150 lines, so read focused ranges.
- `get_status()` and `submit_patch()` are free.

## Workflow
1. Understand. Work out the expected and the actual behaviour. Some issues are pull-request descriptions: skip checklists and template text, keep the substance. Note exact names, messages and values.
2. Localize. Call `code_analyzer` with the issue text; it replies with LOCATION, ROOT CAUSE and FIX PLAN. Confirm by reading those lines. If it is unsure or wrong, search yourself: `git grep -n "<identifier>" -- '*.py' | head -30`.
3. Reproduc
```

## <p style="font-family:JetBrains Mono; font-weight:bold; letter-spacing: 2px; color:#005B46; font-size:140%; text-align:left;padding: 0px; border-bottom: 3px solid #003300">Version 3: memory and robustness</p>

What the released harness code shows (swegemma 0.2.7, adk_submission 0.2.11, google-adk 1.36.1):

- `run_command` keeps only the **first** 5,000 characters of output, but pytest prints its verdict at the end.
- When the conversation is compacted, older tool calls and tool outputs are dropped; only the model's own text is kept, and the original task message is summarized too.
- vLLM rejects a prompt longer than 32,768 minus `max_output_tokens`, and that error, like any uncaught error, discards the task's patch even after `submit_patch()`.
- `include_thoughts: false` turns thinking off entirely; `thinking_budget` and `seed` are never sent to vLLM.
- The file tools reject paths outside /workspace, so `write_file` to `/tmp/repro.py` fails.
- `skip_summarization: true` ends the coder's turn after every analyzer call, which triggers a harness nudge.
- `search_similar_code` returns full function and class bodies with no cap (see the graph-tools section).

Version 3 keeps the model, the tools and the coder-plus-analyzer design, and changes:

| Change | Why |
| :--- | :--- |
| The issue text is repeated at the end of both agents' instructions (`{problem_description}`) | Instructions are resent every turn, so the issue survives compaction |
| Long outputs go to a file in /tmp; the agent reads the end first with `tail`, then pulls more with `grep` or `sed` | Output is cut to its start, and pytest's verdict is at the end |
| The agent writes each important finding as a short note | Compaction keeps text, not tool outputs |
| Scratch files are created with `run_command` | The file tools cannot write to /tmp |
| Same error twice: change method, e.g. `sed -n` when `read_file` fails | Avoids retry loops |
| `skip_summarization: false`, and the coder sends the analyzer a one-line request | No forced turn break; the analyzer already has the issue |
| `max_output_tokens` 4,096, thinking still off | About 28,700 tokens of room for the prompt instead of 24,600 |
| Both agents are told never to call `search_similar_code`; the tool stays registered | One call can overflow the context and lose the patch; the harness's task message still mentions the tool, and calling a tool the agent lacks is also an error |
| `eval_config.yaml` with `max_time_minutes: 4`, `max_turns: 80` and `timeout_seconds: 120` | Tasks run one after another and the whole run must finish within 12 hours, so the average task has to stay under about 5.5 minutes, setup and tests included; my first version 3 submission, with up to 12 minutes per task, failed with *Notebook Exceeded Allowed Compute*. At the time and turn limits the harness still grades the working tree, so a cap only ends that one task, and `max_turns` also stops a model that keeps repeating the same call. `timeout_seconds` bounds each command and the verification tests; 120 seconds covered every test run in my local checks |

Several things change at once again, so a score will not say which change mattered.

```python
V3_FILES = {
    "agent.yaml": r"""name: swe_coder
model: gemma-4-31b-it-qat-w4a16-ct
description: Fixes one repository issue with a small, verified source patch.
instruction: !include prompts/system.md
tools:
  - run_command
  - read_file
  - edit_file
  - write_file
  - get_status
  - submit_patch
  - get_code_neighbors
  - search_similar_code
  - get_code_subgraph
  - agent_tool:
      config_path: sub_agents/code_analyzer.yaml
      skip_summarization: false
generate_content_config: !include configs/sampling.yaml
""",
    "sub_agents/code_analyzer.yaml": r"""name: code_analyzer
model: gemma-4-31b-it-qat-w4a16-ct
description: Read-only code navigator. Given an issue, returns where to fix it, the root cause and a fix plan.
instruction: !include ../prompts/analyzer.md
tools:
  - run_command
  - read_file
  - get_code_neighbors
  - get_code_subgraph
  - search_similar_code
generate_content_config: !include ../configs/sampling.yaml
""",
    "configs/sampling.yaml": r"""temperature: 0.2
top_p: 0.95
top_k: 40
max_output_tokens: 4096
thinking_config:
  include_thoughts: false
""",
    "eval_config.yaml": r"""evaluation:
  timeout_seconds: 120
  max_time_minutes: 4
  max_turns: 80
""",
    "prompts/system.md": r"""You are an autonomous software engineer fixing one issue in the Python repository at /workspace. No one will answer questions. Keep working with your tools until the fix is in place, then call `submit_patch()`.

## How you are graded
- Hidden tests run on your changes in a fresh checkout. Only source changes in the working tree count, and a careful best-effort fix beats no patch.
- If time runs out, the working tree is graded as it is, so never revert a plausible fix.
- Test files, `pytest.ini`, `conftest.py`, `pyproject.toml`, `setup.cfg` and `tox.ini` are reset before grading, so editing them never helps. Fix the source code.

## Environment
- Offline, with dependencies installed. Do not install packages.
- /workspace is a git repository at the base commit.
- Available: git, grep, find, sed, awk, python3. Not available: rg (ripgrep), tree.
- Commands time out after 120 seconds. Output is cut to its first 5,000 characters. `read_file` returns at most 150 lines, so read focused ranges.
- `read_file`, `write_file` and `edit_file` only accept paths inside /workspace. Create scratch files in /tmp with `run_command`.
- `get_status()` and `submit_patch()` are free.

## Workflow
1. Understand. Work out the expected and the actual behaviour. Some issues are pull-request descriptions: skip checklists and template text, keep the substance. Note exact names, messages and values.
2. Localize. Call `code_analyzer` with a one-line request; it already has the issue text and replies with LOCATION, ROOT CAUSE and FIX PLAN. Confirm by reading those lines. If it is unsure or wrong, search yourself: `git grep -n "<identifier>" -- '*.py' | head -30`.
3. Reproduce. Write a minimal script with `run_command`, for example `cat > /tmp/repro.py << 'EOF'` followed by the code and a closing `EOF` line, then run `python3 /tmp/repro.py`.
4. Fix. Edit with `edit_file`: copy `old_string` exactly from the file, including indentation, and keep it short but unique. Fix the root cause, handle the edge cases the issue names, and keep public signatures unchanged. Documentation examples under `docs_src/` count as source when the issue concerns them.
5. Verify. After each edit run `python3 -m py_compile <file>` and rerun /tmp/repro.py, then run the targeted tests described below.
6. Submit. Check `git status --short` and `git diff`, remove anything unintended, then call `submit_patch()` as your last tool call and reply with one line on what changed.

## Notes
- As the conversation grows, older tool outputs are dropped from memory; only what you write as plain text is kept.
- After each important finding, write one or two sentences stating it: the file and line, what it means, and your next step.

## Tests
- Run only the test file or test that exercises your change, saving the full output and reading its end first: `python3 -m pytest tests/test_x.py -q -x -k <name> > /tmp/test_1.log 2>&1; tail -n 30 /tmp/test_1.log`. The same works for `python3 -m unittest tests.test_x`. Find test files with `git ls-files | grep test_<name>`.
- Never run bare `pytest`, `pytest .` or `python3 -m unittest discover`. A whole suite can take minutes and use up your time.
- Existing tests may already fail for reasons unrelated to the issue, such as missing fixtures, no network access or import errors. Ignore those failures: do not fix them, stub them or change test code. Judge your fix by the tests that exercise it.

## Long output
- Output is cut to its first 5,000 characters, and test runners print their verdict at the end. For anything that may be long (tests, tracebacks, big searches), write the full output to a file in /tmp and read the end first, in the same command: `<command> > /tmp/out_1.log 2>&1; tail -n 30 /tmp/out_1.log`.
- Then pull only what you need from the saved file: `grep -n "Error\|FAILED" /tmp/out_1.log | head -20`, or `sed -n 'START,ENDp' /tmp/out_1.log`.
- Use a new file name for each run (`_1`, `_2`, ...) so earlier logs stay available. Files in /tmp are never part of your patch.

## When something fails
- If the same tool call fails twice, change method instead of retrying it. For example, when `read_file` fails, read the lines with `sed -n 'START,ENDp' <file>` through `run_command`.
- If an edit fails twice, reread the exact lines and retry with a smaller snippet. Keep each edit small so the tool call is not cut off.

## Code-graph tools
- `get_code_neighbors` and `get_code_subgraph` show synchronous call relationships only: the graph has only "calls" edges and no async functions. Never pass `edge_type`.
- Never call `search_similar_code`: each result includes the full source of a function or class, and large classes run past 100,000 characters, which overflows your context and discards your work.
- If a graph tool returns an error, stop using it. For async code and everything else, use `git grep` and `read_file`.

## Pace
- You have about 4 minutes and 80 model calls per task. Call `get_status()` every 5 or so tool calls. When half the time is gone, stop exploring: make the fix, run one targeted test and submit.
- Keep outputs short: `tail` for logs, `head` for listings, `grep -n` for searches.

## The issue, repeated so it stays in view
{problem_description}
""",
    "prompts/analyzer.md": r"""You are `code_analyzer`, a read-only code navigator. You never modify files. The coder sends you a short request; the full issue is at the end of these instructions. Find exactly where it must be fixed.

## Tools
- `run_command` for read-only commands only: `git grep -n`, `grep -rn`, `sed -n 'START,ENDp' FILE`, `ls`, `git log -p -S "<text>"`. ripgrep (rg) is not installed. Output is cut to its first 5,000 characters, so pipe long results through `head` or `grep`.
- `read_file` with tight line ranges to confirm what you found. It only accepts paths inside /workspace.
- `get_code_neighbors` and `get_code_subgraph` for synchronous call relationships. The graph has only "calls" edges and no async functions. Never pass `edge_type`.
- Never call `search_similar_code`: each result includes the full source of a function or class, and large classes run past 100,000 characters, which overflows your context and discards your work.
- If a graph tool returns an error, stop using it and search the source instead. If the same call fails twice, change method.

## Method
1. Pull the identifiers out of the issue: function and class names, error messages, file paths, options. Pull-request descriptions may include template text; ignore it.
2. Search for each one, then follow the code until you reach the line where the behaviour diverges from what the issue expects.
3. Confirm by reading the code. Never guess line numbers.

## Answer (at most 250 words, nothing else)
LOCATION: <path>:<start>-<end> (<function or class>)
ROOT CAUSE: <one or two sentences>
FIX PLAN: <the concrete change>
RELATED: <other places needing the same change, or "none">
TESTS: <existing test files that exercise this code>
CONFIDENCE: high | medium | low

## The issue
{problem_description}
""",
}

for name, text in V3_FILES.items():
    if name not in V2_FILES:
        print(f"--- new file: {name}\n{text}")
        continue
    diff = difflib.unified_diff(V2_FILES[name].splitlines(), text.splitlines(), f"v2/{name}", f"v3/{name}", lineterm="", n=0)
    print("\n".join(diff) or f"(unchanged) {name}", end="\n\n")
```
```
[output] --- v2/agent.yaml
+++ v3/agent.yaml
@@ -17 +17 @@
-      skip_summarization: true
+      skip_summarization: false

(unchanged) sub_agents/code_analyzer.yaml

--- v2/configs/sampling.yaml
+++ v3/configs/sampling.yaml
@@ -4,2 +4 @@
-max_output_tokens: 8192
-seed: 42
+max_output_tokens: 4096
@@ -7 +5,0 @@
-  thinking_budget: 4096

--- new file: eval_config.yaml
evaluation:
  timeout_seconds: 120
  max_time_minutes: 4
  max_turns: 80

--- v2/prompts/system.md
+++ v3/prompts/system.md
@@ -6 +6 @@
-- Test files used by the hidden tests are reset before grading, so editing tests never helps. Never edit tests, `pytest.ini` or `conftest.py`.
+- Test files, `pytest.ini`, `conftest.py`, `pyproject.toml`, `setup.cfg` and `tox.ini` are reset before grading, so editing them never helps. Fix the source code.
@@ -12 +12,2 @@
-- Commands time out after 300 seconds and output is cut at 5,000 characters. `read_file` returns at most 150 lines, so read focused ranges.
+- Commands time out after 120 seconds. Output is cut to its first 5,000 characters. `read_file` returns at most 150 lines, so read focused ranges.
+- `read_file`, `write_file` and `edit_file` only accept paths inside /workspace. Create scratch files in /tmp with `run_command`.
@@ -17,2 +18,2 @@
-2. Localize. Call `code_analyzer` with the issue text; it replies with LOCATION, ROOT CAUSE and FIX PLAN. Confirm by reading those lines. If it is unsure or wrong, search yourself: `git grep -n "<identifier>" -- '*.py' | head -30`.
-3. Rep
```

## <p style="font-family:JetBrains Mono; font-weight:bold; letter-spacing: 2px; color:#005B46; font-size:140%; text-align:left;padding: 0px; border-bottom: 3px solid #003300"> Build, validate, and submit </p>

```python
BUNDLE = WORKING / "submission_bundle"
shutil.rmtree(BUNDLE, ignore_errors=True)
for name, text in V3_FILES.items():
    path = BUNDLE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
for name in ["agent.yaml", "configs/sampling.yaml", "eval_config.yaml"]:
    print(f"--- {name}\n{(BUNDLE / name).read_text()}")
```
```
[output] --- agent.yaml
name: swe_coder
model: gemma-4-31b-it-qat-w4a16-ct
description: Fixes one repository issue with a small, verified source patch.
instruction: !include prompts/system.md
tools:
  - run_command
  - read_file
  - edit_file
  - write_file
  - get_status
  - submit_patch
  - get_code_neighbors
  - search_similar_code
  - get_code_subgraph
  - agent_tool:
      config_path: sub_agents/code_analyzer.yaml
      skip_summarization: false
generate_content_config: !include configs/sampling.yaml

--- configs/sampling.yaml
temperature: 0.2
top_p: 0.95
top_k: 40
max_output_tokens: 4096
thinking_config:
  include_thoughts: false

--- eval_config.yaml
evaluation:
  timeout_seconds: 120
  max_time_minutes: 4
  max_turns: 80


```

```python
ROOT_CONFIGS = ["agent.yaml", "agent.yml", "root_agent.yaml", "root_agent.yml"]
ALLOWED_SUFFIXES = {".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"}
yaml.SafeLoader.add_constructor("!include", lambda loader, node: loader.construct_scalar(node))


def validate(bundle: Path) -> None:
    files = [p for p in bundle.rglob("*") if p.is_file()]
    roots = [name for name in ROOT_CONFIGS if (bundle / name).is_file()]
    assert len(roots) == 1, f"need exactly one root config, found {roots}"
    assert not any(p.is_symlink() for p in bundle.rglob("*")), "symlinks are rejected"
    assert all(p.suffix in ALLOWED_SUFFIXES for p in files), [p.name for p in files if p.suffix not in ALLOWED_SUFFIXES]
    assert sum(p.stat().st_size for p in files) < 3 * 2**30, "over 3 GiB unpacked"
    models = set()
    for config in (p for p in files if p.suffix in (".yaml", ".yml")):
        text = config.read_text()
        data = yaml.safe_load(text) or {}
        for target in re.findall(r"!include\s+(\S+)", text):
            assert (config.parent / target).is_file(), f"{config.name}: missing include {target}"
        if "adapter" in data:
            assert (bundle / "adapters" / data["adapter"] / "adapter_model.safetensors").is_file(), f"{config.name}: adapter {data['adapter']} not shipped"
        if "model" in data:
            models.add(data["model"])
    assert len(models) == 1, f"one base model per submission, found {models}"
    print(f"OK: {roots[0]} at the root, {len(files)} files, model {models.pop()}")


validate(BUNDLE)
```
```
[output] OK: agent.yaml at the root, 6 files, model gemma-4-31b-it-qat-w4a16-ct

```

```python
HARNESS_WHEELS = ("google_adk-", "google_genai-", "adk_submission-", "adk_eval_core-", "swegemma-")
MODEL = "gemma-4-31b-it-qat-w4a16-ct"


def install_harness() -> None:
    """Install the official harness from the attached wheelhouse without dependencies, as the hosts' notebook does."""
    found = sorted(Path("/kaggle/input").glob("**/adk_submission-*.whl"))
    if not found:
        raise FileNotFoundError("attach the metric/gemma-4-developer-agent-wheelhouse dataset")
    wheelhouse = found[0].parent
    wheels = [str(w) for w in sorted(wheelhouse.glob("*.whl")) if w.name.startswith(HARNESS_WHEELS)]
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", *wheels], check=True)


# Stand-ins with the real tool signatures: compiling only checks names and schemas, nothing is called.
def run_command(command: str) -> str: ...
def read_file(filepath: str, start_line: int | None = None, end_line: int | None = None) -> str: ...
def write_file(filepath: str, content: str) -> str: ...
def edit_file(filepath: str, old_string: str, new_string: str, allow_multiple: bool = False) -> str: ...
def submit_patch() -> str: ...
def get_status() -> str: ...
def get_code_neighbors(node: str, edge_type: str | None = None, max_neighbors: int = 50) -> str: ...
def search_similar_code(query: str, k: int = 10) -> str: ...
def get_code_subgraph(nodes: list[str]) -> str: ...


try:
    try:
        import adk_submission  # noqa: F401
    except ImportError:
        install_harness()
    from adk_submission import ModelRegistry, compile_submission, validate_directory
    from google.adk.models.lite_llm import LiteLlm
    from swegemma.config import build_submission_limits
    from swegemma.models.discovery import validate_single_declared_model
except Exception as error:
    print(f"Official harness unavailable in this environment ({error!r}); relying on the checks above.")
else:
    limits, constraints = build_submission_limits()
    models = ModelRegistry()
    models.register(MODEL, LiteLlm(model=f"openai/{MODEL}", api_base="http://127.0.0.1:9/v1", api_key="EMPTY"))
    tools = {f.__name__: f for f in [run_command, read_file, write_file, edit_file, submit_patch, get_status,
                                     get_code_neighbors, search_similar_code, get_code_subgraph]}
    validate_directory(BUNDLE, limits)
    print("validate_directory: ok")
    print("validate_single_declared_model:", validate_single_declared_model(BUNDLE))
    agent = compile_submission(BUNDLE, tools, models, limits=limits, generation_constraints=constraints)
    print(f"compile_submission: ok, root agent {agent.name!r}")
```
```
[output] [92m17:40:23 - LiteLLM:WARNING[0m: get_model_cost_map.py:271 - LiteLLM: Failed to fetch remote model cost map from https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json: [Errno -3] Temporary failure in name resolution. Falling back to local backup.

```
```
[output] validate_directory: ok
validate_single_declared_model: gemma-4-31b-it-qat-w4a16-ct
compile_submission: ok, root agent 'swe_coder'

```

```python
ZIP_PATH = WORKING / "submission.zip"
with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(p for p in BUNDLE.rglob("*") if p.is_file()):
        archive.write(path, path.relative_to(BUNDLE).as_posix())

with zipfile.ZipFile(ZIP_PATH) as archive:
    names = archive.namelist()
assert "agent.yaml" in names and not any(name.endswith("/") for name in names)
shutil.rmtree(BUNDLE)
print(f"{ZIP_PATH} ({ZIP_PATH.stat().st_size:,} bytes)", *names, sep="\n  ")
```
```
[output] /kaggle/working/submission.zip (4,872 bytes)
  agent.yaml
  configs/sampling.yaml
  eval_config.yaml
  prompts/analyzer.md
  prompts/system.md
  sub_agents/code_analyzer.yaml

```

### What to try next

- Thinking on versus off within the 12-hour budget: every scoring notebook so far runs with thinking off.
- One agent or coder plus analyzer: the two scoring notebooks differ here, and 0.06 versus 0.12 is only about 4 versus 7 tasks, close to noise.
- When to use the graph tools versus `git grep` and `read_file`, given the gaps in the graph-tools section.

If you have any ideas, please share in the comments.
