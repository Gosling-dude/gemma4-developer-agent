# evaluations/cases
`tasks.jsonl` has 12 execution-verified cases from Textualize/rich merged PRs, in the official tasks.jsonl schema.
Every case: tests fail at base_commit + test_patch, and pass with patch + test_patch (verified by `g4agent.cases`).
Problem statements are the linked GitHub issues. Rebuild: `python -m g4agent.cases --repo Textualize/rich --max-cases 12`.
Use the official 129 tasks instead when available: `--tasks data/tasks.jsonl --data-dir data`.
