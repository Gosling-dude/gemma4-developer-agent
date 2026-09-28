# Competition notes (research log)

Research date: **2026-09-28** (competition started 2026-09-23).
Labels: **VERIFIED** = read in an official text or in installed library source code.
**SOURCED** = official text read through a third-party verbatim copy (kaggle.com pages
render client-side and could not be fetched directly from this machine).
**INFERRED** = our reasoning, not stated anywhere. **TODO** = still open.

## Where the information came from

| Source | How it was accessed | Label |
|---|---|---|
| Competition Overview page | Verbatim capture in `rishaviitd/kaggle.gemma.coding.agent/context/overview.md` (GitHub) | SOURCED |
| Data page | Verbatim capture in `.../context/data.md` | SOURCED |
| `HARNESS_README.md` (49 KB, in dataset) | Copy in `.../context/harness.md` (671 lines) | SOURCED |
| Starter-kit `sample_submission/` | Copies in several public GitHub repos (identical YAML) | SOURCED |
| Google ADK 1.36.1 skill/agent semantics | Source code of `google-adk==1.36.1` installed in `.venv` (the version pinned by the harness lockfile) | VERIFIED |
| Kaggle discussion / leaderboard | Not accessible (JS-rendered, no Kaggle credentials on this machine) | TODO |

Kaggle.com could not be browsed directly: the Chrome extension was signed into a different
account, WebFetch only sees the page title, and there is no `~/.kaggle/kaggle.json`.

## Key facts

### Task and scoring (SOURCED)
- Solve SWE-bench-style Python issues. The public dev set has **129 tasks** from
  `fastapi/fastapi`, `Textualize/rich`, `psf/requests` and `encode/httpx`. The hidden test set has **about 120
  tasks from *private* repositories**, split evenly between the public and private leaderboards.
- Score = resolution rate = resolved / total. A task counts as resolved only if pytest on the hidden
  `test_patch` targets exits 0 **and** the JUnit XML shows >0 passed, 0 failures, 0 errors, and
  every required FAIL_TO_PASS / PASS_TO_PASS node passed without being skipped.
- **12 hours for the whole run**, including sandbox setup but not Phase-2 validation.
  Per-task budgets can be set in `eval_config.yaml`.
- Deadlines: entry and team merger on 2026-11-25, final submission on 2026-12-02, optional paper on 2026-11-12
  (all 23:59 UTC).

### Model and hardware (SOURCED)
- Only `gemma-4-31b-it-qat-w4a16-ct` is allowed, and every agent must use it (`validate_single_declared_model`).
- It is served by vLLM on 4× L4 GPUs with `max_model_len=32768`, the gemma4 tool and reasoning parsers, thinking on by
  default, `litellm.drop_params=True`, and LoRA support (`max_loras=8`, `max_lora_rank=128`).
- Context is compacted by ADK `EventsCompactionConfig` (interval 5, overlap 2, token threshold 14,336).

### Submission format (SOURCED + VERIFIED where marked)
- Exactly one root config at the zip root: `agent.yaml` / `agent.yml` / `root_agent.yaml` / `root_agent.yml`.
- Declarative YAML only. No Python entry points.
- `!include rel/path`: `.md`/`.txt` load as strings, `.yaml`/`.yml` are parsed recursively (depth ≤ 10).
  Paths are resolved **relative to the including file**. Absolute paths, `..`, null bytes and escaping symlinks are rejected.
- **Allowed file extensions:** `.yaml .yml .md .txt .py .json .safetensors`. Anything else is
  rejected, **including `.sh` scripts and `.gitkeep`**.
- Unpacked size must be < 3 GiB (adapters included). Other limits: ≤ 10,000 files, instruction ≤ 1M chars per agent.
- `generate_content_config` must not contain `tools`, `system_instruction`, `http_options`, `safety_settings` or
  `response_schema`.
- Agent classes: `LlmAgent` (default), `SequentialAgent`, `ParallelAgent`, `LoopAgent`.
- `tools:` may only list harness tools (9 names) or `agent_tool: {config_path, skip_summarization}`.
- Optional `eval_config.yaml` → `evaluation: {timeout_seconds, max_tool_calls, max_time_minutes, max_turns}`.

### Skills (SOURCED + VERIFIED against ADK 1.36.1)
- Each skill is a directory with `SKILL.md` that starts with YAML frontmatter containing `name` and `description`.
- VERIFIED (`google/adk/skills/_utils.py`): **the skill `name` must equal the directory name**, and
  must be **kebab-case** (snake_case only behind a feature flag). The description must be ≤ 1024 chars.
