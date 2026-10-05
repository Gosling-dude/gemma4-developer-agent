# Using the code-graph tools well

The harness ships a pre-built AST call/dependency graph and 256-d symbol embeddings for each
repository. Node ids are fully-qualified Python paths such as `pkg.module.Class.method`.

| Tool | Use it when | Don't use it when |
|---|---|---|
| `search_similar_code(query, k)` | You know a symbol name and want related/sibling implementations (e.g. the sync twin of an async function, the other encoder). | For natural-language queries: it only resolves **symbol names** already in the index. |
| `get_code_neighbors(node, edge_type, max_neighbors)` | You'll change a function's behaviour or signature and need its **callers** (who else is affected) or **callees** (where the value really comes from). | The fix is local to one function body. |
| `get_code_subgraph(nodes)` | You have 3–8 candidate symbols and want to see how they connect before picking the fix location. | You have one candidate. |

Tips
- Names resolve by suffix, so `Client.send` usually works. On a "not found" error, try the bare
  name or the module path.
- Use `max_neighbors` around 20 to keep the output small.
- The graph is a snapshot of the base commit. It doesn't reflect your edits.
- Each graph call costs a tool call from the budget, the same as `run_command`. Use them when they
  replace two or more greps or reads.
