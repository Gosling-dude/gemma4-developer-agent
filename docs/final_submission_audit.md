# Final submission audit

## V1.3 candidate (2026-09-30) — NOT submitted
Archive `submission/v1.3/submission.zip`: 19 files, 76,418 bytes unpacked, 35,250 bytes zipped,
sha256 `9f74b068d35d5da601cf7d12888627fd5889e2c5eb85d48d9b66a167508c3bd1`; branch `experiment/v1.3`.

| Check | Result | How |
|---|---|---|
| Byte-reproducible | same sha256 from two independent `g4agent.packager` runs | `package_submission.sh` twice |
| Official `validate_directory` + `compile_submission` (adk-submission 0.2.11, swegemma 0.2.7) | **pass**: LlmAgent `swe_coder`, 9 tools + SkillToolset | `scripts/official_check.py submission/v1.3/submission.zip` |
| Strict validator + google-adk 1.36.1 compile; 12 h projection | **pass**; worst case 11.17 h (116 tasks) / 11.55 h (120) | `g4agent.validator … --compile` |
| Unzipped contents equal the committed sources (prompt, edit.py, eval_config) | **equal** | `diff` against the tree |
| Extensions, secrets, absolute paths, symlinks, `..` | **none found** | member scan (this section's command log) |
| Official Evaluator end to end with a scripted model on the **exact archive** | **resolved** (E008) | `scripts/official_pipeline_test.py` |
| Unit/integration tests | **96 pass** | `scripts/validate.sh` |
| Real-model behaviour | **not measured** | no GPU/credentials (docs/v1_3.md §3) |

---

## V1.1 (2026-09-28)

Archive: `submission/submission.zip`, 17 files, 51,552 bytes unpacked, 28 KB zipped,
sha256 `24b3fab0b3761fc52fc036bee60b3fdaf571ff58c277cd4f058b839454af0f2a` (deterministic: same sources, same hash).

## Contents
```
agent.yaml                                  root LlmAgent swe_coder
eval_config.yaml                            5.0 min / 60 calls / 80 turns / 300 s
configs/sampling.yaml                       T 0.3, top_p 0.95, top_k 64, max 6144, thinking off
prompts/system.md
skills/{repo-navigation,test-discovery,debugging}/SKILL.md
skills/*/scripts/*.py                       nav.py, tests.py, diagnose.py, review.py (stdlib only)
skills/*/references/*.md + resources/*.md   mirrored knowledge files
```
No `sub_agents/` (V1.1 is single-agent) and no `adapters/` (LoRA currently not justified, see experiments/lora).

## Checks

| Check | Result | How |
|---|---|---|
| Official `validate_directory` (adk-submission 0.2.11) | **pass** | `scripts/official_check.py` |
| Official `compile_submission` with swegemma tools, model registry, limits | **pass**: LlmAgent + 9 tools + SkillToolset | same |
| Single declared model = `gemma-4-31b-it-qat-w4a16-ct` | **pass** | official `discover_declared_models` |
| `agent.yaml` at archive root; no nested folder | **pass** | `validate_zip`, `package_submission.sh` |
| Allowed extensions only (.yaml .yml .md .txt .py .json .safetensors) | **pass** | both validators |
| No secrets (key/token/password patterns, `KAGGLE_KEY`, `sk-`, `AIza`) | **none found** | regex scan of every member |
| No absolute paths (`/Users/`, `/home/`, `/private/var`, `C:\`) | **none** | same scan |
| No `..` in includes/skills/config paths; no symlinks | **none** | same scan + official path rules |
| No `.venv`, caches, logs, datasets, results, docs, tests | **none** | same scan |
| Only harness tools referenced; prompt mentions only available tools/skills | **pass** | validator consistency check |
| Instruction placeholders safe (no `{name}` that raises KeyError) | **pass** | validator |
| `timeout_seconds` ≥ 300 (also caps grading pytest) | **pass** (300) | validator warning rule |
| Worst-case 12 h projection (125 tasks) | 10.9 h | budget_model.md |
| Request sent to the model | `enable_thinking: false`, `max_completion_tokens: 6144`, T 0.3, top_p 0.95, top_k 64; 13 tools (9 harness + 4 skill tools) | fake-server request log (E006) |
| End-to-end in the official harness (scripted model) | resolved; skills return real results in the sandbox | E006 |

## Not verifiable here
- Behaviour with the real Gemma 4 model (quality, time per task, cap hits). **TODO**, see docs/real_baseline.md.
- The Docker scorer (`network_mode=none`, Python 3.13). The local official runs used the subprocess sandbox on macOS/py3.12.
- The hidden test set's repositories.
