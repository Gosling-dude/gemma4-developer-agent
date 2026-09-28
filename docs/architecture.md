# Architecture

## 1. What gets submitted (V1)

```
submission.zip
├── agent.yaml                 root LlmAgent "swe_coder" (gemma-4-31b-it-qat-w4a16-ct)
├── eval_config.yaml           4.5 min / 40 tool calls / 60 turns / 120 s per command
├── configs/sampling.yaml      temp 0.3, top_p 0.95, top_k 64, max_output 6144, thinking 1024
├── prompts/system.md          operational workflow prompt (no {placeholders})
└── skills/
    ├── repo-navigation/       nav.py: find | outline | show | usages | layout
    ├── test-discovery/        tests.py: related | run | info
    └── debugging/             diagnose.py: run | cmd ; review.py
        (each: SKILL.md, scripts/*.py, references/*.md mirrored to resources/*.md)
```

One agent, all 9 harness tools, 3 skills. The harness compiles this into an ADK `LlmAgent` whose
tools are the 9 bound harness tools plus a `SkillToolset` (`list_skills`, `load_skill`,
`load_skill_resource`, `run_skill_script`).

### Agent lifecycle, and where each step comes from

| Step | Mechanism | Typical calls |
|---|---|---|
| UNDERSTAND | prompt step 1: extract expected/observed behaviour and hard requirements (names, messages) | 0 |
| ORIENT + LOCATE | `nav.py find <terms>` does IDF-weighted multi-term search with a definition boost and lists related tests, in one call | 1 |
| READ | `nav.py show Symbol` prints numbered source of one symbol; `read_file` for narrow ranges | 1–2 |
| DEPENDENCIES | `get_code_neighbors` (callers/callees) or `search_similar_code` (twin implementations), only when the cause spans functions | 0–2 |
| REPRODUCE | heredoc to `/tmp/repro.py`, then `diagnose.py run`, which shows the innermost *repository* frames | 1–2 |
| HYPOTHESIS | prompt step 4: a one-sentence causal claim, required before editing | 0 |
| PATCH | `edit_file` with a small exact `old_string` (harness 3-tier matching) | 1–3 |
| TEST | `tests.py related` and `tests.py run`, which give a condensed failure report; full-suite runs are refused | 2–4 |
| REPAIR | debugging SKILL loop: classify → locate → hypothesize → change one thing; at most 3 rounds per hypothesis | 0–6 |
| REVIEW | `review.py`: exact diff + stray files + edits to protected files + debug prints + syntax errors + empty diff | 1 |
| SUBMIT | `submit_patch` (free), then a short final text | 0 |

Target: 12–20 tool calls within about 4.5 minutes.

### Why this shape (design decisions and the evidence behind them)

| Decision | Reason | Evidence level |
|---|---|---|
| Single agent, no sub-agents in V1 | Each AgentTool call is a full extra model loop; at about 4.5 min/task that is the scarcest resource | INFERRED from the budget analysis; V2 exists to measure it |
| Skills with scripts | One `run_skill_script` replaces 3–6 grep/read/pytest calls and returns ≤ 4.5 KB of condensed output | Script behaviour VERIFIED by unit tests and the localization benchmark; end-to-end gain TODO (needs a model) |
| Prompt forbids braces | ADK raises KeyError on unknown `{name}` placeholders | VERIFIED in ADK 1.36.1 source; validator enforces it |
| Skills named in kebab-case, dir == name | ADK skill loader requirement | VERIFIED in ADK source; validator enforces it |
| `references/` + mirrored `resources/` | ADK loads `references/`; the competition overview shows `resources/` | INFERRED; harmless duplication (about 3 KB) |
| Scripts use `/workspace` explicitly | `run_skill_script` chdirs into a temp dir | VERIFIED in ADK source |
| No `..` in V1 includes | HARNESS_README lists `..` as blocked; the official sample uses it anyway | SOURCED; the conservative choice costs nothing |
| `thinking_budget: 1024`, `max_output_tokens: 6144` | Decode time dominates a 4.5-min budget; a cut-off tool call costs a nudge turn | INFERRED; needs a timing run on the real server |
| "Edit early" rule | The working tree is graded even without `submit_patch` | SOURCED (HARNESS_README §8.1) |

## 2. Local tooling (never shipped)

```
src/g4agent/
├── rules.py         every competition constant, with provenance
├── loader.py        sandboxed !include loader + agent-tree walk + closure (what to ship)
├── validator.py     strict checks (files, agents, tools, generation config, skills, eval_config, placeholders, zip)
├── compiler.py      YAML -> real google-adk 1.36.1 objects (LlmAgent/AgentTool/SkillToolset)
├── packager.py      stage (+variant overlay) -> closure -> validate -> deterministic zip -> re-validate
├── harness/
│   ├── tools.py     the 9 tools: same signatures, JSON shapes, limits, budget gate, low-budget warning
│   ├── graph.py     official graph/npz loader + AST approximation (lexical-proxy embeddings)
│   ├── tasks.py     tasks.jsonl schema, workspace creation (snapshot or git archive), baseline commit
│   ├── verify.py    Phase 2: patch apply fallbacks, protected-file reset, test_patch, pytest + JUnit
│   └── runner.py    Phase 1 via ADK Runner: prompt sections, 3 nudges, budgets, traces
├── experiment.py    immutable experiment dirs (config, results, patches, traces, summary)
├── analysis.py      failure taxonomy + comparison tables
├── localization.py  offline localization benchmark (no LLM)
└── cases.py         builds execution-verified cases from merged GitHub PRs
```

## 3. Local harness fidelity (differences from the official harness)

| Aspect | Official | Local | Impact |
|---|---|---|---|
| Sandbox | Docker, `network_mode=none`, 4 GiB, 2 vCPU | subprocess + `/workspace` and `/tmp` path rewriting (like the official subprocess backend) | Commands can reach the network locally; the prompt forbids it |
| Python | 3.13 in the container | the per-repo venv (3.12 here) | Rare version-specific behaviour |
| Harness `pytest.ini`/`conftest.py` | written and committed into the baseline | not written | Test collection may differ slightly |
| Graph and embeddings | official files | official files if `--data-dir` is given, else AST approximation + lexical-proxy vectors | Graph-tool conclusions drawn without official data are provisional |
| `get_code_neighbors` output | list of neighbours (exact element format undocumented) | dicts `{node, direction, type}` | Prompts don't depend on the format |
| Grading | FAIL_TO_PASS / PASS_TO_PASS node lists | every test in the files touched by `test_patch` must pass | Local grading is slightly stricter |
| Context compaction | `EventsCompactionConfig` (threshold 14,336 tokens) | not configured | Local runs keep the full history |
| `run_skill_script` executor | runs inside the task container | `SandboxExecutor`: subprocess with the task's Python and `SWE_WORKSPACE` | Same code path in ADK, different process isolation |
