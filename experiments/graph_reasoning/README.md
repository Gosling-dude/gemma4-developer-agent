# Graph reasoning track
Strategies compared (docs/experiments.md §B): undirected expansion around the top files (nav_graph), directed
callee-following from the issue's named API (nav_callees), and symbol-seeded similarity (similar).
Finding (EXPERIMENTAL, approximate AST graph and lexical-proxy embeddings): directed callee-following recovers
"entry point delegates to the buggy module" cases, and together with similarity search it lifts recall@3
from 7/12 to 9/12. Undirected expansion does not help reliably.
Prompt consequence: use `get_code_neighbors` on the named API when its body delegates; use
`search_similar_code` with symbol names for twins. Next: rerun with the official graphs (`--data-dir`).
