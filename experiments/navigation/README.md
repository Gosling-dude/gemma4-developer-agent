# Navigation track
Artifact: `skills/repo-navigation/scripts/nav.py`. Benchmark: `python -m g4agent.localization`.
Results L001–L006 are in docs/experiments.md §B; raw per-task rankings are in `evaluations/analysis/localization_L*.json`.
Main finding: term selection matters most (noisy issue-template terms halve top-1). nav.py's scoring
(definition uniqueness, capped mentions, term order) gives 0.50 top-1 vs 0.08 for naive grep.