- VERIFIED (`google/adk/tools/skill_toolset.py`): the toolset exposes `list_skills`, `load_skill`,
  `load_skill_resource` (paths under `references/`, `assets/`, `scripts/`) and `run_skill_script`.
  Scripts are copied into a **temporary directory, and the process chdirs there** before running.
  A script therefore has to address the repository as `/workspace`, not as `.`.
- The competition overview shows a `resources/` folder, but stock ADK 1.36.1 only loads `references/`
  and `assets/`. INFERRED: we keep knowledge files in `references/` (definitely loaded by ADK) and also
  mirror them to `resources/` when packaging.
- Scripts run "inside the competition's persistent Docker container, sharing filesystem access with
  run_command and debiting execution time against your central budget" (SOURCED).

### ADK instruction templating (VERIFIED, `google/adk/utils/instructions_utils.py`)
- Every `{identifier}` in an agent `instruction` is replaced from session state. **A missing key raises
  `KeyError`**, which crashes the task. The harness only sets `problem_description` and, when non-empty, `hints`.
  Rule: prompts must not contain braces except `{problem_description}` / `{hints?}`.
  `scripts/validate.sh` enforces this.

### Tools (SOURCED)
The limits that matter most: `run_command` output is truncated at 5,000 chars (stdout and stderr each); `read_file` returns
≤ 150 lines / 10,000 chars per call; `submit_patch` and `get_status` are **free** (they don't count against the tool-call budget);
`edit_file` uses 3-tier matching (exact → whitespace-flexible → regex) and fails on non-unique matches.
`search_similar_code` expects a **symbol name**, not natural language (it only looks up nodes that are already in the index).
The graph node id is the fully-qualified Python path, e.g. `fastapi.routing.APIRoute`.

### Patch extraction and grading gotchas (SOURCED)
1. Untracked files in `/workspace` go into the patch (`git add -N .`), so scratch scripts belong in `/tmp`.
2. The harness writes `/workspace/pytest.ini` and `/workspace/conftest.py` and commits them into the baseline. Don't touch them.
3. During verification, any test file, `conftest.py`, `pytest.ini`, `pyproject.toml`, `setup.cfg` or
   `tox.ini` touched by the patch is **reset**. Fixes must go in library code. Adding tests is wasted effort.
4. If the agent never calls `submit_patch`, the working-tree diff is still extracted and graded.
   **Edits made before a timeout still count.**
5. The loop ends after `submit_patch` + end of turn, or after 3 consecutive nudges with no tool call.

## Budget analysis (INFERRED — the most important design driver)

- 12 h = 720 min for about 120 tasks, i.e. **≈ 6 min per task including sandbox setup**, if the scoring notebook
  runs tasks sequentially. We couldn't confirm whether it runs them concurrently, so we plan for the worst case.
- The harness default is 60 min/task and 100 tool calls. **Leaving the default in place would blow the 12 h limit.**
  We set `max_time_minutes: 4.5` (120 × (4.5 + ~0.75 setup) ≈ 10.5 h, leaving margin).
- A 31B W4A16 model with TP=4 on L4s decodes on the order of tens of tokens per second, so 4.5 min is only
  **a few thousand generated tokens per task**. Consequences:
  - Thinking must be short (`thinking_budget: 1024`), and the prompt tells the model to keep reasoning brief.
  - Each tool call should gather as much as possible. The skill scripts do multi-step searches, test
    discovery and condensed test runs in **one** call.
  - The agent should make its edit early. A partial fix still gets graded; no patch always scores 0.
  - Sub-agents cost extra model turns, so they're off by default and treated as an experiment (V2).

## Public-notebook / public-repo observations (2026-09-28, SOURCED/INFERRED)
- The starter kit ships a root agent with all 9 tools plus a `code_analyzer` AgentTool, `temperature 0.2`,
  `thinking_budget 4096` and `max_output_tokens 16384`. Its eval_config (1 min, 10 tool calls) is a demo, not a real setting.
- One public repo (hemantadil) uses `max_time_minutes: 4.5` and reaches the same 12-hour conclusion independently.
- No public leaderboard scores could be read (Kaggle is inaccessible from here). TODO.

## Official links
- Overview: https://www.kaggle.com/competitions/gemma-4-developer-agent/overview
- Data: https://www.kaggle.com/competitions/gemma-4-developer-agent/data
- Rules: https://www.kaggle.com/competitions/gemma-4-developer-agent/rules
- Code: https://www.kaggle.com/competitions/gemma-4-developer-agent/code
- Getting-started notebook: https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent
- Paper track: https://www.kaggle.com/competitions/gemma-4-developer-agent-paper
