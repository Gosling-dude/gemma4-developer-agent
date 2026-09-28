# research/kaggle

Snapshot (2026-09-28) of public competition information, fetched anonymously through Kaggle's web API.
- `kapi.sh SERVICE/METHOD JSON`: anonymous call helper (no credentials).
- `pages/*.md`: official competition pages (Overview/Evaluation/Rules/Data/Model Selection…). Committed.
- `competition.json`, `leaderboard_public_2026-09-28.json`: official metadata and a leaderboard snapshot. Committed.
- `dump_topic.py ID` → `discussion/ID.md`; `fetch_nb.py SLUG…` → `notebooks/*.md`: third-party content.
  Git-ignored and regenerable (`./kapi.sh kernels.KernelsService/ListKernels …` → kernels.json first).
Summaries and how each item was used: `docs/public_research.md`, `docs/competition_notes.md`.
