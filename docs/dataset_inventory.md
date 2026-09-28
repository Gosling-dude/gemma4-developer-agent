# Dataset inventory (2026-09-28)

## Correction to an earlier statement
The earlier report mentioned "129 tasks". That is the size of the **official public dev set** described on the
Data page. **Those files have never been on this machine.** Downloading them requires accepting the rules and
Kaggle credentials; an anonymous download returns HTTP 401 (VERIFIED). No official `tasks.jsonl`, `graphs/`,
`embeddings/`, `snapshots/`, `wheels/`, `docker/` or `sandbox/` exist locally.

## What is available locally

| Asset | Location | Count | Provenance | sha256 (prefix) |
|---|---|---|---|---|
| Local cases (official `tasks.jsonl` schema) | `evaluations/cases/tasks.jsonl` | **12** | built by `g4agent.cases` from merged `Textualize/rich` PRs (created 2024-08-26 … 2026-04-12); linked GitHub issue as the problem statement; hints empty (like all 129 public tasks) | `f8b16e4e0c3c67e3` |
| Snapshots in official layout | `evaluations/.cache/official_local/snapshots/*.tgz` (git-ignored) | 12 | `git archive <base_commit>` + fresh git repo | per-file hashes: `docs/dataset_inventory.md` §hashes |
| Test wheels for the local official runs | `evaluations/.cache/official_local/wheels/` (git-ignored) | 11 | PyPI (`pip download`) | – |
| Graphs/embeddings | `evaluations/.cache/graphs/` (git-ignored) | per case | **our AST approximation** (calls/contains/imports/inherits edges, lexical-proxy vectors), not official | – |
| Official harness wheels | `evaluations/.cache/wheelhouse/` (git-ignored) | 3 | public dataset `metric/gemma-4-developer-agent-wheelhouse` (anonymous range download) | adk_eval_core `b1608c44…`, adk_submission `d14f7d31…`, swegemma `2b74d402…` |

Distribution: 12 × `Textualize/rich`. Every case passes the fail-to-pass check with both our grader and the
**official** `swegemma` Evaluator (E003: gold 12/12; E004: empty 0/12).

Caveats:
- Local IDs use PR numbers. Some may coincide with public dev-set IDs (e.g. `rich_3882`, `rich_3472`). The hidden
  test set comes from **private repositories**, so none of these cases can be in it.
- `rich_3472` passes on our Python 3.12 but is reported unsolvable on the grader's Python 3.13 (discussion 743973).

## No reference-answer leakage
The agent only receives the problem statement (and hints, which are always empty). `patch` and `test_patch` are used only
by (a) the grader after the agent finishes, (b) the oracle/gold **controls**, which never run an agent, and (c) the
offline localization benchmark's scoring. The Kaggle notebook's gold control runs in its own Evaluator before any agent run.

## Snapshot hashes (sha256 prefix)
rich_3472 62dbd212dd35083b · rich_3518 8e6307d87a9b0f86 · rich_3718 5f8fe39a79f0e6ee · rich_3882 5d94ff367f53229d ·
rich_3934 dbc901cae030ea6b · rich_3935 26706cecad4e5341 · rich_3938 b2fdcb2bf8347694 · rich_3944 230937211f16e767 ·
rich_3953 27ca1ec8573e6264 · rich_4075 d3b7cf88b2b82e8a · rich_4076 64d323a10570f142 · rich_4077 2817e27cc7c43e72
(`.tgz` hashes depend on tar metadata. Regenerating them reproduces the contents, not necessarily the hashes.)
