---
name: repo-navigation
description: Localize the code behind an issue in few tool calls. Ranks source files for identifiers or error strings, prints the outline of a file, shows one symbol's source with line numbers, lists usages of a name. Use at the start of a task and whenever the fix location is unclear.
---

# Repository navigation

Run with `run_skill_script(skill_name="repo-navigation", file_path="scripts/nav.py", args=[...])`.
`args` is a list of strings. The first item is the subcommand.

| Goal | args |
|---|---|
| Rank files for issue terms | `["find", "ClassName", "func_name", "exact error text"]` |
| Outline a file with line ranges | `["outline", "pkg/module.py"]` |
| Show a symbol's source with line numbers | `["show", "Class.method"]` or `["show", "func", "pkg/module.py"]` |
| Where a name is defined, used, tested | `["usages", "func_name"]` |
| Build system, packages, test dirs | `["layout"]` |

## Narrowing strategy (stop as soon as the location is clear)
1. Pick 2–5 **specific** terms from the issue, most specific first: symbols in code blocks or tracebacks,
   module paths (`pkg.sub`), exception names, distinctive substrings of error messages, CLI flags,
   parameter names. Leave out generic words (`request`, `data`, `value`) and anything from
   environment/version dumps, URLs or doc links. In our benchmark, noisy terms halved top-1 accuracy.
2. `find` with those terms. Files with a DEFINITION hit and a high score are the candidates.
3. `show` the candidate symbol. It returns up to 120 numbered lines, which saves `read_file` calls.
4. If the named API only delegates, follow its **outgoing calls** with
   `get_code_neighbors("Class.method")`; the fix is often 1–2 calls deeper (e.g. `Text.from_ansi` →
   `AnsiDecoder` in another module). `usages` and the other graph tools are covered in `references/graph_tools.md`.
5. Read the tests that exercise the symbol (`test-discovery` skill) to learn the expected behaviour.

If a script errors, don't retry it. Fall back to
`run_command("git grep -n -e 'term' -- '*.py' | head -40")`.
