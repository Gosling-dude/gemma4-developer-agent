# research/kaggle

Snapshot (2026-09-28) of public competition information, fetched anonymously through Kaggle's web API.
- `kapi.sh SERVICE/METHOD JSON`: anonymous call helper (no credentials).
- `pages/*.md`: official competition pages (Overview/Evaluation/Rules/Data/Model Selection…). Committed.
- `competition.json`, `leaderboard_public_2026-09-28.json`: official metadata and a leaderboard snapshot. Committed.
- `dump_topic.py ID` → `discussion/ID.md`; `fetch_nb.py SLUG…` → `notebooks/*.md`: third-party content.
  Git-ignored and regenerable (`./kapi.sh kernels.KernelsService/ListKernels …` → kernels.json first).
Summaries and how each item was used: `docs/public_research.md`, `docs/competition_notes.md`.

Notebook **outputs** (2026-09-30): `./kapi.sh kernels.KernelsService/ListKernelSessionOutput
'{"kernelSessionId": <scriptVersionId>, "pageSize": 500}'` lists every output file with a signed `downloadUrl`
(anonymous). Used to fetch third-party real-Gemma runs into `evaluations/.cache/third_party/<author>__<slug>/`
(git-ignored, ~560 MB): GraphLoc end-to-end runs 1–3 → `graphloc_e2e/run{1,2,3}/`, GraphLoc failure-analysis
resource, woldywei repaired graphs, nihilisticneuralnet and prvsiyan run outputs. Then
`python -m g4agent.localization_official --build` writes `evaluations/.cache/official_dev/tasks_min.jsonl`.
