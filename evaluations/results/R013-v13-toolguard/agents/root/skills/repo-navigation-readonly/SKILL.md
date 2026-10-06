---
name: repo-navigation-readonly
description: Read-only localization in few tool calls. Ranks source files for identifiers or error strings, prints the outline of a file, shows one symbol's source with line numbers, lists usages of a name. Read-only.
---

# Repository navigation (read-only)

Run with `run_skill_script(skill_name="repo-navigation-readonly", file_path="scripts/nav.py", args=[...])`.
`args` is a list of strings. The first item is the subcommand.

| Goal | args |
|---|---|
| Rank files for issue terms | `["find", "ClassName", "func_name", "exact error text"]` |
| Outline a file with line ranges | `["outline", "pkg/module.py"]` |
| Show a symbol's source with line numbers | `["show", "Class.method"]` or `["show", "func", "pkg/module.py"]` |
| Numbered lines of a file (max 120) | `["read", "pkg/module.py", "120", "180"]` |
| Where a name is defined, used, tested | `["usages", "func_name"]` |
| Build system, packages, test dirs | `["layout"]` |

## Narrowing strategy (stop as soon as the location is clear)
1. Pick 2–5 **specific** terms from the issue, most specific first: symbols in code blocks or tracebacks,
   module paths (`pkg.sub`), exception names, distinctive substrings of error messages, CLI flags,
   parameter names. Leave out generic words (`request`, `data`, `value`) and anything from
   environment/version dumps, URLs or doc links. In our benchmark, noisy terms halved top-1 accuracy.
2. `find` with those terms. Files with a DEFINITION hit and a high score are the candidates.
3. `show` the candidate symbol. It returns up to 120 numbered lines, which saves `read_file` calls.
   Use `read` for other ranges.
4. If the named API only delegates, follow its **outgoing calls** with
   `get_code_neighbors("Class.method")`; the fix is often 1–2 calls deeper (e.g. `Text.from_ansi` →
   `AnsiDecoder` in another module). `usages` and the other graph tools are covered in `references/graph_tools.md`.
5. `usages` also lists the tests that exercise a symbol; name the most targeted one in your CHECK line.

If a script errors or finds nothing, don't retry it: change the terms (a shorter or different spelling,
the class instead of the method), try `usages`, or `read_file` the most likely file.
This skill only reads. Nothing here runs commands, searches git history, edits files or runs tests.
If running something would settle a question, don't try to run it: write it in the CHECK line for the coder.
